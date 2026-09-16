"""
Business (plumber) profile storage in MongoDB, collection "business_profiles",
keyed by the owning account's id (app/accounts_service.py).
"""
from app import calendar_connections_service
from app.business_schemas import BusinessProfile
from app.db import get_db


def _connected_email(connections: dict) -> str:
    """Google preferred, then Apple. Empty string when nothing is connected."""
    for platform in ("google", "apple"):
        if platform in connections:
            return connections[platform]["account"]
    return ""


def _with_live_connection(doc: dict, account_id: str) -> dict:
    """
    Overwrites `connections` and `email` from calendar_connections, the only source of
    truth for both — the client's own values are never trusted. Applied on read as well
    as on write so a profile that somehow drifted still reads correctly.
    """
    connections = calendar_connections_service.public_status(account_id)
    doc["connections"] = connections
    doc["email"] = _connected_email(connections)
    return doc


def refresh_connection_fields(account_id: str) -> None:
    """
    Writes the live connections/email onto the stored profile. Called by
    calendar_connections_service on every connect/disconnect, so business_profiles
    tracks calendar_connections instead of waiting for the owner to re-save their
    profile. No-op when there's no profile yet — connecting happens during onboarding,
    before the first save, and save_profile fills both fields in anyway.
    """
    connections = calendar_connections_service.public_status(account_id)
    get_db().business_profiles.update_one(
        {"_id": account_id},
        {"$set": {"connections": connections, "email": _connected_email(connections)}},
    )


def get_profile(account_id: str) -> dict | None:
    doc = get_db().business_profiles.find_one({"_id": account_id})
    if doc is None:
        return None
    doc.pop("_id")
    return _with_live_connection(doc, account_id)


def get_any_profile(account_id: str | None) -> dict | None:
    """
    ElevenLabs webhook path lookup (no signed-in session) — account_id comes
    from app.call_context, set when the call was triggered, not from the
    shared-secret request itself.
    """
    return get_profile(account_id) if account_id else None


def save_profile(account_id: str, profile: BusinessProfile) -> dict:
    doc = _with_live_connection(profile.model_dump(by_alias=True), account_id)
    get_db().business_profiles.replace_one({"_id": account_id}, doc, upsert=True)
    return doc
