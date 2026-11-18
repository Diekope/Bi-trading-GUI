"""Running a formula over bars: the indicators, the signals, the walk."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from bi_trading.engine.formula import EXIT_FIELDS, EXIT_FUNCTIONS, FUNCTIONS, parse
from bi_trading.engine.formula_eval import (
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
    from bi_trading.engine.formula import ENTRY_FIELDS

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
    from bi_trading.engine.formula_eval import _exit_reason

    exit_ = parse("pnl >= 2 or pnl <= 0 - 2", EXIT_FIELDS, EXIT_FUNCTIONS)
    profit = {"price": 105.0, "entry": 100.0, "tp": 2.0, "sl": 2.0, "pnl": 5.0, "bars": 3}
    loss = {"price": 95.0, "entry": 100.0, "tp": 2.0, "sl": 2.0, "pnl": -5.0, "bars": 3}

    assert _exit_reason(exit_, profit) == "Take profit"
    assert _exit_reason(exit_, loss) == "Stop loss"


def test_a_tp_sl_exit_still_names_the_reason() -> None:
    from bi_trading.engine.formula_eval import _exit_reason

    exit_ = parse("pnl >= tp or pnl <= 0 - sl", EXIT_FIELDS, EXIT_FUNCTIONS)
    profit = {"price": 105.0, "entry": 100.0, "tp": 2.0, "sl": 1.0, "pnl": 5.0, "bars": 3}
    loss = {"price": 95.0, "entry": 100.0, "tp": 2.0, "sl": 1.0, "pnl": -5.0, "bars": 3}

    assert _exit_reason(exit_, profit) == "Take profit"
    assert _exit_reason(exit_, loss) == "Stop loss"


def test_a_time_exit_still_reads_as_time() -> None:
    from bi_trading.engine.formula_eval import _exit_reason

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
    from bi_trading.engine.formula_eval import bar_context

    object_bars = _bars([1.0, 2.0, 3.0])
    dict_bars = [
        {"open": b.open, "high": b.high, "low": b.low, "close": b.close,
         "volume": b.volume}
        for b in object_bars
    ]

    assert bar_context(dict_bars, ("close",)) == bar_context(object_bars, ("close",))
    assert bar_context([], ("close",)) == {"close": []}


def test_bar_context_reads_price_as_the_close_and_skips_bools() -> None:
    from bi_trading.engine.formula_eval import bar_context

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


def _wandering_bars(count: int) -> list:
    import random

    random.seed(7)
    bars = []
    close = 100.0
    for _ in range(count):
        close = max(1.0, close + random.uniform(-2.0, 2.0))
        bars.append(
            Bar(close - 0.5, close + 1.0, close - 1.0, close, random.uniform(1, 5))
        )
    return bars


def test_the_numpy_signals_match_the_list_walk() -> None:
    from bi_trading.engine.formula_eval import _numpy_signals, bar_context, evaluate, _truth

    fields = ("open", "high", "low", "close", "volume")
    bars = _wandering_bars(2000)
    rules = (
        "close < sma(close, 20)",
        "close > ema(close, 10)",
        "rsi(close, 14) < 30",
        "close < bollinger_lower(close, 20, 2)",
        "highest(high, 10) == high",
        "zscore(close, 20) < 0 - 1",
        "change(close, 5) > 0 and volume > 2",
        "shift(close, 1) < close",
        "abs(change(close, 3)) > 1",
        "stdev(close, 20) > 0.5",
        "not (close > sma(close, 20))",
        "min(close, open) < sma(close, 5) - 0.1",
        "sqrt(change(close, 2)) > 1",
    )
    for text in rules:
        formula = parse(text, fields)
        fast = _numpy_signals(formula, bars, fields)
        assert fast is not None, text
        reference = [
            index
            for index, value in enumerate(evaluate(formula, bar_context(bars, fields)))
            if _truth(value)
        ]
        assert fast == reference, text


def test_the_numpy_signals_yield_to_the_list_walk_on_a_gap() -> None:
    from bi_trading.engine.formula_eval import _numpy_signals

    fields = ("close",)
    gappy = [{"close": 1.0}, {"close": None}, {"close": 3.0}]
    formula = parse("close > 0", fields)

    # A None cannot be lifted to an array, so the fast path declines.
    assert _numpy_signals(formula, gappy, fields) is None


# -- shorting ---------------------------------------------------------------


def _falling():
    return _bars([100, 100, 98, 96, 94, 92, 90])


def test_a_short_gains_as_price_falls_and_a_long_loses() -> None:
    entry = parse("close < 101")
    exit_ = parse("bars >= 3", EXIT_FIELDS, EXIT_FUNCTIONS)
    long = backtest(_falling(), entry, exit_, tp=2.0, sl=1.0)
    short = backtest(_falling(), entry, exit_, tp=2.0, sl=1.0, short=True)

    assert long.pnl < 0 < short.pnl
    assert short.wins == short.trades


def test_a_short_exit_rule_reads_pnl_the_way_the_trade_feels() -> None:
    # pnl is positive for a short when the price has dropped.
    entry = parse("close < 101")
    exit_ = parse("pnl >= 4", EXIT_FIELDS, EXIT_FUNCTIONS)
    short = backtest(_falling(), entry, exit_, short=True)
    long = backtest(_falling(), entry, exit_)

    assert short.trades >= 1
    assert short.reasons  # it closed on its own rule, not at the end of data
    assert long.trades == 1 and long.wins == 0  # never reached +4%, ended open


def test_simulate_marks_a_short_exit_on_the_fall() -> None:
    entry = parse("close < 101")
    exit_ = parse("pnl >= 4", EXIT_FIELDS, EXIT_FUNCTIONS)
    _, short_exits = simulate(_falling(), entry, exit_, short=True)
    _, long_exits = simulate(_falling(), entry, exit_)
    assert short_exits and not long_exits


def test_one_rule_set_can_go_long_and_short() -> None:
    bars = _bars([100, 98, 98, 98, 102, 102, 100, 100, 100])
    longs = parse("close < 99")
    shorts = parse("close > 101")
    exit_ = parse("bars >= 2", EXIT_FIELDS, EXIT_FUNCTIONS)

    both = backtest(bars, longs, exit_, short_entry=shorts)
    long_only = backtest(bars, longs, exit_)
    assert both.trades > long_only.trades
    # The short leg made money as price fell from 102 to 100.
    assert both.wins >= 1


def test_a_bar_both_rules_fire_on_opens_nothing() -> None:
    bars = _bars([100, 100, 100, 100])
    rule = parse("close > 0")
    exit_ = parse("bars >= 1", EXIT_FIELDS, EXIT_FUNCTIONS)
    assert backtest(bars, rule, exit_, short_entry=rule).trades == 0


def test_slippage_costs_the_builders_preview_something() -> None:
    entry = parse("close < 101")
    exit_ = parse("bars >= 2", EXIT_FIELDS, EXIT_FUNCTIONS)
    clean = backtest(_bars([100, 100, 100, 100, 100]), entry, exit_, slippage=0.0)
    slipped = backtest(_bars([100, 100, 100, 100, 100]), entry, exit_, slippage=0.001)
    assert slipped.pnl < clean.pnl
    shorted = backtest(
        _bars([100, 100, 100, 100, 100]), entry, exit_, short=True, slippage=0.001
    )
    assert shorted.pnl < clean.pnl


# -- a series fed in pieces ----------------------------------------------------

RULES = [
    "close < sma(close, 20)",
    "close < bollinger_lower(close, 20, 2) and volume > 0.5",
    "ema(close, 12) > ema(close, 26)",
    "rsi(close, 14) < 35",
    "close >= highest(close, 30) or close <= lowest(close, 30)",
    "zscore(close, 25) < 0 - 1.2",
    "change(close, 5) > 0 and shift(close, 3) < close",
    "mid = sma(close, 10)\nslow = ema(mid, 8)\nclose < slow and stdev(close, 15) > 0",
    "sma(sma(close, 7), 9) > sma(close, 30)",
    "not (rsi(ema(close, 5), 9) > 50)",
    "x = rsi(close, 9)\ny = sma(x, 6)\nx < y - 3 and abs(close - open) < 3 * sma(abs(close - open), 12)",
]


def _columns(size: int = 1_400, seed: int = 21) -> dict:
    import random

    import numpy as np

    rng = random.Random(seed)
    price, close = 100.0, []
    for _ in range(size):
        price *= 1.0 + rng.uniform(-0.012, 0.012)
        close.append(price)
    close_a = np.array(close)
    open_a = np.concatenate(([close_a[0]], close_a[:-1]))
    spread = np.array([rng.uniform(0.001, 0.006) for _ in range(size)])
    return {
        "open": open_a, "high": np.maximum(open_a, close_a) * (1 + spread),
        "low": np.minimum(open_a, close_a) * (1 - spread), "close": close_a,
        "volume": np.array([rng.uniform(0.1, 2.0) for _ in range(size)]),
    }


def _fed(formula, columns, cuts, warmup=0):
    from bi_trading.engine.formula_eval import SignalStream

    stream = SignalStream(formula, warmup=warmup)
    out, start = [], 0
    size = len(columns["close"])
    for stop in [*cuts, size]:
        piece = {name: values[start:stop] for name, values in columns.items()}
        out += stream.feed(piece, start)
        start = stop
    return out


@pytest.mark.parametrize("text", RULES)
def test_a_rule_fed_in_pieces_fires_where_the_whole_series_does(text) -> None:
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import STREAM_FIELDS, entry_signals

    formula = parse(text, ENTRY_FIELDS, FUNCTIONS)
    columns = _columns()
    whole = entry_signals(formula, columns, STREAM_FIELDS)
    assert whole, f"the rule never fires on the test data: {text}"
    for cuts in ([], [1], [700], [3, 17, 18, 400, 401], list(range(50, 1_400, 50)), [5, 6, 7, 8, 9, 10]):
        assert _fed(formula, columns, cuts) == whole, (text, cuts)


def test_a_warmup_holds_back_early_signals_across_pieces() -> None:
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import STREAM_FIELDS, entry_signals

    formula = parse("close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS)
    columns = _columns()
    whole = entry_signals(formula, columns, STREAM_FIELDS, warmup=300)
    assert whole and min(whole) >= 300
    assert _fed(formula, columns, [100, 350, 800], warmup=300) == whole


def test_pieces_of_a_single_bar_still_agree() -> None:
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import STREAM_FIELDS, entry_signals

    formula = parse("rsi(close, 5) < 40 and close < sma(close, 4)", ENTRY_FIELDS, FUNCTIONS)
    columns = {name: values[:120] for name, values in _columns().items()}
    assert _fed(formula, columns, list(range(1, 120))) == entry_signals(
        formula, columns, STREAM_FIELDS
    )


def test_what_cannot_be_fed_in_pieces_is_refused_up_front() -> None:
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import SignalStream, StreamUnsupported

    for text in ("model_p > 0.5", "spread < 0.02", "price < sma(close, 5)"):
        formula = parse(text, ENTRY_FIELDS, FUNCTIONS)
        assert SignalStream.supports(formula) is False, text
        with pytest.raises(StreamUnsupported):
            SignalStream(formula)
    assert SignalStream.supports(None) is False
    assert SignalStream.supports(parse("close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS))


def test_a_gap_in_the_data_is_refused() -> None:
    import numpy as np

    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import SignalStream, StreamUnsupported

    columns = _columns(50)
    columns["close"][10] = np.nan
    stream = SignalStream(parse("close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS))
    with pytest.raises(StreamUnsupported):
        stream.feed(columns, 0)


def test_ema_and_rsi_in_pieces_equal_the_list_indicators() -> None:
    from bi_trading.engine.formula_eval import _ema, _rsi

    close = _columns(500)["close"].tolist()
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import SignalStream

    for text, reference in (("ema(close, 9) > 0", _ema(close, 9)), ("rsi(close, 9) >= 0", _rsi(close, 9))):
        formula = parse(text, ENTRY_FIELDS, FUNCTIONS)
        stream = SignalStream(formula)
        picked = []
        for start in range(0, 500, 77):
            piece = {n: v[start:start + 77] for n, v in _columns(500).items()}
            picked += stream.feed(piece, start)
        defined = [i for i, v in enumerate(reference) if v is not None]
        assert picked == defined, text
