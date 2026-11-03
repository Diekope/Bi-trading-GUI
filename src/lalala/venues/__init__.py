"""Venue adapters. Import cost is deferred so the GUI starts without SDKs."""

from __future__ import annotations

from lalala.venues.base import (
    Balance,
    Instrument,
    OrderAck,
    OrderRequest,
    Quote,
    Venue,
    VenueError,
)

__all__ = [
    "Balance",
    "Instrument",
    "OrderAck",
    "OrderRequest",
    "Quote",
    "Venue",
    "VenueError",
    "get_venue",
]


def get_venue(name: str, **config: object) -> Venue:
    """Build an adapter by name: "hyperliquid" or "polymarket"."""
    key = name.strip().lower()
    if key in {"hyperliquid", "hl"}:
        from lalala.venues.hyperliquid import HyperliquidVenue

        return HyperliquidVenue(**config)  # type: ignore[arg-type]
    if key in {"polymarket", "pm"}:
        from lalala.venues.polymarket import PolymarketVenue

        return PolymarketVenue(**config)  # type: ignore[arg-type]
    raise VenueError(f"unknown venue: {name!r}")
