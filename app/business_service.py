"""
Business (plumber) profile storage in MongoDB, collection "business_profiles",
keyed by the owning account's id (app/accounts_service.py).
"""
from app.accounts_service import OWNER_ACCOUNT_ID
from app.business_schemas import BusinessProfile
from app.db import get_db


def get_profile(account_id: str) -> dict | None:
    doc = get_db().business_profiles.find_one({"_id": account_id})
    if doc is None:
        return None
    doc.pop("_id")
    return doc


def get_any_profile(provider: str | None = None) -> dict | None:
    """
    Fallback for the ElevenLabs webhook path (no account_id, shared-secret
    call only). Only one account exists (OWNER_ACCOUNT_ID), so look it up
    directly. `provider` kept for call-site compatibility, unused.
    """
    return get_profile(OWNER_ACCOUNT_ID)


def save_profile(account_id: str, profile: BusinessProfile) -> dict:
    doc = profile.model_dump(by_alias=True)
    get_db().business_profiles.replace_one({"_id": account_id}, doc, upsert=True)
    return doc
