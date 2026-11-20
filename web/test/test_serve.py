"""The relay in serve.py, tested against local fake upstreams (no internet needed).

    uv run python -m unittest web/test/test_serve.py
"""
import asyncio
import json
import os
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        self._reply({"path": self.path, "ua": self.headers.get("User-Agent"), "cookie": self.headers.get("Cookie"), "origin": self.headers.get("Origin")})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self._reply({"path": self.path, "body": json.loads(self.rfile.read(n))})


class RelayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.up.server_address[1]}"
        os.environ.update(BT_GAMMA=base, BT_CLOB=base, BT_HL=base)
        import importlib, serve
        self.serve = importlib.reload(serve)
        import websockets
        self.websockets = websockets

        async def upstream_ws(ws, path=None):
            await ws.send(json.dumps([{"event_type": "book", "asset_id": "a"}]))
            async for m in ws:
                await ws.send(m)  # echo the subscription back

        self.upws_port = free_port()
        self.upws = await websockets.serve(upstream_ws, "127.0.0.1", self.upws_port)
        self.serve.PM_WS = f"ws://127.0.0.1:{self.upws_port}"
        self.http = self.serve.make_http(0)
        self.http_port = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.ws_port = free_port()
        started = asyncio.Event()
        self.ws_task = asyncio.create_task(self.serve.run_ws(self.ws_port, self.http_port, started))
        await asyncio.wait_for(started.wait(), 5)

    async def asyncTearDown(self):
        self.ws_task.cancel()
        self.http.shutdown(); self.up.shutdown(); self.upws.close()

    def get(self, path, data=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.http_port}{path}", data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    async def call(self, *a, **k):
        return await asyncio.to_thread(self.get, *a, **k)

    async def test_gamma_get_is_relayed_without_browser_headers(self):
        status, body = await self.call("/__proxy/gamma/markets?slug=btc-updown-5m-1", headers={"Cookie": "secret=1", "Origin": "http://evil"})
        j = json.loads(body)
        self.assertEqual(status, 200); self.assertEqual(j["path"], "/markets?slug=btc-updown-5m-1")
        self.assertIsNone(j["cookie"]); self.assertIsNone(j["origin"]); self.assertEqual(j["ua"], "bi-trading-sandbox-relay")

    async def test_clob_and_hl(self):
        self.assertEqual((await self.call("/__proxy/clob/time"))[0], 200)
        status, body = await self.call("/__proxy/hl/info", data=json.dumps({"type": "candleSnapshot"}).encode(), headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)["body"], {"type": "candleSnapshot"})

    async def test_allowlist(self):
        self.assertEqual((await self.call("/__proxy/gamma/events"))[0], 403)
        self.assertEqual((await self.call("/__proxy/clob/order"))[0], 403)
        self.assertEqual((await self.call("/__proxy/hl/exchange", data=b"{}"))[0], 403)
        self.assertEqual((await self.call("/__proxy/hl/info"))[0], 403)  # GET on a POST-only route
        self.assertEqual((await self.call("/__proxy/nope/x"))[0], 403)

    async def test_config_and_static(self):
        status, body = await self.call("/__proxy/config")
        self.assertEqual(json.loads(body), {"wsPort": self.ws_port})
        status, body = await self.call("/index.html")
        self.assertEqual(status, 200); self.assertIn(b"bi-trading", body)

    async def test_polymarket_socket_relay(self):
        ws = await self.websockets.connect(f"ws://127.0.0.1:{self.ws_port}/pm", origin=f"http://localhost:{self.http_port}")
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        self.assertEqual(first[0]["event_type"], "book")
        await ws.send(json.dumps({"assets_ids": ["a"], "type": "market"}))
        self.assertEqual(json.loads(await asyncio.wait_for(ws.recv(), 5))["type"], "market")
        await ws.close()

    async def test_foreign_origin_is_refused(self):
        with self.assertRaises(Exception):
            await self.websockets.connect(f"ws://127.0.0.1:{self.ws_port}/pm", origin="http://evil.example")


if __name__ == "__main__":
    unittest.main()
