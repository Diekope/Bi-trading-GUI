"""The results tile: three curves, fixed scale, revealed as the walk goes."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.strat_playback import (  # noqa: E402
    Candle,
    Playback,
    PlaybackTile,
    benchmark_curve,
    bollinger_bands,
    build_session,
    sample_candles,
    simulate_curve,
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


def test_buy_and_hold_tracks_the_price() -> None:
    candles = sample_candles(20)
    curve = benchmark_curve(candles, 1_000.0)

    assert len(curve) == 20
    assert curve[0] == pytest.approx(1_000.0)
    assert curve[-1] == pytest.approx(
        1_000.0 * candles[-1].close / candles[0].close
    )


def test_a_random_buy_is_a_different_walk() -> None:
    candles = sample_candles(200)
    settings = {
        "capital": 10_000.0, "tp": 2.0, "sl": 1.0, "position": 10.0,
        "sizing": "balance", "max_cash": 2_000.0,
    }

    momentum = simulate_curve(candles, settings, "momentum")
    random_buy = simulate_curve(candles, settings, "random")

    # Same exits and costs, different entries, so a different path.
    assert momentum != random_buy
    # And it is deterministic: the same seed replays the same walk.
    assert random_buy == simulate_curve(candles, settings, "random")


def test_a_session_fixes_the_scale_before_the_walk_starts() -> None:
    candles = sample_candles(60)
    session = build_session(candles, PARAMS)

    values = list(session.strategy_curve) + list(session.random_curve) + list(
        session.benchmark
    )
    assert session.low < min(values) < max(values) < session.high
    # Nothing has been walked yet, so only the starting point is there.
    assert session.revealed(session.strategy_curve) == (
        session.strategy_curve[0],
    )
    assert session.return_of(session.benchmark) == pytest.approx(0.0)


def test_the_reveal_follows_the_walk() -> None:
    candles = sample_candles(30)
    session = build_session(candles, PARAMS)

    for _ in range(10):
        session.strategy.advance()

    assert len(session.revealed(session.strategy_curve)) == 11
    assert len(session.revealed(session.benchmark)) == 11
    assert session.current(session.benchmark) == pytest.approx(
        session.benchmark[10]
    )


def test_the_tile_legend_follows_the_curves(app: QApplication) -> None:
    candles = sample_candles(40)
    session = build_session(candles, PARAMS)
    tile = ResultsTile()
    tile.resize(620, 420)
    tile.show()
    app.processEvents()

    assert "no run yet" in tile.note.text()
    tile.set_session(session)
    app.processEvents()
    assert "live" in tile.note.text()
    assert tile.legend["hold"].text() == "buy & hold +0.00%"

    for _ in range(20):
        session.strategy.advance()
    tile.refresh()

    hold = session.return_of(session.benchmark) * 100
    assert tile.legend["hold"].text() == f"buy & hold {hold:+,.2f}%"
    assert not tile.grab().toImage().isNull()
    tile.close()


def test_the_curve_paints_before_any_run(app: QApplication) -> None:
    tile = ResultsTile()
    tile.resize(400, 300)
    tile.show()
    app.processEvents()

    assert not tile.curve.grab().toImage().isNull()
    tile.close()


def test_bollinger_bands_need_history_before_they_exist() -> None:
    candles = sample_candles(30)
    bands = bollinger_bands(candles, period=20, deviations=2.0)

    assert len(bands) == 30
    assert all(band is None for band in bands[:19])
    middle, upper, lower = bands[19]
    assert lower < middle < upper
    # A flat run of closes has no spread at all.
    flat = [Candle(index * 60_000, 5.0, 5.0, 5.0, 5.0, 1.0) for index in range(25)]
    assert bollinger_bands(flat)[24] == (5.0, 5.0, 5.0)


def test_bollinger_reversion_waits_for_a_dip() -> None:
    # Twenty quiet bars, then one that closes far below the band.
    candles = [
        Candle(index * 60_000, 100.0, 100.0, 100.0, 100.0, 1.0)
        for index in range(20)
    ]
    candles.append(Candle(20 * 60_000, 100.0, 100.0, 80.0, 80.0, 1.0))
    play = Playback(
        candles, rule="bollinger", capital=1_000.0, tp=2.0, sl=1.0,
        position=100.0, sizing="fixed", max_cash=1_000.0,
    )

    for _ in range(20):
        play.step()
    assert play.in_position is False   # nothing has dipped yet

    play.step()
    assert play.in_position is True    # the dip bought
    assert play.entry_price == pytest.approx(80.0)


def test_the_tile_reports_how_far_it_has_walked(app: QApplication) -> None:
    tile = PlaybackTile()
    tile.playback = Playback(
        sample_candles(40), rule="random", entry_chance=1.0, capital=1_000.0,
        position=100.0, sizing="fixed", max_cash=1_000.0,
    )
    tile.player.playback = tile.playback
    tile._launched = True

    tile._refresh_metrics()
    values = [value.text() for _, value in tile._metric_labels]
    assert "0% · 0/40" in values

    for _ in range(10):
        tile.playback.advance()
    tile._refresh_metrics()
    values = [value.text() for _, value in tile._metric_labels]
    assert "25% · 10/40" in values
    assert tile.playback.progress == pytest.approx(0.25)
    tile.close()


def test_the_walk_and_its_curve_agree() -> None:
    candles = sample_candles(50)
    session = build_session(candles, PARAMS)

    while not session.strategy.done:
        session.strategy.advance()

    assert tuple(session.strategy.equity_curve) == session.strategy_curve
    assert isinstance(session.strategy, Playback)
