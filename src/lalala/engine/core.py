"""The backtest walk, native when it can be, Python otherwise.

`lalala_core` is a small Rust extension (see `rust/lalala_core`) holding the
bar loop. When it is built and importable it is used; otherwise `walk` falls
back to the same walk in pure Python, so the app runs either way.

`walk(closes, highs, lows, entries, ...)` returns `(trades, equity)` where a
trade is `(entry index, entry price, exit index, exit price, result, fees,
notional, reason, side)` and
`equity` is the realised book per bar. One position at a time, long or short:
a short sells at the entry and buys back at the exit, its take profit below
the entry and its stop above. A trade ends at its stop, its take profit (the
stop first when one candle holds both), its exit rule, or its hold limit.
"""

from __future__ import annotations

from lalala.engine.formula_eval import evaluate_scalar

__all__ = [
    "DEFAULT_HOLD",
    "available",
    "compile_exit",
    "exit_context",
    "random_entries",
    "walk",
]

# How many bars a trade may run unless told otherwise.
DEFAULT_HOLD = 7

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
    max_hold=DEFAULT_HOLD,
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
            if hit_tp or hit_sl or (max_hold > 0 and index - entry_index >= max_hold):
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


# The exit rule, flattened for the native stack machine: (opcode, argument).
# `lib.rs` has the same table; `NaN` stands for an unknown value.
_OPS = {
    "const": 0, "load": 1, "store": 2, "neg": 3, "not": 4, "+": 5, "-": 6,
    "*": 7, "/": 8, "%": 9, "^": 10, "<": 11, "<=": 12, ">": 13, ">=": 14,
    "==": 15, "!=": 16, "and": 17, "or": 18, "abs": 19, "sqrt": 20, "min": 21,
    "max": 22,
}
_CALLS = {"abs": 1, "sqrt": 1, "min": 2, "max": 2}


def compile_exit(formula):
    """An exit rule as `(program, slots)` for the native walk, or None.

    The program is a list of `(opcode, argument)` pairs; `slots` is how many
    values it keeps (the trade's six words, then each named value the rule
    defines). None means the rule is not one the core can run — the walk then
    runs it in Python — which today is never for a rule the parser accepted,
    but keeps the two paths honest.
    """
    from lalala.engine.formula import (
        EXIT_FIELDS,
        Binary,
        Call,
        Name,
        Number,
        Unary,
    )

    slots = {name: index for index, name in enumerate(EXIT_FIELDS)}
    program: list[tuple[int, float]] = []

    def emit(node) -> bool:
        if isinstance(node, Number):
            program.append((_OPS["const"], float(node.value)))
        elif isinstance(node, Name):
            if node.name not in slots:
                return False
            program.append((_OPS["load"], float(slots[node.name])))
        elif isinstance(node, Unary):
            if node.op not in ("-", "not") or not emit(node.operand):
                return False
            program.append((_OPS["neg" if node.op == "-" else "not"], 0.0))
        elif isinstance(node, Binary):
            if node.op not in _OPS or not (emit(node.left) and emit(node.right)):
                return False
            program.append((_OPS[node.op], 0.0))
        elif isinstance(node, Call):
            if _CALLS.get(node.func) != len(node.args):
                return False
            if not all(emit(argument) for argument in node.args):
                return False
            program.append((_OPS[node.func], 0.0))
        else:
            return False
        return True

    if formula is None or formula.condition is None:
        return None
    for assignment in formula.assignments:
        if not emit(assignment.value):
            return None
        slots[assignment.name] = len(slots)
        program.append((_OPS["store"], float(slots[assignment.name])))
    if not emit(formula.condition):
        return None
    return program, len(slots)


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
    max_hold=DEFAULT_HOLD,
    dynamic_tp=False,
    reverse=0.0,
    side="long",
    exit_formula=None,
    short_entries=None,
    slippage=0.0,
):
    """Walk the bars, opening where an entry is true. One position at a time.

    `entries` open longs, or shorts when `side` is `short`. `short_entries`, if
    given, open shorts as well, so one strategy can trade both ways on
    different conditions; a bar both would trade is left alone.

    `sizing` is `balance` (percent of the deployable cash), `fixed` (dollars)
    or `risk` (percent of the deployable cash lost if the stop is hit, so the
    position shrinks as the stop widens). `max_hold` is how many bars a trade
    may run (0 for no limit). `dynamic_tp` trails the take profit: once the
    trade is in profit, a pull-back of `reverse` percent from the best price
    closes it. `exit_formula` is a parsed exit rule, checked on each bar's
    close while a trade is open, after the stop and take profit have had their
    say.

    `slippage` is a fraction (0.0001 is 0.01%) each market fill gives away: an
    entry fills that much worse than the close, and so does every exit except a
    take profit, which is a resting limit order and fills at its price.

    A trade is `(entry index, entry price, exit index, exit price, result,
    fees, notional, reason, side)`.
    """
    if side == "short":
        longs, shorts = None, entries
    else:
        longs, shorts = entries, short_entries
    compiled = compile_exit(exit_formula) if exit_formula is not None else None

    if _NATIVE and (exit_formula is None or compiled is not None):
        import numpy as np

        # Already a float64 array (the span's columns): no copy. A list is
        # copied once, in C, rather than element by element.
        closes = np.ascontiguousarray(closes, dtype=float)
        size = len(closes)

        def flags(values):
            if values is None:
                return np.zeros(size, dtype=bool)
            return np.ascontiguousarray(values, dtype=bool)

        program, slots = compiled if compiled else (None, 0)
        return _native_walk(
            closes,
            np.ascontiguousarray(highs, dtype=float),
            np.ascontiguousarray(lows, dtype=float),
            flags(longs),
            flags(shorts),
            capital, tp, sl, position, sizing, max_cash, fee, int(max_hold),
            bool(dynamic_tp), float(reverse), program, slots, float(slippage),
        )
    # The Python walk indexes the columns one by one, and list indexing is
    # faster than NumPy scalar indexing, so lift to lists once.
    closes = [float(value) for value in closes]
    highs = [float(value) for value in highs]
    lows = [float(value) for value in lows]
    size = len(closes)

    def listed(values):
        if values is None:
            return [False] * size
        return [bool(value) for value in values]

    return _python_walk(
        closes, highs, lows, listed(longs), listed(shorts), capital, tp, sl,
        position, sizing, max_cash, fee, int(max_hold), dynamic_tp, reverse,
        exit_formula, slippage,
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
    closes, highs, lows, longs, shorts, capital, tp, sl, position, sizing,
    max_cash, fee, max_hold, dynamic_tp=False, reverse=0.0, exit_formula=None,
    slippage=0.0,
):
    fixed = sizing == "fixed"
    risk = sizing == "risk"
    cash = capital
    qty = 0.0
    short = False
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
            held = index - entry_index
            price = None
            reason = "time"
            # A candle that holds both the target and the stop cannot say which
            # came first, so the stop is taken: the cautious reading.
            if hit_sl:
                price = stop
                reason = "sl"
            elif hit_tp:
                price = target
                reason = "tp"
            elif hit_trail:
                price = trail
                reason = "tp"
            elif exit_formula is not None and evaluate_scalar(
                exit_formula,
                exit_context(close, entry_price, tp, sl, held, short),
            ):
                price = close
                reason = "rule"
            if price is None and max_hold > 0 and held >= max_hold:
                price = close
                reason = "time"
            if price is not None:
                if reason != "tp":  # a take profit is a limit order: no slip
                    price *= (1.0 + slippage) if short else (1.0 - slippage)
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
                        "short" if short else "long",
                    )
                )
                qty = 0.0
                entry_cost = 0.0
                best = 0.0
        elif index != 0 and longs[index] != shorts[index]:
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
                short = bool(shorts[index])
                fill = close * ((1.0 - slippage) if short else (1.0 + slippage))
                qty = notional / fill
                cash -= notional + cost
                entry_price = fill
                entry_index = index
                entry_fee = cost
                entry_notional = notional
                entry_cost = notional + cost
                best = low if short else high
        equity.append(cash + qty * entry_price)

    return trades, equity
