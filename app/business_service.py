"""
Business (plumber) profile storage in MongoDB, collection "business_profiles",
keyed by the owning account's id (app/accounts_service.py).
"""
from app import calendar_connections_service
from app.business_schemas import BusinessProfile
from app.db import get_db


def get_profile(account_id: str) -> dict | None:
    doc = get_db().business_profiles.find_one({"_id": account_id})
    if doc is None:
        return None
    doc.pop("_id")
    return doc


def get_any_profile(provider: str) -> dict | None:
    """
    Fallback for the ElevenLabs webhook path (no account_id, shared-secret
    call only) — same single-tenant assumption as
    calendar_connections_service.get_any_connection.
    """
    conn = calendar_connections_service.get_any_connection(provider)
    if conn is None:
        return None
    return get_profile(conn["account_id"])


def save_profile(account_id: str, profile: BusinessProfile) -> dict:
    doc = profile.model_dump(by_alias=True)
    get_db().business_profiles.replace_one({"_id": account_id}, doc, upsert=True)
    return doc
