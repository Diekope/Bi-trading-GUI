"""The backtest walk, native when it can be, Python otherwise.

`lalala_core` is a small Rust extension (see `rust/lalala_core`) holding the
bar loop. When it is built and importable it is used; otherwise `walk` falls
back to the same walk in pure Python, so the app runs either way.

`walk(closes, highs, lows, entries, ...)` returns `(trades, equity)` where a
trade is `(entry index, entry price, exit index, exit price, result)` and
`equity` is the realised book per bar. One position at a time, long or short:
a short sells at the entry and buys back at the exit, its take profit below
the entry and its stop above.
"""

from __future__ import annotations

from lalala.engine.formula_eval import evaluate_scalar

__all__ = ["available", "exit_context", "random_entries", "walk"]

try:  # the extension, if it was built
    from lalala_core import random_entries as _native_random_entries  # type: ignore
    from lalala_core import walk as _native_walk  # type: ignore

    _NATIVE = True
except Exception:  # pragma: no cover - depends on the build
    _native_walk = None
    _native_random_entries = None
    _NATIVE = False


def available() -> bool:
    """Whether the native core is in play."""
    return _NATIVE


def random_entries(
    highs,
    lows,
    closes,
    draws,
    tp=2.0,
    sl=1.0,
    max_hold=90,
    chance=0.03,
    short=False,
) -> list[bool]:
    """The coin-flip baseline's entries, one position at a time.

    `draws` is one uniform per bar, generated from the same seed on both paths,
    so the native and Python baselines are identical bar for bar.
    """
    if _NATIVE:
        import numpy as np

        return list(
            _native_random_entries(
                np.ascontiguousarray(highs, dtype=float),
                np.ascontiguousarray(lows, dtype=float),
                np.ascontiguousarray(closes, dtype=float),
                np.ascontiguousarray(draws, dtype=float),
                tp,
                sl,
                max_hold,
                chance,
                bool(short),
            )
        )
    return _python_random_entries(
        highs, lows, closes, draws, tp, sl, max_hold, chance, short
    )


def _python_random_entries(
    highs, lows, closes, draws, tp, sl, max_hold, chance, short=False
) -> list[bool]:
    n = len(closes)
    entries = [False] * n
    in_position = False
    entry_price = 0.0
    entry_index = 0
    drawn = 0
    for index in range(1, n):
        if in_position:
            if short:
                target = entry_price * (1.0 - tp / 100.0)
                stop = entry_price * (1.0 + sl / 100.0)
                hit_tp = tp > 0 and lows[index] <= target
                hit_sl = sl > 0 and highs[index] >= stop
            else:
                target = entry_price * (1.0 + tp / 100.0)
                stop = entry_price * (1.0 - sl / 100.0)
                hit_tp = tp > 0 and highs[index] >= target
                hit_sl = sl > 0 and lows[index] <= stop
            if hit_tp or hit_sl or (index - entry_index >= max_hold):
                in_position = False
        else:
            draw = draws[drawn] if drawn < len(draws) else 1.0
            drawn += 1
            if draw < chance:
                entries[index] = True
                in_position = True
                entry_price = closes[index]
                entry_index = index
    return entries


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
    side="long",
    exit_formula=None,
):
    """Walk the bars, opening where `entries` is true.

    `sizing` is `balance` (percent of the deployable cash), `fixed` (dollars)
    or `risk` (percent of the deployable cash lost if the stop is hit, so the
    position shrinks as the stop widens). `side` is `long` or `short`.
    `dynamic_tp` trails the take profit: once the trade is in profit, a
    pull-back of `reverse` percent from the best price closes it.
    `exit_formula` is a parsed exit rule, checked on each bar's close while a
    trade is open, after the take profit and stop loss have had their say.
    """
    short = side == "short"
    # The native core knows the plain walk; the trailing take profit and an
    # exit rule run in Python.
    if _NATIVE and not dynamic_tp and exit_formula is None:
        import numpy as np

        # Already a float64 array (the span's columns): no copy. A list is
        # copied once, in C, rather than element by element.
        return _native_walk(
            np.ascontiguousarray(closes, dtype=float),
            np.ascontiguousarray(highs, dtype=float),
            np.ascontiguousarray(lows, dtype=float),
            np.ascontiguousarray(entries, dtype=bool),
            capital, tp, sl, position, sizing, max_cash, fee, max_hold, short,
        )
    # The Python walk indexes the columns one by one, and list indexing is
    # faster than NumPy scalar indexing, so lift to lists once.
    closes = [float(value) for value in closes]
    highs = [float(value) for value in highs]
    lows = [float(value) for value in lows]
    entries = [bool(value) for value in entries]
    return _python_walk(
        closes, highs, lows, entries, capital, tp, sl, position, sizing,
        max_cash, fee, max_hold, dynamic_tp, reverse, short, exit_formula,
    )


def exit_context(price, entry, tp, sl, bars, short=False) -> dict:
    """What an exit rule sees of an open trade. `pnl` is signed for the side."""
    ratio = (price / entry - 1.0) if entry else 0.0
    return {
        "price": price,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "pnl": (-ratio if short else ratio) * 100.0,
        "bars": bars,
    }


def _python_walk(
    closes, highs, lows, entries, capital, tp, sl, position, sizing,
    max_cash, fee, max_hold, dynamic_tp=False, reverse=0.0, short=False,
    exit_formula=None,
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
    best = 0.0  # the best price since entry: the high of a long, the low of a short
    trades: list[tuple] = []
    equity: list[float] = []

    for index, close in enumerate(closes):
        high = highs[index]
        low = lows[index]
        if qty > 0.0:
            if short:
                target = entry_price * (1.0 - tp / 100.0)
                stop = entry_price * (1.0 + sl / 100.0)
                if dynamic_tp and reverse > 0.0:
                    best = min(best, low)
                trail = best * (1.0 + reverse / 100.0) if best else 0.0
                hit_tp = tp > 0 and low <= target
                hit_sl = sl > 0 and high >= stop
                hit_trail = (
                    dynamic_tp and reverse > 0 and 0 < best < entry_price
                    and high >= trail
                )
            else:
                target = entry_price * (1.0 + tp / 100.0)
                stop = entry_price * (1.0 - sl / 100.0)
                if dynamic_tp and reverse > 0.0:
                    best = max(best, high)
                trail = best * (1.0 - reverse / 100.0) if best else 0.0
                hit_tp = tp > 0 and high >= target
                hit_sl = sl > 0 and low <= stop
                hit_trail = (
                    dynamic_tp and reverse > 0 and best > entry_price
                    and low <= trail
                )
            price = None
            reason = "time"
            if hit_tp:
                price = target
                reason = "tp"
            elif hit_sl:
                price = stop
                reason = "sl"
            elif hit_trail:
                price = trail
                reason = "tp"
            elif exit_formula is not None and evaluate_scalar(
                exit_formula,
                exit_context(close, entry_price, tp, sl, index - entry_index, short),
            ):
                price = close
                reason = "rule"
            elif index - entry_index >= max_hold:
                price = close
                reason = "time"
            if price is not None:
                # A long is worth qty * price; a short is its margin back plus
                # what the price fell, which can never go below nothing.
                value = (
                    max(0.0, qty * (2.0 * entry_price - price))
                    if short
                    else qty * price
                )
                cost = qty * price * fee
                cash += value - cost
                result = (
                    (value - cost) / entry_cost - 1.0 if entry_cost else 0.0
                )
                trades.append(
                    (
                        entry_index, entry_price, index, price, result,
                        entry_fee + cost, entry_notional, reason,
                    )
                )
                qty = 0.0
                entry_cost = 0.0
                best = 0.0
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
                best = low if short else high
        equity.append(cash + qty * entry_price)

    return trades, equity
