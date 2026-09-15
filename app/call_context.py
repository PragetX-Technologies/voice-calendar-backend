"""
Remembers the phone number and business account of the most recently
triggered outbound call, so tool webhooks (no signed-in session, shared
ElevenLabs agent) know which business the call belongs to and can SMS the
right number even when ElevenLabs doesn't echo back the phone_number
dynamic variable as a tool parameter.

# ponytail: single globals, not keyed by conversation_id — correct only for
# one call in flight at a time. Upgrade to a dict keyed by conversation_id
# once ElevenLabs tool payloads carry it, or once concurrent calls matter.
"""
_last_to_number: str | None = None
_last_account_id: str | None = None


def set_last_to_number(to_number: str) -> None:
    global _last_to_number
    _last_to_number = to_number


def get_last_to_number() -> str | None:
    return _last_to_number


def set_last_account_id(account_id: str) -> None:
    global _last_account_id
    _last_account_id = account_id


def get_last_account_id() -> str | None:
    return _last_account_id
