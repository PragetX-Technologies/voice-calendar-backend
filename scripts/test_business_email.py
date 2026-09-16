"""
Checks that business_profiles.connections/.email track calendar_connections: written
through on every connect/disconnect, and re-derived on read so a drifted profile still
reads correctly. Covers the bug where connecting a different Google account left the
profile (and so the Settings page, and owner confirmation emails) on the old address.

Run manually: python -m scripts.test_business_email (from backend/). No DB: both
collections are stubbed out.
"""
from app import business_service, calendar_connections_service
from app.business_schemas import BusinessProfile

ACCOUNT_ID = "plumber1@business.com"

# The stored business_profiles doc, as it looked with the stale copies in it.
stored: dict = {
    "_id": ACCOUNT_ID,
    "businessName": "Dave's Plumbing",
    "mobile": "+918849484100",
    "email": "demo1.users09092026@gmail.com",
    "connections": {"google": {"account": "demo1.users09092026@gmail.com"}},
}
live: dict[str, dict] = {"google": {"account": "demo1.users09092026@gmail.com"}}


class _FakeProfiles:
    def find_one(self, _query):
        return dict(stored)

    def update_one(self, _query, update):
        stored.update(update["$set"])

    def replace_one(self, _query, doc, upsert=False):
        stored.clear()
        stored.update({"_id": ACCOUNT_ID, **doc})


class _FakeConnections:
    def replace_one(self, _query, doc, upsert=False):
        live[doc["platform"]] = {"account": doc["account"]}

    def delete_one(self, query):
        live.pop(query["_id"].split(":")[-1], None)


class _FakeDb:
    business_profiles = _FakeProfiles()
    calendar_connections = _FakeConnections()


def main() -> None:
    business_service.get_db = lambda: _FakeDb()
    calendar_connections_service.get_db = lambda: _FakeDb()
    calendar_connections_service.public_status = lambda _id: {p: dict(c) for p, c in live.items()}

    # Connecting a different Google account rewrites the stored profile, no re-save needed.
    calendar_connections_service.save_connection(ACCOUNT_ID, "google", "averma@pragetx.com", {"refresh_token": "tok"})
    assert stored["email"] == "averma@pragetx.com", stored["email"]
    assert stored["connections"] == {"google": {"account": "averma@pragetx.com"}}, stored["connections"]

    # ...and the read path agrees.
    assert business_service.get_profile(ACCOUNT_ID)["email"] == "averma@pragetx.com"

    # Disconnecting clears both, so email_service._send no-ops instead of mailing the old owner.
    calendar_connections_service.delete_connection(ACCOUNT_ID, "google")
    assert stored["email"] == "", stored["email"]
    assert stored["connections"] == {}, stored["connections"]

    # A profile save never lets client-supplied values through.
    live["apple"] = {"account": "owner@icloud.com"}
    saved = business_service.save_profile(
        ACCOUNT_ID,
        BusinessProfile(businessName="Dave's Plumbing", mobile="+918849484100",
                        email="typed-by-hand@example.com",
                        connections={"google": {"account": "spoofed@gmail.com"}}),
    )
    assert saved["email"] == "owner@icloud.com", saved["email"]
    assert stored["connections"] == {"apple": {"account": "owner@icloud.com"}}, stored["connections"]

    # A profile that drifted anyway (direct DB edit) still reads correctly.
    stored["email"] = "stale@gmail.com"
    assert business_service.get_profile(ACCOUNT_ID)["email"] == "owner@icloud.com"

    print("business_profiles tracks calendar_connections on connect, disconnect and save")
    print("OK")


if __name__ == "__main__":
    main()
