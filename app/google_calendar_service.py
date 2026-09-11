"""
Google Calendar service layer: same interface as caldav_service.py
(list_events / create_event / update_event / delete_event), backed by
the Google Calendar API v3 instead of CalDAV.

Two Google accounts get mirrored writes, same split as caldav_service.py:
"user" (still hardcoded in .env — GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN,
via scripts/google_oauth_setup.py) and "provider" (the signed-in business
owner's calendar, connected from the UI's "Connect Google Calendar" flow
and looked up per business account via calendar_connections_service — see
app/routers/oauth.py). The webhook path (ElevenLabs tool calls) has no
signed-in session, so it falls back to "whichever business has Google
connected" — same single-tenant fallback as caldav_service.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app import calendar_connections_service
from app.config import settings

logger = logging.getLogger("google_calendar_service")

_services: dict[str, "googleapiclient.discovery.Resource"] = {}


def _client_cache_key(account: str, business_account_id: str | None) -> str:
    return account if account == "user" else f"provider:{business_account_id}"


def _resolve_provider_connection(business_account_id: str | None) -> dict | None:
    if business_account_id:
        conn = calendar_connections_service.get_connection(business_account_id, "google")
        if conn is not None:
            return conn
    return calendar_connections_service.get_any_connection("google")


def _get_service(account: str = "user", business_account_id: str | None = None):
    key = _client_cache_key(account, business_account_id)
    if key not in _services:
        if account == "user":
            # Minted by scripts/google_oauth_setup.py against the Desktop OAuth client.
            refresh_token = settings.google_refresh_token
            client_id, client_secret = settings.google_client_id, settings.google_client_secret
        else:
            # Minted by app/routers/oauth.py's popup flow against the Web OAuth client —
            # refreshing it with the Desktop client's id/secret fails with unauthorized_client.
            conn = _resolve_provider_connection(business_account_id)
            if conn is None:
                raise RuntimeError("Google Calendar isn't connected for any business yet. Connect it from Settings.")
            refresh_token = conn["refresh_token"]
            client_id, client_secret = settings.google_oauth_client_id, settings.google_oauth_client_secret

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        _services[key] = build("calendar", "v3", credentials=creds)
    return _services[key]


def _mirror_to_provider(action: str, fn, business_account_id: str | None) -> None:
    """Best-effort: apply same op on provider account. Log, don't break caller's flow."""
    if _resolve_provider_connection(business_account_id) is None:
        return
    try:
        fn(_get_service("provider", business_account_id))
    except Exception as e:
        logger.error("Provider-calendar mirror failed (%s): %s", action, e)


def _parse_dt(value: str) -> datetime:
    """Parses an ISO 8601 datetime string, assuming default_timezone if none given."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(settings.default_timezone))
    return dt


def list_events(start_iso: str, end_iso: str, account: str = "user", business_account_id: str | None = None) -> list[dict]:
    """Lists events between start and end, used to check availability/conflicts."""
    service = _get_service(account, business_account_id)
    start = _parse_dt(start_iso)
    end = _parse_dt(end_iso)

    result = (
        service.events()
        .list(
            calendarId=settings.google_calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        events.append(
            {
                "uid": item["id"],
                "summary": item.get("summary", ""),
                "start": item["start"].get("dateTime", item["start"].get("date")),
                "end": item["end"].get("dateTime", item["end"].get("date")),
                "location": item.get("location", ""),
                "description": item.get("description", ""),
            }
        )
    return events


def create_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
    business_account_id: str | None = None,
) -> dict:
    """Creates a new event on the calendar."""
    service = _get_service()
    start = _parse_dt(start_iso)
    end = _parse_dt(end_iso)

    # Client-assigned id (Google allows a-v/0-9, 5-1024 chars — uuid4 hex fits) so the
    # provider mirror can be created, updated and deleted by the same uid as the original.
    event_id = uuid.uuid4().hex

    body = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location

    created = service.events().insert(calendarId=settings.google_calendar_id, body=body).execute()

    # Mirror same event (same uid) to the business's connected Google Calendar.
    _mirror_to_provider(
        "create",
        lambda svc: svc.events().insert(calendarId=settings.google_calendar_id, body=body).execute(),
        business_account_id,
    )

    return {"uid": created["id"], "summary": summary, "start": start_iso, "end": end_iso}


def update_event(
    uid: str,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
    location: str | None = None,
    business_account_id: str | None = None,
) -> dict:
    """Updates fields on an existing event, identified by its uid (Google event id)."""
    service = _get_service()

    try:
        event = service.events().get(calendarId=settings.google_calendar_id, eventId=uid).execute()
    except Exception as e:
        raise ValueError(f"No event found with uid '{uid}'") from e

    if summary is not None:
        event["summary"] = summary
    if start_iso is not None:
        event["start"] = {"dateTime": _parse_dt(start_iso).isoformat()}
    if end_iso is not None:
        event["end"] = {"dateTime": _parse_dt(end_iso).isoformat()}
    if description is not None:
        event["description"] = description
    if location is not None:
        event["location"] = location

    service.events().update(calendarId=settings.google_calendar_id, eventId=uid, body=event).execute()

    # create_event assigns the same client-generated id on both calendars, so the
    # provider-side event can be looked up and updated by the same uid.
    def _update_provider(svc):
        p_event = svc.events().get(calendarId=settings.google_calendar_id, eventId=uid).execute()
        if summary is not None:
            p_event["summary"] = summary
        if start_iso is not None:
            p_event["start"] = {"dateTime": _parse_dt(start_iso).isoformat()}
        if end_iso is not None:
            p_event["end"] = {"dateTime": _parse_dt(end_iso).isoformat()}
        if description is not None:
            p_event["description"] = description
        if location is not None:
            p_event["location"] = location
        svc.events().update(calendarId=settings.google_calendar_id, eventId=uid, body=p_event).execute()

    _mirror_to_provider("update", _update_provider, business_account_id)

    return {"uid": uid, "status": "updated"}


def delete_event(uid: str, business_account_id: str | None = None) -> dict:
    """Deletes an event by uid (Google event id)."""
    service = _get_service()
    try:
        service.events().delete(calendarId=settings.google_calendar_id, eventId=uid).execute()
    except Exception as e:
        raise ValueError(f"No event found with uid '{uid}'") from e

    def _delete_provider(svc):
        svc.events().delete(calendarId=settings.google_calendar_id, eventId=uid).execute()

    _mirror_to_provider("delete", _delete_provider, business_account_id)

    return {"uid": uid, "status": "deleted"}
