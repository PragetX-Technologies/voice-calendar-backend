"""
Sends booking confirmation emails over Gmail SMTP, using GOOGLE_SENDER_ID +
its app-specific password.

Best-effort only: a failed send is logged and swallowed, never raised, so
it can never fail or roll back the calendar operation it follows.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent

from app.config import settings

logger = logging.getLogger("email_service")

PRIVACY_NOTE = (
    "Your personal details are stored securely and will not be shared directly "
    "with the plumber. The plumber will contact you using our business number "
    "+44 2046000841, so your personal number remains private."
)


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(settings.default_timezone))
    return dt


def _build_ics(uid: str, summary: str, start_iso: str, end_iso: str, location: str = "", method: str = "REQUEST", status: str = "CONFIRMED") -> bytes:
    """Builds a .ics invite so mail clients offer an 'Add to Calendar' action."""
    ical = ICalendar()
    ical.add("prodid", "-//Voice Calendar Agent//EN")
    ical.add("version", "2.0")
    ical.add("method", method)

    vevent = IEvent()
    vevent.add("uid", uid)
    vevent.add("summary", summary)
    vevent.add("dtstart", _parse_dt(start_iso))
    vevent.add("dtend", _parse_dt(end_iso))
    vevent.add("dtstamp", datetime.now(ZoneInfo("UTC")))
    vevent.add("status", status)
    if location:
        vevent.add("location", location)
    vevent.add("organizer", f"mailto:{settings.google_sender_id}")
    vevent.add("attendee", f"mailto:{settings.booking_notification_email}")

    ical.add_component(vevent)
    return ical.to_ical()


def _send(subject: str, body: str, to_email: str | None = None, ics_bytes: bytes | None = None, ics_method: str = "REQUEST") -> None:
    to_email = to_email or settings.booking_notification_email
    if not to_email:
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.google_sender_id
        msg["To"] = to_email
        msg.set_content(f"{body}\n{PRIVACY_NOTE}\n")

        if ics_bytes is not None:
            msg.add_attachment(
                ics_bytes,
                maintype="text",
                subtype="calendar",
                filename="invite.ics",
                params={"method": ics_method, "name": "invite.ics"},
            )

        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=60) as server:
                server.login(settings.google_sender_id, settings.google_sender_app_specific_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60) as server:
                server.starttls()
                server.login(settings.google_sender_id, settings.google_sender_app_specific_password)
                server.send_message(msg)

        logger.info("Email sent: %s -> %s", subject, to_email)
    except Exception:
        logger.exception(
            "Failed to send email: subject=%s smtp_host=%s smtp_port=%s to=%s",
            subject, settings.smtp_host, settings.smtp_port, to_email,
        )


def send_booking_confirmation(uid: str, summary: str, start_iso: str, end_iso: str, location: str = "", price_estimate: str | None = None, email: str | None = None) -> None:
    body = (
        f"Your appointment has been booked.\n\n"
        f"Summary: {summary}\n"
        f"Start: {start_iso}\n"
        f"End: {end_iso}\n"
        f"Location: {location or '-'}\n"
    )
    if price_estimate:
        body += f"Estimated cost: {price_estimate} (technician confirms final price on site)\n"
    ics = _build_ics(uid, summary, start_iso, end_iso, location, method="REQUEST", status="CONFIRMED")
    _send("Booking Confirmation", body, to_email=email, ics_bytes=ics, ics_method="REQUEST")


def send_update_confirmation(uid: str, summary: str | None, start_iso: str | None, end_iso: str | None, location: str | None = None, email: str | None = None) -> None:
    body = (
        f"Your appointment has been updated.\n\n"
        f"UID: {uid}\n"
        f"Summary: {summary or '-'}\n"
        f"Start: {start_iso or '-'}\n"
        f"End: {end_iso or '-'}\n"
        f"Location: {location or '-'}\n"
    )
    ics = None
    if summary and start_iso and end_iso:
        ics = _build_ics(uid, summary, start_iso, end_iso, location or "", method="REQUEST", status="CONFIRMED")
    _send("Booking Update Confirmation", body, to_email=email, ics_bytes=ics, ics_method="REQUEST")


def send_cancellation_confirmation(uid: str, email: str | None = None) -> None:
    body = f"Your appointment has been cancelled.\n\nUID: {uid}\n"
    _send("Booking Cancellation Confirmation", body, to_email=email)
