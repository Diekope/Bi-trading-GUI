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
):
    """Walk the bars, opening where `entries` is true."""
    closes = [float(value) for value in closes]
    highs = [float(value) for value in highs]
    lows = [float(value) for value in lows]
    entries = [bool(value) for value in entries]
    if _NATIVE:
        return _native_walk(
            closes, highs, lows, entries, capital, tp, sl, position,
            sizing, max_cash, fee, max_hold,
        )
    return _python_walk(
        closes, highs, lows, entries, capital, tp, sl, position, sizing,
        max_cash, fee, max_hold,
    )


def _python_walk(
    closes, highs, lows, entries, capital, tp, sl, position, sizing,
    max_cash, fee, max_hold,
):
    fixed = sizing == "fixed"
    cash = capital
    qty = 0.0
    entry_price = 0.0
    entry_index = 0
    entry_cost = 0.0
    trades: list[tuple] = []
    equity: list[float] = []

    for index, close in enumerate(closes):
        high = highs[index]
        low = lows[index]
        if qty > 0.0:
            target = entry_price * (1.0 + tp / 100.0)
            stop = entry_price * (1.0 - sl / 100.0)
            price = None
            if tp > 0 and high >= target:
                price = target
            elif sl > 0 and low <= stop:
                price = stop
            elif index - entry_index >= max_hold:
                price = close
            if price is not None:
                proceeds = qty * price
                cost = proceeds * fee
                cash += proceeds - cost
                result = (
                    (proceeds - cost) / entry_cost - 1.0 if entry_cost else 0.0
                )
                trades.append((entry_index, entry_price, index, price, result))
                qty = 0.0
                entry_cost = 0.0
        elif index != 0 and entries[index]:
            deployable = min(cash, max_cash)
            notional = (
                max(0.0, min(position, deployable))
                if fixed
                else deployable * max(0.0, position) / 100.0
            )
            if notional > 0.0 and close > 0.0:
                cost = notional * fee
                qty = notional / close
                cash -= notional + cost
                entry_price = close
                entry_index = index
                entry_cost = notional + cost
        equity.append(cash + qty * entry_price)

    return trades, equity
