"""The figures that say how far to trust a run: significance, yearly risk, costs
stress, the like-for-like benchmark and the volume cap."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pytest

from bi_trading.engine import core, stats
from bi_trading.ui.strat.playback_session import ChunkRun, benchmark_value

MS = 1000


def _row(day: int, result: float, notional=100.0, reason="sl", fees=0.12, year=2022):
    stamp = int(dt.datetime(year, 1, 1, tzinfo=dt.UTC).timestamp() * MS) + day * 86_400_000
    return (stamp, 0, 100.0, stamp + 60_000, 3, 100.0, result, notional,
            notional * result, reason, fees, [], "long")


# -- significance ---------------------------------------------------------------

def test_a_handful_of_trades_is_flagged_as_too_few() -> None:
    few = stats.trade_stats([_row(i, 0.01) for i in range(5)], 1_000)
    assert few.few is True
    many = stats.trade_stats([_row(i, 0.01 * (-1) ** i) for i in range(60)], 10_000)
    assert many.few is False


def test_the_t_stat_and_interval_follow_the_trade_returns() -> None:
    returns = [0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, 0.0]
    result = stats.trade_stats([_row(i, r) for i, r in enumerate(returns)], 1_000)
    mean = sum(returns) / len(returns)
    deviation = (sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
    error = deviation / math.sqrt(len(returns))
    assert result.t_stat == pytest.approx(mean / error)
    assert result.sharpe_trade == pytest.approx(mean / deviation)
    assert result.ci_low == pytest.approx(mean - 1.96 * error)
    assert result.ci_high == pytest.approx(mean + 1.96 * error)
    assert 0.0 < result.p_value < 1.0


def test_a_zero_mean_has_no_edge_and_one_trade_has_no_t_stat() -> None:
    flat = stats.trade_stats([_row(i, r) for i, r in enumerate([0.01, -0.01] * 20)], 1_000)
    assert flat.t_stat == pytest.approx(0.0, abs=1e-9)
    assert flat.p_value == pytest.approx(1.0, abs=1e-6)
    one = stats.trade_stats([_row(0, 0.02)], 1_000)
    assert one.t_stat is None and one.p_value is None


# -- risk on the curve ----------------------------------------------------------

def test_yearly_figures_use_the_resolution() -> None:
    assert stats.bars_per_year("1m") == 525_600
    assert stats.bars_per_year("1h") == 8_760
    # 10% in half a year compounds to 21% in a year.
    assert stats.annualised_return(0.10, 262_800, 525_600) == pytest.approx(0.21)
    assert stats.calmar(0.2, -0.1) == pytest.approx(2.0)
    assert stats.calmar(0.2, 0.0) is None


def test_the_longest_underwater_run_counts_bars_below_the_peak() -> None:
    curve = [1, 2, 1.5, 1.4, 2.1, 2.0, 1.9, 1.8, 2.2]
    assert stats.longest_underwater(curve) == 3
    assert stats.longest_underwater([1, 2, 3]) == 0


def test_a_chunked_run_counts_a_dip_that_spans_two_pieces() -> None:
    whole = [100, 110, 105, 104, 103, 102, 111]
    run = ChunkRun(100.0)
    for piece in (whole[:4], whole[4:]):
        run.take([], piece, np.arange(len(piece)), 0, (100.0, 0.0, False, 0.0, 0, 0.0, 0.0, 0.0, 0.0))
    assert run.longest_under == stats.longest_underwater([100] + whole) == 4


# -- costs ----------------------------------------------------------------------

def test_doubling_the_costs_takes_each_trades_fees_and_slippage_again() -> None:
    rows = [_row(0, 0.02, notional=1_000.0, reason="sl", fees=1.2),
            _row(1, 0.02, notional=1_000.0, reason="tp", fees=1.2)]
    pnl, stressed = stats.cost_stress(rows, slippage=0.001)
    assert pnl == pytest.approx(40.0)
    # sl pays slippage twice (2.0), tp once (1.0); fees 1.2 each.
    assert stressed == pytest.approx(40.0 - (1.2 + 2.0) - (1.2 + 1.0))
    assert stats.cost_stress([], 0.001) == (0.0, 0.0)


# -- by year --------------------------------------------------------------------

def test_trades_are_grouped_by_the_year_they_closed() -> None:
    rows = [_row(1, 0.01, year=2021), _row(2, -0.02, year=2021), _row(3, 0.03, year=2022)]
    assert stats.by_year(rows) == [(2021, 2, pytest.approx(-1.0), 0.5), (2022, 1, pytest.approx(3.0), 1.0)]


# -- the benchmark --------------------------------------------------------------

def test_buy_and_hold_risks_the_same_cash_and_pays_the_same_costs() -> None:
    s = {"capital": 10_000.0, "max_cash": 2_000.0, "fee": 0.001, "slippage": 0.001}
    # Costs at the start: 2,000 buys a little less than 20 units at 100.
    assert benchmark_value(s, 100.0, 100.0) < 10_000.0
    flat = benchmark_value(s, 100.0, 100.0)
    assert flat == pytest.approx(10_000.0 - 2_000.0 * (1 - 1 / (1.001 * 1.001)), rel=1e-9)
    # A doubling moves only the invested part: +~2,000, not +10,000.
    doubled = benchmark_value(s, 100.0, 200.0)
    assert doubled - flat == pytest.approx(flat * 0 + 2_000.0 / (1.001 * 1.001) , rel=1e-6)
    free = {"capital": 10_000.0, "max_cash": 10_000.0, "fee": 0.0, "slippage": 0.0}
    assert benchmark_value(free, 100.0, 150.0) == pytest.approx(15_000.0)
    assert list(benchmark_value(free, 100.0, np.array([100.0, 150.0]))) == [10_000.0, 15_000.0]


# -- the volume cap -------------------------------------------------------------

def test_an_entry_is_cut_to_a_share_of_the_bars_traded_value() -> None:
    closes = [100.0, 100.0, 100.0, 100.0]
    entries = [False, True, False, False]
    base = dict(capital=10_000.0, tp=50.0, sl=50.0, position=100.0, sizing="fixed",
                max_cash=10_000.0, fee=0.0, max_hold=1)
    # A bar that traded 5 units at 100 is $500; at 10% a fill may take $50.
    thin = core.walk(closes, closes, closes, entries, volumes=[5.0] * 4,
                     participation=0.10, **dict(base, position=1_000.0))
    assert thin[0][0][6] == pytest.approx(50.0)
    # A deep bar does not bind, and 0 is off.
    deep = core.walk(closes, closes, closes, entries, volumes=[1e6] * 4,
                     participation=0.10, **dict(base, position=1_000.0))
    assert deep[0][0][6] == pytest.approx(1_000.0)
    off = core.walk(closes, closes, closes, entries, volumes=[5.0] * 4,
                    participation=0.0, **dict(base, position=1_000.0))
    assert off[0][0][6] == pytest.approx(1_000.0)


def test_native_and_python_agree_on_the_cap() -> None:
    rng = np.random.default_rng(3)
    closes = (100 + rng.normal(0, 1, 300).cumsum() * 0.1).tolist()
    entries = (rng.random(300) < 0.2).tolist()
    volumes = rng.uniform(0.1, 3.0, 300).tolist()
    args = dict(capital=1_000.0, tp=3.0, sl=3.0, position=100.0, sizing="balance",
                max_cash=1_000.0, fee=0.0006, max_hold=5)
    native = core.walk(closes, closes, closes, entries, volumes=volumes, participation=0.2, **args)
    python = core._python_walk(
        closes, closes, closes, entries, [False] * 300, 1_000.0, 3.0, 3.0, 100.0,
        "balance", 1_000.0, 0.0006, 5, False, 0.0, None, 0.0, 0, None, None,
        volumes, 0.2,
    )
    assert any(t[6] < 100.0 for t in native[0])        # the cap bit somewhere
    assert native[0] == python[0] and native[1] == python[1]
