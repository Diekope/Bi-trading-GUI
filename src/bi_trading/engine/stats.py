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

A trade is the playback's log row:
`(in_stamp, in_index, in_price, out_stamp, out_index, out_price, result, notional,
pnl, reason, fees, path, side)`.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = ["TradeStats", "trade_stats", "trades_csv", "write_trades_csv"]


@dataclass(frozen=True, slots=True)
class TradeStats:
    trades: int = 0
    expectancy: float = 0.0          # mean return per trade, as a fraction
    expectancy_usd: float = 0.0      # mean profit per trade, in dollars
    average_hold: float = 0.0        # bars
    exposure: float = 0.0            # 0..1
    profit_factor: float | None = None   # None: no losing trade to divide by
    sortino: float | None = None         # None: no losing trade, no downside


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
    return TradeStats(
        trades=count,
        expectancy=mean,
        expectancy_usd=sum(profits) / count,
        average_hold=sum(held) / count,
        exposure=min(1.0, sum(held) / total_bars) if total_bars > 0 else 0.0,
        profit_factor=wins / losses if losses > 0 else None,
        sortino=mean / downside**0.5 if downside > 0 else None,
    )


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
