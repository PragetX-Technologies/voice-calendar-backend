"""
One-off: create the business account + business profile (opening hours) the IVR demo needs,
so you don't have to run the dashboard. Safe to re-run (overwrites the same docs).

    python -m scripts.seed_ivr_demo

Uses IVR_ACCOUNT_ID from .env as the account email. Edit the constants below first.
The calendar itself is NOT stored here: bookings go to the calendar whose credentials are in .env
(APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD, or the GOOGLE_* refresh token, per CALENDAR_PROVIDER).
"""
import bcrypt

from app import business_service
from app.business_schemas import BusinessProfile, DayHours
from app.config import settings
from app.db import get_db

PASSWORD = "Demo@pwd123"  # only matters if you later log in to the dashboard with this account
BUSINESS_NAME = "Demo Plumbing"
OWNER_MOBILE = "+919800000000"  # owner gets a copy of confirmation SMS here (only if Twilio is configured)
JOB_TYPES = ["Leaking tap", "Clogged drain", "Water heater", "Burst pipe"]
OPEN, CLOSE = "09:00", "18:00"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
ALL_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def main() -> None:
    email = settings.ivr_account_id
    if not email:
        raise SystemExit("Set IVR_ACCOUNT_ID in .env first")
    password_hash = bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    get_db().accounts.replace_one({"_id": email}, {"_id": email, "email": email, "password_hash": password_hash}, upsert=True)
    profile = BusinessProfile(
        businessName=BUSINESS_NAME,
        mobile=OWNER_MOBILE,
        email=email,  # overwritten from live calendar connections on save (empty when none connected)
        hours={d: DayHours(enabled=d in WEEKDAYS, start=OPEN, end=CLOSE) for d in ALL_DAYS},
        jobTypes=JOB_TYPES,
    )
    business_service.save_profile(email, profile)
    print(f"seeded account + profile for {email} (open {OPEN}-{CLOSE} on {', '.join(WEEKDAYS)})")


if __name__ == "__main__":
    main()
