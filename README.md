# Voice Agent × Apple Calendar Backend

Connects your ElevenLabs voice agent to a user's Apple (iCloud) Calendar via CalDAV.
Handles two flows:

1. **Trigger a call** — your backend tells ElevenLabs to call the user.
2. **Live tool calls** — while on the call, the agent hits your webhooks to create/list/update/delete calendar events.

## 1. Get an Apple app-specific password (required — real Apple ID password won't work)

1. Go to https://appleid.apple.com → Sign-In and Security → App-Specific Passwords
2. Generate one, copy it (format `xxxx-xxxx-xxxx-xxxx`)
3. Put it, plus the Apple ID email, into `.env`

## 2. Set up `.env`

```bash
cp .env.example .env
# fill in APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, ELEVENLABS_API_KEY,
# ELEVENLABS_AGENT_ID, ELEVENLABS_AGENT_PHONE_NUMBER_ID, TOOL_WEBHOOK_SECRET
```

`TOOL_WEBHOOK_SECRET` — make up any long random string. This is what protects your
`/tools/*` endpoints from being called by anyone other than ElevenLabs.

`ELEVENLABS_AGENT_PHONE_NUMBER_ID` — you get this after importing a Twilio number
into ElevenLabs (Phone Numbers tab) and linking it to your agent.

## 3. Install & run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Expose it publicly for ElevenLabs to reach (during dev, use ngrok):

```bash
ngrok http 8000
```

## 4. Configure the ElevenLabs agent's Server Tools

In the ElevenLabs dashboard, on your agent → **Tools** → **Add Tool** → **Webhook**,
create these four, each pointing at your public URL + path below, method `POST`,
with a custom header `X-Webhook-Secret: <your TOOL_WEBHOOK_SECRET>` on every one.

### `list_events`
`POST https://<your-ngrok-domain>/tools/list-events`
Body params (let the LLM fill these from conversation):
- `start_iso` (string, required) — e.g. `2026-07-25T00:00:00`
- `end_iso` (string, required) — e.g. `2026-07-26T00:00:00`

Use this before booking, so the agent can check for conflicts and offer real slots.

### `create_event`
`POST https://<your-ngrok-domain>/tools/create-event`
- `summary` (string, required)
- `start_iso` (string, required)
- `end_iso` (string, required)
- `description` (string, optional)
- `location` (string, optional)

### `update_event`
`POST https://<your-ngrok-domain>/tools/update-event`
- `uid` (string, required) — the agent should have this from a prior create/list call in the same conversation
- `summary`, `start_iso`, `end_iso`, `description`, `location` (all optional)

### `delete_event`
`POST https://<your-ngrok-domain>/tools/delete-event`
- `uid` (string, required)

**System prompt tip:** tell the agent explicitly to call `list_events` first when
booking/rescheduling to check for conflicts, and to keep track of the `uid`
returned by `create_event`/`list_events` in conversation memory so it can
reference it later in the same call for updates/cancellations.

## 5. Trigger an outbound call

From your own backend/cron/CRM webhook:

```bash
curl -X POST https://<your-ngrok-domain>/calls/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "to_number": "+919812345678",
    "customer_name": "Rohan",
    "reason": "Following up on your plumbing quote request"
  }'
```

`customer_name` and `reason` are passed to the agent as dynamic variables — use
`{{customer_name}}` / `{{reason}}` in your agent's first message / system prompt
in the ElevenLabs dashboard to personalize the call.

## Notes / next steps

- **Multi-user**: right now credentials are one hardcoded account in `.env`.
  When you're ready to support many users, replace `app/config.py`'s Apple
  fields with a lookup (DB) keyed by `user_id`, and pass `user_id` as a
  dynamic variable at call-trigger time so ElevenLabs includes it in every
  tool call back to you (add it as a parameter on each tool, or as a header
  via a `secret__user_id` dynamic variable).
- **Timezones**: `DEFAULT_TIMEZONE` is applied to any ISO datetime without
  explicit tz info. Adjust in `.env` if needed.
- **Encrypt credentials at rest** once you move to a real DB — app-specific
  passwords are still sensitive.

## Smart IVR branch (`SmartIVR`) — text API for Interactive Powers' IVR

Same backend plus `POST /smartivr` (Smart IVR sends each caller utterance as text; we reply `ask` / `info` / `transfer` / `hangup`).
The reply text comes from a dedicated **text-only ElevenLabs agent**; it uses the same `/tools/*` calendar webhooks.
Files: `app/routers/smartivr.py`, `app/ivr_sessions.py`, agent prompt in `elevenlabs/ivr_prompt.md`.
Auth: Smart IVR sends `Authorization: Bearer <SMARTIVR_TOKEN>`.

### Extra `.env` values

```
SMARTIVR_TOKEN=<long random string, give this to Smart IVR>   # python -c "import secrets;print(secrets.token_urlsafe(32))"
ELEVENLABS_IVR_AGENT_ID=<agent id of the text-only IVR agent>
IVR_ACCOUNT_ID=<business account (login email) that IVR bookings belong to>
IVR_TRANSFER_DEST=<number/extension Smart IVR transfers to>
IVR_QUIET_SECONDS=0            # optional; 0 (default) = reply the moment the agent answers, higher = wait for a further part (slower)
```

`CALENDAR_PROVIDER` (+ the matching `GOOGLE_*` or `APPLE_*` values) is global: it also switches the calendar used by the Aura/Echo agents.
Run **one** uvicorn worker (IVR sessions live in process memory) — no `--workers N`.

### Test locally

```bash
python -m scripts.seed_ivr_demo                      # one-time: business profile + hours for IVR_ACCOUNT_ID
python scripts/fake_smartivr.py --token <SMARTIVR_TOKEN> --say "Hi, is anyone available today?"
```

### Deploy this branch on the server (EC2)

```bash
cd ~/voice-calendar-backend
git fetch origin && git checkout SmartIVR && git pull origin SmartIVR
source venv/bin/activate && pip install -r requirements.txt
nano .env                                            # add the values above
python -m scripts.seed_ivr_demo                      # first time only
# restart however the app is run (find out with: systemctl list-units | grep -i -E "uvicorn|voice"  or  ps aux | grep uvicorn)
sudo systemctl restart <service-name>
```

Then in ElevenLabs point the IVR agent's 4 webhook tools at `https://<your-domain>/tools/...`, and give Smart IVR `https://<your-domain>/smartivr` + the token.
To go back to the voice-agent-only version: `git checkout main && git pull`, restart the service (the extra `.env` lines are ignored).
