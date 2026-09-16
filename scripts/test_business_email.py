"""
Checks that the business email follows the currently connected calendar account,
including when the calendar is switched without re-saving the profile — the bug
where owner confirmations kept going to the previously connected address.

Run manually: python -m scripts.test_business_email (from backend/). No DB: the
profile lookup and the connection lookup are stubbed out.
"""
from app import business_service

ACCOUNT_ID = "owner@business.com"

connections: dict[str, dict] = {}


class _FakeProfiles:
    def find_one(self, _query):
        return {"_id": ACCOUNT_ID, "businessName": "Acme Plumbing", "email": "stale@icloud.com"}


class _FakeDb:
    business_profiles = _FakeProfiles()


def main() -> None:
    business_service.get_db = lambda: _FakeDb()
    business_service.calendar_connections_service.get_connection = lambda _id, platform: connections.get(platform)

    connections["apple"] = {"account": "first@icloud.com"}
    assert business_service.get_profile(ACCOUNT_ID)["email"] == "first@icloud.com", "should use the connected Apple account"

    # Owner disconnects Apple and connects Google — no profile re-save in between.
    del connections["apple"]
    connections["google"] = {"account": "second@gmail.com"}
    assert business_service.get_profile(ACCOUNT_ID)["email"] == "second@gmail.com", "should follow the new connection"

    # Google wins when both are somehow present.
    connections["apple"] = {"account": "first@icloud.com"}
    assert business_service.get_profile(ACCOUNT_ID)["email"] == "second@gmail.com", "google is preferred"

    # Nothing connected — no address, so email_service._send no-ops instead of mailing the old owner.
    connections.clear()
    assert business_service.get_profile(ACCOUNT_ID)["email"] == "", "no connection means no business email"

    print("business email follows the connected calendar")
    print("OK")


if __name__ == "__main__":
    main()
