"""
Writes one paste-ready JSON file per webhook tool into elevenlabs/webhook_tools/
(ElevenLabs: Agent -> Tools -> New tool -> Webhook tool -> Edit as JSON -> paste).

    python elevenlabs/make_webhook_json.py --base-url https://xxxx.ngrok-free.app

The X-Webhook-Secret value is read from TOOL_WEBHOOK_SECRET in .env, so the output
folder contains a secret - it is git-ignored, don't commit or share it.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "webhook_tools"


def read_secret() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("TOOL_WEBHOOK_SECRET"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("TOOL_WEBHOOK_SECRET not found in .env")


def llm(description: str) -> dict:
    return {"type": "string", "description": description}


CALLER_PHONE = {"type": "string", "description": "", "dynamic_variable": "caller_phone"}

ADDRESS_NEW = {
    "unit_type": llm("Exactly 'House' or 'Apartment'"),
    "address_line": llm("Street address"),
    "unit_number": llm("Apartment/unit number. Only set when unit_type is 'Apartment'"),
    "city": llm("City"),
    "state": llm("State"),
    "zip": llm("ZIP / postal code"),
}
ADDRESS_CHANGED = {k: llm(f"New {k.replace('_', ' ')}, only if the address changes") for k in ADDRESS_NEW}

TOOLS = {
    "get_business_hours": dict(
        path="get-business-hours",
        description="Returns the business's opening hours per weekday, plus the current date/time (`now`) and current weekday (`today`). Call this whenever a date or time comes up, before offering or confirming any slot, and take the current date only from `now`.",
        required=[],
        # backend ignores `request`; ElevenLabs rejects an empty body schema. Constant must have EMPTY description.
        properties={"request": {"type": "string", "description": "", "constant_value": "business_hours"}},
    ),
    "list_events": dict(
        path="list-events",
        description="Lists calendar events between two times. Use it to check whether a slot is free, and to find a caller's existing appointment (match their name in the summary). Each event has a `uid` needed for update_event and delete_event.",
        required=["start_iso", "end_iso"],
        properties={
            "start_iso": llm("Start of the window, local time ISO 8601 without timezone, e.g. 2026-11-21T00:00:00"),
            "end_iso": llm("End of the window, local time ISO 8601 without timezone, e.g. 2026-11-21T23:59:59"),
        },
    ),
    "create_event": dict(
        path="create-event",
        description="Books a plumbing appointment on the calendar. Call only after the caller has clearly confirmed name, problem, address, day and time. Sends a text confirmation to the caller.",
        required=["summary", "start_iso", "end_iso", "unit_type", "address_line", "city", "state", "zip"],
        properties={
            "summary": llm("Title, format: 'Plumbing - <caller name> - <short problem>'"),
            "start_iso": llm("Appointment start, local time ISO 8601 without timezone, e.g. 2026-11-21T15:00:00"),
            "end_iso": llm("Appointment end (1 hour after start unless told otherwise), same format"),
            "description": llm("Details of the plumbing problem as the caller described it"),
            **ADDRESS_NEW,
            "price_estimate": llm("The price range you quoted the caller, e.g. '$150 to $400'"),
            "phone_number": CALLER_PHONE,
        },
    ),
    "update_event": dict(
        path="update-event",
        description="Reschedules or edits an existing appointment. Call only after the caller confirmed the change. Send the event's uid (from list_events) and ONLY the fields that change. To reschedule, send start_iso and end_iso. Sends a text confirmation to the caller.",
        required=["uid"],
        properties={
            "uid": llm("The `uid` of the event, exactly as returned by list_events"),
            "start_iso": llm("New start, local time ISO 8601 without timezone. Only when rescheduling"),
            "end_iso": llm("New end, same format. Always send together with start_iso"),
            "summary": llm("New title, only if changing"),
            "description": llm("New notes, only if changing"),
            **ADDRESS_CHANGED,
            "phone_number": CALLER_PHONE,
        },
    ),
    "delete_event": dict(
        path="delete-event",
        description="Cancels an appointment. Call only after the caller clearly confirmed they want to cancel. Sends a text confirmation to the caller.",
        required=["uid"],
        properties={
            "uid": llm("The `uid` of the event, exactly as returned by list_events"),
            "phone_number": CALLER_PHONE,
        },
    ),
}


def _prop(pid: str, p: dict, required: list[str]) -> dict:
    """Dict-style property above -> the array item ElevenLabs' validator expects."""
    value_type = "dynamic_variable" if "dynamic_variable" in p else "constant" if "constant_value" in p else "llm_prompt"
    return {
        "id": pid,
        "type": p["type"],
        "value_type": value_type,
        "description": p["description"],
        "dynamic_variable": p.get("dynamic_variable", ""),
        "constant_value": p.get("constant_value", ""),
        "required": pid in required,
    }


def build(name: str, spec: dict, base_url: str, secret: str) -> dict:
    uses_phone = "phone_number" in spec["properties"]
    return {
        "type": "webhook",
        "name": name,
        "description": spec["description"],
        "api_schema": {
            "url": f"{base_url}/tools/{spec['path']}",
            "method": "POST",
            "path_params_schema": [],
            "query_params_schema": [],
            "request_body_schema": {
                "id": "body",
                "type": "object",
                "required": False,
                "description": "",
                "properties": [_prop(k, v, spec["required"]) for k, v in spec["properties"].items()],
            },
            "request_headers": [{"type": "value", "name": "X-Webhook-Secret", "value": secret}],
            "content_type": "application/json",
            "auth_connection": None,
            "mtls_auth_connection": None,
            "response_filter": None,
        },
        "response_timeout_secs": 20,
        "follow_redirects": False,
        "follow_redirects_allowed_domains": [],
        "dynamic_variables": {"dynamic_variable_placeholders": {"caller_phone": "+919800000001"} if uses_phone else {}},
        "assignments": [],
        "interruption_mode": "allow",
        "pre_tool_speech": "auto",
        "tool_call_sound": None,
        "tool_call_sound_behavior": "auto",
        "execution_mode": "immediate",
        "tool_error_handling_mode": "auto",
        "response_mocks": [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="public https URL of this backend, no trailing slash")
    args = ap.parse_args()
    secret = read_secret()
    OUT.mkdir(exist_ok=True)
    for name, spec in TOOLS.items():
        (OUT / f"{name}.json").write_text(json.dumps(build(name, spec, args.base_url.rstrip("/"), secret), indent=2), encoding="utf-8")
        print("wrote", OUT / f"{name}.json")


if __name__ == "__main__":
    main()
