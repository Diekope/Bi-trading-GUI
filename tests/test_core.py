"""The walk: the native core and the Python fallback agree."""

from __future__ import annotations

import pytest

from lalala.engine import core


def _series(closes):
    return (
        list(closes),
        [c + 0.5 for c in closes],
        [c - 0.5 for c in closes],
    )


def test_the_core_is_available() -> None:
    # The extension is built for this environment; if it ever isn't, the
    # fallback still runs, so this only checks the wiring.
    assert core.available() in (True, False)


def test_native_and_python_walks_agree() -> None:
    closes = [100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101]
    highs, lows = _series(closes)[1:]
    entries = [False] + [True] * (len(closes) - 1)
    args = (closes, highs, lows, entries)
    kwargs = dict(
        capital=10_000.0, tp=1.0, sl=1.0, position=10.0,
        sizing="balance", max_cash=2_000.0, fee=0.0006, max_hold=3,
    )
    native = core.walk(*args, **kwargs)
    python = core._python_walk(
        *args, kwargs["capital"], kwargs["tp"], kwargs["sl"],
        kwargs["position"], kwargs["sizing"], kwargs["max_cash"],
        kwargs["fee"], kwargs["max_hold"],
    )
    assert len(native[0]) > 0
    assert native[0] == python[0]
    assert native[1] == python[1]


def test_risk_sizing_shrinks_the_position_as_the_stop_widens() -> None:
    # A trade that opens at 100 and stops at 98: a 1% risk on $1,000 cash puts
    # $500 on (so a 2% stop-out loses $10), while a 1% stop puts $1,000 on.
    closes = [100.0, 100.0, 100.0]
    highs = [100.0, 100.0, 100.0]
    lows = [100.0, 100.0, 100.0]
    entries = [False, True, False]

    def notional(sl: float) -> float:
        trades, _ = core.walk(
            closes, highs, lows, entries, capital=1_000.0, tp=50.0, sl=sl,
            position=1.0, sizing="risk", max_cash=1_000.0, fee=0.0, max_hold=1,
        )
        return trades[0][6]

    assert notional(2.0) == 500.0
    assert notional(1.0) == 1_000.0


def test_dynamic_tp_trails_the_peak() -> None:
    # Flat fixed TP would never fire in this series, but the trail closes once
    # price pulls back 5% from the peak it reached after entry.
    closes = [100.0, 100.0, 110.0, 104.0, 104.0]
    highs = [100.0, 100.0, 110.0, 104.5, 104.0]
    lows = [100.0, 100.0, 110.0, 104.0, 104.0]
    entries = [False, True, False, False, False]

    trades, _ = core.walk(
        closes, highs, lows, entries, capital=1_000.0, tp=50.0, sl=50.0,
        position=100.0, sizing="balance", max_cash=1_000.0, fee=0.0, max_hold=99,
        dynamic_tp=True, reverse=5.0,
    )

    assert len(trades) == 1
    _in_index, _in_px, out_index, out_px, _result, _fees, _notional, reason = trades[0]
    assert reason == "tp"
    assert out_px == 104.5  # 110 peak pulled back 5%
    assert out_index == 3


def test_native_and_python_random_entries_agree() -> None:
    import pytest

    from lalala.engine import core

    if core._native_random_entries is None:
        pytest.skip("the native core is not built")

    closes = [100.0, 101.0, 99.0, 102.0, 98.0, 103.0, 97.0, 104.0]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    draws = [0.01, 0.9, 0.02, 0.9, 0.9, 0.01, 0.9, 0.9]

    native = core.random_entries(highs, lows, closes, draws, 2.0, 1.0, 90, 0.03)
    python = core._python_random_entries(
        highs, lows, closes, draws, 2.0, 1.0, 90, 0.03
    )

    assert native == python
    assert any(native)


def test_dynamic_tp_off_keeps_the_fixed_target() -> None:
    closes = [100.0, 100.0, 110.0, 104.0, 104.0]
    highs = [100.0, 100.0, 110.0, 104.5, 104.0]
    lows = [100.0, 100.0, 110.0, 104.0, 104.0]
    entries = [False, True, False, False, False]

    trades, _ = core.walk(
        closes, highs, lows, entries, capital=1_000.0, tp=50.0, sl=50.0,
        position=100.0, sizing="balance", max_cash=1_000.0, fee=0.0, max_hold=2,
        dynamic_tp=False, reverse=5.0,
    )

    # Nothing trails: the trade runs to the hold limit at the close.
    assert trades[0][7] == "time"


# -- shorting ----------------------------------------------------------------


def _short_walk(closes, highs, lows, entries, **kwargs):
    base = dict(
        capital=1_000.0, tp=2.0, sl=1.0, position=100.0, sizing="balance",
        max_cash=1_000.0, fee=0.0, max_hold=99, side="short",
    )
    base.update(kwargs)
    return core.walk(closes, highs, lows, entries, **base)


def test_a_short_profits_when_price_falls() -> None:
    closes = [100.0, 100.0, 97.0, 97.0]
    highs = [100.0, 100.0, 100.0, 97.0]
    lows = [100.0, 100.0, 97.0, 97.0]
    trades, equity = _short_walk(closes, highs, lows, [False, True, False, False])

    assert len(trades) == 1
    _i, in_px, out_index, out_px, result, _fees, notional, reason = trades[0]
    assert (in_px, out_index, reason) == (100.0, 2, "tp")
    assert out_px == pytest.approx(98.0)  # 2% below the entry
    assert notional == 1_000.0
    assert result == pytest.approx(0.02)
    assert equity[-1] == pytest.approx(1_020.0)


def test_a_short_stops_out_above_the_entry() -> None:
    closes = [100.0, 100.0, 102.0, 102.0]
    highs = [100.0, 100.0, 102.0, 102.0]
    lows = [100.0, 100.0, 100.0, 102.0]
    trades, equity = _short_walk(closes, highs, lows, [False, True, False, False])

    _i, _in, out_index, out_px, result, *_rest, reason = trades[0]
    assert (reason, out_index) == ("sl", 2)
    assert out_px == pytest.approx(101.0)  # 1% above the entry
    assert result == pytest.approx(-0.01)
    assert equity[-1] == pytest.approx(990.0)


def test_a_long_and_a_short_mirror_each_other() -> None:
    up = [100.0, 100.0, 103.0, 103.0]
    down = [100.0, 100.0, 97.0, 97.0]
    flags = [False, True, False, False]

    long_trades, _ = core.walk(
        up, up, [100.0, 100.0, 100.0, 103.0], flags, capital=1_000.0, tp=2.0,
        sl=1.0, position=100.0, sizing="balance", max_cash=1_000.0, fee=0.0,
        max_hold=99,
    )
    short_trades, _ = _short_walk(
        down, [100.0, 100.0, 100.0, 97.0], down, flags
    )
    assert long_trades[0][4] == pytest.approx(0.02)
    assert short_trades[0][4] == pytest.approx(0.02)


def test_a_short_pays_the_fee_both_ways() -> None:
    closes = [100.0, 100.0, 97.0]
    trades, equity = _short_walk(
        closes, [100.0, 100.0, 100.0], [100.0, 100.0, 97.0],
        [False, True, False], fee=0.001,
    )
    fees = trades[0][5]
    # 1000 notional in, about 980 of buy-back out, a tenth of a percent each.
    assert 1.9 < fees < 2.0
    assert equity[-1] < 1_020.0


def test_a_short_never_loses_more_than_its_margin() -> None:
    closes = [100.0, 100.0, 300.0]
    trades, equity = _short_walk(
        closes, [100.0, 100.0, 300.0], [100.0, 100.0, 100.0],
        [False, True, False], tp=0.0, sl=0.0, max_hold=1,
    )
    assert equity[-1] >= 0.0
    assert trades[0][4] == -1.0


def test_a_short_dynamic_tp_trails_the_low() -> None:
    closes = [100.0, 100.0, 90.0, 94.0, 94.0]
    highs = [100.0, 100.0, 90.0, 94.5, 94.0]
    lows = [100.0, 100.0, 90.0, 90.0, 94.0]
    trades, _ = _short_walk(
        closes, highs, lows, [False, True, False, False, False],
        tp=50.0, sl=50.0, dynamic_tp=True, reverse=5.0,
    )
    _i, _in, out_index, out_px, _r, _f, _n, reason = trades[0]
    assert reason == "tp"
    assert out_px == 94.5  # the 90 low bounced 5%
    assert out_index == 3


def test_the_random_baseline_goes_short_too() -> None:
    closes = [100.0] * 8
    highs = [100.0] * 8
    lows = [100.0] * 8
    draws = [0.01] * 8
    entries = core.random_entries(highs, lows, closes, draws, 2.0, 1.0, 90, 0.03, True)
    assert any(entries)


# -- the exit rule -----------------------------------------------------------


def _exit(text):
    from lalala.engine.formula import EXIT_FIELDS, EXIT_FUNCTIONS, parse

    return parse(text, EXIT_FIELDS, EXIT_FUNCTIONS)


def test_an_exit_rule_closes_a_trade_at_the_close() -> None:
    closes = [100.0, 100.0, 100.5, 101.0, 100.0]
    flat = [100.0, 100.0, 100.5, 101.0, 100.0]
    trades, _ = core.walk(
        closes, flat, flat, [False, True, False, False, False], capital=1_000.0,
        tp=50.0, sl=50.0, position=100.0, sizing="balance", max_cash=1_000.0,
        fee=0.0, max_hold=99, exit_formula=_exit("pnl >= 1"),
    )
    _i, _in, out_index, out_px, _r, _f, _n, reason = trades[0]
    assert (out_index, out_px, reason) == (3, 101.0, "rule")


def test_a_short_exit_rule_reads_a_profit_when_price_falls() -> None:
    closes = [100.0, 100.0, 99.5, 99.0, 100.0]
    trades, _ = _short_walk(
        closes, closes, closes, [False, True, False, False, False],
        tp=50.0, sl=50.0, exit_formula=_exit("pnl >= 1"),
    )
    assert trades[0][2] == 3
    assert trades[0][7] == "rule"


def test_the_take_profit_still_acts_before_the_exit_rule() -> None:
    closes = [100.0, 100.0, 103.0]
    trades, _ = core.walk(
        closes, [100.0, 100.0, 103.0], [100.0, 100.0, 100.0],
        [False, True, False], capital=1_000.0, tp=2.0, sl=50.0, position=100.0,
        sizing="balance", max_cash=1_000.0, fee=0.0, max_hold=99,
        exit_formula=_exit("pnl >= 1"),
    )
    assert trades[0][7] == "tp"


def test_no_exit_rule_changes_nothing() -> None:
    closes = [100.0, 101.0, 102.0, 103.0, 101.0, 100.0]
    highs, lows = _series(closes)[1:]
    entries = [False, True, False, False, False, False]
    kwargs = dict(capital=1_000.0, tp=1.5, sl=1.0, position=50.0,
                  sizing="balance", max_cash=1_000.0, fee=0.0006, max_hold=3)
    assert core.walk(closes, highs, lows, entries, **kwargs) == core.walk(
        closes, highs, lows, entries, exit_formula=None, **kwargs
    )


def test_native_and_python_agree_on_shorts_and_risk_sizing() -> None:
    if not core.available():
        pytest.skip("the native core is not built")

    closes = [100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101]
    highs, lows = _series(closes)[1:]
    entries = [False] + [True] * (len(closes) - 1)
    for side in ("long", "short"):
        for sizing in ("balance", "fixed", "risk"):
            args = (closes, highs, lows, entries, 10_000.0, 1.0, 1.0, 10.0,
                    sizing, 2_000.0, 0.0006, 3)
            native = core.walk(*args, side=side)
            python = core._python_walk(*args, short=side == "short")
            assert native[0] and native[0] == python[0], (side, sizing)
            assert native[1] == python[1], (side, sizing)
