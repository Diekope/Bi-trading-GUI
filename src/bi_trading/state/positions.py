"""The one open paper position, shared across the hub's rebuildable views.

The hub destroys and rebuilds a view each time the rail changes, so a position
opened in the Live view would vanish with it. Keeping the position in one
process-wide store lets the trade form restore it and lets the Home card
report it. Nothing here places an order; it is the paper position only.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class PositionStore(QObject):
    """A single position (or none), with a `changed` signal when it moves."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._position: dict | None = None

    def get(self) -> dict | None:
        return self._position

    def set(self, position: dict | None) -> None:
        self._position = position
        self.changed.emit()

    def clear(self) -> None:
        self._position = None


_store: PositionStore | None = None


def store() -> PositionStore:
    """The shared store, built on first use."""
    global _store
    if _store is None:
        _store = PositionStore()
    return _store


def change(position: dict, price: float | None) -> float | None:
    """Unrealised PnL for a position at `price`, or None without a price."""
    entry = position.get("entry")
    if not entry or not price:
        return None
    direction = 1.0 if position.get("side") == "LONG" else -1.0
    return (
        (price / entry - 1.0)
        * float(position.get("size", 0.0))
        * float(position.get("leverage", 1))
        * direction
    )


__all__ = ["PositionStore", "change", "store"]
