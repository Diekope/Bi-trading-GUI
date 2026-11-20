"""The streaming walk, the session, and the results tile's live curves."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.data import candles  # noqa: E402
from bi_trading.data.candles import append_rows, candle_file  # noqa: E402
from bi_trading.ui.strat.strat_playback import (  # noqa: E402
    BOLLINGER_PERIOD,
    Candle,
    Playback,
    PlaybackTile,
    aggregate,
    build_session,
    count_bars,
    iter_candles,
    plan_stride,
    sample_candles,
)
from bi_trading.ui.strat.strat_results import ResultsTile  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402

PARAMS = {
    "initial_capital": 10_000.0,
    "tp": 2.0,
    "sl": 1.0,
    "position": 10.0,
    "sizing": "balance",
    "cash": 2_000.0,
}


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()
    from bi_trading.ui.strat import strat_playback

    strat_playback._SPAN_CACHE.clear()


def _bar(index: int, close: float, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(
        stamp=index * 60_000,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=1.0,
    )


def _write(year: int, count: int, price: float = 100.0) -> None:
    append_rows(
        candle_file(year),
        [
            (index * 60_000, price, price + 1.0, price - 1.0, price, 1.0)
            for index in range(count)
        ],
    )


def _playback(bars, **overrides) -> Playback:
    settings = dict(
        capital=1_000.0, tp=2.0, sl=1.0, position=100.0, sizing="fixed",
        max_cash=1_000.0, fee=0.0, max_hold=90,
        # A coin that always says yes: every flat bar takes the trade, which
        # is what these tests are pinning.
        rule="random", entry_chance=1.0,
    )
    settings.update(overrides)
    return Playback(bars, **settings)


# -- the stream ------------------------------------------------------------


def test_aggregate_compacts_the_bar() -> None:
    bars = [
        Candle(0, 10.0, 12.0, 9.0, 11.0, 1.0),
        Candle(1, 11.0, 15.0, 10.0, 14.0, 2.0),
        Candle(2, 14.0, 14.5, 8.0, 9.0, 3.0),
        Candle(3, 9.0, 10.0, 9.0, 9.5, 4.0),
    ]

    two = list(aggregate(iter(bars), 2))

    assert len(two) == 2
    assert two[0] == Candle(0, 10.0, 15.0, 9.0, 14.0, 3.0)  # first open, last close
    assert two[1].stamp == 2
    assert two[1].high == 14.5 and two[1].low == 8.0
    assert list(aggregate(iter(bars), 1)) == bars


def test_the_store_is_streamed_in_order_and_counted() -> None:
    _write(2019, 5, price=50.0)
    _write(2020, 7, price=70.0)

    bars = list(iter_candles([2019, 2020], "1m"))

    assert [round(bar.close) for bar in bars] == [50] * 5 + [70] * 7
    assert count_bars([2019, 2020], "1m") == 12
    # Five-minute bars are whole on the clock: the first file's five minutes make
    # one bar; the second file's last two minutes are not a bar, so they are
    # dropped. The count matches what the stream yields.
    assert count_bars([2019, 2020], "5m") == 2
    assert len(list(iter_candles([2019, 2020], "5m"))) == 2


def test_an_empty_span_counts_nothing() -> None:
    assert count_bars([2019], "1m") == 0
    assert list(iter_candles([2019], "1m")) == []


def test_the_stride_keeps_a_run_watchable() -> None:
    from bi_trading.ui.strat.strat_playback import MAX_TICKS

    assert plan_stride(400) == 1               # short runs play bar by bar
    assert plan_stride(MAX_TICKS) == 1
    assert plan_stride(MAX_TICKS * 10) == 10
    # A decade of minutes still finishes in about the target time.
    assert plan_stride(4_840_000) * MAX_TICKS >= 4_840_000


def test_the_sample_is_deterministic_and_well_formed() -> None:
    first = sample_candles(60)
    second = sample_candles(60)

    assert first == second
    assert len(first) == 60
    for bar in first:
        assert bar.low <= min(bar.open, bar.close)
        assert bar.high >= max(bar.open, bar.close)
        assert bar.volume > 0


# -- the walk --------------------------------------------------------------


def test_a_target_touch_closes_the_trade_in_profit() -> None:
    bars = [_bar(0, 100.0), _bar(1, 101.0), _bar(2, 101.0, high=104.0)]
    play = _playback(bars)

    for _ in range(3):
        play.step()

    assert play.trades == 1
    assert play.win_rate == pytest.approx(1.0)
    assert play.streak == 1 and play.best_win == 1
    assert play.in_position is False
    # $100 of notional at 101, closed at the 2% target (103.02): about +$2.
    assert play.equity == pytest.approx(1_002.0, abs=0.05)


def test_a_stop_touch_closes_the_trade_at_a_loss() -> None:
    bars = [_bar(0, 100.0), _bar(1, 101.0), _bar(2, 101.0, low=98.0)]
    play = _playback(bars)

    for _ in range(3):
        play.step()

    assert play.trades == 1
    assert play.streak == -1 and play.worst_loss == -1
    assert play.equity < 1_000.0
    assert play.max_drawdown < 0.0


def test_the_book_is_realised_only() -> None:
    bars = [_bar(0, 100.0), _bar(1, 100.0)]  # flat: nothing to enter on
    play = _playback(bars)
    play.step()
    assert play.equity == pytest.approx(play.cash)

    rising = _playback([_bar(0, 100.0), _bar(1, 101.0), _bar(2, 105.0, high=110.0)])
    for _ in range(2):
        rising.step()
    assert rising.in_position is True
    # The open position is carried at cost, so entering does not move the book
    # and the rising close is not counted until the trade closes.
    assert rising.equity == pytest.approx(1_000.0)
    assert rising.cash == pytest.approx(900.0)


def test_the_walk_stops_at_the_end() -> None:
    play = _playback([_bar(0, 100.0), _bar(1, 101.0)])

    play.step()
    assert play.index == 1
    play.step()
    assert play.index == 2
    assert play.done is True

    play.step()  # no loop, no reset: starting over is a decision

    assert play.index == 2
    assert play.done is True
    assert play.in_position is True
    assert play.equity == pytest.approx(1_000.0)


def test_a_stride_consumes_several_bars_at_once() -> None:
    bars = sample_candles(30)
    play = Playback(bars, rule="random", stride=5, total=30)

    play.step()
    assert play.index == 5
    play.step()
    assert play.index == 10
    # Only what the picture needs is kept.
    assert len(play.recent()) == 10


def test_the_window_never_grows_past_the_chart() -> None:
    from bi_trading.ui.strat.strat_playback import CHART_BARS

    play = Playback(sample_candles(CHART_BARS + 50), rule="random", stride=25)
    while not play.done:
        play.step()

    assert play.done is True
    assert len(play.recent()) == CHART_BARS


def test_a_seek_matches_the_python_walk() -> None:
    from bi_trading.ui.strat.strat_playback import build_session

    params = {
        "initial_capital": 10_000.0, "tp": 2.0, "sl": 1.0, "position": 10.0,
        "sizing": "balance", "cash": 2_000.0, "fee": 0.06,
    }
    session = build_session([], params, "bollinger", "1m")
    # The span is in memory, so a seek is one walk — native or Python.
    assert session._core_ready() is True
    reference = build_session([], params, "bollinger", "1m")
    for _ in range(200):
        reference.strategy.step()
        reference.random.step()

    session.seek(200)
    assert session.strategy.index == 200
    assert session.strategy.trades == reference.strategy.trades
    assert session.strategy.equity == pytest.approx(
        reference.strategy.equity, abs=1e-6
    )


def test_a_window_around_a_stamp_is_read() -> None:
    from bi_trading.ui.strat.strat_playback import window_around

    _write(2021, 300, price=200.0)
    # The stamp of bar 150 of 2021 (the writer uses index * 60_000).
    bars = window_around([2021], "1m", 150 * 60_000, count=40)
    assert bars
    assert len(bars) <= 40
    assert any(bar.stamp == 150 * 60_000 for bar in bars)


def test_a_saved_rule_can_drive_the_walk() -> None:
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.ui.strat.strat_playback import build_session

    formula = parse("close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS)
    params = {
        "initial_capital": 10_000.0,
        "tp": 2.0,
        "sl": 1.0,
        "position": 10.0,
        "sizing": "balance",
        "cash": 2_000.0,
    }
    session = build_session([], params, "saved", "1m", entry_formula=formula)
    # The rule's bars were worked out up front, and the walk opens on them.
    assert session.strategy._entries is not None
    while not session.strategy.done:
        session.advance()
    assert session.strategy.trades >= 0


def test_sharpe_is_kept_without_the_curve() -> None:
    """No per-bar series is stored: the statistics are updated as it goes."""
    play = _playback(sample_candles(200))

    while not play.done:
        play.step()

    assert not hasattr(play, "equity_curve")
    assert isinstance(play.sharpe, float)
    assert play.progress == pytest.approx(1.0)


def test_one_position_at_a_time() -> None:
    bars = [_bar(index, 100.0 + index, high=100.0 + index + 0.5) for index in range(6)]
    play = _playback(bars)

    for _ in range(6):
        play.step()
        assert play.qty == 0.0 or play.entry_index < play.index


def test_bollinger_bands_need_history_before_they_exist() -> None:
    from bi_trading.ui.strat.strat_playback import bollinger_bands

    candles_ = sample_candles(30)
    bands = bollinger_bands(candles_, period=20, deviations=2.0)

    assert len(bands) == 30
    assert all(band is None for band in bands[:19])
    middle, upper, lower = bands[19]
    assert lower < middle < upper


def test_bollinger_reversion_waits_for_a_dip() -> None:
    # Twenty quiet bars, then one that closes far below the band.
    bars = [_bar(index, 100.0) for index in range(BOLLINGER_PERIOD)]
    bars.append(Candle(20 * 60_000, 100.0, 100.0, 80.0, 80.0, 1.0))
    play = Playback(
        bars, rule="bollinger", capital=1_000.0, tp=2.0, sl=1.0,
        position=100.0, sizing="fixed", max_cash=1_000.0,
    )

    for _ in range(BOLLINGER_PERIOD):
        play.step()
    assert play.in_position is False   # nothing has dipped yet

    play.step()
    assert play.in_position is True    # the dip bought
    assert play.entry_price == pytest.approx(80.0)


# -- the session -----------------------------------------------------------


def test_a_session_walks_the_whole_span_and_samples_its_curves() -> None:
    _write(2020, 120, price=100.0)
    session = build_session([2020], PARAMS)

    assert session.total == 120
    assert session.strategy.stride == 1
    for _ in range(120):
        session.advance()

    assert session.strategy.done is True
    # One point per tick, not one per bar: the chart has no use for more.
    assert len(session.strategy_curve) == 121
    assert len(session.random_curve) == 121
    assert len(session.benchmark) == 121
    assert session.strategy_curve[0] == pytest.approx(PARAMS["initial_capital"])


def test_a_long_span_is_planned_to_fast_forward() -> None:
    _write(2020, 4000, price=100.0)
    session = build_session([2020], PARAMS)

    assert session.total == 4000
    assert session.strategy.stride > 1
    assert session.strategy.stride == session.random.stride


def test_a_span_with_nothing_on_disk_falls_back_to_a_sample() -> None:
    session = build_session([2019], PARAMS)
    assert session.total == 400
    assert session.strategy.total == 400


def test_the_tile_walks_and_reports_progress(app: QApplication) -> None:
    _write(2021, 300, price=200.0)
    tile = PlaybackTile()
    tile.set_source([2021], "1m")
    tile.set_params(PARAMS)
    tile.restart()
    app.processEvents()

    assert tile.playing() is True
    assert tile.source == "2021 · 1m"
    assert tile.playback.total == 300

    for _ in range(30):
        tile._tick()
    assert tile.playback.index > 0

    values = [value.text() for _, value in tile._metric_labels]
    assert all("/ 300" not in text for text in values)  # progress moved out
    assert "300 candles" in tile.progress_label.text()
    assert 0 < tile.progress.value() <= 1000
    tile.close()


def test_the_tile_stops_at_the_end_of_the_series(app: QApplication) -> None:
    _write(2021, 20, price=200.0)
    tile = PlaybackTile()
    tile.set_source([2021], "1m")
    tile.restart()

    for _ in range(200):
        tile._tick()

    assert tile.playback.done is True
    assert tile.playing() is False          # it stopped on its own
    assert tile.run_button.text() == "Run"
    assert "finished" in tile.note.text()
    tile.close()


def test_the_tile_starts_idle(app: QApplication) -> None:
    tile = PlaybackTile()

    assert tile.playing() is False
    assert tile.playback.total == 0
    assert "idle" in tile.note.text()
    assert tile.run_button.text() == "Run"
    tile.close()


def test_the_results_legend_follows_the_curves(app: QApplication) -> None:
    _write(2021, 60, price=100.0)
    session = build_session([2021], PARAMS)
    tile = ResultsTile()
    tile.resize(620, 420)
    tile.show()
    app.processEvents()

    assert "no run yet" in tile.note.text()
    tile.set_session(session)
    app.processEvents()
    assert "return since the start" in tile.note.text()

    for _ in range(60):
        session.advance()
    tile.refresh()

    hold = session.return_of(session.benchmark) * 100
    assert tile.legend["hold"].text() == f"buy & hold {hold:+,.2f}%"
    assert not tile.grab().toImage().isNull()
    tile.close()


def test_the_results_curve_paints_before_any_run(app: QApplication) -> None:
    tile = ResultsTile()
    tile.resize(400, 300)
    tile.show()
    app.processEvents()

    assert not tile.curve.grab().toImage().isNull()
    tile.close()


def test_the_loaded_span_is_memoised(monkeypatch) -> None:
    from bi_trading.ui.strat import playback_data as strat_playback

    _write(2021, 20)
    calls = {"n": 0}
    original = strat_playback.iter_candles

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(strat_playback, "iter_candles", counted)

    first = strat_playback.load_all_candles([2021], "1m")
    second = strat_playback.load_all_candles([2021], "1m")

    assert calls["n"] == 1  # the second read is served from memory
    assert len(first) == len(second) == 20

    _write(2021, 5)  # the file changed: a new signature
    strat_playback.load_all_candles([2021], "1m")
    assert calls["n"] == 2


def _walk_params(**more):
    return {
        "initial_capital": 10_000.0, "tp": 2.0, "sl": 1.0, "position": 10.0,
        "sizing": "balance", "cash": 2_000.0, "fee": 0.06, **more,
    }


def test_a_short_seek_matches_the_stepped_walk() -> None:
    session = build_session([], _walk_params(), "bollinger", "1m", side="short")
    reference = build_session([], _walk_params(), "bollinger", "1m", side="short")
    for _ in range(300):
        reference.strategy.step()
        reference.random.step()

    session.seek(300)
    assert session.strategy.trades == reference.strategy.trades
    assert session.strategy.trades > 0
    assert session.strategy.equity == pytest.approx(
        reference.strategy.equity, abs=1e-6
    )
    assert session.random.trades == reference.random.trades
    # Every logged trade says which way it went.
    assert {record[-1] for record in session.strategy.trades_log} == {"short"}


def test_an_exit_rule_drives_the_walk_and_the_seek_agrees() -> None:
    from bi_trading.engine.formula import (
        ENTRY_FIELDS,
        EXIT_FIELDS,
        EXIT_FUNCTIONS,
        FUNCTIONS,
        parse,
    )

    entry = parse("close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS)
    rule = parse("pnl >= 0.3", EXIT_FIELDS, EXIT_FUNCTIONS)

    def make():
        return build_session(
            [], _walk_params(tp=20.0, sl=20.0), "saved", "1m",
            entry_formula=entry, exit_formula=rule,
        )

    session, reference = make(), make()
    for _ in range(300):
        reference.strategy.step()
    session.seek(300)

    reasons = {record[9] for record in reference.strategy.trades_log}
    assert "rule" in reasons
    assert session.strategy.trades == reference.strategy.trades
    assert session.strategy.equity == pytest.approx(
        reference.strategy.equity, abs=1e-6
    )


def test_a_trade_holds_seven_candles_by_default() -> None:
    from bi_trading.engine.core import DEFAULT_HOLD

    assert DEFAULT_HOLD == 7
    session = build_session([], {k: v for k, v in _walk_params().items()}, "bollinger", "1m")
    assert session.settings["max_hold"] == 7
    assert session.strategy.max_hold == 7


def test_the_hold_parameter_reaches_the_walk() -> None:
    session = build_session([], _walk_params(hold=3), "bollinger", "1m")
    assert session.strategy.max_hold == 3
    session.seek(400)
    held = [t[4] - t[1] for t in session.strategy.trades_log]
    assert held and max(held) <= 3
    assert build_session([], _walk_params(hold=0), "bollinger", "1m").strategy.max_hold == 0


def test_a_strategy_that_goes_both_ways_seeks_like_it_steps() -> None:
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse

    longs = parse("close < sma(close, 8)", ENTRY_FIELDS, FUNCTIONS)
    shorts = parse("close > sma(close, 8) + 1", ENTRY_FIELDS, FUNCTIONS)

    def make():
        return build_session(
            [], _walk_params(hold=10), "saved", "1m", entry_formula=longs,
            side="both", short_entry_formula=shorts,
        )

    session, reference = make(), make()
    for _ in range(500):
        reference.strategy.step()
    session.seek(500)

    sides = {record[-1] for record in reference.strategy.trades_log}
    assert sides == {"long", "short"}
    assert session.strategy.trades == reference.strategy.trades
    assert [r[-1] for r in session.strategy.trades_log] == [
        r[-1] for r in reference.strategy.trades_log
    ]
    assert session.strategy.equity == pytest.approx(
        reference.strategy.equity, abs=1e-6
    )


def test_slippage_reaches_the_walk_and_the_stepped_walk_agrees() -> None:
    params = _walk_params(slippage=0.05)
    assert build_session([], params, "bollinger", "1m").settings["slippage"] == pytest.approx(0.0005)

    def make(slippage):
        return build_session([], _walk_params(slippage=slippage), "bollinger", "1m")

    session, reference = make(0.05), make(0.05)
    for _ in range(300):
        reference.strategy.step()
    session.seek(300)
    assert session.strategy.trades == reference.strategy.trades > 0
    assert session.strategy.equity == pytest.approx(reference.strategy.equity, abs=1e-6)

    # The same run with no slip ends better off.
    frictionless = make(0.0)
    frictionless.seek(300)
    assert frictionless.strategy.equity > session.strategy.equity


def test_finish_walks_off_the_main_thread_and_lands_the_result(
    app: QApplication,
) -> None:
    import time

    _write(2021, 400, price=200.0)
    tile = PlaybackTile()
    tile.set_source([2021], "1m")
    tile.restart(autoplay=False)

    tile.finish()
    if tile.session._core_ready():
        assert tile.run_button.isEnabled() is False  # busy while it walks
        assert "walking" in tile.note.text()
        deadline = time.time() + 10
        while not tile.run_button.isEnabled() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)
    assert tile.run_button.isEnabled() is True
    assert tile.playback.done is True
    assert "finished" in tile.note.text()
    tile.close()


def test_a_restart_drops_a_walk_still_running(app: QApplication) -> None:
    _write(2021, 400, price=200.0)
    tile = PlaybackTile()
    tile.set_source([2021], "1m")
    tile.restart(autoplay=False)
    session = tile.session

    tile.finish()
    tile.restart(autoplay=False)  # the old result must not land on the new run
    for _ in range(20):
        app.processEvents()

    assert tile.session is not session
    assert tile.playback.index == 0
    assert tile.run_button.isEnabled() is True
    tile.close()


# -- sanity clamps ------------------------------------------------------------


def _params(**over) -> dict:
    base = {
        "initial_capital": 10_000.0, "tp": 2.0, "sl": 1.0, "position": 10.0,
        "sizing": "balance", "cash": 2_000.0, "fee": 0.06,
    }
    base.update(over)
    return base


def test_max_cash_is_capped_at_the_capital() -> None:
    from bi_trading.ui.strat.strat_playback import _walk_settings, walk_clamps

    params = _params(cash=50_000.0)
    assert _walk_settings(params)["max_cash"] == 10_000.0
    assert walk_clamps(params) == ["max cash capped at the capital"]


def test_a_fixed_position_is_capped_at_the_capital() -> None:
    from bi_trading.ui.strat.strat_playback import _walk_settings, walk_clamps

    params = _params(sizing="fixed", position=50_000.0)
    assert _walk_settings(params)["position"] == 10_000.0
    assert "position capped at the capital" in walk_clamps(params)
    # A percent position is not a dollar amount: left alone.
    assert _walk_settings(_params(position=50.0))["position"] == 50.0


def test_reverse_means_nothing_without_the_dynamic_take_profit() -> None:
    from bi_trading.ui.strat.strat_playback import _walk_settings, walk_clamps

    off = _params(dyn_tp_reverse=3.0, dynamic_tp=False)
    assert _walk_settings(off)["reverse"] == 0.0
    assert walk_clamps(off) == ["reverse % ignored: dynamic TP is off"]
    on = _params(dyn_tp_reverse=3.0, dynamic_tp=True)
    assert _walk_settings(on)["reverse"] == 3.0
    assert walk_clamps(on) == []


# -- warm-up ------------------------------------------------------------------


def test_warmup_defaults_to_a_hundred_bars_and_can_be_switched_off() -> None:
    from bi_trading.state.settings import BacktestDefaults
    from bi_trading.ui.strat.strat_playback import _walk_settings

    assert BacktestDefaults().warmup == 100
    assert _walk_settings(_params())["warmup"] == 0          # a form that says 0 is off
    assert _walk_settings(_params(warmup=100))["warmup"] == 100


def test_signals_before_the_warmup_do_not_count() -> None:
    from bi_trading.engine.formula import parse
    from bi_trading.engine.formula_eval import entry_signals

    bars = [{"close": 100.0 + i} for i in range(10)]
    formula = parse("close > 0")
    every = entry_signals(formula, bars)
    assert every == list(range(10))
    assert entry_signals(formula, bars, warmup=4) == list(range(4, 10))
    assert entry_signals(formula, bars, warmup=99) == []


def test_the_walk_ignores_entries_in_the_warmup(app: QApplication) -> None:
    from bi_trading.ui.strat.strat_playback import build_session

    _write(2021, 300, price=200.0)
    plain = build_session([2021], _params(), "bollinger", "1m")
    warmed = build_session([2021], _params(warmup=120), "bollinger", "1m")

    assert not any(warmed.strategy_entries[:120])
    assert not any(warmed.random_entries[:120])
    assert warmed.strategy.warmup == 120
    # What it keeps is what the plain run had after the warm-up.
    assert list(warmed.strategy_entries[120:]) == list(plain.strategy_entries[120:])


def test_the_live_bar_holds_its_signal_while_warming_up(app: QApplication) -> None:
    from bi_trading.ui.strategy_bar import StrategyBar

    bar = StrategyBar()
    bar.set_reading(95.0, 100.0)
    assert bar.signal_label.text() == "TRUE"
    bar.set_reading(95.0, 100.0, warming=True)
    assert bar.signal_label.text() == "WARM-UP"
    bar.close()


# -- a span too long to hold, walked in pieces -----------------------------


def _wander(years: list[int], per_year: int = 700) -> None:
    """A random walk on disk, a year at a time, so trades cross year ends."""
    import random as dice

    rng = dice.Random(11)
    price = 100.0
    for year in years:
        rows = []
        for index in range(per_year):
            price *= 1.0 + rng.uniform(-0.012, 0.012)
            rows.append(
                (index * 60_000, price, price * 1.006, price * 0.994, price, 1.0)
            )
        append_rows(candle_file(year), rows)


_PARAMS = {
    "initial_capital": 10_000.0, "tp": 6.0, "sl": 6.0, "hold": 40, "position": 50.0,
    "sizing": "balance", "cash": 8_000.0, "fee": 0.06, "slippage": 0.01,
    "warmup": 30,
}


@pytest.mark.parametrize("rule", ["bollinger", "random"])
@pytest.mark.parametrize("resolution", ["1m", "5m"])
def test_a_chunked_walk_equals_the_whole_one(
    rule, resolution, monkeypatch
) -> None:
    from bi_trading.ui.strat import playback_session
    from bi_trading.ui.strat import strat_playback as sp

    years = [2019, 2020, 2021]
    _wander(years)
    whole = sp.build_session(years, _PARAMS, rule, resolution)
    assert whole.span is not None and not whole._chunk_ready()
    whole.seek(whole.total)

    monkeypatch.setattr(playback_session, "CORE_MAX", 100)        # now the span is "too long"
    chunked = sp.build_session(years, _PARAMS, rule, resolution)
    assert chunked.span is None and chunked._chunk_ready()
    chunked.seek(chunked.total)

    for name in ("strategy", "random"):
        a, b = getattr(whole, name), getattr(chunked, name)
        assert b.index == a.index == whole.total
        assert b.trades_log == a.trades_log
        assert b.trades == a.trades
        if name == "random" or rule == "bollinger":     # a "random" strategy never trades here
            assert b.trades >= 5, (name, b.trades)      # the comparison has something in it
        assert b.fees == pytest.approx(a.fees)
        assert (b.streak, b.best_win, b.worst_loss) == (a.streak, a.best_win, a.worst_loss)
        assert b.equity == pytest.approx(a.equity)
        assert b.max_drawdown == pytest.approx(a.max_drawdown)
        assert b.max_gain == pytest.approx(a.max_gain)
        assert b.sharpe == pytest.approx(a.sharpe)
        assert b.peak == pytest.approx(a.peak)
        assert b.recent() == a.recent()
        assert list(b.markers) == list(a.markers)
        assert b.first_close == a.first_close
    # At least one trade opened in one year's piece and closed in the next.
    year_end = 700 // sp.FACTOR[resolution] + (700 % sp.FACTOR[resolution] > 0)
    crossing = [
        row for row in chunked.random.trades_log + chunked.strategy.trades_log
        if row[1] < year_end <= row[4] or row[1] < 2 * year_end <= row[4]
    ]
    if rule == "bollinger":
        assert crossing, "no trade crossed a year boundary"
    # The curves hold one point a tick, and agree with the whole run's at those ticks.
    stride = chunked.strategy.stride
    ticks = list(range(stride - 1, whole.total, stride))
    if whole.total % stride:
        ticks.append(whole.total - 1)
    assert len(chunked.strategy_curve) == len(ticks) + 1
    assert chunked.strategy_curve[1:] == pytest.approx([whole.strategy_curve[i] for i in ticks])
    assert chunked.random_curve[1:] == pytest.approx([whole.random_curve[i] for i in ticks])
    assert chunked.benchmark[1:] == pytest.approx([whole.benchmark[i] for i in ticks])
    assert chunked.strategy_curve[0] == chunked.benchmark[0] == _PARAMS["initial_capital"]


def test_a_chunked_seek_stops_where_asked_and_can_play_on(monkeypatch) -> None:
    from bi_trading.ui.strat import playback_session
    from bi_trading.ui.strat import strat_playback as sp

    years = [2019, 2020]
    _wander(years)
    monkeypatch.setattr(playback_session, "CORE_MAX", 100)
    session = sp.build_session(years, _PARAMS, "bollinger", "1m")
    reference = sp.build_session(years, _PARAMS, "bollinger", "1m")
    for _ in range(900):
        reference.strategy.step()

    session.seek(900)
    assert session.strategy.index == 900 and not session.strategy.done
    assert session.strategy.trades == reference.strategy.trades
    def core(play):  # what a trade is, without the stepped walk's own bookkeeping
        return [(r[1], r[2], r[4], r[5], r[6], r[9], r[12]) for r in play.trades_log]

    assert core(session.strategy) == core(reference.strategy)
    # The run can be played on from the seek (as after a core seek, flat).
    session.strategy.step()
    assert session.strategy.index == 901


def test_finish_on_a_span_too_long_to_hold_walks_it_in_pieces(
    app: QApplication, monkeypatch
) -> None:
    import time

    from bi_trading.ui.strat import playback_session

    _wander([2019, 2020])
    monkeypatch.setattr(playback_session, "CORE_MAX", 100)
    tile = PlaybackTile()
    tile.set_source([2019, 2020], "1m")
    tile.restart(autoplay=False)
    assert tile.session._chunk_ready()

    tile.finish()
    assert tile.run_button.isEnabled() is False          # off the main thread
    deadline = time.time() + 10
    while not tile.run_button.isEnabled() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert tile.playback.done is True
    assert tile.playback.trades > 0
    assert "finished" in tile.note.text()
    tile.close()


# -- a formula strategy over a span too long to hold ---------------------------

FORMULAS = {
    "average": ("close < sma(close, 20)", "pnl >= tp or pnl <= 0 - sl"),
    "bands": ("close < bollinger_lower(close, 20, 2) and volume > 0.5", "bars >= 12"),
    "momentum": ("rsi(close, 14) < 40 and ema(close, 10) < ema(close, 30)", "pnl >= tp"),
    "named": ("m = sma(close, 12)\nz = ema(m, 6)\nclose < z and stdev(close, 10) > 0", "pnl <= 0 - sl or bars >= 20"),
}


def _wander_volume(years: list[int], per_year: int = 700) -> None:
    """Like `_wander`, with a volume that moves, so rules about it can fire."""
    import random as dice

    rng = dice.Random(13)
    price = 100.0
    for year in years:
        rows = []
        for index in range(per_year):
            price *= 1.0 + rng.uniform(-0.012, 0.012)
            rows.append((index * 60_000, price, price * 1.006, price * 0.994, price, rng.uniform(0.1, 2.0)))
        append_rows(candle_file(year), rows)


def _formula_session(sp, years, resolution, entry, exit_, side="long", short_entry=None):
    from bi_trading.engine.formula import ENTRY_FIELDS, EXIT_FIELDS, EXIT_FUNCTIONS, FUNCTIONS, parse

    return sp.build_session(
        years, _PARAMS, "saved", resolution,
        entry_formula=parse(entry, ENTRY_FIELDS, FUNCTIONS),
        exit_formula=parse(exit_, EXIT_FIELDS, EXIT_FUNCTIONS) if exit_ else None,
        side=side,
        short_entry_formula=parse(short_entry, ENTRY_FIELDS, FUNCTIONS) if short_entry else None,
    )


@pytest.mark.parametrize("name", FORMULAS)
@pytest.mark.parametrize("resolution", ["1m", "5m"])
def test_a_formula_walked_in_pieces_equals_the_whole_walk(name, resolution, monkeypatch) -> None:
    from bi_trading.ui.strat import playback_session
    from bi_trading.ui.strat import strat_playback as sp

    years = [2019, 2020, 2021]
    _wander_volume(years)
    entry, exit_ = FORMULAS[name]
    whole = _formula_session(sp, years, resolution, entry, exit_)
    assert whole.span is not None and not whole._chunk_ready()
    whole.seek(whole.total)

    monkeypatch.setattr(playback_session, "CORE_MAX", 100)
    chunked = _formula_session(sp, years, resolution, entry, exit_)
    assert chunked.span is None and chunked._chunk_ready()      # not loaded whole
    chunked.seek(chunked.total)

    a, b = whole.strategy, chunked.strategy
    assert b.trades >= 5, (name, resolution, b.trades)
    assert b.trades_log == a.trades_log
    assert b.fees == pytest.approx(a.fees)
    assert b.equity == pytest.approx(a.equity)
    assert b.max_drawdown == pytest.approx(a.max_drawdown)
    assert b.sharpe == pytest.approx(a.sharpe)
    assert list(b.markers) == list(a.markers)
    stride = chunked.strategy.stride
    ticks = list(range(stride - 1, whole.total, stride))
    if whole.total % stride:
        ticks.append(whole.total - 1)
    assert chunked.strategy_curve[1:] == pytest.approx([whole.strategy_curve[i] for i in ticks])


def test_a_both_ways_formula_in_pieces_equals_the_whole_walk(monkeypatch) -> None:
    from bi_trading.ui.strat import playback_session
    from bi_trading.ui.strat import strat_playback as sp

    years = [2019, 2020]
    _wander_volume(years)
    args = ("close < sma(close, 15)", "bars >= 10")
    whole = _formula_session(sp, years, "1m", *args, side="both", short_entry="close > sma(close, 15) * 1.004")
    whole.seek(whole.total)
    monkeypatch.setattr(playback_session, "CORE_MAX", 100)
    chunked = _formula_session(sp, years, "1m", *args, side="both", short_entry="close > sma(close, 15) * 1.004")
    assert chunked._chunk_ready()
    chunked.seek(chunked.total)

    assert chunked.strategy.trades_log == whole.strategy.trades_log
    sides = {row[12] for row in whole.strategy.trades_log}
    assert sides == {"long", "short"}


def test_a_warmup_applies_to_a_formula_in_pieces(monkeypatch) -> None:
    from bi_trading.ui.strat import playback_session
    from bi_trading.ui.strat import strat_playback as sp

    years = [2019, 2020]
    _wander_volume(years)
    params = dict(_PARAMS, warmup=500)
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse

    formula = parse("close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS)
    whole = sp.build_session(years, params, "saved", "1m", entry_formula=formula)
    whole.seek(whole.total)
    monkeypatch.setattr(playback_session, "CORE_MAX", 100)
    chunked = sp.build_session(years, params, "saved", "1m", entry_formula=formula)
    chunked.seek(chunked.total)
    assert chunked.strategy.trades_log == whole.strategy.trades_log
    assert min(row[1] for row in chunked.strategy.trades_log) >= 500


def test_a_rule_that_cannot_be_split_still_loads_the_span_whole(monkeypatch) -> None:
    """model_p has no history on disk: the whole-span path is the only one for it."""
    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.ui.strat import playback_session
    from bi_trading.ui.strat import strat_playback as sp

    _wander_volume([2019])
    monkeypatch.setattr(playback_session, "CORE_MAX", 100)
    session = sp.build_session(
        [2019], _PARAMS, "saved", "1m",
        entry_formula=parse("model_p > 0.5 or close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS),
    )
    assert session.span is not None and not session._chunk_ready()


def test_run_on_a_formula_too_long_to_hold_walks_it_in_pieces(app: QApplication, monkeypatch) -> None:
    import time

    from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from bi_trading.ui.strat import playback_session

    _wander_volume([2019, 2020])
    monkeypatch.setattr(playback_session, "CORE_MAX", 100)
    tile = PlaybackTile()
    tile.set_source([2019, 2020], "1m")
    tile.set_saved_strategy(
        "avg", "close < sma(close, 20)", ENTRY_FIELDS, "pnl >= tp", "long", ""
    )
    assert parse("close < sma(close, 20)", ENTRY_FIELDS, FUNCTIONS) is not None
    tile.restart(autoplay=False)
    assert tile.session._chunk_ready() and tile.session.stream[3] is not None

    tile._on_run()                                  # Run does not step it: it walks it whole
    assert tile.playing() is False
    deadline = time.time() + 10
    while not tile.run_button.isEnabled() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert tile.playback.done and tile.playback.trades > 0
    tile.close()
