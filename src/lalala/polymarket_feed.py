"""Live data for one Polymarket five-minute BTC up/down market.

Everything network-facing runs on the asyncio worker thread owned by
`AsyncRunner`; results reach the GUI as Qt signals, so widgets never touch an
asyncio object.

One market at a time
    The slug is derived from the clock (`btc-updown-5m-<aligned ts>`), so the
    panel shows the window that is open right now. At expiry the feed moves to
    the next slug by itself; nothing on the GUI side has to know about time.

Per window
    Gamma  one request: question, tokens, liquidity, spread, timestamps
    CLOB   one `/book` per outcome token, as a snapshot before the stream
    WS     one subscription to both tokens: book, price_change, trades

Reconnects keep the current window; when the window closes the socket is
dropped deliberately and the next one starts on a fresh slug.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import websockets
from PySide6.QtCore import QObject, Signal

from lalala.polymarket_data import (
    PolymarketMarket,
    TokenBook,
    Trade,
    apply_price_change,
    market_slug,
    parse_book,
    parse_last_trade,
    parse_market,
    parse_price_changes,
)
from lalala.venues.runner import AsyncRunner

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

RESOLVE_RETRY = 1.5     # seconds between attempts, while the next slug is not listed
CLOSE_GRACE = 3.0       # keep the socket a moment past the close, for late prints
MAX_BACKOFF = 8.0
FLUSH_EVERY = 0.1       # UI books refresh at most 10x/s; the wire is much faster
CLOCK_POLL = 0.5        # how often the socket watchdog re-reads the clock
LATENCY_EVERY = 5.0     # websocket ping/pong round trip, seconds between probes


class PolymarketFeed(QObject):
    market_ready = Signal(object)  # PolymarketMarket
    book_updated = Signal(object)  # TokenBook
    trade = Signal(object)         # Trade
    latency = Signal(int)          # websocket ping/pong round trip, milliseconds
    status = Signal(str)           # waiting / snapshot / live / reconnecting / closed
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("pm-feed")
        self._market: PolymarketMarket | None = None
        # Only touched on the asyncio thread (or directly in tests).
        self._books: dict[str, TokenBook] = {}
        # Insertion-ordered so a flush emits each token once, in arrival order.
        self._dirty: dict[str, None] = {}
        self._started = False
        self._stopping = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._started = True
        self._runner.start()
        self._runner.submit(self._main())

    def stop(self) -> None:
        self._stopping = True
        self._runner.stop()

    def market(self) -> PolymarketMarket | None:
        """The market on show, for a late-joining consumer."""
        return self._market

    # -- asyncio side ------------------------------------------------------

    async def _main(self) -> None:
        async with httpx.AsyncClient(timeout=12.0) as http:
            flush_task = asyncio.create_task(self._flush_loop())
            latency_task = asyncio.create_task(self._latency_loop())
            try:
                while not self._stopping:
                    slug = market_slug()
                    market: PolymarketMarket | None = None
                    try:
                        market = await self._resolve(http, slug)
                    except Exception as exc:
                        self.error.emit(f"gamma: {type(exc).__name__}: {exc}")

                    if market is None:
                        self.status.emit("waiting")
                        await asyncio.sleep(RESOLVE_RETRY)
                        continue

                    self._books.clear()
                    self._dirty.clear()
                    self._market = market
                    self.market_ready.emit(market)
                    await self._watch(http, market)
            finally:
                flush_task.cancel()
                latency_task.cancel()
                await asyncio.gather(
                    flush_task, latency_task, return_exceptions=True
                )

    async def _resolve(
        self, http: httpx.AsyncClient, slug: str
    ) -> PolymarketMarket | None:
        response = await http.get(f"{GAMMA_URL}/markets", params={"slug": slug})
        response.raise_for_status()
        return parse_market(response.json())

    async def _watch(
        self, http: httpx.AsyncClient, market: PolymarketMarket
    ) -> None:
        deadline = max(market.end_ms / 1000, time.time()) + CLOSE_GRACE
        tokens = [outcome.token_id for outcome in market.outcomes]

        await self._snapshot(http, tokens)

        backoff = 1.0
        while not self._stopping and time.time() < deadline:
            try:
                await self._session(tokens, deadline)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The venue closes the socket at resolution; that is expected,
                # not an error worth printing every five minutes.
                if time.time() < market.end_ms / 1000 - 1.0:
                    self.error.emit(f"market ws: {type(exc).__name__}: {exc}")
            # Do not reconnect in the last seconds of a window: the market is
            # about to close and the next slug is a fresh session anyway.
            if self._stopping or time.time() >= deadline - 2.0:
                break
            self.status.emit("reconnecting")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

        self.status.emit("closed")

    async def _snapshot(self, http: httpx.AsyncClient, tokens: list[str]) -> None:
        """The stream sends a full book on connect, but REST lands sooner."""
        self.status.emit("snapshot")
        for token in tokens:
            try:
                response = await http.get(
                    f"{CLOB_URL}/book", params={"token_id": token}
                )
                if response.status_code == 404:
                    continue  # no book yet; the WS frame will arrive shortly
                response.raise_for_status()
                book = parse_book(response.json())
            except Exception as exc:
                self.error.emit(f"book: {type(exc).__name__}: {exc}")
                continue
            if book is not None:
                self._apply_book(book)
        # Do not make the first paint wait for the next tick of the flusher.
        self.flush_books()

    async def _session(self, tokens: list[str], deadline: float) -> None:
        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=2,
            # A busy market pushes several hundred frames a second. Give the
            # reader room to absorb a burst instead of pausing the socket and
            # tripping the venue's slow-consumer guard.
            max_queue=256,
        ) as ws:
            await ws.send(json.dumps({"assets_ids": tokens, "type": "market"}))
            self.status.emit("live")
            # A task rather than `wait_for` per frame: the venue sends ~700
            # frames/s, and a timeout wrapper per recv costs more than the
            # routing itself.
            watchdog = asyncio.create_task(self._close_at(ws, deadline))
            try:
                async for raw in ws:
                    self.dispatch(raw)
                    if self._stopping:
                        break
            finally:
                watchdog.cancel()
                await asyncio.gather(watchdog, return_exceptions=True)

    async def _latency_loop(self) -> None:
        """Ping a socket of our own, so the readout survives a busy market.

        The market subscription can be closed by the venue's slow-consumer
        guard when a window is busy. Measuring on that socket made the delay
        readout go blank exactly when the book was hottest, so the probe keeps
        a second, subscription-free connection whose only traffic is the ping.
        """
        backoff = 1.0
        while not self._stopping:
            try:
                async with websockets.connect(
                    WS_URL,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=2,
                ) as ws:
                    backoff = 1.0
                    while not self._stopping:
                        started = time.perf_counter()
                        pong = await ws.ping()
                        await asyncio.wait_for(pong, timeout=4.0)
                        if self._stopping:
                            break
                        milliseconds = round(
                            (time.perf_counter() - started) * 1000
                        )
                        self.latency.emit(int(milliseconds))
                        await asyncio.sleep(LATENCY_EVERY)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # a probe failure is not an app error
            if self._stopping:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    async def _close_at(self, ws: Any, deadline: float) -> None:
        """Close the socket when the window ends or the app asks to stop."""
        while not self._stopping and time.time() < deadline:
            await asyncio.sleep(CLOCK_POLL)
        await ws.close()

    # -- routing -----------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Coalesce the wire's burst rate down to something a UI can paint.

        The venue pushes several hundred book updates a second. Applying each
        one to the held book is cheap, but emitting each one costs a queued
        signal per update; at 10 Hz the panel still looks live and the GUI
        thread only sees a fraction of the frames.
        """
        while True:
            await asyncio.sleep(FLUSH_EVERY)
            self.flush_books()

    def flush_books(self) -> None:
        """Emit the current state of every book that changed since last flush."""
        if not self._dirty:
            return
        dirty, self._dirty = self._dirty, {}
        for token_id in dirty:
            book = self._books.get(token_id)
            if book is not None:
                self.book_updated.emit(book)

    def dispatch(self, raw: str | bytes) -> None:
        """Route one websocket frame. Pure apart from the held-book update."""
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return

        # The venue sometimes batches events into a list.
        events = payload if isinstance(payload, list) else [payload]
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("event_type")
            if kind == "book":
                book = parse_book(event)
                if book is not None:
                    self._apply_book(book)
            elif kind == "price_change":
                self._apply_changes(event)
            elif kind == "last_trade_price":
                trade: Trade | None = parse_last_trade(event)
                if trade is not None:
                    self.trade.emit(trade)
            # tick_size_change and subscription acks need no action.

    def _apply_book(self, book: TokenBook) -> None:
        self._books[book.token_id] = book
        self._dirty[book.token_id] = None

    def _apply_changes(self, message: dict[str, Any]) -> None:
        for change in parse_price_changes(message):
            held = self._books.get(change.token_id)
            if held is None:
                # A change before the snapshot cannot be applied to nothing;
                # the next `book` frame repairs the ladder.
                continue
            self._books[change.token_id] = apply_price_change(held, change)
            self._dirty[change.token_id] = None
