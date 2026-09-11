"""
Centralized configuration, loaded from environment variables (.env file).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Which calendar backend is active ---
    calendar_provider: str = "apple"  # "apple" or "google"

    # --- Apple iCloud CalDAV (used when calendar_provider == "apple") ---
    # The "user" account below is still hardcoded here; the "provider" (business)
    # account instead comes from calendar_connections_service, populated by the
    # UI's "Connect Apple Calendar" flow — see app/caldav_service.py.
    apple_id: str = ""  # e.g. someone@icloud.com
    apple_app_specific_password: str = ""  # generated at appleid.apple.com
    apple_caldav_url: str = "https://caldav.icloud.com"
    calendar_name: str | None = None  # if None, uses the first/default calendar found
    default_timezone: str = "Asia/Kolkata"  # used when creating events

    # --- Google Calendar (used when calendar_provider == "google") ---
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""  # obtained once via scripts/google_oauth_setup.py
    google_calendar_id: str = "primary"

    # --- Google OAuth (business "Connect Google Calendar" flow, app/routers/oauth.py) ---
    google_oauth_redirect_uri: str = "http://localhost:8000/oauth/google/callback"
    frontend_base_url: str = "http://localhost:5173"  # postMessage target origin after OAuth popup completes

    # --- ElevenLabs: one booking agent per calendar provider, picked at call-trigger time ---
    elevenlabs_api_key: str
    elevenlabs_google_agent_id: str = ""
    elevenlabs_google_agent_phone_number_id: str = ""
    elevenlabs_apple_agent_id: str = ""
    elevenlabs_apple_agent_phone_number_id: str = ""

    # --- ElevenLabs: one reminder-call agent (Echo), regardless of calendar provider ---
    elevenlabs_reminder_agent_id: str = ""
    elevenlabs_reminder_agent_phone_number_id: str = ""

    # --- Security for the webhook tool endpoints ElevenLabs will call mid-conversation ---
    tool_webhook_secret: str

    # --- Booking confirmation emails (sent via Gmail SMTP) ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    google_sender_id: str = ""  # e.g. someone@gmail.com
    google_sender_app_specific_password: str = ""  # generated at myaccount.google.com/apppasswords
    user_email: str = ""  # caller's confirmation email — hardcoded here, agent no longer asks for it on the call

    # --- Booking confirmation SMS (sent via Twilio) ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""  # Twilio number SMS is sent from, E.164
    twilio_status_callback_url: str = ""  # e.g. https://voice-calendar-backend.pragetx.ai/api/sms/webhook
    default_sms_country_code: str = "+91"  # prepended when phone_number arrives without a '+' (e.g. raw caller ID)

    # --- MongoDB (business profile storage) ---
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "voice_calendar"

    # --- Business owner auth (single hardcoded account, JWT bearer tokens) ---
    owner_username: str
    owner_password: str
    jwt_secret: str
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
