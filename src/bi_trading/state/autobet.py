"""Auto-bet: when a strategy's signal fires, bet on its own.

This module is the decision and the bookkeeping, with no Qt, so it can be tested
alone. The terminal (`ui/main_window.py`) calls it when the strategy's signal
turns true and sends the order it decides on.

What it will and will not do, in order:

  - Only while the Auto-bet box is on (off by default).
  - One bet per five-minute window, however long the signal stays true.
  - Never more than the **max stake**, never less than Polymarket's $1 minimum.
  - Nothing once today's **daily loss limit** is reached; a warning at 70% of it.
  - A real order only when live orders are armed and Polymarket is connected.
    Otherwise it is a **paper** bet: nothing is sent, but it is logged and
    resolved like a real one, so the strategy can be judged without risk.

A bet resolves when its window ends. The result is worked out from BTC against
the window's opening target. Polymarket settles on its own Chainlink price, so
this is an estimate, and a real bet's result is marked as one.
"""

from __future__ import annotations

from dataclasses import dataclass

from bi_trading.state.events import EventLog

MIN_STAKE = 1.0
# How long past a window's end to wait for Polymarket's own settlement before
# a real bet falls back to the estimate from BTC.
GRACE_MS = 10 * 60 * 1000
WARN_AT = 0.7   # warn when this share of the daily loss limit is gone


@dataclass(frozen=True)
class Plan:
    """What to do about a signal: bet `stake`, or skip for `reason`."""

    stake: float = 0.0
    reason: str = ""

    @property
    def go(self) -> bool:
        return self.stake > 0


@dataclass
class Bet:
    slug: str
    side: str            # "up" | "down"
    price: float         # what a share cost, 0..1
    stake: float         # dollars
    strategy: str
    paper: bool          # nothing was sent
    end_ms: int
    token: str = ""      # the outcome token bought, to match the venue's fill
    filled: bool = False  # stake and price are the venue's, not the intended ones

    @property
    def shares(self) -> float:
        return self.stake / self.price if self.price > 0 else 0.0

    def result(self, winner: str) -> float:
        """Profit in dollars if `winner` won: a share pays $1, a loss costs the stake."""
        return self.shares - self.stake if winner == self.side else -self.stake


def plan(
    *,
    stake: float,
    max_stake: float,
    daily_loss_limit: float,
    today_pnl: float,
    window: str,
    last_window: str,
    price: float | None,
) -> Plan:
    """Decide whether to bet on this signal and for how much."""
    if window == last_window:
        return Plan(reason="already bet in this window")
    if not price or price <= 0:
        return Plan(reason="no price yet")
    if max_stake > 0:
        stake = min(stake, max_stake)
    if stake < MIN_STAKE:
        return Plan(reason=f"the smallest bet is ${MIN_STAKE:g}")
    if daily_loss_limit > 0 and -today_pnl >= daily_loss_limit:
        return Plan(
            reason=f"daily loss limit reached (${-today_pnl:,.0f} of ${daily_loss_limit:,.0f})"
        )
    return Plan(stake=stake)


def loss_share(today_pnl: float, daily_loss_limit: float) -> float:
    """How much of the daily loss limit is used, 0..1+ (0 with no limit)."""
    if daily_loss_limit <= 0 or today_pnl >= 0:
        return 0.0
    return -today_pnl / daily_loss_limit


def winner(btc: float | None, target: float | None) -> str | None:
    """Which side a window ended on: up if BTC finished at or above its open."""
    if btc is None or target is None:
        return None
    return "up" if btc >= target else "down"


class AutoBet:
    """The bets still waiting on their window, and the log they report to."""

    def __init__(self, log: EventLog) -> None:
        self._log = log
        self.open: list[Bet] = []
        self.last_window = ""
        self._warned_on: str = ""   # the day the 70% warning was last given

    def place_paper(self, bet: Bet) -> None:
        """Log a bet that sends nothing, and keep it for its result."""
        self.last_window = bet.slug
        self.open.append(bet)
        self._log.record(
            "info", "polymarket", "ORDER",
            f"Buy {bet.side.upper()} ${bet.stake:,.2f} · paper", "auto", bet.strategy,
            request=[f"side: BUY · outcome: {bet.side.upper()}",
                     f"price: {bet.price:g} · stake: ${bet.stake:,.2f}", "paper: nothing sent"],
        )
        self._log.record(
            "info", "polymarket", "FILLED",
            f"{bet.side.upper()} {bet.price * 100:.0f}¢ × {bet.shares:,.1f} · "
            f"${bet.stake:,.2f} · paper", "auto", bet.strategy,
        )

    def track_real(self, bet: Bet) -> None:
        """Keep a real bet (the order service logs it) for its estimated result."""
        self.last_window = bet.slug
        self.open.append(bet)

    def fill(self, token: str, shares: float, dollars: float) -> None:
        """A real bet's fill: take the venue's price and stake over the intended ones."""
        if shares <= 0 or dollars <= 0:
            return
        for bet in self.open:
            if not bet.paper and not bet.filled and bet.token == token:
                bet.stake = dollars
                bet.price = dollars / shares
                bet.filled = True
                return

    def awaiting(self, current_slug: str) -> list[str]:
        """Windows of real bets that are over and wait on Polymarket's settlement."""
        return sorted({
            bet.slug for bet in self.open if not bet.paper and bet.slug != current_slug
        })

    def resolve(
        self,
        current_slug: str,
        btc: float | None,
        target: float | None,
        official: dict[str, str] | None = None,
        now_ms: int = 0,
    ) -> int:
        """Log the result of every bet whose window is over; how many were.

        A paper bet is settled from BTC against the window's open. A real bet
        waits for Polymarket's own settlement (`official`, by window); only if
        that has not come `GRACE_MS` after the window ended does it fall back to
        the BTC estimate, and is marked as one.
        """
        estimate = winner(btc, target)
        official = official or {}
        count = 0
        keep: list[Bet] = []
        for bet in self.open:
            if bet.slug == current_slug:
                keep.append(bet)
                continue
            side = official.get(bet.slug) if not bet.paper else None
            exact = side is not None
            if side is None:
                late = bet.paper or (now_ms and now_ms > bet.end_ms + GRACE_MS)
                side = estimate if late else None
            if side is None:
                keep.append(bet)
                continue
            self._settle(bet, side, btc, target, exact)
            count += 1
        self.open = keep
        return count

    def _settle(
        self, bet: Bet, side: str, btc: float | None, target: float | None, exact: bool
    ) -> None:
        profit = bet.result(side)
        sign = "+" if profit >= 0 else "−"
        estimate = "" if bet.paper or exact else "≈ "
        tail = " · paper" if bet.paper else " · settled by Polymarket" if exact else " · estimated"
        self._log.record(
            "info", "polymarket", "RESOLVED",
            f"Market closed · {side.upper()} won · {estimate}{sign}${abs(profit):,.2f}" + tail,
            "auto", bet.strategy,
            pnl=round(profit, 2),
            why=[line for line in [
                f"bet {bet.side.upper()} at {bet.price * 100:.0f}¢ for ${bet.stake:,.2f}"
                + (" (the venue's fill)" if bet.filled else ""),
                "Polymarket's own settlement" if exact else
                f"BTC {btc:,.1f} vs open {target:,.1f}"
                if btc is not None and target is not None else "",
                "" if exact or bet.paper else
                "an estimate: Polymarket's settlement had not arrived",
            ] if line],
        )

    def check_limit(self, today_pnl: float, daily_loss_limit: float, today: str) -> None:
        """Log one warning a day when 70% of the daily loss limit is gone."""
        share = loss_share(today_pnl, daily_loss_limit)
        if share >= WARN_AT and self._warned_on != today:
            self._warned_on = today
            self._log.record(
                "warn", "strategy", "LIMIT",
                f"Daily loss ${-today_pnl:,.0f} of ${daily_loss_limit:,.0f} ({share * 100:.0f}%)",
                "auto",
            )


__all__ = ["AutoBet", "Bet", "GRACE_MS", "MIN_STAKE", "Plan", "WARN_AT", "loss_share", "plan", "winner"]
