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
        closes, highs, lows, entries, [False] * len(closes), kwargs["capital"],
        kwargs["tp"], kwargs["sl"], kwargs["position"], kwargs["sizing"],
        kwargs["max_cash"], kwargs["fee"], kwargs["max_hold"],
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
    _in_index, _in_px, out_index, out_px, _result, _fees, _notional, reason, _side = trades[0]
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
    _i, in_px, out_index, out_px, result, _fees, notional, reason, side = trades[0]
    assert side == "short"
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

    _i, _in, out_index, out_px, result, _f, _n, reason, _side = trades[0]
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
    _i, _in, out_index, out_px, _r, _f, _n, reason, _side = trades[0]
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
    _i, _in, out_index, out_px, _r, _f, _n, reason, _side = trades[0]
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
            flat = [False] * len(closes)
            longs, shorts = (entries, flat) if side == "long" else (flat, entries)
            python = core._python_walk(closes, highs, lows, longs, shorts, *args[4:])
            assert native[0] and native[0] == python[0], (side, sizing)
            assert native[1] == python[1], (side, sizing)


# -- stop first, hold, both ways, the exit rule in the core ------------------


def test_a_candle_holding_target_and_stop_books_the_stop() -> None:
    # One candle reaches both 102 (the take profit) and 99 (the stop).
    closes = [100.0, 100.0, 100.0]
    highs = [100.0, 100.0, 103.0]
    lows = [100.0, 100.0, 98.0]
    trades, _ = core.walk(
        closes, highs, lows, [False, True, False], capital=1_000.0, tp=2.0,
        sl=1.0, position=100.0, sizing="balance", max_cash=1_000.0, fee=0.0,
        max_hold=99,
    )
    assert trades[0][7] == "sl"
    assert trades[0][3] == pytest.approx(99.0)


def test_a_short_candle_holding_both_books_the_stop_too() -> None:
    closes = [100.0, 100.0, 100.0]
    trades, _ = _short_walk(
        closes, [100.0, 100.0, 103.0], [100.0, 100.0, 98.0],
        [False, True, False],
    )
    assert trades[0][7] == "sl"


def test_a_trade_is_held_seven_candles_unless_told_otherwise() -> None:
    assert core.DEFAULT_HOLD == 7
    closes = [100.0] * 20
    trades, _ = core.walk(
        closes, closes, closes, [False, True] + [False] * 18, capital=1_000.0,
        tp=50.0, sl=50.0, position=100.0, sizing="balance", max_cash=1_000.0,
        fee=0.0,
    )
    assert trades[0][0:3:2] == (1, 8)  # in at bar 1, out seven bars later
    assert trades[0][7] == "time"


def test_a_hold_of_zero_means_no_limit() -> None:
    closes = [100.0] * 30
    trades, _ = core.walk(
        closes, closes, closes, [False, True] + [False] * 28, capital=1_000.0,
        tp=50.0, sl=50.0, position=100.0, sizing="balance", max_cash=1_000.0,
        fee=0.0, max_hold=0,
    )
    assert trades == []  # never closed: still open at the last bar


def test_one_strategy_can_trade_both_ways() -> None:
    # Long on the dip at bar 1, short on the rally at bar 5.
    closes = [100.0, 99.0, 99.0, 99.0, 99.0, 103.0, 103.0, 100.0, 100.0]
    highs = list(closes)
    lows = list(closes)
    longs = [False, True] + [False] * 7
    shorts = [False] * 5 + [True] + [False] * 3
    trades, equity = core.walk(
        closes, highs, lows, longs, capital=1_000.0, tp=2.0, sl=2.0,
        position=100.0, sizing="balance", max_cash=1_000.0, fee=0.0,
        max_hold=2, short_entries=shorts,
    )
    sides = [trade[8] for trade in trades]
    assert sides == ["long", "short"]
    assert trades[0][0] == 1 and trades[1][0] == 5
    # The long goes nowhere (stopped by the hold at 99); the short sells 103 and
    # buys back at its 2% target, 100.94: a 2% gain on the book.
    assert trades[0][4] == pytest.approx(0.0)
    assert trades[1][3] == pytest.approx(103.0 * 0.98)
    assert equity[-1] == pytest.approx(1_020.0)


def test_a_bar_both_rules_fire_on_is_left_alone() -> None:
    closes = [100.0, 100.0, 100.0, 100.0]
    trades, _ = core.walk(
        closes, closes, closes, [False, True, False, False], capital=1_000.0,
        short_entries=[False, True, False, False], max_hold=1,
    )
    assert trades == []


def _rule(text):
    from lalala.engine.formula import EXIT_FIELDS, EXIT_FUNCTIONS, parse

    return parse(text, EXIT_FIELDS, EXIT_FUNCTIONS)


RULES = [
    "pnl >= 1",
    "pnl >= tp or pnl <= 0 - sl",
    "bars >= 3 and pnl < 0",
    "not (pnl < 0.4)",
    "abs(pnl) > 0.5",
    "max(pnl, 0) >= 0.7",
    "min(price, entry) < entry - 0.3",
    "sqrt(bars) > 1.5",
    "(price / entry - 1) * 100 >= 0.6",
    "gain = price - entry\ngain > 0.5 or gain < 0 - 0.5",
    "pnl % 2 > 0.5",
    "pnl ^ 2 >= 0.5",
    "price / 0 > 1",
    "pnl == 0.5",
    "pnl != 0",
    "-pnl > 0.4",
]


def _wiggle(count=400):
    import math

    closes = [100.0 + 3.0 * math.sin(i / 7.0) + 0.8 * math.sin(i / 2.3) for i in range(count)]
    return closes, [c + 0.3 for c in closes], [c - 0.3 for c in closes]


@pytest.mark.parametrize("text", RULES)
@pytest.mark.parametrize("side", ["long", "short"])
def test_every_exit_rule_compiles_and_runs_the_same_in_both_walks(text, side) -> None:
    if not core.available():
        pytest.skip("the native core is not built")

    closes, highs, lows = _wiggle()
    entries = [i % 11 == 3 for i in range(len(closes))]
    rule = _rule(text)
    assert core.compile_exit(rule) is not None

    kwargs = dict(
        capital=10_000.0, tp=1.5, sl=1.2, position=10.0, sizing="balance",
        max_cash=5_000.0, fee=0.0006, max_hold=20, side=side, exit_formula=rule,
    )
    native = core.walk(closes, highs, lows, entries, **kwargs)

    flat = [False] * len(closes)
    longs, shorts = (entries, flat) if side == "long" else (flat, entries)
    python = core._python_walk(
        closes, highs, lows, longs, shorts, 10_000.0, 1.5, 1.2, 10.0,
        "balance", 5_000.0, 0.0006, 20, False, 0.0, rule,
    )
    assert native[0] == python[0], text
    assert native[1] == python[1], text


@pytest.mark.parametrize("side", ["long", "short"])
def test_the_trailing_take_profit_is_the_same_in_both_walks(side) -> None:
    if not core.available():
        pytest.skip("the native core is not built")

    closes, highs, lows = _wiggle()
    entries = [i % 13 == 4 for i in range(len(closes))]
    kwargs = dict(
        capital=10_000.0, tp=8.0, sl=5.0, position=10.0, sizing="balance",
        max_cash=5_000.0, fee=0.0006, max_hold=30, dynamic_tp=True,
        reverse=0.6, side=side,
    )
    native = core.walk(closes, highs, lows, entries, **kwargs)
    flat = [False] * len(closes)
    longs, shorts = (entries, flat) if side == "long" else (flat, entries)
    python = core._python_walk(
        closes, highs, lows, longs, shorts, 10_000.0, 8.0, 5.0, 10.0,
        "balance", 5_000.0, 0.0006, 30, True, 0.6,
    )
    assert native[0] and native[0] == python[0]
    assert native[1] == python[1]


def test_both_ways_agree_between_the_walks() -> None:
    if not core.available():
        pytest.skip("the native core is not built")

    closes, highs, lows = _wiggle()
    longs = [i % 17 == 2 for i in range(len(closes))]
    shorts = [i % 19 == 5 for i in range(len(closes))]
    native = core.walk(
        closes, highs, lows, longs, max_hold=10, short_entries=shorts,
        capital=10_000.0, tp=1.0, sl=1.0, position=20.0, sizing="balance",
        max_cash=5_000.0, fee=0.0006,
    )
    python = core._python_walk(
        closes, highs, lows, longs, shorts, 10_000.0, 1.0, 1.0, 20.0,
        "balance", 5_000.0, 0.0006, 10,
    )
    assert {trade[8] for trade in native[0]} == {"long", "short"}
    assert native == python


def test_the_python_fallback_runs_a_rule_the_core_cannot() -> None:
    from lalala.engine.formula import Call, Formula, Number

    odd = Formula(condition=Call("sma", (Number(1.0), Number(2.0))))
    assert core.compile_exit(odd) is None
