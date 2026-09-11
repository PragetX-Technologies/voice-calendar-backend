"""
Endpoints for the demo frontend: reads/writes events on the user's calendar
(Apple iCloud or Google, picked via `provider`). Writes (create/update/delete)
auto-mirror to the provider's calendar inside caldav_service/google_calendar_service,
same as the ElevenLabs tool webhooks do — the frontend demo shows both
accounts being kept in sync live.

The "provider" account's credentials come from the signed-in business's
calendar connection (connected via Settings), not .env — every route here
is scoped to the caller's account via require_account_id.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import caldav_service, calendar_events_service, google_calendar_service
from app.auth import require_account_id

logger = logging.getLogger("calendar_view")

router = APIRouter(prefix="/calendar", tags=["calendar-view"])

_BACKENDS = {
    "apple": caldav_service,
    "google": google_calendar_service,
}


def _backend(provider: str):
    return _BACKENDS[provider]


class CreateEventBody(BaseModel):
    summary: str = Field(...)
    start_iso: str = Field(...)
    end_iso: str = Field(...)
    description: str = ""
    location: str = ""


class UpdateEventBody(BaseModel):
    summary: str | None = None
    start_iso: str | None = None
    end_iso: str | None = None
    description: str | None = None
    location: str | None = None


@router.get("/events")
def get_events(
    account: str = Query(..., pattern="^(user|provider)$"),
    provider: str = Query("apple", pattern="^(apple|google)$"),
    start_iso: str = Query(...),
    end_iso: str = Query(...),
    account_id: str = Depends(require_account_id),
):
    try:
        events = _backend(provider).list_events(start_iso, end_iso, account=account, business_account_id=account_id)
        return {"account": account, "provider": provider, "events": events, "count": len(events)}
    except Exception as e:
        logger.exception("get_events failed for account=%s provider=%s", account, provider)
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@router.get("/pending-reminders")
def get_pending_reminders(
    hours_ahead: int | None = Query(None, description="Restrict to events starting within this many hours from now; omit for all pending"),
    account_id: str = Depends(require_account_id),
):
    events = calendar_events_service.list_pending_reminders(hours_ahead=hours_ahead)
    return {"events": events, "count": len(events)}


@router.post("/events")
def create_event(
    payload: CreateEventBody,
    provider: str = Query("apple", pattern="^(apple|google)$"),
    account_id: str = Depends(require_account_id),
):
    try:
        result = _backend(provider).create_event(
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            description=payload.description,
            location=payload.location,
            business_account_id=account_id,
        )
        calendar_events_service.upsert_event(
            uid=result["uid"],
            provider=provider,
            account="user",
            business_account_id=account_id,
            summary=payload.summary,
            start=payload.start_iso,
            end=payload.end_iso,
            location=payload.location,
            description=payload.description,
        )
        return result
    except Exception as e:
        logger.exception("create_event failed")
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@router.patch("/events/{uid}")
def update_event(
    uid: str,
    payload: UpdateEventBody,
    provider: str = Query("apple", pattern="^(apple|google)$"),
    account_id: str = Depends(require_account_id),
):
    try:
        result = _backend(provider).update_event(
            uid=uid,
            summary=payload.summary,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            description=payload.description,
            location=payload.location,
            business_account_id=account_id,
        )
        calendar_events_service.upsert_event(
            uid=uid,
            provider=provider,
            account="user",
            business_account_id=account_id,
            summary=payload.summary,
            start=payload.start_iso,
            end=payload.end_iso,
            location=payload.location,
            description=payload.description,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("update_event failed")
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@router.delete("/events/{uid}")
def delete_event(
    uid: str,
    provider: str = Query("apple", pattern="^(apple|google)$"),
    account_id: str = Depends(require_account_id),
):
    try:
        result = _backend(provider).delete_event(uid=uid, business_account_id=account_id)
        calendar_events_service.delete_event(uid=uid, provider=provider, account="user", business_account_id=account_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("delete_event failed")
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
