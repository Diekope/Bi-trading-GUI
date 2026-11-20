"""Figures about a run's trades, beyond PnL and Sharpe. No Qt.

All of them are read off the trade log, so they cost one pass over the trades and
nothing over the bars:

* **Expectancy** — the average trade, as a return and in dollars. What one more
  trade is worth, on average; the figure a quick glance should land on first after
  PnL, because it says whether the edge is per trade or the result of a few lucky ones.
* **Average hold** — bars a trade ran.
* **Exposure** — the share of bars with a position open.
* **Profit factor** — what the winners made over what the losers lost.
* **Sortino** — the average trade over its *downside* deviation (only losing trades
  count as risk), not annualised and per trade, unlike the Sharpe, which is per bar.
* **Trade Sharpe, t-stat, 95% interval** — the same per-trade basis as the Sortino, so
  the two compare, and how far the average trade sits from zero in standard errors.
  The interval and the p-value assume the trades are independent draws, which a rule
  that fires in clusters breaks, so read them as a floor on the doubt, not a proof.

A trade is the playback's log row:
`(in_stamp, in_index, in_price, out_stamp, out_index, out_price, result, notional,
pnl, reason, fees, path, side)`.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "TradeStats",
    "annualised_return",
    "bars_per_year",
    "by_year",
    "calmar",
    "cost_stress",
    "longest_underwater",
    "underwater_runs",
    "trade_stats",
    "trades_csv",
    "write_trades_csv",
]

# Fewer trades than this and the average trade says very little.
MIN_TRADES = 30


@dataclass(frozen=True, slots=True)
class TradeStats:
    trades: int = 0
    expectancy: float = 0.0          # mean return per trade, as a fraction
    expectancy_usd: float = 0.0      # mean profit per trade, in dollars
    average_hold: float = 0.0        # bars
    exposure: float = 0.0            # 0..1
    profit_factor: float | None = None   # None: no losing trade to divide by
    sortino: float | None = None         # None: no losing trade, no downside
    sharpe_trade: float | None = None    # mean / stdev of the trade returns
    t_stat: float | None = None          # mean / standard error; None under 2 trades
    ci_low: float = 0.0                  # 95% interval of the average trade, fraction
    ci_high: float = 0.0
    p_value: float | None = None         # two-sided, normal approximation
    few: bool = True                     # fewer than MIN_TRADES: too few to tell


def trade_stats(trades: Sequence[Sequence], total_bars: int) -> TradeStats:
    """The figures for a list of log rows over a run of `total_bars` bars."""
    count = len(trades)
    if not count:
        return TradeStats()
    returns = [float(row[6]) for row in trades]
    profits = [float(row[8]) for row in trades]
    held = [max(0, int(row[4]) - int(row[1])) for row in trades]

    mean = sum(returns) / count
    wins = sum(value for value in profits if value > 0)
    losses = -sum(value for value in profits if value < 0)
    downside = sum(min(0.0, value) ** 2 for value in returns) / count
    sharpe_trade = t_stat = p_value = None
    ci_low = ci_high = mean
    if count > 1:
        variance = sum((value - mean) ** 2 for value in returns) / (count - 1)
        deviation = variance**0.5
        error = deviation / count**0.5
        if deviation > 0:
            sharpe_trade = mean / deviation
            t_stat = mean / error
            # Two-sided p from the normal curve: erfc(|t| / sqrt 2).
            p_value = math.erfc(abs(t_stat) / math.sqrt(2.0))
        ci_low, ci_high = mean - 1.96 * error, mean + 1.96 * error
    return TradeStats(
        trades=count,
        expectancy=mean,
        expectancy_usd=sum(profits) / count,
        average_hold=sum(held) / count,
        exposure=min(1.0, sum(held) / total_bars) if total_bars > 0 else 0.0,
        profit_factor=wins / losses if losses > 0 else None,
        sortino=mean / downside**0.5 if downside > 0 else None,
        sharpe_trade=sharpe_trade,
        t_stat=t_stat,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        few=count < MIN_TRADES,
    )


# -- risk on the book's own curve --------------------------------------------------

MINUTES_PER_YEAR = 365 * 24 * 60     # BTC trades every minute of the year


def bars_per_year(resolution: str) -> float:
    """How many bars of `resolution` a year holds (1m, 3m, 5m, 15m, 30m, 1h)."""
    minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
    return MINUTES_PER_YEAR / minutes.get(resolution, 1)


def annualised_return(total_return: float, bars: int, per_year: float) -> float:
    """A return over `bars` bars as a yearly rate (compounded); 0 for no bars."""
    if bars <= 0 or total_return <= -1.0:
        return -1.0 if total_return <= -1.0 else 0.0
    return (1.0 + total_return) ** (per_year / bars) - 1.0


def calmar(annual_return: float, max_drawdown: float) -> float | None:
    """Yearly return over the deepest drawdown (a negative fraction); None with none."""
    if max_drawdown >= 0.0:
        return None
    return annual_return / -max_drawdown


def underwater_runs(below):
    """The lengths of the runs of True in a boolean array, in order."""
    import numpy as np

    flags = np.asarray(below, dtype=np.int8)
    edges = np.diff(np.concatenate(([0], flags, [0])))
    return np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)


def longest_underwater(equity) -> int:
    """The longest run of bars the book spent below its previous peak."""
    import numpy as np

    values = np.asarray(equity, dtype=float)
    if values.size < 2:
        return 0
    runs = underwater_runs(values < np.maximum.accumulate(values))
    return int(runs.max()) if runs.size else 0


# -- what the figures survive ----------------------------------------------------

def cost_stress(trades: Sequence[Sequence], slippage: float, factor: float = 2.0):
    """`(pnl, stressed pnl)` in dollars if fees and slippage were `factor` times as big.

    First order, off the trade log: each trade's own fees and the slippage it paid
    (a fraction per fill; a take profit is a resting order and pays none on the way
    out) are scaled, and the sizes of later trades are not re-worked. It is a
    sensitivity, not a second run.
    """
    pnl = stressed = 0.0
    for row in trades:
        notional, profit, reason, fees = float(row[7]), float(row[8]), row[9], float(row[10])
        slip = notional * slippage * (1 if reason == "tp" else 2)
        pnl += profit
        stressed += profit - (factor - 1.0) * (fees + slip)
    return pnl, stressed


def by_year(trades: Sequence[Sequence]) -> list[tuple[int, int, float, float]]:
    """`(year, trades, profit in dollars, win rate)` by the year each trade closed."""
    rows: dict[int, list[float]] = {}
    for row in trades:
        stamp = int(row[3]) or int(row[0])
        year = dt.datetime.fromtimestamp(stamp / 1000, tz=dt.UTC).year if stamp else 0
        rows.setdefault(year, []).append(float(row[8]))
    return [
        (year, len(profits), sum(profits), sum(1 for p in profits if p > 0) / len(profits))
        for year, profits in sorted(rows.items())
    ]


HEADER = (
    "entry_time", "entry_index", "entry_price", "exit_time", "exit_index",
    "exit_price", "side", "notional", "pnl", "return_pct", "reason", "fees",
)


def _iso(stamp: int) -> str:
    if not stamp:
        return ""
    return dt.datetime.fromtimestamp(stamp / 1000, tz=dt.UTC).strftime("%Y-%m-%d %H:%M")


def trades_csv(trades: Iterable[Sequence]) -> list[list]:
    """The trades as rows for a CSV, header first. Times are UTC."""
    rows: list[list] = [list(HEADER)]
    for row in trades:
        rows.append([
            _iso(int(row[0])), int(row[1]), round(float(row[2]), 6),
            _iso(int(row[3])), int(row[4]), round(float(row[5]), 6),
            row[12] if len(row) > 12 else "long", round(float(row[7]), 2),
            round(float(row[8]), 2), round(float(row[6]) * 100, 4), row[9],
            round(float(row[10]), 4),
        ])
    return rows


def write_trades_csv(trades: Iterable[Sequence], path: str | Path) -> int:
    """Write the trades to `path`; returns how many."""
    rows = trades_csv(trades)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    return len(rows) - 1
