"""
Business owner accounts, collection "accounts" in MongoDB — each business
owner has their own account (email + bcrypt-hashed password), scoped to
their own account id everywhere via require_account_id. Seed/update accounts
with scripts/seed_accounts.py; no signup endpoint.
"""
import bcrypt

from app.db import get_db


def authenticate(username: str, password: str) -> dict | None:
    doc = get_db().accounts.find_one({"email": username})
    if doc is None:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), doc["password_hash"].encode("utf-8")):
        return None
    return {"_id": doc["_id"], "email": doc["email"]}


def get_account(account_id: str) -> dict | None:
    doc = get_db().accounts.find_one({"_id": account_id})
    if doc is None:
        return None
    return {"_id": doc["_id"], "email": doc["email"]}
