"""Console test for the WebSocket endpoint: type what the caller says, see the JSON replies.
    python scripts/fake_smartivr_ws.py [ws-url]      (token from SMARTIVR_TOKEN in .env)
"""
import asyncio, json, sys, time
import websockets
from app.config import settings

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8000/smartivr/ws"


async def main():
    cid = f"919800000001-{int(time.time())}"
    headers = {"Authorization": f"Bearer {settings.smartivr_token}", "X-Phone": "919800000001", "X-Destination": "5550100"}
    async with websockets.connect(URL, additional_headers=headers) as ws:
        loop = asyncio.get_running_loop()
        while True:
            text = await loop.run_in_executor(None, input, "caller> ")
            t0 = time.monotonic()
            await ws.send(json.dumps({"id": cid, "text": text}))
            reply_type = ""
            while True:
                try:  # after 'info' the answer is pushed; if nothing comes (transfer/hangup announcement) do the empty callback
                    reply = json.loads(await asyncio.wait_for(ws.recv(), 3 if reply_type == "info" else 60))
                except asyncio.TimeoutError:
                    await ws.send(json.dumps({"id": cid, "text": ""}))
                    reply_type = "callback"
                    continue
                reply_type = reply["type"]
                print(f"  [{time.monotonic() - t0:.2f}s] {reply}")
                if reply["type"] in ("ask", "hangup", "transfer", "error"):
                    break
            if reply["type"] in ("hangup", "transfer"):
                return


asyncio.run(main())
