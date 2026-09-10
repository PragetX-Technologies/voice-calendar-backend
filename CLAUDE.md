# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000   # run dev server
ngrok http 8000                              # expose for ElevenLabs webhooks during dev
```

No test suite, linter, or build step configured in this repo.

## Architecture

FastAPI backend bridging an ElevenLabs voice agent to a business's calendar (Apple iCloud via CalDAV, or Google Calendar), plus a multi-tenant dashboard (business signup/login, calendar connect, profile). Two calendar accounts per business: "user" (the caller's own calendar, credentials hardcoded in `.env`) and "provider" (the signed-in business owner's calendar, connected via the dashboard). Writes mirror to both — see `_mirror_to_provider` in each calendar service.

### Request directions

1. **Outbound trigger** (`app/routers/calls.py`, `POST /calls/trigger`) — this backend calls ElevenLabs' API to place a call, passing `customer_name`/`reason` as dynamic variables the agent's prompt can reference. There's one ElevenLabs agent per calendar provider (`ELEVENLABS_GOOGLE_AGENT_ID`/`ELEVENLABS_APPLE_AGENT_ID` + matching phone number id in `.env`); the request's `provider` field picks which agent/phone number places the call, falling back to `CALENDAR_PROVIDER` if omitted.
2. **Inbound tool webhooks** (`app/routers/tools.py`, `POST /tools/*`) — ElevenLabs calls back into this backend mid-conversation when the agent decides to list/create/update/delete a calendar event, or fetch business working hours (`get-business-hours`, for availability checks). Every route is gated by `verify_webhook_secret` (`X-Webhook-Secret` header vs `TOOL_WEBHOOK_SECRET`) — the only auth here, since this path has no signed-in session. No `business_account_id` context either; calendar and business-profile lookups fall back to "whichever business has this provider connected" (`calendar_connections_service.get_any_connection`, `business_service.get_any_profile`) — single-tenant assumption, noted as `# ponytail:` in that file. `create`/`update`/`delete-event` each fire background SMS/email confirmations to both the customer (`phone_number`/`email` from the call) and the business owner (`business_profiles.mobile`/`.email`, via `_owner_contact`) — same message mirrored to both.
3. **Dashboard API** (`app/routers/auth.py`, `business.py`, `oauth.py`, `calendar_view.py`) — JWT-bearer-scoped endpoints for the frontend. Every route depends on `require_account_id` (`app/auth.py`) to scope reads/writes to the signed-in business.
4. **Reminder call sweep** (`app/reminder_job.py`, `run_reminder_sweep`) — `BackgroundScheduler` job wired via `lifespan` in `main.py`, runs every 15 min. Queries `calendar_events` for upcoming appointments (next 24h, `reminder_sent != True`), places a call per match through the same in-process trigger logic as `POST /calls/trigger`, then marks `reminder_sent: true`. No retry/backoff on failed calls.

### Calendar layer

`app/calendar_service.py` dispatches to whichever backend is active (`settings.calendar_provider`) for the ElevenLabs tool-webhook path only (no `business_account_id`, no `account` param — always "user"). `app/routers/calendar_view.py` (dashboard path) calls `caldav_service`/`google_calendar_service` directly instead, since it needs `account`/`business_account_id` threaded through. Both backends expose the same four functions (`list_events`/`create_event`/`update_event`/`delete_event`), each taking `account` ("user"/"provider") and `business_account_id`:

- `app/caldav_service.py` — Apple iCloud via CalDAV. Per-account client/calendar cache (`_clients`/`_calendars`, keyed by `_client_cache_key`). "user" auth is an app-specific password from `.env`; "provider" auth comes from `calendar_connections_service`. `update_event`/`delete_event` look up the target event via `_find_event_by_uid` — a wide `date_search` (1yr past/2yr future) with manual UID matching, not `calendar.event_by_uid()`, since iCloud's CalDAV server 412s on UID-only queries with no time-range.
- `app/google_calendar_service.py` — Google Calendar API v3, same account/provider split. "user" auth is a long-lived refresh token in `.env` (`scripts/google_oauth_setup.py` mints one interactively); "provider" auth comes from `calendar_connections_service`. `uid` for Google events is the Google event id (client-assigned via `uuid.uuid4().hex` at create, so both accounts' mirrored events share the same id).

Provider choice is per-request: every tool webhook schema has an optional `provider` field (`"apple"`/`"google"`), falling back to `CALENDAR_PROVIDER` in `.env`. This supports running two ElevenLabs agents against one backend, each pointed at its own calendar. `POST /calls/trigger` (`app/routers/calls.py`) sets a `provider` dynamic variable at call start (same mechanism as `phone_number`) so the agent doesn't have to guess which calendar it's talking to — the ElevenLabs tool config must default each tool's `provider` param to `{{provider}}` (dashboard-side config, not code) for this to reach the webhook calls. All datetimes without explicit tz info are assumed to be `settings.default_timezone` (each service has its own `_parse_dt`).

### MongoDB (`app/db.py`, `get_db()`)

Module-level `MongoClient` singleton (`MONGODB_URI`/`MONGODB_DB_NAME` in `.env`), same lazy-cache pattern as the CalDAV client. Collections, one service module each:

- No `accounts` collection — single hardcoded owner account (`accounts_service.py`), checked against `OWNER_USERNAME`/`OWNER_PASSWORD` in `.env`, fixed id `"owner"`. No signup.
- `business_profiles` (`business_service.py`) — business profile (contact/hours/job types), keyed by account id. `hours` (`business_schemas.DayHours` per weekday) drives availability checks: agent calls `get-business-hours` before offering/confirming a slot, no backend-side enforcement (prompt-trust only). `get_any_profile(provider)` is the webhook-path fallback lookup, same pattern as `calendar_connections_service.get_any_connection`.
- `calendar_connections` (`calendar_connections_service.py`) — per-(account, platform) "provider" calendar credentials (refresh token / app-specific password), kept separate from `business_profiles` so secrets never round-trip through the profile GET/PUT. Stored plaintext (`# ponytail:` note to encrypt later).
- `calendar_events` (`calendar_events_service.py`) — a synced *read cache* of every calendar event, mirrored on every create/update/delete from both `tools.py` and `calendar_view.py` (`$set`-based `upsert_event`, `delete_event`), now storing `phone_number`/`email`/`reminder_sent` too. The live calendar (CalDAV/Google) stays source of truth; `app/reminder_job.py`'s sweep reads this cache to find appointments due a reminder call. `sync_range()` backfills a date range from the live calendar for events that predate this cache — not wired to any endpoint, call manually when needed. Events created before the `phone_number`/`email`/`reminder_sent` fields existed lack them (no backfill migration run).

`app/config.py` defines `Settings` (pydantic-settings), loaded from `.env` — all credentials, JWT secret, Mongo URI, etc. `app/schemas.py` holds tool-webhook + call-trigger request models; `app/business_schemas.py` and `app/auth_schemas.py` hold their respective routers' models.

All routers log every request payload and, on failure, the full exception traceback (`logging.basicConfig` set up in `main.py`) — check the uvicorn console when a live agent call fails, since ElevenLabs only ever hears the agent's generic "having trouble" fallback line.

### SMS / email

`app/sms_service.py` and `app/email_service.py` each append a fixed `PRIVACY_NOTE` to every message in `_send()` (one place, not per-caller). Both take an optional recipient override (`to_number`/`email`); `email_service._send` falls back to `settings.booking_notification_email` if none given. Phone numbers are normalized to E.164 via `sms_service._to_e164()` (uses `settings.default_sms_country_code`, `"+91"`) — also imported into `app/routers/calls.py` so outbound-call `to_number` gets the same treatment, not just SMS.
