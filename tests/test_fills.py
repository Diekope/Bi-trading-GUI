"""Fill realism: stops that gap fill at the open, limits need a trade-through,
the trail is a market exit, and an entry can wait for the next open."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from bi_trading.engine import core  # noqa: E402
from bi_trading.ui.strat.strat_playback import build_session  # noqa: E402

BASE = dict(
    capital=1_000.0, tp=5.0, sl=2.0, position=100.0, sizing="fixed",
    max_cash=1_000.0, fee=0.0, max_hold=0,
)


def run(opens, highs, lows, closes, entries, native=True, **more):
    args = {**BASE, **more}
    if not native:
        saved = core._NATIVE
        core._NATIVE = False
    try:
        return core.walk(closes, highs, lows, entries, opens=opens, **args)
    finally:
        if not native:
            core._NATIVE = saved


def lead(*columns):
    """A flat first bar in front, since the walk never opens on bar 0."""
    return [[column[0], *column] for column in columns]


@pytest.mark.parametrize("native", [True, False])
def test_a_stop_the_market_gapped_past_fills_at_the_open(native) -> None:
    # Long from 100, stop 98; the next bar opens at 95.
    o, h, lo, c = lead([100, 95, 95], [100, 96, 96], [100, 94, 94], [100, 95, 95])
    trades, _ = run(o, h, lo, c, [False, True, False, False], native=native)
    assert trades[0][7] == "sl"
    assert trades[0][3] == pytest.approx(95.0)


@pytest.mark.parametrize("native", [True, False])
def test_a_target_the_market_gapped_past_fills_at_the_better_open(native) -> None:
    o, h, lo, c = lead([100, 110, 110], [100, 111, 111], [100, 109, 109], [100, 110, 110])
    trades, _ = run(o, h, lo, c, [False, True, False, False], native=native)
    assert trades[0][7] == "tp"
    assert trades[0][3] == pytest.approx(110.0)


@pytest.mark.parametrize("native", [True, False])
def test_a_limit_needs_a_trade_through(native) -> None:
    # The target is 105; the bar reaches exactly 105, then 105.2.
    entries = [False, True, False, False]
    o, h, lo, c = lead([100, 100, 100], [100, 105, 105], [100, 99, 99], [100, 100, 100])
    touched = run(o, h, lo, c, entries, native=native, through=0.001)
    assert touched[0] == []                  # touched, not traded through
    o, h, lo, c = lead([100, 100, 100], [100, 105.2, 105], [100, 99, 99], [100, 100, 100])
    through = run(o, h, lo, c, entries, native=native, through=0.001)
    assert through[0][0][7] == "tp"


@pytest.mark.parametrize("native", [True, False])
def test_the_trail_is_a_market_exit_and_slips(native) -> None:
    kwargs = dict(dynamic_tp=True, reverse=1.0, tp=0.0, sl=0.0, slippage=0.01)
    o, h, lo, c = lead([100, 100, 100], [100, 110, 110], [100, 100, 108], [100, 110, 108])
    trades, _ = run(o, h, lo, c, [False, True, False, False], native=native, **kwargs)
    assert trades[0][3] == pytest.approx(110 * 0.99 * 0.99)


@pytest.mark.parametrize("native", [True, False])
def test_an_entry_at_the_next_open_fills_there_and_can_stop_out_in_its_bar(native) -> None:
    signals = core.delayed([True, False, False, False])
    assert signals.tolist() == [False, True, False, False]
    trades, _ = run(
        [100, 101, 101, 101], [100, 101, 101, 101], [100, 90, 101, 101],
        [100, 101, 101, 101], signals, native=native, entry_open=True,
    )
    assert trades[0][0] == 1 and trades[0][1] == pytest.approx(101.0)
    assert trades[0][2] == 1 and trades[0][7] == "sl"   # stopped in its own bar


def test_a_signal_before_a_hole_is_dropped_by_delayed() -> None:
    out = core.delayed([True, False, True], gaps=[True, False, False])
    assert out.tolist() == [False, False, False]
    # A piece of a longer span carries the bar before it.
    assert core.delayed([False, False], previous=True).tolist() == [True, False]
    assert core.delayed([False, False], previous=True, previous_gap=True).tolist() == [
        False, False,
    ]


def test_native_and_python_agree_on_random_bars() -> None:
    if not core.available():
        pytest.skip("native core not built")
    rng = np.random.default_rng(7)
    n = 3_000
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    opens = np.r_[closes[0], closes[:-1]] * (1 + rng.normal(0, 0.002, n))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.002, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.002, n)))
    entries = core.delayed(rng.random(n) < 0.05)
    shorts = core.delayed(rng.random(n) < 0.03)
    kwargs = dict(
        capital=10_000.0, tp=1.0, sl=0.8, position=50.0, sizing="balance",
        max_cash=5_000.0, fee=0.0006, max_hold=12, dynamic_tp=True, reverse=0.4,
        short_entries=shorts, slippage=0.0001, opens=opens, entry_open=True,
        through=0.0001,
    )
    native, curve, _ = core.walk_chunk(closes, highs, lows, entries, **kwargs)
    saved = core._NATIVE
    core._NATIVE = False
    try:
        python, curve_py, _ = core.walk_chunk(closes, highs, lows, entries, **kwargs)
    finally:
        core._NATIVE = saved
    assert len(native) > 20
    assert [t[:3] + t[7:] for t in native] == [t[:3] + t[7:] for t in python]
    assert np.allclose(curve, curve_py)


def test_the_stepped_walk_and_the_seek_agree_with_the_next_open_entry() -> None:
    params = {
        "initial_capital": 10_000.0, "tp": 2.0, "sl": 1.0, "position": 10.0,
        "sizing": "balance", "cash": 2_000.0, "fee": 0.06, "slippage": 0.01,
        "entry": "open", "limit_through": 0.01,
    }
    session = build_session([], params, "bollinger", "1m")
    reference = build_session([], params, "bollinger", "1m")
    for _ in range(400):
        reference.strategy.step()
    session.seek(400)
    assert reference.strategy.trades > 0
    assert session.strategy.trades == reference.strategy.trades
    # The in-trade path and its excursion are not rebuilt by a seek; the rest is.
    keep = lambda log: [r[:8] + r[9:11] + r[12:] for r in log]  # noqa: E731
    assert keep(session.strategy.trades_log) == keep(reference.strategy.trades_log)
    assert session.strategy.equity == pytest.approx(reference.strategy.equity, abs=1e-6)
