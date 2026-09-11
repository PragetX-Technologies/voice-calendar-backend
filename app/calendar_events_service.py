"""
Mirrors every calendar event into MongoDB, collection "calendar_events".
The calendar (CalDAV/Google) stays source of truth — this is a synced
read cache, updated on every create/update/delete (see routers/tools.py
and routers/calendar_view.py) and backfillable via sync_range for events
that already existed before this cache was introduced.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app import caldav_service, google_calendar_service
from app.db import get_db

logger = logging.getLogger("calendar_events_service")

_BACKENDS = {
    "apple": caldav_service,
    "google": google_calendar_service,
}


def _doc_id(business_account_id: str | None, account: str, provider: str, uid: str) -> str:
    return f"{business_account_id or 'default'}:{account}:{provider}:{uid}"


def upsert_event(
    uid: str,
    provider: str,
    account: str = "user",
    business_account_id: str | None = None,
    **fields,
) -> None:
    """fields: any subset of summary/start/end/location/description — only given keys are set."""
    doc_id = _doc_id(business_account_id, account, provider, uid)
    get_db().calendar_events.update_one(
        {"_id": doc_id},
        {
            "$set": {
                "business_account_id": business_account_id,
                "account": account,
                "provider": provider,
                "uid": uid,
                **{k: v for k, v in fields.items() if v is not None},
            }
        },
        upsert=True,
    )


def delete_event(uid: str, provider: str, account: str = "user", business_account_id: str | None = None) -> None:
    get_db().calendar_events.delete_one({"_id": _doc_id(business_account_id, account, provider, uid)})


def list_pending_reminders(hours_ahead: int | None = None) -> list[dict]:
    """
    Cached events not yet reminder-called (same "reminder_sent != True" query
    run_reminder_sweep() uses), for the dashboard to show what's still pending.
    hours_ahead, if given, restricts to events starting within that window from now.
    """
    query = {"reminder_sent": {"$ne": True}}
    if hours_ahead is not None:
        now = datetime.now()
        query["start"] = {"$gte": now.isoformat(), "$lte": (now + timedelta(hours=hours_ahead)).isoformat()}
    docs = list(get_db().calendar_events.find(query).sort("start", 1))
    for doc in docs:
        doc["id"] = doc.pop("_id")
    return docs


def sync_range(
    start_iso: str,
    end_iso: str,
    provider: str,
    account: str = "user",
    business_account_id: str | None = None,
) -> int:
    """Backfill: pulls every event in [start_iso, end_iso] from the live calendar and upserts each into Mongo."""
    events = _BACKENDS[provider].list_events(start_iso, end_iso, account=account, business_account_id=business_account_id)
    for event in events:
        upsert_event(
            uid=event["uid"],
            provider=provider,
            account=account,
            business_account_id=business_account_id,
            summary=event.get("summary"),
            start=event.get("start"),
            end=event.get("end"),
            location=event.get("location"),
            description=event.get("description"),
        )
    return len(events)
