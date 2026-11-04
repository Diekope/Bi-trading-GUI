"""The playback: candle series, the walk, and the tile's loop."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala import candles  # noqa: E402
from lalala.candles import append_rows, candle_file  # noqa: E402
from lalala.strat_playback import (  # noqa: E402
    Candle,
    Playback,
    PlaybackTile,
    aggregate,
    load_candles,
    sample_candles,
)
from lalala.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()


def _bar(index: int, close: float, high: float | None = None, low: float | None = None, volume: float = 1.0) -> Candle:
    return Candle(
        stamp=index * 60_000,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=volume,
    )


# -- series ----------------------------------------------------------------


def test_aggregate_compacts_the_bar() -> None:
    bars = [
        Candle(0, 10.0, 12.0, 9.0, 11.0, 1.0),
        Candle(1, 11.0, 15.0, 10.0, 14.0, 2.0),
        Candle(2, 14.0, 14.5, 8.0, 9.0, 3.0),
        Candle(3, 9.0, 10.0, 9.0, 9.5, 4.0),
    ]

    two = aggregate(bars, 2)

    assert len(two) == 2
    assert two[0] == Candle(0, 10.0, 15.0, 9.0, 14.0, 3.0)   # first open, last close
    assert two[1].stamp == 2
    assert two[1].high == 14.5 and two[1].low == 8.0
    assert aggregate(bars, 1) == bars


def test_the_sample_is_deterministic_and_well_formed() -> None:
    first = sample_candles(60)
    second = sample_candles(60)

    assert first == second
    assert len(first) == 60
    for bar in first:
        assert bar.low <= min(bar.open, bar.close)
        assert bar.high >= max(bar.open, bar.close)
        assert bar.volume > 0


def test_the_store_is_read_from_the_latest_year_and_skips_the_quiet_open() -> None:
    # 2017 opens with flat, trade-less minutes; they must not be played.
    append_rows(
        candle_file(2017),
        [(0, 100.0, 100.0, 100.0, 100.0, 0.0)] * 3
        + [(3 * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0)],
    )
    append_rows(
        candle_file(2021),
        [(index * 60_000, 200.0, 201.0, 199.0, 200.5, 2.0) for index in range(5)],
    )

    bars = load_candles([2017, 2021], "1m", 10)

    assert len(bars) == 5
    assert bars[0].close == pytest.approx(200.5)  # the later year wins


def test_nothing_on_disk_means_no_bars() -> None:
    assert load_candles([2019, 2020], "1m", 10) == []


def test_the_resolution_compacts_what_is_read() -> None:
    append_rows(
        candle_file(2021),
        [(index * 60_000, 100.0, 101.0, 99.0, 100.0, 1.0) for index in range(10)],
    )

    hourly = load_candles([2021], "1h", 10)

    assert len(hourly) == 1  # ten minutes is one hourly bar
    assert hourly[0].volume == pytest.approx(10.0)


# -- the walk --------------------------------------------------------------


def _playback(bars: list[Candle], **overrides) -> Playback:
    settings = dict(
        capital=1_000.0, tp=2.0, sl=1.0, position=100.0, sizing="fixed",
        max_cash=1_000.0, fee=0.0, max_hold=90,
    )
    settings.update(overrides)
    return Playback(bars, **settings)


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


def test_equity_is_cash_plus_the_open_position() -> None:
    bars = [_bar(0, 100.0), _bar(1, 100.0)]  # flat: nothing to enter on
    play = _playback(bars)
    play.step()
    assert play.equity == pytest.approx(play.cash)

    rising = _playback([_bar(0, 100.0), _bar(1, 101.0), _bar(2, 105.0, high=110.0)])
    for _ in range(2):
        rising.step()
    assert rising.in_position is True
    assert rising.equity == pytest.approx(
        rising.cash + rising.qty * 105.0, rel=1e-9
    )


def test_the_loop_starts_over_at_the_end() -> None:
    play = _playback([_bar(0, 100.0), _bar(1, 101.0)])

    play.advance()
    assert play.index == 1
    play.advance()
    assert play.index == 2
    assert play.done is True

    play.advance()  # wraps: reset, then the first step of the new loop

    assert play.index == 1
    assert play.trades == 0
    assert play.equity == pytest.approx(1_000.0, rel=1e-3)


def test_one_position_at_a_time() -> None:
    # A long rise: the placeholder rule wants in on every up bar, but only one
    # position may exist, and the target closes it before another opens.
    bars = [_bar(index, 100.0 + index, high=100.0 + index + 0.5) for index in range(6)]
    play = _playback(bars)

    for _ in range(6):
        play.step()
        assert play.qty == 0.0 or play.entry_index < play.index


# -- the tile --------------------------------------------------------------


def test_the_tile_advances_and_swaps_its_source(app: QApplication) -> None:
    tile = PlaybackTile()
    tile.show()
    app.processEvents()

    assert tile.source == "example"
    assert len(tile.playback.candles) == len(sample_candles())
    assert tile.playing() is False

    tile.play()
    assert tile.playing() is True
    start = tile.playback.index
    for _ in range(4):
        tile._tick()
    assert tile.playback.index > start

    append_rows(
        candle_file(2021),
        [(index * 60_000, 300.0, 301.0, 299.0, 300.0, 1.0) for index in range(12)],
    )
    tile.set_source([2021], "1m")

    assert tile.source == "2021 · 1m"
    assert len(tile.playback.candles) == 12
    assert tile.playback.index == 0  # a new source restarts the walk
    assert tile._metric_labels[0][1].text() != ""
    tile.close()


def test_a_new_capital_restarts_but_a_new_target_does_not(
    app: QApplication,
) -> None:
    tile = PlaybackTile()
    app.processEvents()
    for _ in range(3):
        tile.playback.advance()
    index = tile.playback.index

    tile.set_params(
        {
            "initial_capital": 10_000.0, "tp": 3.0, "sl": 1.0,
            "position": 10.0, "sizing": "balance", "cash": 2_000.0,
        }
    )
    assert tile.playback.index == index       # same book: keep walking
    assert tile.playback.tp == pytest.approx(3.0)

    tile.set_params(
        {
            "initial_capital": 5_000.0, "tp": 3.0, "sl": 1.0,
            "position": 10.0, "sizing": "balance", "cash": 2_000.0,
        }
    )
    assert tile.playback.index == 0           # smaller book: start over
