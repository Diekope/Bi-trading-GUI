"""Venue abstraction shared by Hyperliquid and Polymarket.

Every adapter implements the same async `Venue` protocol, so UI code never
branches on which exchange it is talking to.

Threading contract: adapters are `asyncio`-based and must never be awaited on
the Qt event-loop thread. Run one asyncio loop in a worker thread (see
`lalala.venues.runner`) and hand results back to widgets through Qt signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal, Protocol, runtime_checkable

Side = Literal["buy", "sell"]


class VenueError(Exception):
    """Raised for rejected orders, auth failures and transport errors."""


# A 403 from the CLOB is almost always a geoblock; say so plainly.
_REGION_HINTS = ("region", "restricted", "not available in your")
# The legacy client can no longer sign orders since the CLOB V2 cutover.
_STALE_HINTS = ("order version", "order_version", "latest clob-client")
# The V2 flow acts for the signer's deposit wallet; a mismatched address is
# rejected.
_DEPOSIT_HINTS = ("deposit wallet",)


def friendly_message(exc: object) -> str:
    """A human line for an order failure — a region block, a stale client, a
    wallet mismatch, or the raw text."""
    text = str(exc)
    low = text.lower()
    if any(hint in low for hint in _STALE_HINTS):
        return (
            "Polymarket's order client is out of date. Since the CLOB V2 "
            "cutover the legacy py-clob-client can no longer place orders; the "
            "venue SDK needs updating (polymarket-client / py-clob-client-v2)."
        )
    if any(hint in low for hint in _DEPOSIT_HINTS):
        return (
            "The wallet address does not match this key's Polymarket deposit "
            "wallet. Leave the wallet address blank to act for the deposit "
            "wallet the client derives, or enter that exact deposit wallet."
        )
    if any(hint in low for hint in _REGION_HINTS) or "403" in text:
        return (
            "Trading is not allowed from your region. Polymarket's blocked "
            "regions are listed at https://docs.polymarket.com/developers"
        )
    return text


@dataclass(frozen=True, slots=True)
class Instrument:
    """A tradable market.

    `symbol` is venue-native: a perp name on Hyperliquid, a CLOB token id on
    Polymarket. Never assume the two are interchangeable.
    """

    venue: str
    symbol: str
    tick: float
    size_step: float


@dataclass(frozen=True, slots=True)
class Balance:
    asset: str
    free: float
    locked: float = 0.0


@dataclass(frozen=True, slots=True)
class Quote:
    """Top of book snapshot."""

    instrument: Instrument
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    ts_ms: int


@dataclass(frozen=True, slots=True)
class OrderRequest:
    instrument: Instrument
    side: Side
    price: float
    size: float
    reduce_only: bool = False
    client_id: str | None = None


@dataclass(frozen=True, slots=True)
class OrderAck:
    """Venue acknowledgement of a submitted order."""

    venue_order_id: str
    client_id: str | None = None
    accepted: bool = True
    reason: str | None = None


@runtime_checkable
class Venue(Protocol):
    name: str

    async def connect(self) -> None:
        """Open REST/WebSocket sessions and authenticate if credentials exist."""

    async def close(self) -> None:
        """Release every socket and client cleanly."""

    async def balances(self) -> list[Balance]: ...

    def quotes(self, instrument: Instrument) -> AsyncIterator[Quote]:
        """Yield book updates until the caller stops iterating."""

    async def submit(self, order: OrderRequest) -> OrderAck: ...

    async def cancel(self, instrument: Instrument, venue_order_id: str) -> None: ...
