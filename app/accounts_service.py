"""
Single hardcoded business owner account (OWNER_USERNAME/OWNER_PASSWORD in
.env). No signup, no accounts DB — one account, id fixed as "owner".
"""
from app.config import settings

OWNER_ACCOUNT_ID = "owner"


def authenticate(username: str, password: str) -> dict | None:
    if username != settings.owner_username or password != settings.owner_password:
        return None
    return {"_id": OWNER_ACCOUNT_ID, "email": settings.owner_username}


def get_account(account_id: str) -> dict | None:
    if account_id != OWNER_ACCOUNT_ID:
        return None
    return {"_id": OWNER_ACCOUNT_ID, "email": settings.owner_username}
