"""
Checks that the calendar client caches are invalidated when a business reconnects a
different calendar account — the bug where the dashboard kept showing the previously
connected calendar's events until the server was restarted.

Run manually: python -m scripts.test_calendar_cache (from backend/). No network or DB:
the connection lookup and the CalDAV/Google client constructors are stubbed out.
"""
from app import caldav_service, google_calendar_service

ACCOUNT_ID = "owner@business.com"


class _FakeCalendar:
    def __init__(self, name):
        self.name = name


class _FakeDavClient:
    def __init__(self, url, username, password):
        self.username = username

    def principal(self):
        return self

    def calendars(self):
        return [_FakeCalendar(self.username)]


def _check_caldav() -> None:
    connection = {"account": "first@icloud.com", "app_specific_password": "pw-one"}

    caldav_service._calendars.clear()
    caldav_service.calendar_connections_service.get_any_connection = lambda _id, _p: connection
    caldav_service.caldav.DAVClient = _FakeDavClient
    caldav_service.settings.calendar_name = None

    first = caldav_service._get_calendar("provider", ACCOUNT_ID)
    assert first.name == "first@icloud.com", first.name

    cached = caldav_service._get_calendar("provider", ACCOUNT_ID)
    assert cached is first, "same credentials should reuse the cached calendar"

    # The business disconnects and connects a different Apple ID.
    connection = {"account": "second@icloud.com", "app_specific_password": "pw-two"}
    after_reconnect = caldav_service._get_calendar("provider", ACCOUNT_ID)
    assert after_reconnect.name == "second@icloud.com", after_reconnect.name

    # Rotating the app-specific password on the same Apple ID also has to rebuild.
    connection = {"account": "second@icloud.com", "app_specific_password": "pw-three"}
    rotated = caldav_service._get_calendar("provider", ACCOUNT_ID)
    assert rotated is not after_reconnect, "rotated password should rebuild the client"

    print("caldav_service: cache invalidates on reconnect")


def _check_google() -> None:
    connection = {"refresh_token": "token-one"}
    built = []

    google_calendar_service._services.clear()
    google_calendar_service.calendar_connections_service.get_any_connection = lambda _id, _p: connection
    google_calendar_service.build = lambda *_a, credentials, **_kw: built.append(credentials.refresh_token) or object()

    google_calendar_service._get_service("provider", ACCOUNT_ID)
    google_calendar_service._get_service("provider", ACCOUNT_ID)
    assert built == ["token-one"], f"same token should build one service, got {built}"

    # The business disconnects and connects a different Google account.
    connection = {"refresh_token": "token-two"}
    google_calendar_service._get_service("provider", ACCOUNT_ID)
    assert built == ["token-one", "token-two"], f"new token should rebuild, got {built}"

    print("google_calendar_service: cache invalidates on reconnect")


if __name__ == "__main__":
    _check_caldav()
    _check_google()
    print("OK")
