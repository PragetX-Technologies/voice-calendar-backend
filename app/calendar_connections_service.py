"""
Stores verified calendar connection credentials per (account, platform),
collection "calendar_connections". Kept separate from business_profiles so
secrets (refresh tokens / app-specific passwords) never round-trip through
the business profile GET/PUT the frontend uses.

# ponytail: secrets stored as plaintext, same as GOOGLE_REFRESH_TOKEN /
# APPLE_APP_SPECIFIC_PASSWORD already are in .env; encrypt-at-rest later.
"""
from app.accounts_service import OWNER_ACCOUNT_ID
from app.db import get_db

PLATFORMS = ("google", "apple")


def _doc_id(account_id: str, platform: str) -> str:
    return f"{account_id}:{platform}"


def save_connection(account_id: str, platform: str, account: str, secret: dict) -> None:
    get_db().calendar_connections.replace_one(
        {"_id": _doc_id(account_id, platform)},
        {"account_id": account_id, "platform": platform, "account": account, **secret},
        upsert=True,
    )


def get_connection(account_id: str, platform: str) -> dict | None:
    doc = get_db().calendar_connections.find_one({"_id": _doc_id(account_id, platform)})
    if doc is None:
        return None
    doc.pop("_id")
    return doc


def get_any_connection(platform: str) -> dict | None:
    """
    Fallback for callers with no account context (the ElevenLabs webhook
    path — a shared-secret call, not a signed-in session). Only one account
    exists (OWNER_ACCOUNT_ID, see accounts_service), so look it up directly
    instead of guessing "whichever business has this platform connected" —
    that guess could return a stale doc left over from an old account id.
    """
    return get_connection(OWNER_ACCOUNT_ID, platform)


def get_any_platform() -> str | None:
    """
    Whichever platform the owner account actually has connected — used to
    override the ElevenLabs `provider` dynamic variable, which the LLM
    sometimes gets wrong (e.g. still says "google" after only "apple" was
    ever connected).
    """
    doc = get_db().calendar_connections.find_one({"account_id": OWNER_ACCOUNT_ID})
    return doc["platform"] if doc else None


def delete_connection(account_id: str, platform: str) -> None:
    get_db().calendar_connections.delete_one({"_id": _doc_id(account_id, platform)})


def public_status(account_id: str) -> dict:
    """Account info only, no secrets — safe to send to the frontend."""
    status = {}
    for platform in PLATFORMS:
        conn = get_connection(account_id, platform)
        if conn:
            status[platform] = {"account": conn["account"]}
    return status
