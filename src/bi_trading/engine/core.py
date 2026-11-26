"""The backtest walk, native when it can be, Python otherwise.

`bi_trading_core` is a small Rust extension (see `rust/bi_trading_core`) holding the
bar loop. When it is built and importable it is used; otherwise `walk` falls
back to the same walk in pure Python, so the app runs either way.

`walk(closes, highs, lows, entries, ...)` returns `(trades, equity)` where a
trade is `(entry index, entry price, exit index, exit price, result, fees,
notional, reason, side)` and
`equity` is the book per bar, an open position marked at the close. One position at a time, long or short:
a short sells at the entry and buys back at the exit, its take profit below
the entry and its stop above. A trade ends at its stop, its take profit (the
stop first when one candle holds both), its exit rule, or its hold limit.
"""

from __future__ import annotations

from bi_trading.engine.formula_eval import evaluate_scalar

__all__ = [
    "DEFAULT_HOLD",
    "available",
    "compile_exit",
    "exit_context",
    "fresh_state",
    "random_entries",
    "random_entries_chunk",
    "walk",
    "walk_chunk",
]

# How many bars a trade may run unless told otherwise.
DEFAULT_HOLD = 7

try:  # the extension, if it was built
    from bi_trading_core import random_entries as _native_random_entries  # type: ignore
    from bi_trading_core import random_entries_chunk as _native_random_chunk  # type: ignore
    from bi_trading_core import walk_chunk as _native_walk_chunk  # type: ignore

    _NATIVE = True
except ImportError:  # pragma: no cover - depends on the build
    _native_walk_chunk = None
    _native_random_entries = None
    _native_random_chunk = None
    _NATIVE = False


def _flags(values):
    """A boolean array for the native core, or None when there is nothing."""
    if values is None:
        return None
    import numpy as np

    return np.ascontiguousarray(values, dtype=bool)


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
    gaps=None,
) -> list[bool]:
    """The coin-flip baseline's entries, one position at a time.

    `gaps` flags the bars that are the last before a hole in the data (see
    `walk_chunk`): the baseline does not open there and drops what it holds.

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
                _flags(gaps),
            )
        )
    return _python_random_entries(
        highs, lows, closes, draws, tp, sl, max_hold, chance, short, gaps=gaps
    )[0]


def random_entries_chunk(
    highs, lows, closes, draws, tp=2.0, sl=1.0, max_hold=DEFAULT_HOLD,
    chance=0.03, short=False, offset=0, state=None, gaps=None,
):
    """`random_entries` for one piece of a longer span, carrying its state.

    `offset` is the piece's first bar in the whole span; `state` is what the
    piece before returned (None for the first). `draws` are the next uniforms of
    the stream, at least one per bar. Returns `(entries, state)`; the state's
    last item says how many draws were used, so the caller knows where the next
    piece's draws begin (it counts the draws *this* piece used).
    """
    if _NATIVE:
        import numpy as np

        entries, end = _native_random_chunk(
            np.ascontiguousarray(highs, dtype=float),
            np.ascontiguousarray(lows, dtype=float),
            np.ascontiguousarray(closes, dtype=float),
            np.ascontiguousarray(draws, dtype=float),
            tp, sl, max_hold, chance, bool(short), int(offset),
            None if state is None else tuple(state), _flags(gaps),
        )
        return list(entries), end
    return _python_random_entries(
        highs, lows, closes, draws, tp, sl, max_hold, chance, short, offset, state,
        gaps,
    )


def _python_random_entries(
    highs, lows, closes, draws, tp, sl, max_hold, chance, short=False,
    offset=0, state=None, gaps=None,
):
    n = len(closes)
    entries = [False] * n
    in_position, entry_price, entry_index, _ = state or (False, 0.0, 0, 0)
    drawn = 0   # this piece's own draws; the caller adds them up
    for local in range(n):
        index = offset + local
        if index == 0:
            continue
        gap_after = bool(gaps[local]) if gaps is not None else False
        if in_position:
            if short:
                target = entry_price * (1.0 - tp / 100.0)
                stop = entry_price * (1.0 + sl / 100.0)
                hit_tp = tp > 0 and lows[local] <= target
                hit_sl = sl > 0 and highs[local] >= stop
            else:
                target = entry_price * (1.0 + tp / 100.0)
                stop = entry_price * (1.0 - sl / 100.0)
                hit_tp = tp > 0 and highs[local] >= target
                hit_sl = sl > 0 and lows[local] <= stop
            if (
                hit_tp or hit_sl or gap_after
                or (max_hold > 0 and index - entry_index >= max_hold)
            ):
                in_position = False
        elif gap_after:
            pass  # the walk does not open on the last bar before a hole
        else:
            if drawn < len(draws):
                draw = draws[drawn]
                drawn += 1
            else:
                draw = 1.0
            if draw < chance:
                entries[local] = True
                in_position = True
                entry_price = closes[local]
                entry_index = index
    return entries, (in_position, entry_price, entry_index, drawn)


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
    from bi_trading.engine.formula import (
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


def fresh_state(capital: float) -> tuple:
    """The book before the first bar: all cash, nothing open."""
    return (capital, 0.0, False, 0.0, 0, 0.0, 0.0, 0.0, 0.0)


def walk(*args, **kwargs):
    """`walk_chunk` over a whole span: `(trades, equity)`."""
    trades, equity, _ = walk_chunk(*args, **kwargs)
    return trades, equity


def walk_chunk(
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
    offset=0,
    state=None,
    gaps=None,
    volumes=None,
    participation=0.0,
    opens=None,
    entry_open=False,
    through=0.0,
):
    """Walk the bars, opening where an entry is true. One position at a time.

    `gaps` is one flag per bar: True when the bar is the last before a hole in
    the data (the next bar is more than one step later). A position cannot be
    held through a hole, so it is closed at that bar's close, as a market exit
    that reads `gap`, and no trade opens on such a bar.

    `volumes` (the bars' traded volume, in the asset) with a `participation`
    fraction above zero caps an entry at that share of the entry bar's traded
    value (volume x close), so a size the market could not have absorbed is cut.

    `opens` (each bar's open) lets a stop or trail that the market gapped past
    fill at the open instead of the price it jumped over, and a take profit
    that it gapped past fill at the better open. `through` is how far (a
    fraction) the market must trade past a take profit's price before that
    limit order counts as filled; touching it is not enough. The trailing stop
    is a market exit and slips like one.

    `entry_open` fills an entry at the bar's open instead of the close, the
    signal having come from the bar before: the caller passes entries already
    delayed by a bar (see `delayed`), and the entry bar's own range can then
    stop it out or fill its target.

    Returns `(trades, equity, state)`. A long span can be walked in chunks:
    pass each chunk's `offset` (its first bar's index in the whole span) and
    the `state` the chunk before it returned (None for the first). A trade can
    open in one chunk and close in a later one, and trades carry whole-span
    indices. `walk` is the same without the state, for one piece.

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
        trades, curve, end = _native_walk_chunk(
            closes,
            np.ascontiguousarray(highs, dtype=float),
            np.ascontiguousarray(lows, dtype=float),
            flags(longs),
            flags(shorts),
            capital, tp, sl, position, sizing, max_cash, fee, int(max_hold),
            bool(dynamic_tp), float(reverse), program, slots, float(slippage),
            int(offset), None if state is None else tuple(state),
            None if gaps is None else flags(gaps),
            None if volumes is None else np.ascontiguousarray(volumes, dtype=float),
            float(participation),
            None if opens is None else np.ascontiguousarray(opens, dtype=float),
            bool(entry_open), float(through),
        )
        return trades, curve, end
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
        exit_formula, slippage, offset, state,
        None if gaps is None else listed(gaps),
        None if volumes is None else [float(v) for v in volumes],
        participation,
        None if opens is None else [float(v) for v in opens],
        bool(entry_open), through,
    )


def delayed(flags, gaps=None, previous=False, previous_gap=False):
    """Entry flags moved one bar later, for entries filled at the next open.

    A signal on the last bar before a hole is dropped: the bar after it is not
    the next bar. `previous` and `previous_gap` are the flag and gap of the bar
    before this piece (a piece of a longer span), so the first bar can be fed.
    """
    import numpy as np

    flags = np.asarray(flags, dtype=bool)
    out = np.zeros(len(flags), dtype=bool)
    if len(flags) == 0:
        return out
    held = flags if gaps is None else flags & ~np.asarray(gaps, dtype=bool)
    out[1:] = held[:-1]
    out[0] = bool(previous) and not bool(previous_gap)
    return out


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
    slippage=0.0, offset=0, state=None, gaps=None, volumes=None,
    participation=0.0, opens=None, entry_open=False, through=0.0,
):
    """The bar loop. `offset` is the first bar's index in the whole span and
    `state` what the previous chunk ended in (None to begin); returns the
    trades, the equity per bar, and the state to carry on from."""
    fixed = sizing == "fixed"
    risk = sizing == "risk"
    if state is None:
        state = fresh_state(capital)
    (
        cash, qty, short, entry_price, entry_index, entry_cost, entry_fee,
        entry_notional, best,
    ) = state  # best: the high of a long since entry, the low of a short
    trades: list[tuple] = []
    equity: list[float] = []

    for local, close in enumerate(closes):
        index = offset + local
        high = highs[local]
        low = lows[local]
        gap_after = bool(gaps[local]) if gaps is not None else False
        open_ = opens[local] if opens is not None else None  # None: gaps unknown
        opened_now = False
        # An entry is looked at first, while the book is flat: at the close of
        # the bar that made the signal, or (`entry_open`) at the open of the
        # bar after it, the signal having been delayed a bar by the caller.
        if qty == 0.0 and index != 0 and not gap_after and longs[local] != shorts[local]:
            basis = open_ if (entry_open and open_ is not None) else close
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
            if participation > 0.0 and volumes is not None:
                notional = min(notional, volumes[local] * basis * participation)
            if notional > 0.0 and basis > 0.0:
                cost = notional * fee
                short = bool(shorts[local])
                fill = basis * ((1.0 - slippage) if short else (1.0 + slippage))
                qty = notional / fill
                cash -= notional + cost
                entry_price = fill
                entry_index = index
                entry_fee = cost
                entry_notional = notional
                entry_cost = notional + cost
                best = low if short else high
                opened_now = True
        # A position opened at the close has nothing left of its bar to trade;
        # one opened at the open lives through the whole bar.
        if qty > 0.0 and (not opened_now or entry_open):
            prev_best = best   # the trail as the bars before this one left it
            if short:
                target = entry_price * (1.0 - tp / 100.0)
                stop = entry_price * (1.0 + sl / 100.0)
                if dynamic_tp and reverse > 0.0:
                    best = min(best, low)
                trail = best * (1.0 + reverse / 100.0) if best else 0.0
                hit_tp = tp > 0 and low <= target * (1.0 - through)
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
                hit_tp = tp > 0 and high >= target * (1.0 + through)
                hit_sl = sl > 0 and low <= stop
                hit_trail = (
                    dynamic_tp and reverse > 0 and best > entry_price
                    and low <= trail
                )
            held = index - entry_index
            price = None
            reason = "time"
            limit = False   # only the take profit is a resting limit order
            # A candle that holds both the target and the stop cannot say which
            # came first, so the stop is taken: the cautious reading. A bar that
            # opened past the stop or trail fills at its open, not at the price
            # it jumped over; one that opened past the target gets the better open.
            if hit_sl:
                price = stop if open_ is None else (max(stop, open_) if short else min(stop, open_))
                reason = "sl"
            elif hit_tp:
                price = target if open_ is None else (min(target, open_) if short else max(target, open_))
                reason = "tp"
                limit = True
            elif hit_trail:
                # The trail is a stop that follows the price: a market exit.
                before = prev_best * (1.0 + reverse / 100.0 if short else 1.0 - reverse / 100.0)
                gapped = open_ is not None and (
                    open_ >= before if short else open_ <= before
                )
                price = open_ if gapped else trail
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
            if price is None and gap_after:
                # The data stops after this bar: no holding through a hole.
                price = close
                reason = "gap"
            if price is not None:
                if not limit:  # every exit but the take profit slips
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
        # Marked to market: an open long is worth its quantity at the close, an
        # open short its margin plus what the price has fallen (never below 0).
        if qty > 0.0:
            held_value = (
                max(0.0, qty * (2.0 * entry_price - close)) if short else qty * close
            )
        else:
            held_value = 0.0
        equity.append(cash + held_value)

    end = (
        cash, qty, short, entry_price, entry_index, entry_cost, entry_fee,
        entry_notional, best,
    )
    return trades, equity, end
