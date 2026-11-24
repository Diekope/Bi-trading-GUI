from __future__ import annotations

import numpy as np
import pytest

from bi_trading.data.polymarket_history import NOT_FOUND, WindowRow
from bi_trading.engine import binary, binary_price
from bi_trading.engine.formula import PM_ENTRY_FIELDS, PM_EXIT_FIELDS, parse

W = 1_795_532_400_000  # a window boundary


def _candles(windows: int, closes=None) -> dict:
    n = windows * 5
    ts = W + np.arange(n) * 60_000
    close = np.full(n, 100.0) if closes is None else np.asarray(closes, dtype=float)
    return {"timestamp": ts, "open": close.copy(), "high": close + 1, "low": close - 1,
            "close": close, "volume": np.full(n, 10.0)}


def _row(i: int, outcome: int, prices=(0.5, 0.5, 0.5, 0.5, 0.5)) -> WindowRow:
    # a sample at 10 s then one at each minute mark
    return WindowRow(W + i * 300_000, outcome, 1.0, (10, 60, 120, 180, 240), tuple(prices))


def _rule(text: str):
    return parse(text, PM_ENTRY_FIELDS)


P = binary.BinaryParams(capital=1_000.0, stake_pct=10.0, half_spread=0.0)


def test_a_winning_up_bet_pays_one_per_share() -> None:
    result = binary.run_binary(_candles(1), [_row(0, 1)], _rule("minute == 1"), None, P)
    (trade,) = result.trades
    # stake 100 at 0.5 -> 200 shares -> 200 back
    assert trade.entry_price == pytest.approx(0.5)
    assert trade.pnl == pytest.approx(100.0) and trade.won
    assert trade.reason == binary.REASON_SETTLED and not trade.estimated_outcome
    assert result.final_equity == pytest.approx(1_100.0)


def test_a_losing_bet_loses_the_stake_and_down_is_one_minus_up() -> None:
    lost = binary.run_binary(_candles(1), [_row(0, 0)], _rule("minute == 1"), None, P)
    assert lost.trades[0].pnl == pytest.approx(-100.0)
    down = binary.run_binary(
        _candles(1), [_row(0, 0, (0.7,) * 5)], _rule("minute == 1"), None,
        binary.BinaryParams(1_000.0, 10.0, "down", half_spread=0.0),
    )
    # a Down share costs 1 - 0.7 = 0.3 and Down won: 100 / 0.3 shares
    assert down.trades[0].entry_price == pytest.approx(0.3)
    assert down.trades[0].pnl == pytest.approx(100 / 0.3 - 100)


def test_the_spread_makes_a_buy_dearer() -> None:
    params = binary.BinaryParams(1_000.0, 10.0, half_spread=0.02)
    result = binary.run_binary(_candles(1), [_row(0, 1)], _rule("minute == 1"), None, params)
    assert result.trades[0].entry_price == pytest.approx(0.52)


def test_the_exit_rule_cashes_out_early_at_the_bid() -> None:
    # price jumps to 0.8 from minute 2; exit when the bet is up 20%
    row = _row(0, 0, (0.5, 0.5, 0.8, 0.8, 0.8))
    exit_ = parse("pnl >= 20", PM_EXIT_FIELDS)
    result = binary.run_binary(
        _candles(1), [row], _rule("minute == 1"), exit_,
        binary.BinaryParams(1_000.0, 10.0, half_spread=0.0),
    )
    (trade,) = result.trades
    assert trade.exit_minute == 2 and trade.exit_price == pytest.approx(0.8)
    assert trade.pnl == pytest.approx(60.0)       # 200 shares sold at 0.8, though Down won
    assert trade.reason != binary.REASON_SETTLED and result.early == 1


def test_an_unknown_outcome_settles_from_binance_and_says_so() -> None:
    closes = [100.0] * 4 + [99.0]                  # ended below where it opened
    result = binary.run_binary(
        _candles(1, closes), [_row(0, -1)], _rule("minute == 1"), None, P
    )
    assert result.trades[0].estimated_outcome and not result.trades[0].won


def test_without_history_the_price_is_simulated_and_not_counted_real() -> None:
    result = binary.run_binary(_candles(2), [], _rule("minute == 2"), None, P)
    assert len(result.trades) == 2 and result.real_windows == 0
    assert not any(t.real_price for t in result.trades)
    assert 0.01 <= result.trades[0].entry_price <= 0.99


def test_a_window_with_a_missing_minute_is_skipped() -> None:
    candles = _candles(2)
    for name in candles:
        candles[name] = np.delete(candles[name], 7)
    result = binary.run_binary(candles, [], _rule("minute == 1"), None, P)
    assert result.windows == 1


def test_rules_can_mix_binance_and_polymarket_names() -> None:
    row = _row(0, 1, (0.3,) * 5)
    both = _rule("up_price < 0.4 and close > 50 and minute >= 2")
    result = binary.run_binary(_candles(1), [row], both, None, P)
    assert result.trades[0].entry_minute == 2
    never = _rule("up_price > 0.9")
    assert not binary.run_binary(_candles(1), [row], never, None, P).trades


def test_not_found_rows_are_ignored() -> None:
    gone = WindowRow(W, NOT_FOUND, 0.0, (), ())
    assert binary.run_binary(_candles(1), [gone], _rule("minute == 1"), None, P).real_windows == 0


def test_the_baseline_buys_every_window() -> None:
    history = [_row(0, 1), _row(1, 0)]
    up = binary.always_side(_candles(2), history, "up", P)
    assert len(up.trades) == 2 and up.trades[0].won and not up.trades[1].won


def test_fair_price_rises_with_the_move_and_falls_with_time() -> None:
    sigma = np.array([1e-4, 1e-4, 1e-4])
    price = binary_price.fair_up(
        np.array([100.0] * 3), np.array([99.9, 100.0, 100.1]), sigma, np.array([120.0] * 3)
    )
    assert price[1] == pytest.approx(0.5)
    assert price[0] < price[1] < price[2]
    late = binary_price.fair_up(np.array([100.0]), np.array([100.1]), sigma[:1], np.array([10.0]))
    assert late[0] > price[2]


def test_calibration_reports_per_bin() -> None:
    table = binary_price.calibration(np.array([0.1, 0.12, 0.9]), np.array([0, 1, 1]), bins=10)
    assert table[0][2] == 2 and table[0][1] == pytest.approx(0.5)


def test_a_rule_for_each_side_bets_the_side_that_fires() -> None:
    row = _row(0, 0, (0.3, 0.3, 0.7, 0.7, 0.7))
    up = _rule("up_price < 0.4")
    down = _rule("up_price > 0.6")
    result = binary.run_binary(_candles(1), [row], up, None, P, entry_down=down)
    (trade,) = result.trades
    assert trade.side == "up" and trade.entry_minute == 1       # UP fires first, at minute 1
    late = binary.run_binary(
        _candles(1), [row], _rule("minute == 4"), None, P, entry_down=_rule("minute == 3"))
    assert late.trades[0].side == "down" and late.trades[0].entry_minute == 3
    assert late.trades[0].won                                   # Down won (outcome 0)


def test_when_both_rules_fire_together_neither_bets_that_minute() -> None:
    row = _row(0, 1)
    both = binary.run_binary(
        _candles(1), [row], _rule("minute == 2"), None, P, entry_down=_rule("minute == 2"))
    assert both.trades == []
    later = binary.run_binary(
        _candles(1), [row], _rule("minute >= 2"), None, P, entry_down=_rule("minute == 2"))
    assert later.trades[0].entry_minute == 3 and later.trades[0].side == "up"
