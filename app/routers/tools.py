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

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from app import calendar_events_service, call_context, calendar_service, email_service, sms_service
from app.config import settings
from app.schemas import (
    CreateEventRequest,
    DeleteEventRequest,
    ListEventsRequest,
    UpdateEventRequest,
)

logger = logging.getLogger("tools")

router = APIRouter(prefix="/tools", tags=["elevenlabs-tools"])


def verify_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    if x_webhook_secret != settings.tool_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/list-events", dependencies=[Depends(verify_webhook_secret)])
def list_events(payload: ListEventsRequest):
    logger.info("list-events payload=%s", payload.model_dump())
    try:
        events = calendar_service.list_events(payload.start_iso, payload.end_iso, provider=payload.provider)
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.exception("list-events failed")
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@router.post("/create-event", dependencies=[Depends(verify_webhook_secret)])
def create_event(payload: CreateEventRequest, background_tasks: BackgroundTasks):
    logger.info("create-event payload=%s", payload.model_dump())
    try:
        result = calendar_service.create_event(
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            description=payload.description,
            location=payload.location,
            provider=payload.provider,
        )
        background_tasks.add_task(
            email_service.send_booking_confirmation,
            uid=result["uid"],
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=payload.location,
            price_estimate=payload.price_estimate,
        )
        background_tasks.add_task(
            sms_service.send_booking_confirmation,
            to_number=payload.phone_number or call_context.get_last_to_number(),
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=payload.location,
            price_estimate=payload.price_estimate,
        )
        background_tasks.add_task(
            calendar_events_service.upsert_event,
            uid=result["uid"],
            provider=payload.provider or settings.calendar_provider,
            summary=payload.summary,
            start=payload.start_iso,
            end=payload.end_iso,
            location=payload.location,
            description=payload.description,
            phone_number=payload.phone_number or call_context.get_last_to_number(),
            reminder_sent=False,
        )
        return {"status": "created", **result}
    except Exception as e:
        logger.exception("create-event failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/update-event", dependencies=[Depends(verify_webhook_secret)])
def update_event(payload: UpdateEventRequest, background_tasks: BackgroundTasks):
    logger.info("update-event payload=%s", payload.model_dump())
    try:
        result = calendar_service.update_event(
            uid=payload.uid,
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            description=payload.description,
            location=payload.location,
            provider=payload.provider,
        )
        background_tasks.add_task(
            email_service.send_update_confirmation,
            uid=payload.uid,
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=payload.location,
        )
        background_tasks.add_task(
            sms_service.send_update_confirmation,
            to_number=payload.phone_number or call_context.get_last_to_number(),
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            location=payload.location,
        )
        background_tasks.add_task(
            calendar_events_service.upsert_event,
            uid=payload.uid,
            provider=payload.provider or settings.calendar_provider,
            summary=payload.summary,
            start=payload.start_iso,
            end=payload.end_iso,
            location=payload.location,
            description=payload.description,
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
    try:
        result = calendar_service.delete_event(uid=payload.uid, provider=payload.provider)
        background_tasks.add_task(email_service.send_cancellation_confirmation, uid=payload.uid)
        background_tasks.add_task(sms_service.send_cancellation_confirmation, to_number=payload.phone_number or call_context.get_last_to_number())
        background_tasks.add_task(
            calendar_events_service.delete_event,
            uid=payload.uid,
            provider=payload.provider or settings.calendar_provider,
        )
        return result
    except ValueError as e:
        logger.exception("delete-event failed")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("delete-event failed")
        raise HTTPException(status_code=400, detail=str(e))
