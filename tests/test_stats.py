"""The trade figures beyond PnL, and the CSV of trades."""

from __future__ import annotations

import csv

import pytest

from bi_trading.engine.stats import TradeStats, trade_stats, trades_csv, write_trades_csv


def _row(result: float, notional: float = 1_000.0, held: int = 5, start: int = 0,
         side: str = "long", reason: str = "tp"):
    return (
        1_600_000_000_000 + start * 60_000, start, 100.0,
        1_600_000_000_000 + (start + held) * 60_000, start + held, 100.0 * (1 + result),
        result, notional, notional * result, reason, 1.5, [], side,
    )


def test_no_trades_is_all_zeros() -> None:
    assert trade_stats([], 1_000) == TradeStats()


def test_the_figures_of_a_small_run() -> None:
    trades = [_row(0.02, held=4, start=0), _row(-0.01, held=6, start=10),
              _row(0.03, held=5, start=30), _row(-0.02, held=5, start=50)]
    stats = trade_stats(trades, 100)

    assert stats.trades == 4
    assert stats.expectancy == pytest.approx(0.005)               # (2 - 1 + 3 - 2) / 4 %
    assert stats.expectancy_usd == pytest.approx(5.0)
    assert stats.average_hold == pytest.approx(5.0)
    assert stats.exposure == pytest.approx(0.20)                  # 20 of 100 bars
    assert stats.profit_factor == pytest.approx(50.0 / 30.0)      # $50 won over $30 lost
    downside = ((0.01**2 + 0.02**2) / 4) ** 0.5
    assert stats.sortino == pytest.approx(0.005 / downside)


def test_without_a_loser_there_is_no_profit_factor_or_sortino() -> None:
    stats = trade_stats([_row(0.01), _row(0.02, start=10)], 100)
    assert stats.profit_factor is None and stats.sortino is None
    assert stats.expectancy == pytest.approx(0.015)


def test_exposure_is_capped_and_an_empty_span_is_safe() -> None:
    assert trade_stats([_row(0.01, held=500)], 100).exposure == 1.0
    assert trade_stats([_row(0.01)], 0).exposure == 0.0


def test_the_csv_has_a_header_and_one_row_a_trade(tmp_path) -> None:
    trades = [_row(0.02), _row(-0.01, start=10, side="short", reason="sl")]
    rows = trades_csv(trades)
    assert rows[0][0] == "entry_time" and len(rows) == 3
    assert rows[1][0] == "2020-09-13 12:26"          # UTC
    assert rows[1][6] == "long" and rows[2][6] == "short"
    assert rows[1][9] == pytest.approx(2.0)           # return, in percent
    assert rows[2][10] == "sl"

    path = tmp_path / "trades.csv"
    assert write_trades_csv(trades, path) == 2
    with open(path, newline="") as handle:
        read = list(csv.reader(handle))
    assert read[0] == rows[0] and read[2][6] == "short"
