"""
Plays "fake Smart IVR" against POST /smartivr so you can test without them.

Interactive:   python scripts/fake_smartivr.py --token YOUR_SMARTIVR_TOKEN
Scripted:      python scripts/fake_smartivr.py --token T --say "hi" --say "book a demo tomorrow 3pm"
Hang up:       type  /hangup  (sends the 'client hangup' marker so the backend cleans up)

Mimics Smart IVR: same `id` for the whole call, empty text after an `info`,
stops on transfer/hangup.
"""
import argparse
import sys
import time

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/smartivr")
    ap.add_argument("--token", required=True)
    ap.add_argument("--phone", default="919800000001")
    ap.add_argument("--destination", default="+34910000000")
    ap.add_argument("--say", action="append", help="caller line (repeatable); omit for interactive")
    args = ap.parse_args()

    call_id = f"{args.phone}-{int(time.time())}"
    headers = {"Authorization": f"Bearer {args.token}", "X-Phone": args.phone, "X-Destination": args.destination}
    lines = iter(args.say) if args.say else None
    print(f"call id: {call_id}\n")

    def post(text: str) -> dict:
        r = httpx.post(args.url, json={"id": call_id, "text": text}, headers=headers, timeout=60)
        if r.status_code != 200:
            sys.exit(f"HTTP {r.status_code}: {r.text}")
        return r.json()

    text = ""  # Smart IVR's first request for a call is often empty
    while True:
        started = time.time()
        resp = post(text)
        print(f"  <- {resp}  ({time.time() - started:.1f}s)")
        kind = resp["type"]
        if kind in ("transfer", "hangup"):
            print("call ended by backend")
            return
        if kind == "info":
            text = ""  # real Smart IVR calls straight back with empty text
            continue
        try:
            text = next(lines) if lines is not None else input("caller> ")
        except (StopIteration, EOFError):
            text = "client hangup"
        if text.strip() == "/hangup":
            text = "client hangup"
        print(f"caller> {text}")
        if text == "client hangup":
            print(f"  <- {post(text)}")
            return


if __name__ == "__main__":
    main()
