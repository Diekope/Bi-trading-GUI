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
