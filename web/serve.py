#!/usr/bin/env python3
"""Static server for the web sandbox, plus a small same-origin relay to the venues.

Why: browsers refuse cross-origin calls that the venue does not allow, and Polymarket's Gamma API is
reported to allow only its own origin. Python is not subject to that, so this relay makes the calls
server-side and the page talks to `localhost` only.

    uv run python web/serve.py            # then open http://localhost:8000
    python3 web/serve.py --port 8080      # works without uv if `websockets` is installed

What it relays (an allowlist, read-only market data, bound to 127.0.0.1):
    GET  /__proxy/gamma/markets?...       -> Polymarket Gamma  /markets
    GET  /__proxy/clob/time | /book       -> Polymarket CLOB   /time, /book
    POST /__proxy/hl/info                 -> Hyperliquid       /info
    GET  /__proxy/data/value | /v2/value  -> Polymarket Data API  (positions value of a public address)
    ws://localhost:<port+1>/pm            -> the Polymarket market WebSocket (the browser would send an Origin)
Nothing from the browser (cookies, headers) is forwarded, and nothing is logged beyond the request line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPSTREAM = {
    "gamma": os.environ.get("BT_GAMMA", "https://gamma-api.polymarket.com"),
    "clob": os.environ.get("BT_CLOB", "https://clob.polymarket.com"),
    "hl": os.environ.get("BT_HL", "https://api.hyperliquid.xyz"),
    "data": os.environ.get("BT_DATA", "https://data-api.polymarket.com"),
}
PM_WS = os.environ.get("BT_PM_WS", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
# (service, method) -> allowed path prefixes. Anything else is refused.
ALLOWED = {
    ("gamma", "GET"): ("/markets",),
    ("clob", "GET"): ("/time", "/book"),
    ("hl", "POST"): ("/info",),
    ("data", "GET"): ("/value", "/v2/value"),
}
MAX_BODY = 64 * 1024
state = {"ws_port": 0, "relay": False}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):  # quiet: the request line only, no client details
        if os.environ.get("BT_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, method: str) -> None:
        raw, _, query = self.path.partition("?")
        service, _, rest = raw[len("/__proxy/"):].partition("/")
        if service == "config":
            self._send(200, json.dumps({"wsPort": state["ws_port"] if state["relay"] else 0}).encode())
            return
        path = "/" + rest
        allowed = ALLOWED.get((service, method))
        if allowed is None or not any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in allowed):
            self._send(403, b'{"error":"not on the relay allowlist"}')
            return
        data = None
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(413, b'{"error":"body too large"}')
                return
            data = self.rfile.read(length)
        url = UPSTREAM[service] + path + (("?" + query) if query else "")
        headers = {"User-Agent": "bi-trading-sandbox-relay", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=10) as r:
                self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as e:
            self._send(e.code, e.read())
        except Exception as e:  # network down, DNS, timeout
            self._send(502, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode())

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/__proxy/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/__proxy/"):
            self._proxy("POST")
        else:
            self._send(405, b'{"error":"method not allowed"}')


async def relay(client, path=None):
    """Pipe one browser WebSocket to the Polymarket market socket (no Origin header goes upstream)."""
    import websockets

    async with websockets.connect(PM_WS, max_queue=256, compression=None) as upstream:
        async def up():
            async for message in client:
                await upstream.send(message)

        async def down():
            async for message in upstream:
                await client.send(message)

        tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()


def make_http(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


async def run_ws(port: int, http_port: int, started: asyncio.Event | None = None):
    import websockets

    origins = [f"http://localhost:{http_port}", f"http://127.0.0.1:{http_port}"]
    async with websockets.serve(relay, "127.0.0.1", port, origins=origins):
        state.update(ws_port=port, relay=True)
        if started:
            started.set()
        await asyncio.Future()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    httpd = make_http(args.port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"Sandbox: http://localhost:{args.port}   (offline demo: http://localhost:{args.port}/test/mock.html)")
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("`websockets` is not installed: REST is relayed, but the Polymarket socket is not (use `uv run`).")
        threading.Event().wait()
        return
    print(f"Relaying Polymarket's socket on ws://localhost:{args.port + 1}/pm")
    try:
        asyncio.run(run_ws(args.port + 1, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
