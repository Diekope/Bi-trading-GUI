"""Auto-bet: the rules, with no window."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.state.autobet import GRACE_MS, AutoBet, Bet, loss_share, plan, winner  # noqa: E402
from bi_trading.state.events import EventLog  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _plan(**over):
    base = dict(stake=20.0, max_stake=100.0, daily_loss_limit=200.0, today_pnl=0.0,
                window="w1", last_window="", price=0.4)
    base.update(over)
    return plan(**base)


def test_a_clear_signal_bets_the_stake() -> None:
    assert _plan().stake == 20.0 and _plan().go


def test_the_max_stake_caps_it_and_zero_means_no_cap() -> None:
    assert _plan(stake=500.0).stake == 100.0
    assert _plan(stake=500.0, max_stake=0.0).stake == 500.0


@pytest.mark.parametrize(
    ("over", "words"),
    [
        (dict(last_window="w1"), "already bet"),
        (dict(price=None), "no price"),
        (dict(price=0.0), "no price"),
        (dict(stake=0.5), "smallest bet"),
        (dict(today_pnl=-200.0), "daily loss limit"),
        (dict(today_pnl=-350.0), "daily loss limit"),
    ],
)
def test_the_reasons_to_skip(over, words) -> None:
    chosen = _plan(**over)
    assert not chosen.go and words in chosen.reason


def test_a_profit_or_a_small_loss_does_not_stop_it() -> None:
    assert _plan(today_pnl=500.0).go
    assert _plan(today_pnl=-199.0).go
    assert _plan(today_pnl=-5_000.0, daily_loss_limit=0.0).go        # no limit set


def test_loss_share() -> None:
    assert loss_share(-142.0, 200.0) == pytest.approx(0.71)
    assert loss_share(30.0, 200.0) == 0.0
    assert loss_share(-50.0, 0.0) == 0.0


def test_the_winner_is_up_at_or_above_the_open() -> None:
    assert winner(101.0, 100.0) == "up"
    assert winner(100.0, 100.0) == "up"
    assert winner(99.0, 100.0) == "down"
    assert winner(None, 100.0) is None and winner(99.0, None) is None


def test_a_bet_pays_a_dollar_a_share_or_loses_its_stake() -> None:
    bet = Bet("w", "up", 0.4, 20.0, "S", True, 0)
    assert bet.shares == pytest.approx(50.0)
    assert bet.result("up") == pytest.approx(30.0)      # 50 shares - $20
    assert bet.result("down") == pytest.approx(-20.0)


def test_a_real_bet_waits_for_polymarkets_own_settlement(app, tmp_path) -> None:
    log = EventLog(tmp_path / "e.jsonl")
    auto = AutoBet(log)
    auto.track_real(Bet("w1", "up", 0.5, 10.0, "S", False, 1_000))

    assert auto.resolve("w1", 100.0, 99.0) == 0          # the window is still current
    # Over, but not settled yet and not late: it waits, even though BTC says up.
    assert auto.resolve("w2", 100.0, 99.0, {}, now_ms=2_000) == 0
    assert auto.awaiting("w2") == ["w1"]
    # Polymarket settled it DOWN although BTC finished above the open.
    assert auto.resolve("w2", 100.0, 99.0, {"w1": "down"}, now_ms=2_000) == 1
    (event,) = log.events()
    assert event.message.startswith("Market closed · DOWN won · −$10.00")
    assert "settled by Polymarket" in event.message and event.pnl == -10.0
    assert "≈" not in event.message


def test_a_real_bet_falls_back_to_the_estimate_when_settlement_is_late(app, tmp_path) -> None:
    log = EventLog(tmp_path / "e.jsonl")
    auto = AutoBet(log)
    auto.track_real(Bet("w1", "up", 0.5, 10.0, "S", False, 1_000))

    late = 1_000 + GRACE_MS + 1
    assert auto.resolve("w2", 100.0, 99.0, {}, now_ms=late) == 1
    (event,) = log.events()
    assert event.message.startswith("Market closed · UP won · ≈ +$10.00")
    assert "estimated" in event.message and event.pnl == 10.0


def test_the_venues_fill_replaces_the_intended_stake_and_price(app, tmp_path) -> None:
    log = EventLog(tmp_path / "e.jsonl")
    auto = AutoBet(log)
    bet = Bet("w1", "up", 0.50, 10.0, "S", False, 0, token="tok")
    auto.track_real(bet)

    auto.fill("other", 5.0, 2.0)            # not this bet's token
    assert bet.stake == 10.0
    auto.fill("tok", 16.0, 8.0)             # got 16 shares for $8: 50¢... a smaller fill
    assert (bet.stake, bet.price, bet.filled) == (8.0, 0.5, True)
    auto.fill("tok", 1.0, 1.0)              # one fill per bet
    assert bet.stake == 8.0


def test_the_limit_warning_is_given_once_a_day(app, tmp_path) -> None:
    log = EventLog(tmp_path / "e.jsonl")
    auto = AutoBet(log)
    auto.check_limit(-100.0, 200.0, "2026-11-17")       # 50%: quiet
    auto.check_limit(-150.0, 200.0, "2026-11-17")       # 75%: warns
    auto.check_limit(-190.0, 200.0, "2026-11-17")       # same day: quiet
    auto.check_limit(-150.0, 200.0, "2026-11-18")       # next day: warns again
    assert [e.kind for e in log.events()] == ["LIMIT", "LIMIT"]
    assert "75%" in log.events()[0].message
