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
from bi_trading.venues.base import Instrument, OrderRequest, VenueError, friendly_message
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

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("orders")
        self._runner.start()

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
        adapter = None
        try:
            adapter = get_venue(venue, **config)
            await adapter.connect()
            balances = await adapter.balances()
            free = balances[0].free if balances else 0.0
            self.balance_ready.emit(venue, float(free))
        except Exception as exc:  # the SDKs raise a wide variety of types
            log.warning("%s balance check failed: %s", venue, exc)
            self.balance_failed.emit(venue, f"{type(exc).__name__}: {exc}"[:140])
        finally:
            if adapter is not None:
                with contextlib.suppress(Exception):
                    await adapter.close()

    async def _place(
        self, venue: str, order: OrderRequest, config: dict, origin: str = "manual",
        strategy: str = "",
    ) -> None:
        from bi_trading.state.events import event_log

        adapter = None
        started = time.perf_counter()
        try:
            adapter = get_venue(venue, **config)
            await adapter.connect()
            ack = await adapter.submit(order)
            took = (time.perf_counter() - started) * 1000.0
            if ack.accepted:
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
            self.failed.emit(venue, text[:240])
        finally:
            if adapter is not None:
                with contextlib.suppress(Exception):
                    await adapter.close()
            self.busy.emit(venue, False)

    def shutdown(self) -> None:
        self._runner.stop()


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
