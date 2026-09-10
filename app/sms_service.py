"""
Sends booking confirmation SMS via Twilio's REST API (plain httpx POST, no
twilio SDK needed since httpx is already a dependency).

Best-effort only: a failed send is logged and swallowed, never raised, so
it can never fail or roll back the calendar operation it follows.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("sms_service")

TWILIO_MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

PRIVACY_NOTE = (
    "Your personal details are stored securely and will not be shared directly "
    "with the plumber. The plumber will contact you using our business number "
    "+44 2046000841, so your personal number remains private."
)


def _to_e164(raw: str) -> str:
    """Twilio requires E.164 (+<country><number>); raw caller IDs / LLM-filled
    params sometimes arrive as a bare local number, e.g. '9691169650'."""
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if digits.startswith("+"):
        return digits
    return settings.default_sms_country_code + digits


def _send(to_number: str | None, body: str) -> None:
    if not to_number:
        logger.warning("SMS skipped: no to_number (phone_number missing from tool payload)")
        return
    if not settings.twilio_account_sid:
        logger.warning("SMS skipped: TWILIO_ACCOUNT_SID not configured")
        return
    to_number = _to_e164(to_number)
    body = f"{body}\n{PRIVACY_NOTE}"
    try:
        url = TWILIO_MESSAGES_URL.format(sid=settings.twilio_account_sid)
        data = {"From": settings.twilio_from_number, "To": to_number, "Body": body}
        if settings.twilio_status_callback_url:
            data["StatusCallback"] = settings.twilio_status_callback_url
        logger.info("SMS sending -> %s from=%s", to_number, settings.twilio_from_number)
        resp = httpx.post(
            url,
            data=data,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.error("SMS failed to=%s status=%s body=%s", to_number, resp.status_code, resp.text)
            return
        resp.raise_for_status()
        sid = resp.json().get("sid")
        logger.info("SMS sent -> %s sid=%s", to_number, sid)
    except Exception:
        logger.exception("SMS send raised to=%s", to_number)


def send_booking_confirmation(to_number: str | None, summary: str, start_iso: str, end_iso: str, location: str = "", price_estimate: str | None = None) -> None:
    body = f"Appointment booked: {summary}\nStart: {start_iso}\nEnd: {end_iso}"
    if location:
        body += f"\nLocation: {location}"
    if price_estimate:
        body += f"\nEstimated cost: {price_estimate} (technician confirms final price on site)"
    _send(to_number, body)


def send_update_confirmation(to_number: str | None, summary: str | None, start_iso: str | None, end_iso: str | None, location: str | None = None) -> None:
    body = f"Appointment updated: {summary or '-'}\nStart: {start_iso or '-'}\nEnd: {end_iso or '-'}"
    if location:
        body += f"\nLocation: {location}"
    _send(to_number, body)


def send_cancellation_confirmation(to_number: str | None) -> None:
    _send(to_number, "Your appointment has been cancelled.")
