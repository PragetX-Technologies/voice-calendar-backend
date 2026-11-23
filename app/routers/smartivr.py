"""
Smart IVR <-> PragetX agent: the HTTP "four-verb" contract.

Smart IVR does STT/TTS and POSTs each caller utterance here; we answer with
one of ask / info / transfer / hangup. The reply text comes from an
ElevenLabs text-only agent (app/ivr_sessions.py), which calls the existing
/tools/* webhooks for calendar work.
"""
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app import ivr_sessions
from app.config import settings

logger = logging.getLogger("smartivr")

router = APIRouter(tags=["smartivr"])
_bearer = HTTPBearer(auto_error=False)  # also gives Swagger an "Authorize" button

LANG = "en-US"  # ponytail: English only for now; make per-session when other languages are needed


def verify_token(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    expected = settings.smartivr_token
    if not expected or creds is None or not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


class IvrRequest(BaseModel):
    id: str = Field(..., description="Conversation id, PHONE-CALLTIMESTAMP, e.g. 666555444-1784037502")
    text: str = Field("", description="Caller's transcribed speech; empty after an 'info' reply")


class MetadataItem(BaseModel):
    name: str
    value: str


class IvrResponse(BaseModel):
    type: str  # ask | info | transfer | hangup
    text: str | None = None
    lang: str | None = None
    dest: str | None = None
    metadata: list[MetadataItem] | None = None


def _is_hangup_text(text: str) -> bool:
    phrases = {p.strip().lower() for p in settings.ivr_hangup_phrases.split(",") if p.strip()}
    return text.strip().lower() in phrases


def _action_response(session: ivr_sessions.IvrSession) -> IvrResponse:
    if session.pending_action == "transfer":
        return IvrResponse(
            type="transfer",
            dest=settings.ivr_transfer_dest,
            metadata=[
                MetadataItem(name="X-TicketID", value=session.ticket_id),
                MetadataItem(name="X-CustomerPhone", value=session.phone),
                MetadataItem(name="X-TransferReason", value=session.transfer_reason),
                MetadataItem(name="X-CallSummary", value=session.summary),
            ],
        )
    return IvrResponse(type="hangup")


@router.post("/smartivr", response_model=IvrResponse, response_model_exclude_none=True, dependencies=[Depends(verify_token)])
async def smartivr(
    payload: IvrRequest,
    x_phone: str = Header(default="", description="Caller's phone as seen by Smart IVR"),
    x_destination: str = Header(default="", description="Number the caller dialed"),
):
    logger.info("smartivr id=%s phone=%s destination=%s text=%r", payload.id, x_phone, x_destination, payload.text)

    # Caller hung up (agreed marker text): free the ElevenLabs socket, nothing to say back.
    if _is_hangup_text(payload.text):
        await ivr_sessions.close(payload.id)
        return IvrResponse(type="hangup")

    text = payload.text.strip()
    try:
        session = await ivr_sessions.get_or_create(payload.id, x_phone, x_destination)
    except Exception:
        logger.exception("could not open agent session")
        return IvrResponse(type="ask", text="Sorry, I'm having trouble right now. Please try again.", lang=LANG)

    async with session.lock:
        ivr_sessions.touch(session)

        # A transfer/hangup was announced last turn (sent as 'info'); Smart IVR has now called back empty.
        if session.pending_action and not text:
            response = _action_response(session)
            if response.type == "hangup":
                await ivr_sessions.close(payload.id)
            return response

        # Last turn returned the agent's "one moment" line as 'info' while a tool ran: fetch the real answer now.
        if session.continuing and not text:
            try:
                reply = await ivr_sessions.resume(session)
            except Exception:
                logger.exception("agent resume failed id=%s", payload.id)
                await ivr_sessions.close(payload.id)
                return IvrResponse(type="ask", text="Sorry, something went wrong. Could you repeat that?", lang=LANG)
            return await _finish(session, payload.id, reply)

        # First contact, or silence: nothing to forward to the agent yet.
        if not text:
            if not session.opened:
                session.opened = True
                return IvrResponse(type="ask", text=settings.ivr_greeting, lang=LANG)
            return IvrResponse(type="ask", text="Sorry, I didn't catch that. Could you say it again?", lang=LANG)

        session.opened = True
        try:
            reply = await ivr_sessions.ask(session, text)
        except Exception:
            logger.exception("agent turn failed id=%s", payload.id)
            await ivr_sessions.close(payload.id)  # next turn opens a fresh conversation
            return IvrResponse(type="ask", text="Sorry, something went wrong. Could you repeat that?", lang=LANG)

        return await _finish(session, payload.id, reply)


async def _finish(session: ivr_sessions.IvrSession, call_id: str, reply: str) -> IvrResponse:
    """Turn the agent's reply into one of the four verbs."""
    if session.continuing:  # spoke, then started a tool: say the line now, answer follows on the empty callback
        return IvrResponse(type="info", text=reply, lang=LANG)
    if session.pending_action:
        if reply:  # say the agent's line first, perform the action on the empty callback
            return IvrResponse(type="info", text=reply, lang=LANG)
        response = _action_response(session)
        if response.type == "hangup":
            await ivr_sessions.close(call_id)
        return response
    return IvrResponse(type="ask", text=reply or "Sorry, could you say that again?", lang=LANG)
