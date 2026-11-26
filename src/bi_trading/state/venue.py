"""Which venue the app is working on: Polymarket, Hyperliquid, or both.

The rail's top switch sets it and every screen follows. It is remembered between
runs. In `both` the strategy screens (Builder, Backtest) do not exist: strategy
work is per venue.
"""

from __future__ import annotations

from bi_trading.state.settings import load_choice, save_choice

PM = "pm"
HL = "hl"
BOTH = "both"
VENUES = (PM, HL, BOTH)
NAMES = {PM: "Polymarket", HL: "Hyperliquid", BOTH: "PM + HL"}
KEY = "hub.venue"


def current() -> str:
    """The remembered venue; Polymarket the first time."""
    value = load_choice(KEY)
    return value if value in VENUES else PM


def save(venue: str) -> None:
    if venue in VENUES:
        save_choice(KEY, venue)


def has_strategies(venue: str) -> bool:
    """Builder and Backtest exist for one venue, not for both at once."""
    return venue != BOTH


__all__ = ["BOTH", "HL", "NAMES", "PM", "VENUES", "current", "has_strategies", "save"]
