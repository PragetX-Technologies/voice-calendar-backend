"""
Periodic reminder-call sweep: finds calendar events starting soon that
haven't had a reminder call placed yet, and triggers one by reusing the
existing /calls/trigger logic in-process.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app import calendar_events_service
from app.config import settings
from app.db import get_db
from app.routers.calls import trigger_call
from app.schemas import TriggerCallRequest

logger = logging.getLogger("reminder_job")

REMINDER_LOOKAHEAD_HOURS = 24


def run_reminder_sweep() -> None:
    now = datetime.now()
    window_end = now + timedelta(hours=REMINDER_LOOKAHEAD_HOURS)

    due = list(get_db().calendar_events.find({
        "reminder_sent": {"$ne": True},
        "start": {"$gte": now.isoformat(), "$lte": window_end.isoformat()},
    }))
    logger.info("reminder_job: %d event(s) due for a reminder call", len(due))

    for doc in due:
        phone_number = doc.get("phone_number")
        if not phone_number:
            logger.warning("reminder_job: skipping uid=%s, no phone_number on record", doc.get("uid"))
            continue
        try:
            asyncio.run(trigger_call(TriggerCallRequest(
                to_number=phone_number,
                reason="appointment reminder",
                provider=doc.get("provider") or settings.calendar_provider,
                purpose="reminder",
            )))
            calendar_events_service.upsert_event(
                uid=doc["uid"],
                provider=doc["provider"],
                account=doc.get("account", "user"),
                business_account_id=doc.get("business_account_id"),
                reminder_sent=True,
            )
        except Exception:
            logger.exception("reminder_job: failed to trigger reminder call for uid=%s", doc.get("uid"))


def _demo() -> None:
    """ponytail self-check: no pytest in this repo, so a plain assert-based demo."""
    from unittest.mock import patch

    now = datetime.now()
    fake_docs = [
        {"uid": "a", "provider": "google", "start": (now + timedelta(hours=1)).isoformat(), "phone_number": "+15550001"},
        {"uid": "b", "provider": "google", "start": (now + timedelta(hours=2)).isoformat(), "phone_number": None},
        {"uid": "c", "provider": "google", "start": (now + timedelta(hours=48)).isoformat(), "phone_number": "+15550002"},
    ]

    class FakeCollection:
        def find(self, query):
            return [d for d in fake_docs if query["start"]["$gte"] <= d["start"] <= query["start"]["$lte"]]

    class FakeDb:
        calendar_events = FakeCollection()

    triggered, upserted = [], []

    async def fake_trigger_call(payload):
        triggered.append(payload.to_number)

    with patch("app.reminder_job.get_db", return_value=FakeDb()), \
         patch("app.reminder_job.trigger_call", new=fake_trigger_call), \
         patch("app.calendar_events_service.upsert_event", side_effect=lambda **kw: upserted.append(kw["uid"])):
        run_reminder_sweep()

    assert triggered == ["+15550001"], f"expected only doc 'a' (in window, has phone) to be called, got {triggered}"
    assert upserted == ["a"], f"expected only doc 'a' marked reminder_sent, got {upserted}"
    print("reminder_job self-check passed")


if __name__ == "__main__":
    _demo()
