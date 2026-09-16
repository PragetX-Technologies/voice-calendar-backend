"""
Business (plumber) profile storage in MongoDB, collection "business_profiles",
keyed by the owning account's id (app/accounts_service.py).
"""
from app import calendar_connections_service
from app.business_schemas import BusinessProfile
from app.db import get_db


def _connected_email(account_id: str) -> str:
    """
    The business email is whichever calendar account is connected right now —
    google preferred — never owner-typed. Empty when nothing is connected.
    """
    for platform in ("google", "apple"):
        conn = calendar_connections_service.get_connection(account_id, platform)
        if conn is not None:
            return conn["account"]
    return ""


def get_profile(account_id: str) -> dict | None:
    doc = get_db().business_profiles.find_one({"_id": account_id})
    if doc is None:
        return None
    doc.pop("_id")
    # Derived on every read, not trusted from the stored doc: connecting a different
    # calendar has to change the address owner confirmations go to immediately, not
    # only after the owner happens to re-save their profile.
    doc["email"] = _connected_email(account_id)
    return doc


def get_any_profile(account_id: str | None) -> dict | None:
    """
    ElevenLabs webhook path lookup (no signed-in session) — account_id comes
    from app.call_context, set when the call was triggered, not from the
    shared-secret request itself.
    """
    return get_profile(account_id) if account_id else None


def save_profile(account_id: str, profile: BusinessProfile) -> dict:
    doc = profile.model_dump(by_alias=True)
    doc["email"] = _connected_email(account_id)
    get_db().business_profiles.replace_one({"_id": account_id}, doc, upsert=True)
    return doc
