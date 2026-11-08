"""The streaming walk, the session, and the results tile's live curves."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala import candles  # noqa: E402
from lalala.candles import append_rows, candle_file  # noqa: E402
from lalala.strat_playback import (  # noqa: E402
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
from lalala.strat_results import ResultsTile  # noqa: E402
from lalala.theme import apply_dark_theme  # noqa: E402

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
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()


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
    # Five-minute bars: five, then two, because each file is compacted on its
    # own — and the count matches what the stream actually yields.
    assert count_bars([2019, 2020], "5m") == 3
    assert len(list(iter_candles([2019, 2020], "5m"))) == 3


def test_an_empty_span_counts_nothing() -> None:
    assert count_bars([2019], "1m") == 0
    assert list(iter_candles([2019], "1m")) == []


def test_the_stride_keeps_a_run_watchable() -> None:
    from lalala.strat_playback import MAX_TICKS

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
    from lalala.strat_playback import CHART_BARS

    play = Playback(sample_candles(CHART_BARS + 50), rule="random", stride=25)
    while not play.done:
        play.step()

    assert play.done is True
    assert len(play.recent()) == CHART_BARS


def test_a_saved_rule_can_drive_the_walk() -> None:
    from lalala.formula import ENTRY_FIELDS, FUNCTIONS, parse
    from lalala.strat_playback import build_session

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
    from lalala.strat_playback import bollinger_bands

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
