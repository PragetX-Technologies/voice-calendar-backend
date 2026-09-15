"""
Dispatches to a calendar backend (Apple CalDAV or Google Calendar) for the
ElevenLabs tool-webhook path. Each call can pass provider="apple"|"google"
explicitly; falls back to whichever platform this business account actually
has connected (calendar_connections_service.get_any_platform(business_account_id)),
then settings.calendar_provider as a last resort before any connection
exists. business_account_id comes from app.call_context (set when the call
was triggered) — this path has no signed-in session of its own. Both
backends expose the same list_events / create_event / update_event /
delete_event functions.
"""
from app import caldav_service, calendar_connections_service, google_calendar_service
from app.config import settings

_PROVIDERS = {
    "apple": caldav_service,
    "google": google_calendar_service,
}


def _active(provider: str | None, business_account_id: str | None):
    provider = provider or calendar_connections_service.get_any_platform(business_account_id) or settings.calendar_provider
    try:
        return _PROVIDERS[provider]
    except KeyError:
        raise RuntimeError(f"Unknown provider '{provider}', expected one of {list(_PROVIDERS)}")


def list_events(start_iso: str, end_iso: str, provider: str | None = None, business_account_id: str | None = None) -> list[dict]:
    return _active(provider, business_account_id).list_events(start_iso, end_iso, business_account_id=business_account_id)


def create_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
    provider: str | None = None,
    business_account_id: str | None = None,
) -> dict:
    return _active(provider, business_account_id).create_event(summary, start_iso, end_iso, description, location, business_account_id=business_account_id)


def update_event(
    uid: str,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
    location: str | None = None,
    provider: str | None = None,
    business_account_id: str | None = None,
) -> dict:
    return _active(provider, business_account_id).update_event(uid, summary, start_iso, end_iso, description, location, business_account_id=business_account_id)


def delete_event(uid: str, provider: str | None = None, business_account_id: str | None = None) -> dict:
    return _active(provider, business_account_id).delete_event(uid, business_account_id=business_account_id)
