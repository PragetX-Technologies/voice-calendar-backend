"""
Remembers the phone number and business account of the most recently
triggered outbound call, so tool webhooks (no signed-in session, shared
ElevenLabs agent) know which business the call belongs to and can SMS the
right number even when ElevenLabs doesn't echo back the phone_number
dynamic variable as a tool parameter.

account_id is also set on dashboard login / every authenticated dashboard
request (app.auth.require_account_id), so inbound calls — which never go
through /calls/trigger — resolve to the signed-in business owner.

Persisted in Mongo (not a process-local global) so it survives across
worker processes/instances and restarts between the trigger call and the
webhook calls ElevenLabs makes seconds later.

# ponytail: single doc, not keyed by conversation_id — correct only for one
# business active at a time (a second account signing in mid-call repoints
# that call's webhooks). Upgrade: ElevenLabs conversation-initiation webhook
# mapping called number -> account, stored per conversation_id.
"""
from app.db import get_db

_DOC_ID = "last_call"


def set_last_to_number(to_number: str) -> None:
    get_db().call_context.update_one({"_id": _DOC_ID}, {"$set": {"to_number": to_number}}, upsert=True)


def get_last_to_number() -> str | None:
    doc = get_db().call_context.find_one({"_id": _DOC_ID})
    return doc.get("to_number") if doc else None


def set_last_account_id(account_id: str) -> None:
    get_db().call_context.update_one({"_id": _DOC_ID}, {"$set": {"account_id": account_id}}, upsert=True)


def get_last_account_id() -> str | None:
    doc = get_db().call_context.find_one({"_id": _DOC_ID})
    return doc.get("account_id") if doc else None
