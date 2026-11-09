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

from PySide6.QtCore import QObject, Signal

from lalala.accounts import HL_KEY, PM_KEY, get_secret, load_accounts
from lalala.venues import get_venue
from lalala.venues.base import Instrument, OrderRequest
from lalala.venues.runner import AsyncRunner

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
        }
    return None


def armed() -> bool:
    """Whether the user has turned live orders on (off by default)."""
    from lalala.settings import Settings

    return Settings.load().trading.live_orders


def can_trade(venue: str) -> bool:
    """A real order may go out: armed and the venue is connected."""
    return armed() and config_for(venue) is not None


class OrderService(QObject):
    """Submits orders off the GUI thread and reports back on it."""

    placed = Signal(str, str)   # venue, a short human summary
    failed = Signal(str, str)   # venue, the reason
    busy = Signal(str, bool)    # venue, in-flight?

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("orders")
        self._runner.start()

    def submit(self, venue: str, order: OrderRequest, config: dict) -> None:
        self.busy.emit(venue, True)
        self._runner.submit(self._place(venue, order, config))

    async def _place(self, venue: str, order: OrderRequest, config: dict) -> None:
        adapter = None
        try:
            adapter = get_venue(venue, **config)
            await adapter.connect()
            ack = await adapter.submit(order)
            if ack.accepted:
                self.placed.emit(venue, _summary(order, ack))
            else:
                self.failed.emit(venue, ack.reason or "the venue rejected it")
        except Exception as exc:  # the SDKs raise a wide variety of types
            self.failed.emit(venue, f"{type(exc).__name__}: {exc}"[:180])
        finally:
            if adapter is not None:
                try:
                    await adapter.close()
                except Exception:
                    pass
            self.busy.emit(venue, False)

    def shutdown(self) -> None:
        self._runner.stop()


def _summary(order: OrderRequest, ack) -> str:
    side = "Buy" if order.side == "buy" else "Sell"
    tail = f" · {ack.venue_order_id}" if ack.venue_order_id else ""
    return f"{side} {order.size:g} {order.instrument.symbol} @ {order.price:g}{tail}"


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
