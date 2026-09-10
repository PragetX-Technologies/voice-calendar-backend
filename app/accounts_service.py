"""
Business owner accounts, collection "accounts". Email/password auth —
passwords hashed with bcrypt, sessions are JWT bearer tokens (app/auth.py).
"""
import uuid

import bcrypt

from app.db import get_db


def create_account(email: str, password: str) -> dict:
    email = email.strip().lower()
    if get_db().accounts.find_one({"email": email}):
        raise ValueError("An account with this email already exists")

    account = {
        "_id": str(uuid.uuid4()),
        "email": email,
        "password_hash": bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
    }
    get_db().accounts.insert_one(account)
    return account


def authenticate(email: str, password: str) -> dict | None:
    account = get_db().accounts.find_one({"email": email.strip().lower()})
    if account is None:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), account["password_hash"].encode("utf-8")):
        return None
    return account


def get_account(account_id: str) -> dict | None:
    return get_db().accounts.find_one({"_id": account_id})
