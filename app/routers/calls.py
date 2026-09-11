"""
This is what YOUR backend calls (e.g. from a cron job, a form submission,
a CRM event) to make the ElevenLabs voice agent place an outbound call.

Requires: a Twilio phone number imported into your ElevenLabs workspace and
linked to your agent (Phone Numbers tab in ElevenLabs dashboard).
"""
import httpx
from fastapi import APIRouter, HTTPException

from app import calendar_connections_service, call_context
from app.config import settings
from app.schemas import TriggerCallRequest
from app.sms_service import _to_e164

router = APIRouter(prefix="/calls", tags=["call-trigger"])

ELEVENLABS_OUTBOUND_CALL_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound_call"


@router.post("/trigger")
async def trigger_call(payload: TriggerCallRequest):
    provider = payload.provider or calendar_connections_service.get_any_platform() or settings.calendar_provider

    if payload.purpose == "reminder":
        agent_id, agent_phone_number_id = settings.elevenlabs_reminder_agent_id, settings.elevenlabs_reminder_agent_phone_number_id
    elif payload.purpose == "booking":
        agent_id, agent_phone_number_id = settings.elevenlabs_agent_id, settings.elevenlabs_agent_phone_number_id
    else:
        raise HTTPException(status_code=400, detail="Unknown purpose, expected 'booking' or 'reminder'")

    to_number = _to_e164(payload.to_number)
    call_context.set_last_to_number(to_number)

    dynamic_variables = {"phone_number": to_number, "provider": provider}
    if payload.customer_name:
        dynamic_variables["customer_name"] = payload.customer_name
    if payload.reason:
        dynamic_variables["reason"] = payload.reason
    if payload.appointment_uid:
        dynamic_variables["appointment_uid"] = payload.appointment_uid
    if payload.appointment_summary:
        dynamic_variables["appointment_summary"] = payload.appointment_summary
    if payload.appointment_time:
        dynamic_variables["appointment_time"] = payload.appointment_time

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
