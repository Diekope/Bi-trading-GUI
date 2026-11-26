"""The random baseline: the strategy's signal rate and side mix, through the
same walk, and the spread of many such runs behind "beats X% of random"."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random as dice  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from bi_trading.data import candles  # noqa: E402
from bi_trading.data.candles import append_rows, candle_file  # noqa: E402
from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse  # noqa: E402
from bi_trading.ui.strat import playback_data as data  # noqa: E402
from bi_trading.ui.strat import playback_session as ps  # noqa: E402
from bi_trading.ui.strat.strat_playback import build_session  # noqa: E402

PARAMS = {
    "initial_capital": 10_000.0, "tp": 2.0, "sl": 1.0, "position": 10.0,
    "sizing": "balance", "cash": 2_000.0, "fee": 0.06, "slippage": 0.01,
    "warmup": 30,
}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()
    data._COUNTS.clear()
    from bi_trading.ui.strat import strat_playback

    strat_playback._SPAN_CACHE.clear()


def _wander(count: int = 3_000) -> None:
    rng = dice.Random(5)
    price, rows = 100.0, []
    for index in range(count):
        price *= 1.0 + rng.uniform(-0.01, 0.01)
        rows.append((index * 60_000, price, price * 1.005, price * 0.995, price, 1.0))
    append_rows(candle_file(2022), rows)


def _formula(text):
    return parse(text, ENTRY_FIELDS, FUNCTIONS)


def test_the_baseline_copies_the_signal_rate_and_side_mix() -> None:
    longs = np.zeros(1_000, dtype=bool)
    shorts = np.zeros(1_000, dtype=bool)
    longs[::50] = True          # 20 long signals
    shorts[7::100] = True       # 10 short signals
    chance, share = ps.matched_chance(longs, shorts)
    assert chance == pytest.approx(0.03)
    assert share == pytest.approx(20 / 30)
    # No signals to copy: the fixed rate, long only.
    assert ps.matched_chance(np.zeros(10, dtype=bool), None) == (ps.FALLBACK_CHANCE, 1.0)


def test_random_flags_split_the_signals_by_the_share() -> None:
    draws = ps.random_draws(200_000)
    up, down = ps.random_flags(draws, 0.1, 0.75)
    assert not (up & down).any()
    assert up.sum() + down.sum() == (draws < 0.1).sum()
    assert up.sum() / (up.sum() + down.sum()) == pytest.approx(0.75, abs=0.02)


def test_a_piece_of_the_stream_is_what_the_whole_would_give() -> None:
    whole = ps.random_draws(1_000)
    rng = np.random.default_rng(ps.RANDOM_SEED)
    pieces = np.concatenate([rng.random(300), rng.random(300), rng.random(400)])
    assert np.array_equal(whole, pieces)


def test_a_two_sided_strategy_gets_a_two_sided_baseline() -> None:
    _wander()
    session = build_session(
        [2022], PARAMS, "saved", "1m",
        entry_formula=_formula("close < sma(close, 5)"),
        short_entry_formula=_formula("close > sma(close, 5)"),
        side="both",
    )
    assert session.random_short_arr is not None
    assert session.random_entries_arr.any() and session.random_short_arr.any()
    # Its signal rate is the strategy's, not the fixed 3%.
    rate = (session.random_entries_arr.sum() + session.random_short_arr.sum()) / session.total
    wanted, _ = ps.matched_chance(session.strategy_entries_arr, session.short_entries_arr)
    assert rate == pytest.approx(wanted, abs=0.03)
    session.seek(session.total)
    sides = {record[-1] for record in session.random.trades_log}
    assert sides == {"long", "short"}


def _wait(session, seconds: float = 30.0) -> None:
    end = time.time() + seconds
    while session.band_state == "running" and time.time() < end:
        time.sleep(0.02)


def test_the_band_is_many_runs_through_the_same_walk() -> None:
    _wander()
    session = build_session([2022], PARAMS, "bollinger", "1m")
    session.seek(session.total)
    assert session.band_state in ("running", "done")
    _wait(session)
    band = session.band
    assert band is not None and band["runs"] == ps.BAND_RUNS
    returns = band["returns"]
    assert returns == sorted(returns) and len(returns) == ps.BAND_RUNS
    # Different seeds, so a real spread rather than one number a hundred times.
    assert len(set(round(r, 6) for r in returns)) > ps.BAND_RUNS // 2
    # The same session twice gives the same band (seeded, not drawn from the clock).
    again = session.random_band(session.total)
    assert again["returns"] == returns


def test_a_part_way_seek_computes_no_band() -> None:
    _wander()
    session = build_session([2022], PARAMS, "bollinger", "1m")
    session.seek(session.total // 2)
    assert session.band_state == "" and session.band is None


def test_a_span_too_long_for_enough_runs_gets_no_band(monkeypatch) -> None:
    _wander()
    session = build_session([2022], PARAMS, "bollinger", "1m")
    monkeypatch.setattr(ps, "BAND_BUDGET", 5 * session.total)   # five runs fit: too few
    assert session.random_band(session.total) is None
