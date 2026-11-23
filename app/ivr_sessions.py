"""
One ElevenLabs text-only conversation per Smart IVR call id.

Smart IVR sends one stateless HTTP request per caller turn, but an ElevenLabs
agent conversation is a stateful WebSocket. This module bridges the two: the
first request for an `id` opens a socket, later requests reuse it, and a
reaper closes sockets that have gone idle (Smart IVR never says when the
caller hangs up).

# ponytail: sessions live in this process's memory — run a single uvicorn
# worker. Upgrade: move socket ownership to a worker keyed by id (e.g. sticky
# routing) or switch to a stateless LLM call with history in Mongo.
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import websockets

from app import business_service
from app.config import settings

logger = logging.getLogger("ivr")

SIGNED_URL_ENDPOINT = "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url"
WAIT_MARKERS = ("one moment", "one second", "hold on", "let me check", "let me look", "let me book", "let me move", "let me cancel", "let me update", "checking")


def _is_wait_line(text: str) -> bool:
    """The agent's "one moment..." line said right before a calendar tool runs (a question is never a waiting line)."""
    t = text.lower()
    return "?" not in t and any(m in t for m in WAIT_MARKERS)


WAIT_LINE_AFTER = 1.0  # no event at all this long after the caller spoke = the agent is running a tool; we say the waiting line ourselves
WAIT_LINES = ("One moment, please.", "Just a moment.", "One moment while I check that.")
NUDGE_AFTER = 7.0  # seconds of silence after a waiting line before we poke the agent
_CLOSED = object()  # queue sentinel: the socket died


@dataclass
class IvrSession:
    id: str
    phone: str
    destination: str
    account_id: str
    ws: object = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one caller turn at a time
    last_active: float = field(default_factory=time.monotonic)
    reader: asyncio.Task | None = None
    ticket_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8].upper())
    # set by the agent's client tools (request_transfer / end_conversation), consumed by the router
    pending_action: str | None = None  # "transfer" | "hangup"
    transfer_reason: str = ""
    summary: str = ""
    opened: bool = False  # False until first caller turn has been answered (used for the greeting)
    # a turn that returned early with the agent's "one moment" line while a tool still runs; the router calls resume() on Smart IVR's empty callback
    continuing: bool = False
    tools_in_flight: int = 0
    wait_line_idx: int = 0


_sessions: dict[str, IvrSession] = {}
_create_lock = asyncio.Lock()


def _time_context(account_id: str) -> dict:
    """Current date + opening hours handed to the agent up front, so it needs no get_business_hours tool call (saves a round trip per booking)."""
    now = datetime.now(ZoneInfo(settings.default_timezone))
    hours = (business_service.get_any_profile(account_id) or {}).get("hours", {})
    hours_text = "; ".join(
        f"{d} {h['start']}-{h['end']}" if (h := hours.get(d)) and h.get("enabled") else f"{d} closed"
        for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    )
    next_days = "; ".join((now + timedelta(days=i)).strftime("%a %Y-%m-%d") for i in range(8))
    return {
        "current_datetime": now.strftime("%A %d %B %Y, %H:%M") + f" ({settings.default_timezone})",
        "next_8_days": next_days,  # e.g. "Thu 2026-11-19; Fri 2026-11-20; ..." - first entry is today
        "business_hours": hours_text,
    }


async def _signed_url() -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            SIGNED_URL_ENDPOINT,
            params={"agent_id": settings.elevenlabs_ivr_agent_id},
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
    resp.raise_for_status()
    return resp.json()["signed_url"]


async def _reader(session: IvrSession) -> None:
    """Pumps socket messages into session.queue; answers pings and the agent's client tools inline."""
    try:
        async for raw in session.ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "ping":
                await session.ws.send(json.dumps({"type": "pong", "event_id": msg["ping_event"]["event_id"]}))
            elif kind == "client_tool_call":
                await _handle_client_tool(session, msg["client_tool_call"])
            else:
                await session.queue.put(msg)
    except Exception:
        logger.exception("ivr reader for %s stopped", session.id)
    finally:
        await session.queue.put(_CLOSED)


async def _handle_client_tool(session: IvrSession, call: dict) -> None:
    name, params = call.get("tool_name"), call.get("parameters") or {}
    if name == "request_transfer":
        session.pending_action = "transfer"
        session.transfer_reason = str(params.get("reason", ""))
        session.summary = str(params.get("summary", ""))
        result = "ok"
    elif name == "end_conversation":
        session.pending_action = "hangup"
        result = "ok"
    else:
        result = f"unknown tool {name}"
    if call.get("expects_response"):
        await session.ws.send(json.dumps({
            "type": "client_tool_result",
            "tool_call_id": call["tool_call_id"],
            "result": result,
            "is_error": result != "ok",
        }))


def get(session_id: str) -> IvrSession | None:
    return _sessions.get(session_id)


async def get_or_create(session_id: str, phone: str, destination: str) -> IvrSession:
    async with _create_lock:
        session = _sessions.get(session_id)
        if session and session.reader and not session.reader.done():
            return session
        session = IvrSession(id=session_id, phone=phone, destination=destination, account_id=settings.ivr_account_id)
        session.ws = await websockets.connect(await _signed_url())
        await session.ws.send(json.dumps({
            "type": "conversation_initiation_client_data",
            "conversation_config_override": {"conversation": {"text_only": True}},
            "dynamic_variables": {
                "session_id": session_id,
                "caller_phone": phone,
                "destination": destination,
                "account_id": session.account_id,
                "ticket_id": session.ticket_id,
                **await asyncio.to_thread(_time_context, session.account_id),
            },
        }))
        session.reader = asyncio.create_task(_reader(session))
        _sessions[session_id] = session
        logger.info("ivr session opened id=%s phone=%s destination=%s", session_id, phone, destination)
        return session


async def ask(session: IvrSession, text: str) -> str:
    """Send one caller turn, return the agent's reply text ('' if it said nothing).
    If the agent speaks and then starts a tool (e.g. "One moment while I check"), returns just that line with
    session.continuing = True; the rest of the turn is fetched by resume()."""
    while not session.queue.empty():  # drop anything left over from a previous turn
        item = session.queue.get_nowait()
        if item is _CLOSED:
            raise RuntimeError("ElevenLabs socket closed")
    session.tools_in_flight = 0
    session.continuing = False
    await session.ws.send(json.dumps({"type": "user_message", "text": text}))
    return await _collect(session, early_on_tool=True)


async def resume(session: IvrSession) -> str:
    """Finish a turn that ask() returned early: wait for the tool result and the agent's real answer."""
    session.continuing = False
    return await _collect(session, early_on_tool=False)


async def _collect(session: IvrSession, early_on_tool: bool) -> str:
    parts: list[str] = []
    nudged = False
    got_event = False
    started = time.monotonic()
    deadline = started + settings.ivr_turn_timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("ivr turn timed out id=%s parts=%d", session.id, len(parts))
            break
        # Docs don't say which end-of-turn event fires in text-only mode, so: finish on
        # agent_response_complete, or once we have some text and the socket goes quiet.
        # While a tool call is running, wait much longer for the agent's follow-up answer.
        quiet = settings.ivr_quiet_seconds if session.tools_in_flight == 0 else 8.0
        # After a waiting line the tool normally answers within ~3s. If nothing at all arrives for NUDGE_AFTER seconds the agent
        # said "one moment" but never called the tool (seen with the "update" line): poke it once instead of dead air.
        watch_stuck = not early_on_tool and not parts and not nudged
        # Fresh caller turn and the agent has produced nothing yet: a normal reply starts within ~0.6s. Silence past
        # WAIT_LINE_AFTER means a tool is running, so speak the waiting line from here instead of relying on the LLM to write it.
        watch_silence = early_on_tool and not got_event and not parts and not session.pending_action
        wait = quiet if parts else (WAIT_LINE_AFTER if watch_silence else NUDGE_AFTER if watch_stuck else remaining)
        try:
            msg = await asyncio.wait_for(session.queue.get(), timeout=min(remaining, wait))
        except asyncio.TimeoutError:
            if parts:
                break
            if watch_silence:
                session.continuing = True
                session.wait_line_idx += 1
                logger.info("ivr silent %.1fs after caller turn id=%s, tool assumed running -> waiting line", WAIT_LINE_AFTER, session.id)
                return WAIT_LINES[session.wait_line_idx % len(WAIT_LINES)]
            if watch_stuck:
                nudged = True
                logger.warning("ivr agent silent after waiting line id=%s, nudging", session.id)
                await session.ws.send(json.dumps({"type": "user_message", "text": "Yes, please go ahead and do it now."}))
            continue
        got_event = True
        logger.info("ivr evt id=%s +%.2fs %s", session.id, time.monotonic() - started, msg.get("type") if msg is not _CLOSED else "CLOSED")
        if msg is _CLOSED:
            if parts:
                break
            raise RuntimeError("ElevenLabs socket closed")
        kind = msg.get("type")
        if kind == "agent_response":
            if not early_on_tool and _is_wait_line(msg["agent_response_event"]["agent_response"]):
                continue  # the agent also wrote its own "one moment" after we already said ours: don't read it out as the answer
            parts.append(msg["agent_response_event"]["agent_response"])
            # Text-only mode emits no tool events, so the agent's waiting line ("...one moment.") is the only sign a tool is running.
            if early_on_tool and _is_wait_line(parts[-1]):
                session.continuing = True
                break
            # The agent calls request_transfer/end_conversation BEFORE speaking, so pending_action is already set here;
            # it then repeats its line once more ~0.5s later, which we don't want. quiet <= 0 = reply as soon as text arrives.
            if session.pending_action or settings.ivr_quiet_seconds <= 0:
                break
        elif kind == "agent_tool_request":
            session.tools_in_flight += 1
            if early_on_tool and parts:  # "One moment..." was spoken, tool now running: let Smart IVR say it, come back for the answer
                session.continuing = True
                break
        elif kind == "agent_tool_response":
            session.tools_in_flight = max(0, session.tools_in_flight - 1)
        elif kind == "agent_response_correction":
            if parts:
                parts[-1] = msg["agent_response_correction_event"]["corrected_agent_response"]
        elif kind == "agent_response_complete":
            if parts or session.pending_action:
                break
        elif kind == "client_error":
            logger.error("ivr client_error id=%s %s", session.id, msg)
        else:
            logger.debug("ivr ignoring %s", kind)
    session.last_active = time.monotonic()
    if session.continuing:  # the model sometimes says two waiting lines; speak only the last one
        lines = [l.strip() for p in parts for l in p.splitlines() if _is_wait_line(l)]
        return lines[-1] if lines else " ".join(p.strip() for p in parts)
    unique: list[str] = []
    for p in (x.strip() for x in parts):  # the model sometimes repeats the same sentence (e.g. goodbye before and after a tool)
        if p and p not in unique:
            unique.append(p)
    return " ".join(unique)


async def close(session_id: str) -> None:
    session = _sessions.pop(session_id, None)
    if not session:
        return
    if session.reader:
        session.reader.cancel()
    try:
        await session.ws.close()
    except Exception:
        pass
    logger.info("ivr session closed id=%s", session_id)


async def reap_idle_forever() -> None:
    """Started from main.lifespan. Closes sessions idle longer than ivr_session_idle_seconds."""
    while True:
        await asyncio.sleep(30)
        now = time.monotonic()
        for sid, s in list(_sessions.items()):
            if now - s.last_active > settings.ivr_session_idle_seconds and not s.lock.locked():
                await close(sid)


def touch(session: IvrSession) -> None:
    session.last_active = time.monotonic()
