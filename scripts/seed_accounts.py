"""
One-off: seed/update business owner accounts in the "accounts" collection.
Run manually: python -m scripts.seed_accounts (from backend/).
"""
import bcrypt

from app.db import get_db

ACCOUNTS = [
    ("plumber1@business.com", "Plumber1@pwd123"),
    ("plumber2@business.com", "Plumber2@pwd123"),
    ("plumber3@business.com", "Plumber3@pwd123"),
]


def main() -> None:
    db = get_db()
    for email, password in ACCOUNTS:
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        db.accounts.replace_one(
            {"_id": email},
            {"_id": email, "email": email, "password_hash": password_hash},
            upsert=True,
        )
        print(f"seeded {email}")


if __name__ == "__main__":
    main()
