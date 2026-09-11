"""
Real calendar-connect flows for the business onboarding/settings UI:

- Google: standard OAuth2 authorization-code flow, run in a popup window.
  /google/authorize redirects to Google's consent screen; /google/callback
  exchanges the code for a refresh token, looks up the account email, saves
  it, then serves a tiny HTML page that postMessages the result back to the
  window.opener and closes itself.
- Apple: no public consumer OAuth for iCloud CalDAV. The user pastes an
  app-specific password generated at appleid.apple.com; /apple/connect
  verifies it with a real CalDAV login before saving it.

Every connection is scoped to the signed-in business account. The Google leg
is a top-level browser navigation (window.open), so it can't carry an
Authorization header — the frontend passes the JWT as a query param instead,
which we decode once and thread through the OAuth `state` round-trip.
Credentials are stored via calendar_connections_service, not returned to the
frontend — only /connections (account email, no secrets) is.
"""
import json
import logging
import secrets

import caldav
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel

from app import calendar_connections_service as connections
from app.auth import decode_account_id, require_account_id
from app.config import settings

logger = logging.getLogger("oauth")

router = APIRouter(prefix="/oauth", tags=["oauth"])

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

# ponytail: in-memory state -> account_id map — fine for a single dev process;
# move to Mongo with a TTL index if this ever runs behind more than one worker.
_pending_states: dict[str, str] = {}


def _google_flow() -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_oauth_redirect_uri],
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=settings.google_oauth_redirect_uri,
    )


def _popup_response(ok: bool, platform: str, account: str | None = None, error: str | None = None) -> HTMLResponse:
    payload = json.dumps({"type": "calendar-oauth", "ok": ok, "platform": platform, "account": account, "error": error})
    message = "Connected — you can close this window." if ok else f"Connection failed: {error}"
    html = f"""<!doctype html><html><body style="font-family:sans-serif;padding:24px">
<script>
  if (window.opener) {{
    window.opener.postMessage({payload}, {json.dumps(settings.frontend_base_url)});
  }}
  window.close();
</script>
<p>{message}</p>
</body></html>"""
    return HTMLResponse(html)


@router.get("/google/authorize")
def google_authorize(token: str = Query(..., description="Business account's JWT access token")):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET missing)")

    account_id = decode_account_id(token)

    flow = _google_flow()
    state = secrets.token_urlsafe(24)
    _pending_states[state] = account_id
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return RedirectResponse(auth_url)


@router.get("/google/callback")
def google_callback(code: str = Query(...), state: str = Query(...)):
    account_id = _pending_states.pop(state, None)
    if account_id is None:
        return _popup_response(ok=False, platform="google", error="Invalid or expired OAuth state")

    if connections.get_connection(account_id, "apple") is not None:
        return _popup_response(ok=False, platform="google", error="Apple Calendar is already connected — disconnect it first, then connect Google.")

    try:
        flow = _google_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials

        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        resp.raise_for_status()
        email = resp.json().get("email", "")

        if not creds.refresh_token:
            raise RuntimeError("Google did not return a refresh token — revoke prior access at myaccount.google.com/permissions and try again")

        connections.save_connection(account_id, "google", email, {"refresh_token": creds.refresh_token})
        return _popup_response(ok=True, platform="google", account=email)
    except Exception as e:
        logger.exception("google_callback failed")
        return _popup_response(ok=False, platform="google", error=str(e))


class AppleConnectBody(BaseModel):
    email: str
    app_specific_password: str


@router.post("/apple/connect")
def apple_connect(payload: AppleConnectBody, account_id: str = Depends(require_account_id)):
    if connections.get_connection(account_id, "google") is not None:
        raise HTTPException(status_code=400, detail="Google Calendar is already connected — disconnect it first, then connect Apple.")
    try:
        client = caldav.DAVClient(
            url=settings.apple_caldav_url,
            username=payload.email,
            password=payload.app_specific_password,
        )
        calendars = client.principal().calendars()
        if not calendars:
            raise RuntimeError("Signed in, but no calendars were found on this Apple ID")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not connect to iCloud calendar: {e}")

    connections.save_connection(account_id, "apple", payload.email, {"app_specific_password": payload.app_specific_password})
    return {"account": payload.email}


@router.get("/connections")
def list_connections(account_id: str = Depends(require_account_id)):
    return connections.public_status(account_id)


@router.delete("/{platform}/connection")
def disconnect(platform: str, account_id: str = Depends(require_account_id)):
    if platform not in connections.PLATFORMS:
        raise HTTPException(status_code=404, detail="Unknown platform")
    connections.delete_connection(account_id, platform)
    return {"status": "disconnected"}
