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
    Fills in `connections` and `email` from calendar_connections, which is the only
    source of truth for both. They are never persisted on the profile: a stored copy
    goes stale the moment a different calendar is connected, and the profile is only
    re-saved when the owner happens to open Settings — so the dashboard kept showing,
    and owner confirmations kept going to, the previously connected account.
    """
    connections = calendar_connections_service.public_status(account_id)
    doc["connections"] = connections
    doc["email"] = _connected_email(connections)
    return doc


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
    doc = profile.model_dump(by_alias=True)
    doc.pop("email", None)
    doc.pop("connections", None)
    get_db().business_profiles.replace_one({"_id": account_id}, doc, upsert=True)
    return _with_live_connection(doc, account_id)
