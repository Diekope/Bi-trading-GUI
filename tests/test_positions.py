"""The shared paper position: one at a time, and its unrealised PnL."""

from __future__ import annotations

import pytest

from bi_trading.state.positions import PositionStore, change, store


def test_the_store_holds_one_position() -> None:
    window = PositionStore()
    assert window.get() is None

    position = {"side": "LONG", "leverage": 5, "size": 2_000.0, "entry": 100.0}
    window.set(position)
    assert window.get() == position

    window.set(None)
    assert window.get() is None


def test_the_store_signals_every_change() -> None:
    window = PositionStore()
    seen: list[int] = []
    window.changed.connect(lambda: seen.append(len(seen)))

    window.set({"side": "SHORT"})
    window.set(None)

    assert len(seen) == 2


def test_change_follows_the_side_and_the_leverage() -> None:
    long = {"side": "LONG", "leverage": 5, "size": 2_000.0, "entry": 100.0}
    short = {"side": "SHORT", "leverage": 5, "size": 2_000.0, "entry": 100.0}

    # +10% on a $2,000 long: 10% * 2000. Leverage sets the margin, not the PnL.
    assert change(long, 110.0) == pytest.approx(200.0)
    # The same move against a short loses the same amount.
    assert change(short, 110.0) == pytest.approx(-200.0)


def test_change_needs_a_price_and_an_entry() -> None:
    assert change({"side": "LONG", "leverage": 5, "size": 1.0}, None) is None
    assert change({"side": "LONG", "leverage": 5, "size": 1.0, "entry": 0.0}, 100.0) is None


def test_the_shared_store_is_a_singleton() -> None:
    assert store() is store()
