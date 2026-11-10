"""The backtest walk, native when it can be, Python otherwise.

`lalala_core` is a small Rust extension (see `rust/lalala_core`) holding the
bar loop. When it is built and importable it is used; otherwise `walk` falls
back to the same walk in pure Python, so the app runs either way.

`walk(closes, highs, lows, entries, ...)` returns `(trades, equity)` where a
trade is `(entry index, entry price, exit index, exit price, result)` and
`equity` is the realised book per bar.
"""

from __future__ import annotations

__all__ = ["available", "walk"]

try:  # the extension, if it was built
    from lalala_core import walk as _native_walk  # type: ignore

    _NATIVE = True
except Exception:  # pragma: no cover - depends on the build
    _native_walk = None
    _NATIVE = False


def available() -> bool:
    """Whether the native core is in play."""
    return _NATIVE


def walk(
    closes,
    highs,
    lows,
    entries,
    capital=10_000.0,
    tp=2.0,
    sl=1.0,
    position=10.0,
    sizing="balance",
    max_cash=2_000.0,
    fee=0.0006,
    max_hold=90,
    dynamic_tp=False,
    reverse=0.0,
):
    """Walk the bars, opening where `entries` is true.

    `sizing` is `balance` (percent of the deployable cash), `fixed` (dollars)
    or `risk` (percent of the deployable cash lost if the stop is hit, so the
    position shrinks as the stop widens). `dynamic_tp` trails the take profit:
    once the trade is in profit, a pull-back of `reverse` percent from the
    peak closes it.
    """
    # The native core knows the plain walk only; the trailing take profit and
    # risk sizing run in Python.
    if _NATIVE and not dynamic_tp and sizing != "risk":
        import numpy as np

        # Already a float64 array (the span's columns): no copy. A list is
        # copied once, in C, rather than element by element.
        return _native_walk(
            np.ascontiguousarray(closes, dtype=float),
            np.ascontiguousarray(highs, dtype=float),
            np.ascontiguousarray(lows, dtype=float),
            np.ascontiguousarray(entries, dtype=bool),
            capital, tp, sl, position, sizing, max_cash, fee, max_hold,
        )
    # The Python walk indexes the columns one by one, and list indexing is
    # faster than NumPy scalar indexing, so lift to lists once.
    closes = [float(value) for value in closes]
    highs = [float(value) for value in highs]
    lows = [float(value) for value in lows]
    entries = [bool(value) for value in entries]
    return _python_walk(
        closes, highs, lows, entries, capital, tp, sl, position, sizing,
        max_cash, fee, max_hold, dynamic_tp, reverse,
    )


def _python_walk(
    closes, highs, lows, entries, capital, tp, sl, position, sizing,
    max_cash, fee, max_hold, dynamic_tp=False, reverse=0.0,
):
    fixed = sizing == "fixed"
    risk = sizing == "risk"
    cash = capital
    qty = 0.0
    entry_price = 0.0
    entry_index = 0
    entry_cost = 0.0
    entry_fee = 0.0
    entry_notional = 0.0
    peak = 0.0
    trades: list[tuple] = []
    equity: list[float] = []

    for index, close in enumerate(closes):
        high = highs[index]
        low = lows[index]
        if qty > 0.0:
            target = entry_price * (1.0 + tp / 100.0)
            stop = entry_price * (1.0 - sl / 100.0)
            if dynamic_tp and reverse > 0.0:
                peak = max(peak, high)
            trail = peak * (1.0 - reverse / 100.0) if peak else 0.0
            price = None
            reason = "time"
            if tp > 0 and high >= target:
                price = target
                reason = "tp"
            elif sl > 0 and low <= stop:
                price = stop
                reason = "sl"
            elif dynamic_tp and reverse > 0 and peak > entry_price and low <= trail:
                price = trail
                reason = "tp"
            elif index - entry_index >= max_hold:
                price = close
                reason = "time"
            if price is not None:
                proceeds = qty * price
                cost = proceeds * fee
                cash += proceeds - cost
                result = (
                    (proceeds - cost) / entry_cost - 1.0 if entry_cost else 0.0
                )
                trades.append(
                    (
                        entry_index, entry_price, index, price, result,
                        entry_fee + cost, entry_notional, reason,
                    )
                )
                qty = 0.0
                entry_cost = 0.0
                peak = 0.0
        elif index != 0 and entries[index]:
            deployable = min(cash, max_cash)
            if fixed:
                notional = max(0.0, min(position, deployable))
            elif risk:
                # Size so a stop-out costs `position` percent of the cash in
                # play; a wider stop means a smaller position.
                notional = (
                    deployable * max(0.0, position) / sl if sl > 0 else deployable
                )
                notional = max(0.0, min(notional, deployable))
            else:
                notional = deployable * max(0.0, position) / 100.0
            if notional > 0.0 and close > 0.0:
                cost = notional * fee
                qty = notional / close
                cash -= notional + cost
                entry_price = close
                entry_index = index
                entry_fee = cost
                entry_notional = notional
                entry_cost = notional + cost
                peak = high
        equity.append(cash + qty * entry_price)

    return trades, equity
