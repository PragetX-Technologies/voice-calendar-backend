"""
Smart IVR <-> PragetX agent: the HTTP "four-verb" contract.

Smart IVR does STT/TTS and POSTs each caller utterance here; we answer with
one of ask / info / transfer / hangup. The reply text comes from an
ElevenLabs text-only agent (app/ivr_sessions.py), which calls the existing
/tools/* webhooks for calendar work.
"""
import json
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
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
    return await handle_turn(payload.id, payload.text, x_phone, x_destination)


async def handle_turn(call_id: str, raw_text: str, phone: str, destination: str) -> IvrResponse:
    """One caller turn -> one reply. Shared by the HTTP endpoint and the WebSocket endpoint."""
    logger.info("smartivr id=%s phone=%s destination=%s text=%r", call_id, phone, destination, raw_text)

    # Caller hung up (agreed marker text): free the ElevenLabs socket, nothing to say back.
    if _is_hangup_text(raw_text):
        await ivr_sessions.close(call_id)
        return IvrResponse(type="hangup")

    text = raw_text.strip()
    try:
        session = await ivr_sessions.get_or_create(call_id, phone, destination)
    except Exception:
        logger.exception("could not open agent session")
        return IvrResponse(type="ask", text="Sorry, I'm having trouble right now. Please try again.", lang=LANG)

    async with session.lock:
        ivr_sessions.touch(session)

        # A transfer/hangup was announced last turn (sent as 'info'); Smart IVR has now called back empty.
        if session.pending_action and not text:
            response = _action_response(session)
            if response.type == "hangup":
                await ivr_sessions.close(call_id)
            return response

        # Last turn returned the agent's "one moment" line as 'info' while a tool ran: fetch the real answer now.
        if session.continuing and not text:
            try:
                reply = await ivr_sessions.resume(session)
            except Exception:
                logger.exception("agent resume failed id=%s", call_id)
                await ivr_sessions.close(call_id)
                return IvrResponse(type="ask", text="Sorry, something went wrong. Could you repeat that?", lang=LANG)
            return await _finish(session, call_id, reply)

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
            logger.exception("agent turn failed id=%s", call_id)
            await ivr_sessions.close(call_id)  # next turn opens a fresh conversation
            return IvrResponse(type="ask", text="Sorry, something went wrong. Could you repeat that?", lang=LANG)

        return await _finish(session, call_id, reply)


# ---------------------------------------------------------------- WebSocket (same messages as HTTP)

def _ws_authorized(ws: WebSocket) -> bool:
    expected = settings.smartivr_token
    auth = ws.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ws.query_params.get("token", "")
    return bool(expected) and secrets.compare_digest(token, expected)


async def _ws_send(ws: WebSocket, resp: IvrResponse) -> None:
    await ws.send_text(resp.model_dump_json(exclude_none=True))


@router.websocket("/smartivr/ws")
async def smartivr_ws(ws: WebSocket):
    """Same contract as POST /smartivr, over one socket per call: client sends {id, text}, we send {type, text, lang, dest, metadata}.
    Bonus over HTTP: after an 'info' waiting line we push the real answer ourselves as a second message,
    so Smart IVR needn't send the empty callback (if it still does, that one empty message is ignored)."""
    if not _ws_authorized(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    phone = ws.headers.get("x-phone") or ws.query_params.get("phone", "")
    destination = ws.headers.get("x-destination") or ws.query_params.get("destination", "")
    call_ids: set[str] = set()
    skip_empty = False
    try:
        while True:
            try:
                data = json.loads(await ws.receive_text())
                call_id = str(data["id"])
                text = str(data.get("text") or "")
            except (ValueError, KeyError, TypeError):
                await ws.send_text(json.dumps({"type": "error", "text": 'expected JSON {"id": "...", "text": "..."}'}))
                continue
            if not text.strip() and skip_empty:  # the empty callback after a pushed answer
                skip_empty = False
                continue
            skip_empty = False
            call_ids.add(call_id)
            resp = await handle_turn(call_id, text, data.get("phone") or phone, data.get("destination") or destination)
            await _ws_send(ws, resp)
            session = ivr_sessions.get(call_id)
            while resp.type == "info" and session and session.continuing:
                resp = await handle_turn(call_id, "", phone, destination)  # resume: the tool's real answer
                await _ws_send(ws, resp)
                skip_empty = True
            if resp.type in ("hangup", "transfer"):
                skip_empty = False
    except WebSocketDisconnect:
        pass
    finally:  # socket gone = call over
        for cid in call_ids:
            await ivr_sessions.close(cid)


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
