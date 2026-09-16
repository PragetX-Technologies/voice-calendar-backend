"""
Checks that the profile's `connections` and `email` follow the currently connected
calendar account, including when the calendar is switched without re-saving the
profile — the bug where the Settings page kept showing, and owner confirmations kept
going to, the previously connected account.

Run manually: python -m scripts.test_business_email (from backend/). No DB: the
profile lookup and the connections collection are stubbed out.
"""
from app import business_service
from app.business_schemas import BusinessProfile

ACCOUNT_ID = "plumber1@business.com"

connections: dict[str, dict] = {}
stored: dict = {}


class _FakeProfiles:
    def find_one(self, _query):
        return {"_id": ACCOUNT_ID, "businessName": "Dave's Plumbing", "mobile": "+918849484100",
                "email": "stale@gmail.com", "connections": {"google": {"account": "stale@gmail.com"}}}

    def replace_one(self, _query, doc, upsert=False):
        stored.clear()
        stored.update(doc)


class _FakeDb:
    business_profiles = _FakeProfiles()


def main() -> None:
    business_service.get_db = lambda: _FakeDb()
    business_service.calendar_connections_service.public_status = lambda _id: {
        p: {"account": c["account"]} for p, c in connections.items()
    }

    connections["google"] = {"account": "demo1.users09092026@gmail.com"}
    profile = business_service.get_profile(ACCOUNT_ID)
    assert profile["email"] == "demo1.users09092026@gmail.com", profile["email"]
    assert profile["connections"] == {"google": {"account": "demo1.users09092026@gmail.com"}}, profile["connections"]

    # Owner connects a different Google account — no profile re-save in between.
    connections["google"] = {"account": "averma@pragetx.com"}
    profile = business_service.get_profile(ACCOUNT_ID)
    assert profile["email"] == "averma@pragetx.com", profile["email"]
    assert profile["connections"] == {"google": {"account": "averma@pragetx.com"}}, profile["connections"]

    # Apple only.
    connections.clear()
    connections["apple"] = {"account": "owner@icloud.com"}
    assert business_service.get_profile(ACCOUNT_ID)["email"] == "owner@icloud.com"

    # Nothing connected — no address, so email_service._send no-ops instead of
    # mailing whoever was connected last.
    connections.clear()
    profile = business_service.get_profile(ACCOUNT_ID)
    assert profile["email"] == "", profile["email"]
    assert profile["connections"] == {}, profile["connections"]

    # Saving never persists either field, so no stale copy can come back.
    connections["google"] = {"account": "averma@pragetx.com"}
    saved = business_service.save_profile(
        ACCOUNT_ID,
        BusinessProfile(businessName="Dave's Plumbing", mobile="+918849484100",
                        email="typed-by-hand@example.com",
                        connections={"apple": {"account": "spoofed@icloud.com"}}),
    )
    assert "email" not in stored and "connections" not in stored, stored
    assert saved["email"] == "averma@pragetx.com", saved["email"]
    assert saved["connections"] == {"google": {"account": "averma@pragetx.com"}}, saved["connections"]

    print("connections and email follow the connected calendar; neither is persisted")
    print("OK")


if __name__ == "__main__":
    main()
