"""Live Hyperliquid market data. Public endpoints only — no keys, no signing.

Everything network-facing runs on the asyncio worker thread owned by
`AsyncRunner`. Results reach the GUI as Qt signals, which Qt delivers queued
onto the main thread, so widgets never touch an asyncio object.

Streams
    allMids   every market, main dex and each HIP-3 dex (mid prices)
    candle    one subscription per (coin, interval) on screen; the venue pushes
              every new or updated bar, so no periodic polling is needed

Fetched once per watch
    candleSnapshot   initial history for a (coin, interval) pair

Latency
    A WebSocket ping/pong every few seconds; the measured round trip is what
    the header shows. It is the real path to the venue, unlike an HTTP timer.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import httpx
import websockets
from PySide6.QtCore import QObject, Signal

from lalala.market_data import (
    Book,
    Candle,
    CandleSeries,
    Market,
    candle_window_ms,
    parse_all_mids,
    parse_book,
    parse_candles,
    parse_universe,
)
from lalala.venues.runner import AsyncRunner

INFO_URL = "https://api.hyperliquid.xyz/info"
WS_URL = "wss://api.hyperliquid.xyz/ws"

# Main perps first, then builder-deployed dexs we surface in search.
DEXES: tuple[str, ...] = ("", "xyz")

RECV_TIMEOUT = 0.5        # also the worst-case delay for a new subscription
MAX_BACKOFF = 10.0
PING_EVERY = 2.0          # seconds between latency probes
CANDLE_COUNT = 300        # history kept for panning back
CANDLE_RECONCILE = 60.0   # slow REST re-sync; the stream carries live updates


class MarketFeed(QObject):
    connected = Signal(bool)
    latency = Signal(float)           # websocket round trip, ms
    universe_ready = Signal(object)   # list[Market]
    mids_updated = Signal(object)     # dict[str, float]
    book_updated = Signal(object)     # Book
    candles_updated = Signal(object)  # CandleSeries
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("hl-feed")
        self._lock = threading.Lock()
        self._books: set[str] = set()
        # (method, subscription) exactly as it goes on the wire.
        self._pending: list[tuple[str, dict[str, Any]]] = []
        self._watches: set[tuple[str, str]] = set()
        self._candle_cache: dict[tuple[str, str], tuple[Candle, ...]] = {}
        self._candles_dirty = True
        self._markets: dict[str, Market] = {}
        self._stopping = False
        self._http: httpx.AsyncClient | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._runner.start()
        self._runner.submit(self._main())

    def stop(self) -> None:
        self._stopping = True
        self._runner.stop()

    # -- called from the GUI thread ---------------------------------------

    def market(self, coin: str) -> Market | None:
        return self._markets.get(coin)

    def track(self, coin: str) -> None:
        with self._lock:
            if coin in self._books:
                return
            self._books.add(coin)
            self._pending.append(
                ("subscribe", {"type": "l2Book", "coin": coin})
            )

    def untrack(self, coin: str) -> None:
        with self._lock:
            if coin not in self._books:
                return
            self._books.discard(coin)
            self._pending.append(
                ("unsubscribe", {"type": "l2Book", "coin": coin})
            )

    def watch_candles(self, coin: str, interval: str) -> None:
        with self._lock:
            key = (coin, interval)
            if key in self._watches:
                return
            self._watches.add(key)
            self._candles_dirty = True
            self._pending.append(
                (
                    "subscribe",
                    {"type": "candle", "coin": coin, "interval": interval},
                )
            )

    def unwatch_candles(self, coin: str, interval: str) -> None:
        with self._lock:
            key = (coin, interval)
            if key not in self._watches:
                return
            self._watches.discard(key)
            self._candle_cache.pop(key, None)
            self._pending.append(
                (
                    "unsubscribe",
                    {"type": "candle", "coin": coin, "interval": interval},
                )
            )

    # -- asyncio side ------------------------------------------------------

    async def _main(self) -> None:
        async with httpx.AsyncClient(timeout=15.0) as http:
            self._http = http
            try:
                await self._load_universe()
            except Exception as exc:  # network hiccup: stream first, retry later
                self.error.emit(f"universe: {type(exc).__name__}: {exc}")

            candle_task = asyncio.create_task(self._candle_loop())
            try:
                await self._stream_forever()
            finally:
                candle_task.cancel()
                await asyncio.gather(candle_task, return_exceptions=True)
                self._http = None

    async def _stream_forever(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                await self._session()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error.emit(f"stream: {type(exc).__name__}: {exc}")
            finally:
                self.connected.emit(False)
            if self._stopping:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    async def _load_universe(self) -> None:
        assert self._http is not None
        payloads = await asyncio.gather(
            *(
                self._post({"type": "meta", **({"dex": d} if d else {})})
                for d in DEXES
            )
        )

        markets: list[Market] = []
        for dex, payload in zip(DEXES, payloads):
            if payload:
                markets.extend(parse_universe(payload, dex))

        with self._lock:
            self._markets = {m.coin: m for m in markets}
        self.universe_ready.emit(markets)

    async def _post(self, body: dict[str, Any]) -> Any:
        assert self._http is not None
        response = await self._http.post(INFO_URL, json=body)
        response.raise_for_status()
        return response.json()

    async def _session(self) -> None:
        async with websockets.connect(
            WS_URL, ping_interval=20, ping_timeout=20, close_timeout=2
        ) as ws:
            await ws.send(
                json.dumps({"method": "subscribe", "subscription": {"type": "allMids"}})
            )
            for dex in DEXES:
                if dex:
                    await ws.send(
                        json.dumps(
                            {
                                "method": "subscribe",
                                "subscription": {"type": "allMids", "dex": dex},
                            }
                        )
                    )

            with self._lock:
                books = sorted(self._books)
                candle_watches = sorted(self._watches)
                self._pending.clear()

            for coin in books:
                await self._send(
                    ws, "subscribe", {"type": "l2Book", "coin": coin}
                )
            for coin, interval in candle_watches:
                await self._send(
                    ws,
                    "subscribe",
                    {"type": "candle", "coin": coin, "interval": interval},
                )

            self.connected.emit(True)
            ping_task = asyncio.create_task(self._ping_loop(ws))
            try:
                while not self._stopping:
                    for method, subscription in self._drain_pending():
                        await self._send(ws, method, subscription)
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)
                    except asyncio.TimeoutError:
                        continue
                    self.dispatch(raw)
            finally:
                ping_task.cancel()
                await asyncio.gather(ping_task, return_exceptions=True)

    async def _ping_loop(self, ws: Any) -> None:
        """Measure the real websocket round trip and publish it."""
        while not self._stopping:
            try:
                pong = await ws.ping()
                seconds = await asyncio.wait_for(pong, timeout=5.0)
            except Exception:  # socket gone, reconnecting will retry
                return
            self.latency.emit(float(seconds) * 1000.0)
            await asyncio.sleep(PING_EVERY)

    async def _candle_loop(self) -> None:
        """Fetch history once per watch, then a slow reconcile.

        Live bars arrive over the candle stream; polling every second was
        enough request pressure to draw HTTP 429s from the venue.
        """
        last_reconcile = 0.0
        while not self._stopping:
            with self._lock:
                dirty = self._candles_dirty
                self._candles_dirty = False
                watches = sorted(self._watches)

            if not watches:
                await asyncio.sleep(0.25)
                continue

            now = time.monotonic()
            if not dirty and (now - last_reconcile) < CANDLE_RECONCILE:
                await asyncio.sleep(0.25)
                continue
            last_reconcile = now

            results = await asyncio.gather(
                *(self._fetch_candles(coin, interval) for coin, interval in watches),
                return_exceptions=True,
            )
            for key, result in zip(watches, results):
                if isinstance(result, CandleSeries):
                    with self._lock:
                        if key not in self._watches:
                            continue  # card closed while the fetch was in flight
                        self._candle_cache[key] = result.candles
                    self.candles_updated.emit(result)
                elif isinstance(result, Exception):
                    self.error.emit(f"candles: {type(result).__name__}: {result}")

    async def _fetch_candles(self, coin: str, interval: str) -> CandleSeries:
        now = int(time.time() * 1000)
        payload = await self._post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": now - candle_window_ms(interval, CANDLE_COUNT),
                    "endTime": now,
                },
            }
        )
        return CandleSeries(coin, interval, parse_candles(payload))

    @staticmethod
    async def _send(ws: Any, method: str, subscription: dict[str, Any]) -> None:
        await ws.send(json.dumps({"method": method, "subscription": subscription}))

    def _drain_pending(self) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            pending, self._pending = self._pending, []
        return pending

    # -- routing -----------------------------------------------------------

    def dispatch(self, raw: str | bytes) -> None:
        """Route one websocket frame to a signal. Pure, so it is testable."""
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return

        channel = message.get("channel")
        data = message.get("data")

        if channel == "allMids" and isinstance(data, dict):
            self.mids_updated.emit(parse_all_mids(data))
        elif channel == "l2Book" and isinstance(data, dict):
            book: Book = parse_book(data)
            if book.coin:
                self.book_updated.emit(book)
        elif channel == "candle" and isinstance(data, dict):
            self.apply_candle(data)
        elif channel == "error":
            self.error.emit(str(data))

    # -- candle stream -----------------------------------------------------

    def apply_candle(self, data: dict) -> None:
        """Upsert one bar pushed by the venue and publish the whole series."""
        try:
            coin = str(data["s"])
            interval = str(data["i"])
            candle = Candle(
                t=int(data["t"]),
                o=float(data["o"]),
                h=float(data["h"]),
                l=float(data["l"]),
                c=float(data["c"]),
                v=float(data.get("v", 0.0) or 0.0),
            )
        except (KeyError, TypeError, ValueError):
            return

        key = (coin, interval)
        with self._lock:
            if key not in self._watches:
                return
            series = list(self._candle_cache.get(key, ()))
            if series and series[-1].t == candle.t:
                series[-1] = candle
            elif not series or candle.t > series[-1].t:
                series.append(candle)
            else:
                for index, existing in enumerate(series):
                    if existing.t == candle.t:
                        series[index] = candle
                        break
                else:
                    return
            series = series[-CANDLE_COUNT:]
            self._candle_cache[key] = tuple(series)

        self.candles_updated.emit(CandleSeries(coin, interval, tuple(series)))
