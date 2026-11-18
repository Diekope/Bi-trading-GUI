"""Placing orders: one worker, one place to reach every venue.

The trade form and the Polymarket column hand a request here. It runs on the
asyncio worker thread — never the Qt event-loop thread — builds the adapter
from the saved account, submits, and reports the outcome back as Qt signals.

Nothing is sent unless the user has **armed** live orders (Settings → Trading
defaults, off by default) *and* the venue has credentials. Otherwise the caller
keeps its paper position and says so. `config_for(venue)` is `None` when a
venue is not connected; `armed()` reads the setting.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Signal

from bi_trading.state.accounts import (
    HL_KEY,
    PM_KEY,
    get_secret,
    load_accounts,
    polymarket_builder,
)
from bi_trading.venues import get_venue
from bi_trading.venues.base import (
    Instrument,
    OrderRequest,
    Venue,
    VenueError,
    friendly_message,
)
from bi_trading.venues.runner import AsyncRunner
import contextlib

log = logging.getLogger(__name__)

HL_BTC = Instrument(venue="hyperliquid", symbol="BTC", tick=0.1, size_step=0.00001)


def config_for(venue: str) -> dict | None:
    """The adapter kwargs for a venue, or None when it is not connected."""
    accounts = load_accounts()
    if venue == "hyperliquid":
        key = get_secret(HL_KEY)
        if not key or not accounts.hyperliquid.address:
            return None
        return {
            "private_key": key,
            "account_address": accounts.hyperliquid.address,
            "testnet": accounts.hyperliquid.testnet,
        }
    if venue == "polymarket":
        key = get_secret(PM_KEY)
        if not key:
            return None
        return {
            "private_key": key,
            "funder": accounts.polymarket.address,
            "signature_type": accounts.polymarket.signature_type,
            "builder": polymarket_builder(),
        }
    return None


def armed() -> bool:
    """Whether the user has turned live orders on (off by default)."""
    from bi_trading.state.settings import Settings

    return Settings.load().trading.live_orders


def can_trade(venue: str) -> bool:
    """A real order may go out: armed and the venue is connected."""
    return armed() and config_for(venue) is not None


class OrderService(QObject):
    """Submits orders off the GUI thread and reports back on it."""

    placed = Signal(str, str)   # venue, a short human summary
    failed = Signal(str, str)   # venue, the reason
    busy = Signal(str, bool)    # venue, in-flight?
    balance_ready = Signal(str, float)   # venue, free USDC
    balance_failed = Signal(str, str)    # venue, the reason
    filled = Signal(str, str, str, float, float)  # venue, token, side, shares, dollars
    holdings_changed = Signal()          # the shares held moved

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("orders")
        self._runner.start()
        # One signed-in client per venue, kept open: building it costs a key
        # derivation, a handshake and a credentials round trip, which is most of
        # what an order used to take. Touched only on the runner's loop.
        self._adapters: dict[str, tuple[str, Venue]] = {}
        # Shares held per Polymarket token, from the fills seen this session.
        self._held: dict[str, float] = {}

    # -- the warm client ---------------------------------------------------

    async def _adapter(self, venue: str, config: dict) -> Venue:
        """The venue's open client, built and connected once and then reused.

        A different account (the config changed) replaces it.
        """
        key = repr(sorted(config.items(), key=lambda item: item[0]))
        cached = self._adapters.get(venue)
        if cached is not None and cached[0] == key:
            return cached[1]
        if cached is not None:
            with contextlib.suppress(Exception):
                await cached[1].close()
            self._adapters.pop(venue, None)
        adapter = get_venue(venue, **config)
        await adapter.connect()
        self._adapters[venue] = (key, adapter)
        return adapter

    async def _drop(self, venue: str) -> None:
        """Forget a client that may have gone bad, so the next order rebuilds it."""
        cached = self._adapters.pop(venue, None)
        if cached is not None:
            with contextlib.suppress(Exception):
                await cached[1].close()

    def warm(self, venue: str) -> None:
        """Sign in ahead of the first order, so that one is as fast as the next.

        Does nothing unless live orders are armed and the venue is connected.
        """
        config = config_for(venue)
        if config is None or not armed():
            return
        self._runner.submit(self._warm(venue, config))

    async def _warm(self, venue: str, config: dict) -> None:
        try:
            await self._adapter(venue, config)
        except Exception as exc:  # a warm-up that fails just means a cold first order
            log.info("%s warm-up failed: %s", venue, exc)

    def held(self, token: str) -> float:
        """Shares of a Polymarket token bought and not yet sold this session."""
        return self._held.get(token, 0.0)

    def _note_fill(self, venue: str, order: OrderRequest, ack) -> None:
        if ack.shares <= 0:
            return
        token = order.instrument.symbol
        sign = 1.0 if order.side == "buy" else -1.0
        if venue == "polymarket":
            self._held[token] = max(0.0, self._held.get(token, 0.0) + sign * ack.shares)
            if self._held[token] < 1e-6:
                self._held.pop(token, None)
            self.holdings_changed.emit()
        self.filled.emit(venue, token, order.side, ack.shares, ack.dollars)

    def submit(
        self, venue: str, order: OrderRequest, config: dict, origin: str = "manual",
        strategy: str = "",
    ) -> None:
        """Send an order. `origin` is `manual` (the user pressed it) or `auto`;
        `strategy` names the one behind an automatic order."""
        from bi_trading.state.events import event_log

        event_log().record(
            "info", venue, "ORDER", _request_text(order), origin, strategy,
            request=_request_lines(order),
        )
        self.busy.emit(venue, True)
        self._runner.submit(self._place(venue, order, config, origin, strategy))

    def request_balance(self, venue: str) -> None:
        """Ask a venue for its free collateral; the answer arrives by signal."""
        config = config_for(venue)
        if config is None:
            self.balance_failed.emit(venue, "not connected")
            return
        self._runner.submit(self._fetch_balance(venue, config))

    async def _fetch_balance(self, venue: str, config: dict) -> None:
        try:
            adapter = await self._adapter(venue, config)
            balances = await adapter.balances()
            free = balances[0].free if balances else 0.0
            self.balance_ready.emit(venue, float(free))
        except Exception as exc:  # the SDKs raise a wide variety of types
            log.warning("%s balance check failed: %s", venue, exc)
            await self._drop(venue)
            self.balance_failed.emit(venue, f"{type(exc).__name__}: {exc}"[:140])

    async def _place(
        self, venue: str, order: OrderRequest, config: dict, origin: str = "manual",
        strategy: str = "",
    ) -> None:
        from bi_trading.state.events import event_log

        started = time.perf_counter()
        try:
            adapter = await self._adapter(venue, config)
            ack = await adapter.submit(order)
            took = (time.perf_counter() - started) * 1000.0
            if ack.accepted:
                self._note_fill(venue, order, ack)
                log.info("%s order accepted: %s", venue, _summary(order, ack))
                matched = ack.detail.startswith(("matched", "filled"))
                event_log().record(
                    "info", venue, "FILLED" if matched else "ACCEPTED",
                    _summary(order, ack), origin, strategy, latency_ms=round(took),
                    request=[*_request_lines(order), f"answer: {ack.detail or 'accepted'}"],
                )
                self.placed.emit(venue, _summary(order, ack))
            else:
                reason = ack.reason or "the venue rejected it"
                log.warning("%s order rejected: %s", venue, reason)
                event_log().record(
                    "error", venue, "REJECTED", f"{_request_text(order)} · {reason}",
                    origin, strategy, latency_ms=round(took),
                    request=[*_request_lines(order), f"error: {reason}"],
                )
                self.failed.emit(venue, reason)
        except Exception as exc:  # the SDKs raise a wide variety of types
            text = friendly_message(exc)
            if not isinstance(exc, VenueError):
                text = f"{type(exc).__name__}: {text}"
            # The status line is the only other place this shows, and it is
            # gone on the next message: keep the full reason in the log.
            log.warning("%s order failed: %s", venue, text, exc_info=True)
            event_log().record(
                "error", venue, "REJECTED", f"{_request_text(order)} · {text[:160]}",
                origin, strategy,
                request=[*_request_lines(order), f"error: {text[:240]}"],
            )
            # The client may be what failed (a dropped connection, expired
            # credentials): rebuild it for the next order rather than guess.
            await self._drop(venue)
            self.failed.emit(venue, text[:240])
        finally:
            self.busy.emit(venue, False)

    def shutdown(self) -> None:
        # Sign the warm clients out before the loop goes, if it still can.
        if self._adapters:
            with contextlib.suppress(Exception):
                self._runner.submit(self._close_all()).result(timeout=2.0)
        self._runner.stop()

    async def _close_all(self) -> None:
        for venue in list(self._adapters):
            await self._drop(venue)


def _request_text(order: OrderRequest) -> str:
    """The order as one line: `Buy $20.00 · limit 0.42`, `Sell 0.05 BTC @ 75,600`."""
    side = "Buy" if order.side == "buy" else "Sell"
    if order.notional is not None:
        return f"{side} ${order.notional:,.2f} · up to {order.price:g}"
    return f"{side} {order.size:g} {order.instrument.symbol[:12]} @ {order.price:g}"


def _request_lines(order: OrderRequest) -> list[str]:
    """What was sent, a line at a time, for the Logs details."""
    lines = [
        f"side: {order.side.upper()} · market: {order.instrument.symbol[:18]}",
        f"price: {order.price:g}"
        + (f" · stake: ${order.notional:,.2f}" if order.notional is not None
           else f" · size: {order.size:g}"),
    ]
    if order.reduce_only:
        lines.append("reduce only")
    return lines


def _summary(order: OrderRequest, ack) -> str:
    side = "Buy" if order.side == "buy" else "Sell"
    if order.notional is not None:
        what = f"{side} ${order.notional:,.2f}"
    else:
        what = f"{side} {order.size:g} {order.instrument.symbol} @ {order.price:g}"
    tail = ack.detail or (f"order {ack.venue_order_id}" if ack.venue_order_id else "")
    return f"{what} · {tail}" if tail else what


_service: OrderService | None = None


def service() -> OrderService:
    """The shared service, built on first use."""
    global _service
    if _service is None:
        _service = OrderService()
    return _service


__all__ = [
    "HL_BTC",
    "OrderService",
    "armed",
    "can_trade",
    "config_for",
    "service",
]
