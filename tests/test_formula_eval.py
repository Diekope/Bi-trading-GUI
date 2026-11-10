"""Running a formula over bars: the indicators, the signals, the walk."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS, FUNCTIONS, parse
from lalala.formula_eval import (
    backtest,
    bar_context,
    entry_signals,
    evaluate,
    evaluate_scalar,
    simulate,
)


@dataclass
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float


def _bars(closes, volume: float = 1.0) -> list[Bar]:
    return [
        Bar(close, close + 1.0, close - 1.0, close, volume) for close in closes
    ]


def _series(formula: str, bars):
    return evaluate(parse(formula), bar_context(bars))


# -- the indicators ---------------------------------------------------------


def test_a_rolling_average_waits_for_its_window() -> None:
    bars = _bars([1, 2, 3, 4, 5])

    values = _series("close > sma(close, 3)", bars)

    # Nothing to compare until three bars are in.
    assert values[:2] == [None, None]
    assert evaluate(parse("sma(close, 3)"), bar_context(bars)) == [
        None, None, 2.0, 3.0, 4.0,
    ]


def test_highest_lowest_change_and_shift() -> None:
    bars = _bars([1, 5, 2, 4, 3])

    assert evaluate(parse("highest(close, 3)"), bar_context(bars)) == [
        None, None, 5.0, 5.0, 4.0,
    ]
    assert evaluate(parse("lowest(close, 3)"), bar_context(bars)) == [
        None, None, 1.0, 2.0, 2.0,
    ]
    assert evaluate(parse("change(close, 1)"), bar_context(bars)) == [
        None, 4.0, -3.0, 2.0, -1.0,
    ]
    assert evaluate(parse("shift(close, 2)"), bar_context(bars)) == [
        None, None, 1.0, 5.0, 2.0,
    ]


def test_bollinger_bands_bracket_the_average() -> None:
    bars = _bars([1, 2, 3, 4, 5])
    formula = parse(
        "bollinger_lower(close, 3, 2) < close and close < bollinger_upper(close, 3, 2)"
    )

    values = evaluate(formula, bar_context(bars))

    # From the third bar on, the close sits inside its own bands.
    assert values[2:] == [1.0, 1.0, 1.0]
    middle = evaluate(parse("bollinger_middle(close, 3, 2)"), bar_context(bars))
    assert middle[:2] == [None, None]
    assert middle[2] == pytest.approx(2.0)


def test_rsi_is_high_when_everything_rises_and_none_before() -> None:
    rising = _bars([1, 2, 3, 4, 5, 6])
    values = evaluate(parse("rsi(close, 3)"), bar_context(rising))

    assert values[:3] == [None, None, None]
    assert values[3] == pytest.approx(100.0)  # nothing but gains

    falling = evaluate(
        parse("rsi(close, 3)"), bar_context(_bars([6, 5, 4, 3, 2, 1]))
    )
    assert falling[3] == pytest.approx(0.0)


def test_ema_follows_the_series() -> None:
    values = evaluate(parse("ema(close, 2)"), bar_context(_bars([1, 2, 3])))
    # Seeded on the first bar, then smoothed toward each new value.
    assert values[0] == pytest.approx(1.0)
    assert values[1] == pytest.approx(1.0 * (1 / 3) + 2.0 * (2 / 3))
    assert values[2] > values[1]


def test_maths_functions_and_arithmetic() -> None:
    bars = _bars([4, 9, 16])

    assert evaluate(parse("sqrt(close)"), bar_context(bars)) == [2.0, 3.0, 4.0]
    assert evaluate(parse("abs(0 - close)"), bar_context(bars)) == [4.0, 9.0, 16.0]
    assert evaluate(parse("min(close, 9)"), bar_context(bars)) == [4.0, 9.0, 9.0]
    assert evaluate(parse("max(close, 9)"), bar_context(bars)) == [9.0, 9.0, 16.0]
    assert evaluate(parse("close / 2 + 1"), bar_context(bars)) == [3.0, 5.5, 9.0]


def test_a_division_by_zero_is_unknown_not_infinite() -> None:
    assert evaluate(parse("close / 0"), bar_context(_bars([1, 2]))) == [None, None]


# -- the condition and the signals -----------------------------------------


def test_logic_and_comparisons_come_out_true_or_false() -> None:
    bars = _bars([1, 2, 3])

    assert _series("close > 1", bars) == [0.0, 1.0, 1.0]
    assert _series("close > 1 and close < 3", bars) == [0.0, 1.0, 0.0]
    assert _series("close < 1 or close > 2", bars) == [0.0, 0.0, 1.0]
    assert _series("not close > 1", bars) == [1.0, 0.0, 0.0]


def test_signals_are_the_bars_where_the_rule_holds() -> None:
    bars = _bars([100, 100, 80, 80, 120, 120])

    assert entry_signals(parse("close < 90"), bars) == [2, 3]
    # Nothing to say yet: no signals.
    assert entry_signals(parse("close < sma(close, 3)"), bars) == [2, 3]


def test_an_empty_formula_has_no_signals() -> None:
    bars = _bars([1, 2, 3])
    assert entry_signals(parse(""), bars) == []


def test_bars_can_be_dicts_or_objects() -> None:
    dicts = [
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 3.0},
        {"open": 1.5, "high": 2.5, "low": 1.0, "close": 2.5, "volume": 4.0},
    ]
    assert evaluate(parse("close > 2"), bar_context(dicts)) == [0.0, 1.0]


# -- the exit rule, bar by bar ---------------------------------------------


def test_an_exit_rule_is_checked_against_the_open_trade() -> None:
    exit_rule = parse("pnl >= tp", EXIT_FIELDS, EXIT_FUNCTIONS)

    assert evaluate_scalar(
        exit_rule, {"price": 103.0, "entry": 100.0, "tp": 2.0, "sl": 1.0,
                    "pnl": 3.0, "bars": 5}
    ) is True
    assert evaluate_scalar(
        exit_rule, {"price": 100.5, "entry": 100.0, "tp": 2.0, "sl": 1.0,
                    "pnl": 0.5, "bars": 5}
    ) is False


def test_the_walk_opens_on_a_signal_and_closes_on_the_exit() -> None:
    # Down to 80, then up to 120: in on the dip, out on the target.
    bars = _bars([100, 100, 100, 80, 80, 120, 120])
    entry = parse("close < 90")
    exit_ = parse(
        "pnl >= tp or pnl <= 0 - sl or bars >= 5", EXIT_FIELDS, EXIT_FUNCTIONS
    )

    entries, exits = simulate(bars, entry, exit_, tp=10.0, sl=5.0)

    assert entries == [3]
    assert exits == [5]  # +50% at bar 5, past the 10% target


def test_the_walk_stops_a_losing_trade_on_the_stop() -> None:
    bars = _bars([100, 100, 80, 70, 70])
    entry = parse("close < 90")
    exit_ = parse("pnl <= 0 - sl", EXIT_FIELDS, EXIT_FUNCTIONS)

    entries, exits = simulate(bars, entry, exit_, tp=10.0, sl=5.0)

    # In on the dip, out on the stop, and the rule fires again afterwards.
    assert entries == [2, 4]
    assert exits == [3]  # 80 -> 70 is -12.5%, past the 5% stop


def test_the_walk_holds_one_position_at_a_time() -> None:
    bars = _bars([80, 80, 80, 80, 80])
    entry = parse("close < 90")
    exit_ = parse("bars >= 1", EXIT_FIELDS, EXIT_FUNCTIONS)

    entries, exits = simulate(bars, entry, exit_)

    # In on the first, out on the next, in again, and so on — never two.
    assert entries == [0, 2, 4]
    assert exits == [1, 3]
    assert all(
        entries[i] < exits[i] for i in range(len(exits))
    )


def test_the_new_indicators_run() -> None:
    bars = _bars([1, 2, 3, 4, 5, 6])

    stdev = evaluate(parse("stdev(close, 3)"), bar_context(bars))
    assert stdev[:2] == [None, None]
    assert stdev[2] == pytest.approx((2 / 3) ** 0.5)  # [1, 2, 3]

    zscore = evaluate(parse("zscore(close, 3)"), bar_context(bars))
    assert zscore[:2] == [None, None]
    assert zscore[2] == pytest.approx((3 - 2) / (2 / 3) ** 0.5)

    log = evaluate(parse("log(close)"), bar_context(bars))
    assert log[0] == pytest.approx(0.0)  # log(1)
    assert log[1] == pytest.approx(math.log(2))


def test_a_name_with_no_history_makes_a_rule_silent() -> None:
    from lalala.formula import ENTRY_FIELDS

    bars = _bars([1, 2, 3, 4, 5])
    # The rule validates, but `spread` carries nothing, so it never fires.
    rule = parse("close > 0 and spread > 0", ENTRY_FIELDS, FUNCTIONS)
    assert entry_signals(rule, bars) == []
    values = evaluate(rule, bar_context(bars))
    assert values == [None] * len(bars) or not any(values)


def test_the_walk_needs_both_rules() -> None:
    bars = _bars([80, 80, 80])
    assert simulate(bars, None, None) == ([], [])
    assert simulate(bars, parse("close < 90"), None) == ([0], [])


# -- the run, and what to compare it to ------------------------------------


def test_a_run_draws_three_curves_from_the_same_capital() -> None:
    bars = _bars([100 + index % 20 for index in range(300)])
    report = backtest(bars, parse("close < sma(close, 5)"), None, capital=1_000.0)

    assert len(report.strategy) == len(bars)
    assert len(report.random) == len(bars)
    assert len(report.hold) == len(bars)
    # All three start where they started.
    assert report.strategy[0] == pytest.approx(1_000.0)
    assert report.hold[0] == pytest.approx(1_000.0)
    assert report.capital == 1_000.0


def test_the_numbers_above_the_curves() -> None:
    bars = _bars([100 + index % 20 for index in range(300)])
    exit_ = parse("pnl >= tp or pnl <= 0 - sl", EXIT_FIELDS, EXIT_FUNCTIONS)
    report = backtest(
        bars, parse("close < sma(close, 5)"), exit_, tp=2.0, sl=1.0
    )

    assert report.trades > 0
    assert 0.0 <= report.win_rate <= 1.0
    assert report.wins <= report.trades
    assert report.pnl == pytest.approx(report.return_of(report.strategy))
    assert report.max_drawdown <= 0.0
    assert isinstance(report.sharpe, float)


def test_buy_and_hold_is_the_whole_book_from_the_first_bar() -> None:
    bars = _bars([100, 110, 90, 120])
    report = backtest(bars, None, None, capital=1_000.0)

    assert report.hold == pytest.approx([1_000.0, 1_100.0, 900.0, 1_200.0])


def test_a_run_with_no_bars_is_empty() -> None:
    report = backtest([], parse("close < 10"), None)
    assert report.strategy == []
    assert report.trades == 0
    assert report.pnl == 0.0
    assert report.win_rate == 0.0
    assert report.sharpe == 0.0


def test_a_pnl_exit_names_take_profit_and_stop_loss() -> None:
    # A rule written against pnl — no tp or sl token in sight — must still
    # read as Take profit / Stop loss, not a bare Rule.
    from lalala.formula_eval import _exit_reason

    exit_ = parse("pnl >= 2 or pnl <= 0 - 2", EXIT_FIELDS, EXIT_FUNCTIONS)
    profit = {"price": 105.0, "entry": 100.0, "tp": 2.0, "sl": 2.0, "pnl": 5.0, "bars": 3}
    loss = {"price": 95.0, "entry": 100.0, "tp": 2.0, "sl": 2.0, "pnl": -5.0, "bars": 3}

    assert _exit_reason(exit_, profit) == "Take profit"
    assert _exit_reason(exit_, loss) == "Stop loss"


def test_a_tp_sl_exit_still_names_the_reason() -> None:
    from lalala.formula_eval import _exit_reason

    exit_ = parse("pnl >= tp or pnl <= 0 - sl", EXIT_FIELDS, EXIT_FUNCTIONS)
    profit = {"price": 105.0, "entry": 100.0, "tp": 2.0, "sl": 1.0, "pnl": 5.0, "bars": 3}
    loss = {"price": 95.0, "entry": 100.0, "tp": 2.0, "sl": 1.0, "pnl": -5.0, "bars": 3}

    assert _exit_reason(exit_, profit) == "Take profit"
    assert _exit_reason(exit_, loss) == "Stop loss"


def test_a_time_exit_still_reads_as_time() -> None:
    from lalala.formula_eval import _exit_reason

    exit_ = parse("bars >= 3", EXIT_FIELDS, EXIT_FUNCTIONS)
    context = {"price": 100.0, "entry": 100.0, "tp": 2.0, "sl": 1.0, "pnl": 0.0, "bars": 5}

    assert _exit_reason(exit_, context) == "Time"


def test_a_pnl_exit_reports_fewer_rules_in_a_run() -> None:
    bars = _bars([100 + (index % 11) - 5 for index in range(400)])
    exit_ = parse("pnl >= 2 or pnl <= 0 - 2", EXIT_FIELDS, EXIT_FUNCTIONS)
    report = backtest(bars, parse("close < sma(close, 5)"), exit_, tp=2.0, sl=2.0)

    labels = {label for label, _count, _share in report.reason_shares}
    assert "Take profit" in labels
    assert "Rule" not in labels


def test_bar_context_reads_objects_and_dicts_alike() -> None:
    from lalala.formula_eval import bar_context

    object_bars = _bars([1.0, 2.0, 3.0])
    dict_bars = [
        {"open": b.open, "high": b.high, "low": b.low, "close": b.close,
         "volume": b.volume}
        for b in object_bars
    ]

    assert bar_context(dict_bars, ("close",)) == bar_context(object_bars, ("close",))
    assert bar_context([], ("close",)) == {"close": []}


def test_bar_context_reads_price_as_the_close_and_skips_bools() -> None:
    from lalala.formula_eval import bar_context

    # A bar object with no `price` reads the close for it, as the engine needs.
    class Bar:
        def __init__(self, close):
            self.open = close
            self.high = close
            self.low = close
            self.close = close
            self.volume = True  # a bool is not a number

    context = bar_context([Bar(10.0), Bar(11.0)], ("price", "volume", "missing"))

    assert context["price"] == [10.0, 11.0]
    assert context["volume"] == [None, None]
    assert context["missing"] == [None, None]
