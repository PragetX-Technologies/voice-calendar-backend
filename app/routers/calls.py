"""
This is what YOUR backend calls (e.g. from a cron job, a form submission,
a CRM event) to make the ElevenLabs voice agent place an outbound call.

Requires: a Twilio phone number imported into your ElevenLabs workspace and
linked to your agent (Phone Numbers tab in ElevenLabs dashboard).
"""
import httpx
from fastapi import APIRouter, HTTPException

from app import call_context
from app.config import settings
from app.schemas import TriggerCallRequest
from app.sms_service import _to_e164

router = APIRouter(prefix="/calls", tags=["call-trigger"])

ELEVENLABS_OUTBOUND_CALL_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound_call"

_AGENTS = {
    "google": (settings.elevenlabs_google_agent_id, settings.elevenlabs_google_agent_phone_number_id),
    "apple": (settings.elevenlabs_apple_agent_id, settings.elevenlabs_apple_agent_phone_number_id),
}


@router.post("/trigger")
async def trigger_call(payload: TriggerCallRequest):
    provider = payload.provider or settings.calendar_provider
    if provider not in _AGENTS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}', expected one of {list(_AGENTS)}")
    agent_id, agent_phone_number_id = _AGENTS[provider]

    to_number = _to_e164(payload.to_number)
    call_context.set_last_to_number(to_number)

    dynamic_variables = {"phone_number": to_number, "provider": provider}
    if payload.customer_name:
        dynamic_variables["customer_name"] = payload.customer_name
    if payload.reason:
        dynamic_variables["reason"] = payload.reason

    body = {
        "agent_id": agent_id,
        "agent_phone_number_id": agent_phone_number_id,
        "to_number": to_number,
        "conversation_initiation_client_data": {
            "dynamic_variables": dynamic_variables
        },
    }

    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(ELEVENLABS_OUTBOUND_CALL_URL, json=body, headers=headers)

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return resp.json()
