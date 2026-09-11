"""
Dispatches to a calendar backend (Apple CalDAV or Google Calendar). Each call
can pass provider="apple"|"google" explicitly (used when multiple ElevenLabs
agents share this backend, one per provider); falls back to whichever
platform the business owner actually has connected
(calendar_connections_service.get_any_platform()), then settings.calendar_provider
as a last resort before any connection exists. Both backends expose the same
list_events / create_event / update_event / delete_event functions.
"""
from app import caldav_service, calendar_connections_service, google_calendar_service
from app.config import settings

_PROVIDERS = {
    "apple": caldav_service,
    "google": google_calendar_service,
}


def _active(provider: str | None):
    provider = provider or calendar_connections_service.get_any_platform() or settings.calendar_provider
    try:
        return _PROVIDERS[provider]
    except KeyError:
        raise RuntimeError(f"Unknown provider '{provider}', expected one of {list(_PROVIDERS)}")


def list_events(start_iso: str, end_iso: str, provider: str | None = None) -> list[dict]:
    return _active(provider).list_events(start_iso, end_iso)


def create_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
    provider: str | None = None,
) -> dict:
    return _active(provider).create_event(summary, start_iso, end_iso, description, location)


def update_event(
    uid: str,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
    location: str | None = None,
    provider: str | None = None,
) -> dict:
    return _active(provider).update_event(uid, summary, start_iso, end_iso, description, location)


def delete_event(uid: str, provider: str | None = None) -> dict:
    return _active(provider).delete_event(uid)
