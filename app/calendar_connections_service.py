"""
Stores verified calendar connection credentials per (account, platform),
collection "calendar_connections". Kept separate from business_profiles so
secrets (refresh tokens / app-specific passwords) never round-trip through
the business profile GET/PUT the frontend uses.

# ponytail: secrets stored as plaintext, same as GOOGLE_REFRESH_TOKEN /
# APPLE_APP_SPECIFIC_PASSWORD already are in .env; encrypt-at-rest later.
"""
from app.db import get_db

PLATFORMS = ("google", "apple")


def _doc_id(account_id: str, platform: str) -> str:
    return f"{account_id}:{platform}"


def _sync_profile(account_id: str) -> None:
    """
    Mirrors the change onto business_profiles.connections/.email. Imported here rather
    than at module scope because business_service imports this module.
    """
    from app import business_service

    business_service.refresh_connection_fields(account_id)


def save_connection(account_id: str, platform: str, account: str, secret: dict) -> None:
    get_db().calendar_connections.replace_one(
        {"_id": _doc_id(account_id, platform)},
        {"account_id": account_id, "platform": platform, "account": account, **secret},
        upsert=True,
    )
    _sync_profile(account_id)


def get_connection(account_id: str, platform: str) -> dict | None:
    doc = get_db().calendar_connections.find_one({"_id": _doc_id(account_id, platform)})
    if doc is None:
        return None
    doc.pop("_id")
    return doc


def get_any_connection(account_id: str | None, platform: str) -> dict | None:
    """
    ElevenLabs webhook path lookup (no signed-in session) — account_id comes
    from app.call_context, set when the call was triggered. Never guess
    "whichever business has this platform connected" across multiple
    accounts — that can return the wrong business's secret.
    """
    return get_connection(account_id, platform) if account_id else None


def get_any_platform(account_id: str | None) -> str | None:
    """
    Whichever platform this business account actually has connected — used
    to override the ElevenLabs `provider` dynamic variable, which the LLM
    sometimes gets wrong (e.g. still says "google" after only "apple" was
    ever connected). account_id comes from app.call_context.
    """
    if not account_id:
        return None
    doc = get_db().calendar_connections.find_one({"account_id": account_id})
    return doc["platform"] if doc else None


def delete_connection(account_id: str, platform: str) -> None:
    get_db().calendar_connections.delete_one({"_id": _doc_id(account_id, platform)})
    _sync_profile(account_id)


def public_status(account_id: str) -> dict:
    """Account info only, no secrets — safe to send to the frontend."""
    status = {}
    for platform in PLATFORMS:
        conn = get_connection(account_id, platform)
        if conn:
            status[platform] = {"account": conn["account"]}
    return status
