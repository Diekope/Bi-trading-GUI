"""The /api bridge to the engine, on a throwaway candle store and strategies file.

    uv run python -m unittest web/test/test_engine_api.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

TMP = tempfile.TemporaryDirectory()
os.environ["BI_TRADING_DATA"] = TMP.name
os.environ["BI_TRADING_STRATEGIES"] = str(Path(TMP.name) / "strategies.json")

import engine_api  # noqa: E402
import serve  # noqa: E402
from bi_trading.data import candles  # noqa: E402

NOW_MS = int(time.time() * 1000) // 60_000 * 60_000


def _seed_candles(days: int = 3) -> None:
    rows, price = [], 50_000.0
    for i in range(days * 1440):
        t = NOW_MS - (days * 1440 - i) * 60_000
        move = 40 * math.sin(i / 37) + 15 * math.sin(i / 7)
        o, c = price, price + move * 0.1
        rows.append((t, o, max(o, c) + 5, min(o, c) - 5, c, 1.0 + (i % 50 == 0) * 10))
        price = c
    by_year: dict[int, list] = {}
    for r in rows:
        by_year.setdefault(time.gmtime(r[0] / 1000).tm_year, []).append(r)
    for year, part in by_year.items():
        candles.append_rows(candles.candle_file(year), part)


_seed_candles()


class EngineApi(unittest.TestCase):
    def test_parse(self):
        self.assertTrue(engine_api.check_rule({"text": "close > sma(close, 20)"})["ok"])
        bad = engine_api.check_rule({"text": "close >"})
        self.assertFalse(bad["ok"])
        self.assertIn("line 1", bad["error"])
        # Polymarket words only read on Polymarket
        self.assertFalse(engine_api.check_rule({"text": "up_price < 0.4"})["ok"])
        self.assertTrue(engine_api.check_rule({"text": "up_price < 0.4", "venue": "Polymarket"})["ok"])
        self.assertTrue(engine_api.check_rule({"text": "pnl >= tp", "kind": "exit"})["ok"])

    def test_resample(self):
        c = engine_api.load_candles(NOW_MS - 3 * 86_400_000, NOW_MS)
        r = engine_api.resample(c, 15)
        self.assertLess(len(r["timestamp"]), len(c["timestamp"]) / 14)
        self.assertTrue((r["timestamp"] % (15 * 60_000) == 0).all())
        self.assertAlmostEqual(r["volume"].sum(), c["volume"].sum())
        self.assertTrue((r["high"] >= r["low"]).all())

    def test_hyperliquid_run(self):
        out = engine_api.run_hyperliquid({"entry": "close > sma(close, 20)", "timeframe": "5m", "days": 3, "tp": 0.05, "sl": 0.05})
        self.assertGreater(out["bars"], 100)
        self.assertGreater(out["trades"], 0)
        self.assertEqual(out["exit"], engine_api.DEFAULT_EXIT)     # empty exit = TP or SL
        self.assertLessEqual(len(out["curves"]["strategy"]), engine_api.MAX_POINTS)
        self.assertNotIn("End of data", [r["label"] for r in out["reasons"]][:1])
        json.dumps(out)                                             # the page gets JSON

    def test_errors(self):
        with self.assertRaises(engine_api.ApiError):
            engine_api.run_hyperliquid({"entry": "", "timeframe": "5m"})
        with self.assertRaises(engine_api.ApiError):
            engine_api.run_hyperliquid({"entry": "close > open", "timeframe": "7m"})
        with self.assertRaises(engine_api.ApiError):
            engine_api.run_hyperliquid({"entry": "close > open", "tp": "abc"})
        with self.assertRaises(engine_api.ApiError):
            engine_api.run_polymarket({})

    def test_save_and_list(self):
        engine_api.save_strategy({"name": "t1", "entry": "close > open", "exit": "pnl >= tp"})
        engine_api.save_strategy({"name": "pm1", "entry": "up_price < 0.3", "venue": "Polymarket"})
        got = {s["name"]: s for s in engine_api.list_strategies()["strategies"]}
        self.assertEqual(got["t1"]["venue"], "Hyperliquid")
        self.assertEqual(got["pm1"]["venue"], "Polymarket")
        with self.assertRaises(engine_api.ApiError):
            engine_api.save_strategy({"name": "bad", "entry": "close >"})


class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = serve.make_http(0)
        cls.port = cls.httpd.server_port
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_status_and_run(self):
        code, out = self.call("/api/status")
        self.assertEqual(code, 200)
        self.assertTrue(out["candles"])
        code, out = self.call("/api/backtest", {"entry": "close > open", "timeframe": "15m", "days": 3})
        self.assertEqual(code, 200, out)

    def test_bad_request_is_400(self):
        code, out = self.call("/api/backtest", {"entry": "close >"})
        self.assertEqual(code, 400)
        self.assertIn("entry", out["error"])

    def test_unknown_route_and_cross_origin(self):
        self.assertEqual(self.call("/api/nope")[0], 404)
        code, _ = self.call("/api/strategies", {"name": "x"}, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
