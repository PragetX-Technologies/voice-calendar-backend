"""
Business (plumber) profile storage in MongoDB, collection "business_profiles",
keyed by the owning account's id (app/accounts_service.py).
"""
from app.business_schemas import BusinessProfile
from app.db import get_db


def get_profile(account_id: str) -> dict | None:
    doc = get_db().business_profiles.find_one({"_id": account_id})
    if doc is None:
        return None
    doc.pop("_id")
    return doc


def save_profile(account_id: str, profile: BusinessProfile) -> dict:
    doc = profile.model_dump(by_alias=True)
    get_db().business_profiles.replace_one({"_id": account_id}, doc, upsert=True)
    return doc
