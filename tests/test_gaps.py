"""Holes in the data: a trade is never held through one, and a coarse bar is
only built from minutes that are all there."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from bi_trading.data import candles  # noqa: E402
from bi_trading.data.candles import append_rows, candle_file  # noqa: E402
from bi_trading.engine import core  # noqa: E402
from bi_trading.ui.strat import playback_data as data  # noqa: E402
from bi_trading.ui.strat.playback_walk import Playback  # noqa: E402
from bi_trading.ui.strat.strat_playback import Candle, build_session, iter_candles  # noqa: E402

MIN = 60_000
BASE = dict(
    capital=1_000.0, tp=50.0, sl=50.0, position=100.0, sizing="fixed",
    max_cash=1_000.0, fee=0.0, max_hold=0,
)
PARAMS = {
    "initial_capital": 1_000.0, "tp": 50.0, "sl": 50.0, "position": 100.0,
    "sizing": "fixed", "cash": 1_000.0, "fee": 0.0, "slippage": 0.0, "hold": 0,
}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()
    data._COUNTS.clear()
    from bi_trading.ui.strat import strat_playback

    strat_playback._SPAN_CACHE.clear()


def _write(year: int, minutes: list[int], price=100.0) -> None:
    append_rows(
        candle_file(year),
        [(m * MIN, price, price, price, price + (i % 3) * 0.01, 1.0)
         for i, m in enumerate(minutes)],
    )


# -- the flags ---------------------------------------------------------------

def test_gap_flags_mark_the_bar_before_a_hole() -> None:
    stamps = np.array([0, 1, 2, 5, 6]) * MIN
    assert data.gap_flags(stamps, MIN).tolist() == [False, False, True, False, False]
    # A piece of a longer series looks at the bar that follows it.
    assert data.gap_flags(stamps[:3], MIN, int(stamps[3])).tolist() == [False, False, True]
    assert data.gap_flags(stamps[:3], MIN, 3 * MIN).tolist() == [False, False, False]
    # Stamps that are not milliseconds apart (a synthetic series) are no hole.
    assert not data.gap_flags(np.arange(5), MIN).any()


# -- the walk ----------------------------------------------------------------

def _walk_inputs():
    closes = [100.0, 100.0, 101.0, 102.0, 103.0, 104.0]
    entries = [False, True, False, False, False, False]
    gaps = [False, False, False, True, False, False]   # a hole after bar 3
    return closes, entries, gaps


def test_a_position_is_closed_before_a_hole_not_filled_through_it() -> None:
    closes, entries, gaps = _walk_inputs()
    trades, _ = core.walk(closes, closes, closes, entries, gaps=gaps, **BASE)
    assert len(trades) == 1
    entry, _, exit_, price, _, _, _, reason, _ = trades[0]
    assert (entry, exit_, reason) == (1, 3, "gap")
    assert price == 102.0                 # the last close it saw, not what came after

    # Without the flag the same walk holds on (no hole known): it never exits.
    open_trades, _ = core.walk(closes, closes, closes, entries, **BASE)
    assert open_trades == []


def test_no_trade_opens_on_the_last_bar_before_a_hole() -> None:
    closes = [100.0] * 5
    entries = [False, False, True, False, False]
    gaps = [False, False, True, False, False]
    trades, equity = core.walk(closes, closes, closes, entries, gaps=gaps, **BASE)
    assert trades == [] and equity == [1_000.0] * 5


def test_native_and_python_walks_agree_over_holes() -> None:
    rng = np.random.default_rng(7)
    closes = (100 + rng.normal(0, 1, 400).cumsum() * 0.1).tolist()
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    entries = (rng.random(400) < 0.2).tolist()
    gaps = (rng.random(400) < 0.05).tolist()
    kwargs = dict(BASE, tp=5.0, sl=5.0, max_hold=6, fee=0.0006, slippage=0.0001)
    native = core.walk(closes, highs, lows, entries, gaps=gaps, **kwargs)
    python = core._python_walk(
        closes, highs, lows, entries, [False] * 400, 1_000.0, 5.0, 5.0, 100.0,
        "fixed", 1_000.0, 0.0006, 6, False, 0.0, None, 0.0001, 0, None, gaps,
    )
    assert any(t[7] == "gap" for t in native[0])
    assert native[0] == python[0]
    assert native[1] == python[1]


def test_a_walk_in_pieces_matches_the_whole_over_a_hole() -> None:
    closes, entries, gaps = _walk_inputs()
    whole, _ = core.walk(closes, closes, closes, entries, gaps=gaps, **BASE)
    first = core.walk_chunk(
        closes[:3], closes[:3], closes[:3], entries[:3], gaps=gaps[:3], **BASE
    )
    second = core.walk_chunk(
        closes[3:], closes[3:], closes[3:], entries[3:], offset=3, state=first[2],
        gaps=gaps[3:], **BASE,
    )
    assert first[0] + second[0] == whole


def test_the_baseline_does_not_hold_or_open_across_a_hole() -> None:
    n = 30
    closes = [100.0] * n
    draws = np.zeros(n)             # every flat bar says yes
    gaps = np.zeros(n, dtype=bool)
    gaps[10] = True
    entries = core.random_entries(closes, closes, closes, draws, 50, 50, 0, 1.0, gaps=gaps)
    # In at bar 1 and held (nothing exits it), dropped at the hole after bar 10,
    # and in again at bar 11. Nothing opens on bar 10 itself.
    assert [i for i, on in enumerate(entries) if on] == [1, 11]


# -- the stepped walk ---------------------------------------------------------

def _bars(minutes, closes):
    return [Candle(m * MIN, c, c, c, c, 1.0) for m, c in zip(minutes, closes, strict=True)]


def test_the_stepped_walk_closes_before_a_hole_like_the_core() -> None:
    bars = _bars([0, 1, 2, 3, 10, 11], [100.0, 100.0, 101.0, 102.0, 110.0, 111.0])
    play = Playback(
        bars, entries={1}, total=len(bars), rule="bollinger",
        **{k: v for k, v in BASE.items()},
    )
    while not play.done:
        play.step()
    assert [(t[1], t[4], t[9]) for t in play.trades_log] == [(1, 3, "gap")]
    assert play.trades_log[0][5] == 102.0


# -- clock-aligned bars ------------------------------------------------------

def test_a_coarse_bar_needs_every_minute_and_sits_on_the_clock() -> None:
    # Minutes 0..4 whole; 5 and 6 missing; 7..11 present but off the 5-minute grid.
    _write(2021, [0, 1, 2, 3, 4, 7, 8, 9, 10, 11])
    bars = list(iter_candles([2021], "5m"))
    assert [b.stamp for b in bars] == [0]                 # 5..9 and 10..14 are incomplete
    assert data.count_bars([2021], "5m") == len(bars) == 1


def test_a_whole_bucket_after_a_hole_is_kept_on_its_grid() -> None:
    _write(2021, [0, 1, 2, 3, 4] + list(range(15, 25)))   # a 10-minute hole, then 15..24
    bars = list(iter_candles([2021], "5m"))
    assert [b.stamp // MIN for b in bars] == [0, 15, 20]
    flags = data.gap_flags([b.stamp for b in bars], data.step_ms("5m"))
    assert flags.tolist() == [True, False, False]


def test_a_coarse_bar_is_built_from_its_own_minutes() -> None:
    append_rows(
        candle_file(2021),
        [(i * MIN, 10 + i, 20 + i, 5 + i, 11 + i, 2.0) for i in range(5)],
    )
    (bar,) = list(iter_candles([2021], "5m"))
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (10, 24, 5, 15, 10.0)


# -- a whole run over a stored hole -------------------------------------------

def test_a_run_over_the_store_never_holds_through_an_outage() -> None:
    # 40 minutes, with minutes 20..29 missing. Opening on every flat bar.
    minutes = list(range(0, 20)) + list(range(30, 50))
    _write(2021, minutes)
    session = build_session([2021], PARAMS, "bollinger", "1m")
    assert session.gaps is not None and int(session.gaps.sum()) == 1
    # Drive a walk that trades every bar, through the same path a run uses.
    n = len(minutes)
    entries = np.ones(n, dtype=bool)
    entries[0] = False
    closes = session.span.closes
    trades, _ = core.walk(
        closes, session.span.highs, session.span.lows, entries, gaps=session.gaps,
        **dict(BASE, tp=50.0, sl=50.0, max_hold=0),
    )
    stamps = session.span.stamps
    for t in trades:
        in_, out = int(stamps[t[0]]), int(stamps[t[2]])
        assert out - in_ < 20 * MIN or (in_ // MIN) >= 30   # none spans minutes 19..30
    assert any(t[7] == "gap" for t in trades)


def test_the_chunked_walk_sees_the_hole_between_two_years() -> None:
    _write(2019, [0, 1, 2, 3])
    _write(2020, [10, 11, 12, 13])       # the next year starts a long way on
    pieces = list(data._stream_chunks([2019, 2020], "1m", 8))
    assert [(o, len(d[0]), nxt) for o, d, nxt in pieces] == [
        (0, 4, 10 * MIN), (4, 4, None),
    ]
    flags = data.gap_flags(pieces[0][1][0], MIN, pieces[0][2])
    assert flags.tolist() == [False, False, False, True]
