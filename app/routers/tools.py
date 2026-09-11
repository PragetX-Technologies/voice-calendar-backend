"""
These endpoints are what you register as "Server Tools" / "Webhook Tools"
in the ElevenLabs agent configuration. During a live call, the agent decides
to call one of these (e.g. the user says "book me Thursday at 2pm") and
ElevenLabs sends an HTTP request here with parameters it extracted from
the conversation.

Security: ElevenLabs lets you attach custom headers to each tool's outgoing
request. We check for a shared-secret header so random requests can't hit
these endpoints and mess with the calendar.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from app import (
    business_service,
    calendar_connections_service,
    calendar_events_service,
    call_context,
    calendar_service,
    email_service,
    sms_service,
)
from app.config import settings
from app.schemas import (
    CreateEventRequest,
    DeleteEventRequest,
    GetBusinessHoursRequest,
    ListEventsRequest,
    UpdateEventRequest,
)

logger = logging.getLogger("tools")

router = APIRouter(prefix="/tools", tags=["elevenlabs-tools"])


def verify_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    if x_webhook_secret != settings.tool_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _resolve_provider(payload_provider: str | None) -> str | None:
    """Single-tenant: trust which platform is actually connected over whatever the agent guessed."""
    return calendar_connections_service.get_any_platform() or payload_provider


def _owner_contact(provider: str | None) -> tuple[str | None, str | None]:
    """(mobile, email) of the business owner, for mirroring customer confirmations to them too."""
    profile = business_service.get_any_profile(provider or calendar_connections_service.get_any_platform() or settings.calendar_provider)
    if not profile:
        return None, None
    return profile.get("mobile"), profile.get("email")


_ADDRESS_FIELDS = ("address_line", "unit_type", "unit_number", "city", "state", "zip")


def _build_location_string(address_line: str, unit_type: str, unit_number: str, city: str, state: str, zip_code: str) -> str:
    """Single-line address for the actual calendar event (CalDAV LOCATION / Google Calendar `location` only accept one string)."""
    unit = f"{unit_type} {unit_number}".strip() if unit_number else unit_type
    return ", ".join(p for p in (address_line, unit, city, state, zip_code) if p)


def _build_location_array(payload) -> list[str] | None:
    """[address_line, unit_type, unit_number, city, state, zip] for the calendar_events Mongo cache — None if the caller sent no address fields at all (so an update leaves the cached address untouched)."""
    if all(getattr(payload, f) is None for f in _ADDRESS_FIELDS):
        return None
    return [getattr(payload, f) or "" for f in _ADDRESS_FIELDS]


@router.post("/get-business-hours", dependencies=[Depends(verify_webhook_secret)])
def get_business_hours(payload: GetBusinessHoursRequest):
    logger.info("get-business-hours payload=%s", payload.model_dump())
    profile = business_service.get_any_profile(_resolve_provider(payload.provider) or settings.calendar_provider)
    if not profile:
        raise HTTPException(status_code=404, detail="No business profile found for this provider")
    now = datetime.now(ZoneInfo(settings.default_timezone))
    return {
        "hours": profile.get("hours", {}),
        "now": now.isoformat(),
        "today": now.strftime("%a"),  # "Mon".."Sun", matches business_profiles.hours keys
    }


@router.post("/list-events", dependencies=[Depends(verify_webhook_secret)])
def list_events(payload: ListEventsRequest):
    logger.info("list-events payload=%s", payload.model_dump())
    try:
        events = calendar_service.list_events(payload.start_iso, payload.end_iso, provider=_resolve_provider(payload.provider))
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.exception("list-events failed")
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@router.post("/create-event", dependencies=[Depends(verify_webhook_secret)])
def create_event(payload: CreateEventRequest, background_tasks: BackgroundTasks):
    logger.info("create-event payload=%s", payload.model_dump())
    provider = _resolve_provider(payload.provider)
    location_str = _build_location_string(payload.address_line, payload.unit_type, payload.unit_number, payload.city, payload.state, payload.zip)
    try:
        result = calendar_service.create_event(
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            description=payload.description,
            location=location_str,
            provider=provider,
        )
        background_tasks.add_task(
            email_service.send_booking_confirmation,
            uid=result["uid"],
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=location_str,
            price_estimate=payload.price_estimate,
            email=settings.user_email,  # caller no longer asked for email; hardcoded via USER_EMAIL env var
        )
        background_tasks.add_task(
            sms_service.send_booking_confirmation,
            to_number=payload.phone_number or call_context.get_last_to_number(),
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=location_str,
            price_estimate=payload.price_estimate,
        )
        owner_mobile, owner_email = _owner_contact(provider)
        if owner_email:
            background_tasks.add_task(
                email_service.send_booking_confirmation,
                uid=result["uid"],
                summary=payload.summary,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                location=location_str,
                price_estimate=payload.price_estimate,
                email=owner_email,
            )
        if owner_mobile:
            background_tasks.add_task(
                sms_service.send_booking_confirmation,
                to_number=owner_mobile,
                summary=payload.summary,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                location=location_str,
                price_estimate=payload.price_estimate,
            )
        background_tasks.add_task(
            calendar_events_service.upsert_event,
            uid=result["uid"],
            provider=provider or settings.calendar_provider,
            summary=payload.summary,
            start=payload.start_iso,
            end=payload.end_iso,
            location=_build_location_array(payload),  # [address_line, unit_type, unit_number, city, state, zip]
            description=payload.description,
            phone_number=payload.phone_number or call_context.get_last_to_number(),
            email=settings.user_email,  # caller no longer asked for email; hardcoded via USER_EMAIL env var
            reminder_sent=False,
        )
        return {"status": "created", **result}
    except Exception as e:
        logger.exception("create-event failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/update-event", dependencies=[Depends(verify_webhook_secret)])
def update_event(payload: UpdateEventRequest, background_tasks: BackgroundTasks):
    logger.info("update-event payload=%s", payload.model_dump())
    provider = _resolve_provider(payload.provider)
    location_array = _build_location_array(payload)
    # only build a location string (and touch the calendar event's location) if the caller actually sent an address field
    location_str = _build_location_string(payload.address_line or "", payload.unit_type or "", payload.unit_number or "", payload.city or "", payload.state or "", payload.zip or "") if location_array is not None else None
    try:
        result = calendar_service.update_event(
            uid=payload.uid,
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            description=payload.description,
            location=location_str,
            provider=provider,
        )
        background_tasks.add_task(
            email_service.send_update_confirmation,
            uid=payload.uid,
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=location_str,
            email=settings.user_email,  # caller no longer asked for email; hardcoded via USER_EMAIL env var
        )
        background_tasks.add_task(
            sms_service.send_update_confirmation,
            to_number=payload.phone_number or call_context.get_last_to_number(),
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=location_str,
        )
        owner_mobile, owner_email = _owner_contact(provider)
        if owner_email:
            background_tasks.add_task(
                email_service.send_update_confirmation,
                uid=payload.uid,
                summary=payload.summary,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                location=location_str,
                email=owner_email,
            )
        if owner_mobile:
            background_tasks.add_task(
                sms_service.send_update_confirmation,
                to_number=owner_mobile,
                summary=payload.summary,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                location=location_str,
            )
        background_tasks.add_task(
            calendar_events_service.upsert_event,
            uid=payload.uid,
            provider=provider or settings.calendar_provider,
            summary=payload.summary,
            start=payload.start_iso,
            end=payload.end_iso,
            location=location_array,  # [address_line, unit_type, unit_number, city, state, zip], or None if unchanged
            description=payload.description,
            email=settings.user_email,  # caller no longer asked for email; hardcoded via USER_EMAIL env var
        )
        return result
    except ValueError as e:
        logger.exception("update-event failed")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("update-event failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/delete-event", dependencies=[Depends(verify_webhook_secret)])
def delete_event(payload: DeleteEventRequest, background_tasks: BackgroundTasks):
    logger.info("delete-event payload=%s", payload.model_dump())
    provider = _resolve_provider(payload.provider)
    try:
        result = calendar_service.delete_event(uid=payload.uid, provider=provider)
        background_tasks.add_task(email_service.send_cancellation_confirmation, uid=payload.uid, email=settings.user_email)  # caller no longer asked for email; hardcoded via USER_EMAIL env var
        background_tasks.add_task(sms_service.send_cancellation_confirmation, to_number=payload.phone_number or call_context.get_last_to_number())
        owner_mobile, owner_email = _owner_contact(provider)
        if owner_email:
            background_tasks.add_task(email_service.send_cancellation_confirmation, uid=payload.uid, email=owner_email)
        if owner_mobile:
            background_tasks.add_task(sms_service.send_cancellation_confirmation, to_number=owner_mobile)
        background_tasks.add_task(
            calendar_events_service.delete_event,
            uid=payload.uid,
            provider=provider or settings.calendar_provider,
        )
        return result
    except ValueError as e:
        logger.exception("delete-event failed")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("delete-event failed")
        raise HTTPException(status_code=400, detail=str(e))
