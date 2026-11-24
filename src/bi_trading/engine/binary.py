"""The Polymarket backtest: bets on five-minute up/down markets. No Qt.

A bet buys shares of one side at the market price, up to one per window, and
either sells them early when the exit rule fires or holds them to settlement,
where a share pays $1 if its side won and $0 if not. There is no long or short.

The rule sees the Binance candles and the Up share's price in one row per
minute. A decision at minute `k` (1 to 4) uses the candle that closed at that
moment and the price at that moment, never later ones.

    window:   |-- m0 --|-- m1 --|-- m2 --|-- m3 --|-- m4 --|
    decide at:         k=1      k=2      k=3      k=4      (settles)

The price is the real one downloaded from Polymarket where there is any, and a
fair price from `binary_price` where not (counted in the result). Buying costs
`price + half_spread`, selling returns `price - half_spread`: the book's depth
and spread were never recorded, so those are assumptions you set.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from bi_trading.engine import binary_price
from bi_trading.engine.formula import PM_ENTRY_FIELDS, Formula
from bi_trading.engine.formula_eval import (
    _exit_reason,
    entry_signals,
    evaluate_scalar,
)

WINDOW_MS = 300_000
MINUTE_MS = 60_000
STEPS = 5                      # minutes in a window

REASON_SETTLED = "Settled"
REASON_UNKNOWN = "Settled (est.)"


@dataclass(frozen=True, slots=True)
class BinaryParams:
    capital: float = 1_000.0
    stake_pct: float = 5.0           # of current equity, per bet
    side: str = "up"                 # which share the rule buys: "up" or "down"
    first_minute: int = 1            # the earliest decision minute (1 to 4)
    half_spread: float = 0.01        # added to a buy, taken off a sell
    fee_pct: float = 0.0             # of the stake on a buy and of proceeds on a sell
    tp: float = 0.0                  # exit rule words, in percent of the share price
    sl: float = 0.0


@dataclass(frozen=True, slots=True)
class BinaryTrade:
    start_ms: int
    side: str
    entry_minute: int
    entry_price: float
    exit_minute: int                 # 5 when held to settlement
    exit_price: float
    stake: float
    pnl: float
    reason: str
    won: bool
    real_price: bool                 # the entry price was a real one
    estimated_outcome: bool          # settled from Binance, not from Polymarket


@dataclass(slots=True)
class BinaryResult:
    params: BinaryParams
    trades: list[BinaryTrade] = field(default_factory=list)
    windows: int = 0                 # windows with a complete minute run
    real_windows: int = 0            # of which at least one real price was used
    final_equity: float = 0.0
    max_drawdown: float = 0.0        # as a fraction of the running peak
    equity: list[float] = field(default_factory=list)

    @property
    def pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def win_rate(self) -> float:
        return sum(t.won for t in self.trades) / len(self.trades) if self.trades else 0.0

    @property
    def early(self) -> int:
        return sum(1 for t in self.trades if t.exit_minute < STEPS)

    @property
    def roi(self) -> float:
        """Profit over everything staked."""
        staked = sum(t.stake for t in self.trades)
        return self.pnl / staked if staked else 0.0


# -- the minute frame ----------------------------------------------------------


@dataclass(slots=True)
class Frame:
    """One row per candle minute, for the windows that have all five."""

    columns: dict[str, np.ndarray]
    start_ms: np.ndarray             # the window each row belongs to
    step: np.ndarray                 # minute inside the window, 0 to 4
    real: np.ndarray                 # the price in the row is a downloaded one
    up: np.ndarray
    window_rows: list[tuple[int, int]]   # (window start, first row index)


def build_frame(candles: dict[str, np.ndarray], history: Sequence) -> Frame:
    """Join the candles with the Polymarket prices.

    `candles` holds `timestamp, open, high, low, close, volume`, ascending; `history` is
    `WindowRow`s (see `data.polymarket_history`).
    """
    ts = np.asarray(candles["timestamp"], dtype=np.int64)
    start = ts - ts % WINDOW_MS
    step = ((ts - start) // MINUTE_MS).astype(int)

    # keep only windows whose five minutes are all there
    keep = np.zeros(len(ts), dtype=bool)
    if len(ts):
        change = np.flatnonzero(np.diff(start) != 0) + 1
        bounds = np.concatenate(([0], change, [len(ts)]))
        for a, b in zip(bounds[:-1], bounds[1:], strict=False):
            if b - a == STEPS and step[a] == 0 and step[b - 1] == STEPS - 1:
                keep[a:b] = True
    ts, start, step = ts[keep], start[keep], step[keep]
    cols = {name: np.asarray(candles[name], dtype=float)[keep]
            for name in ("open", "high", "low", "close", "volume")}
    n = len(ts)

    by_start = {row.start_ms: row for row in history if row.prices and row.outcome != -2}
    up = np.full(n, np.nan)
    real = np.zeros(n, dtype=bool)
    # Real price at each decision time: the last sample at or before it.
    first_rows = np.flatnonzero(step == 0)
    for a in first_rows:
        row = by_start.get(int(start[a]))
        if row is None:
            continue
        offsets = np.asarray(row.offsets, dtype=np.int64)
        prices = np.asarray(row.prices, dtype=float)
        for k in range(STEPS):
            seen = np.flatnonzero(offsets <= 60 * (k + 1))
            if len(seen):
                up[int(a) + k] = prices[int(seen[-1])]
                real[int(a) + k] = True

    # Fair price for the rest.
    window_open = cols["open"][np.repeat(first_rows, STEPS)[:n]] if n else np.array([])
    # the model needs a positive time left; the window's last row reports 0
    seconds_left = np.where(step == STEPS - 1, 1.0, 300.0 - 60.0 * (step + 1))
    sigma = binary_price.minute_sigma(cols["close"]) if n else np.array([])
    missing = np.isnan(up)
    if missing.any():
        fair = binary_price.fair_up(window_open, cols["close"], sigma, seconds_left)
        up[missing] = fair[missing]

    columns = dict(cols)
    columns["price"] = cols["close"]
    columns["up_price"] = up
    columns["down_price"] = 1.0 - up
    columns["seconds_left"] = np.where(step == STEPS - 1, 0.0, seconds_left)
    columns["minute"] = (step + 1).astype(float)
    return Frame(columns, start, step, real, up, [(int(start[a]), int(a)) for a in first_rows])


# -- the walk ------------------------------------------------------------------


def _outcome(row, frame: Frame, first: int) -> tuple[bool, bool]:
    """(Up won, estimated from Binance) for the window starting at row `first`."""
    if row is not None and row.outcome in (0, 1):
        return row.outcome == 1, False
    opened = frame.columns["open"][first]
    closed = frame.columns["close"][first + STEPS - 1]
    return bool(closed >= opened), True


def run_binary(
    candles: dict[str, np.ndarray],
    history: Sequence,
    entry: Formula,
    exit_: Formula | None,
    params: BinaryParams = BinaryParams(),
    entry_down: Formula | None = None,
) -> BinaryResult:
    """Walk every window once: enter on a rule, cash out on the exit rule or settle.

    `entry` bets `params.side` (UP by default). With `entry_down` the strategy has
    a rule for each side: `entry` bets UP, `entry_down` bets DOWN, and a minute at
    which both are true bets neither (the rules disagree).
    """
    frame = build_frame(candles, history)
    result = BinaryResult(params, windows=len(frame.window_rows), final_equity=params.capital)
    if not frame.window_rows:
        return result
    up_side = "up" if entry_down is not None else params.side
    signals = {
        i: up_side for i in entry_signals(entry, frame.columns, PM_ENTRY_FIELDS)
    }
    if entry_down is not None:
        for i in entry_signals(entry_down, frame.columns, PM_ENTRY_FIELDS):
            signals[i] = "both" if i in signals else "down"
    rows = {r.start_ms: r for r in history}
    cols = frame.columns
    equity = params.capital
    peak = equity
    result.equity.append(equity)
    for start, first in frame.window_rows:
        row = rows.get(start)
        if row is not None and row.prices:
            result.real_windows += 1
        decision = next(
            (k for k in range(max(0, params.first_minute - 1), STEPS - 1)
             if signals.get(first + k) in ("up", "down")),   # "both" = rules disagree
            None,
        )
        if decision is None:
            continue
        i = first + decision
        side = signals[i]
        quote = cols["up_price"][i] if side == "up" else cols["down_price"][i]
        entry_price = min(0.99, float(quote) + params.half_spread)
        stake = equity * params.stake_pct / 100.0
        if stake <= 0 or entry_price <= 0:
            continue
        shares = stake / entry_price
        fee_in = stake * params.fee_pct / 100.0
        up_won, estimated = _outcome(row, frame, first)
        won_side = up_won == (side == "up")

        exit_minute, reason, proceeds = STEPS, REASON_UNKNOWN if estimated else REASON_SETTLED, 0.0
        if exit_ is not None and exit_.condition is not None:
            for k in range(decision + 1, STEPS - 1):
                j = first + k
                held = cols["up_price"][j] if side == "up" else cols["down_price"][j]
                bid = max(0.0, float(held) - params.half_spread)
                context = _exit_context(bid, entry_price, params, k - decision, cols, j)
                if evaluate_scalar(exit_, context):
                    exit_minute = k + 1
                    reason = _exit_reason(exit_, context)
                    proceeds = shares * bid * (1.0 - params.fee_pct / 100.0)
                    break
        if exit_minute == STEPS:
            proceeds = shares if won_side else 0.0
        pnl = proceeds - stake - fee_in
        exit_price = proceeds / shares if shares else 0.0
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            result.max_drawdown = max(result.max_drawdown, (peak - equity) / peak)
        result.equity.append(equity)
        result.trades.append(
            BinaryTrade(
                start, side, decision + 1, entry_price, exit_minute, exit_price,
                stake, pnl, reason, pnl > 0, bool(frame.real[i]), estimated,
            )
        )
    result.final_equity = equity
    return result


def _exit_context(bid, entry_price, params, bars, cols, j) -> dict:
    ratio = (bid / entry_price - 1.0) if entry_price else 0.0
    context = {
        "price": bid, "entry": entry_price, "tp": params.tp, "sl": params.sl,
        "pnl": ratio * 100.0, "bars": float(bars),
    }
    for name in ("open", "high", "low", "close", "volume",
                 "up_price", "down_price", "seconds_left", "minute"):
        context[name] = float(cols[name][j])
    return context


def always_side(
    candles: dict[str, np.ndarray], history: Sequence, side: str, params: BinaryParams,
    minute: int = 1,
) -> BinaryResult:
    """The baseline: buy `side` at `minute` in every window, hold to settlement."""
    from bi_trading.engine.formula import parse

    rule = parse(f"minute == {minute}", PM_ENTRY_FIELDS)
    return run_binary(candles, history, rule, None, replace(params, side=side))


__all__ = [
    "BinaryParams", "BinaryResult", "BinaryTrade", "always_side", "build_frame", "run_binary",
]
