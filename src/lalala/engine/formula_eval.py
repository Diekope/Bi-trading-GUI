"""Run a formula over bars. No Qt.

`lalala.engine.formula` says whether a formula holds up; this says what it does. Each
expression becomes a value per bar, the condition becomes a truth per bar, and
the bars where it is true are the signals.

A series is a list with one entry per bar, a float or `None` where there is not
enough history yet — a 20-bar average has nothing to say about the first
nineteen bars. Nothing looks ahead: every value at bar *i* is built from bars
*i* and earlier.

Entry rules read the bar, so they are evaluated over a whole series at once.
Exit rules read the trade, which only exists while one is open, so they are
evaluated a bar at a time against the open trade's numbers.
"""

from __future__ import annotations

import operator
from collections import deque
from dataclasses import dataclass, field

try:  # a fast, vectorised path for the entry rule; the list walk is the reference
    import numpy as _np
except ModuleNotFoundError:  # pragma: no cover - numpy is a hard dependency
    _np = None

from lalala.engine.formula import (
    ENTRY_FIELDS,
    Assignment,
    Binary,
    Call,
    Formula,
    Name,
    Number,
    Unary,
)

__all__ = [
    "FEE",
    "REASON_END",
    "REASON_ORDER",
    "REASON_RULE",
    "REASON_STOP_LOSS",
    "REASON_TAKE_PROFIT",
    "REASON_TIME",
    "Report",
    "backtest",
    "bar_context",
    "curve_drawdown",
    "curve_return",
    "curve_sharpe",
    "entry_signals",
    "names_used",
    "evaluate",
    "evaluate_scalar",
    "watch_values",
    "simulate",
]


# -- reading the bars -------------------------------------------------------


def _num(raw):
    """A field's value as a float, or None when it is missing / not a number."""
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _value(bar, name: str):
    if isinstance(bar, dict):
        raw = bar.get(name)
    else:
        raw = getattr(bar, name, None)
        if raw is None and name == "price":
            # On a bar, the market price is the close.
            raw = getattr(bar, "close", None)
    return _num(raw)


def bar_context(bars, fields=ENTRY_FIELDS) -> dict:
    """One series per field, in the order the bars were given.

    The bar kind (mapping or object) is decided once, not per field, so a long
    span is not re-typed field by field.
    """
    fields = tuple(fields)
    if not bars:
        return {name: [] for name in fields}

    if isinstance(bars[0], dict):
        return {name: [_num(bar.get(name)) for bar in bars] for name in fields}

    has_price = hasattr(bars[0], "price")
    columns = {}
    for name in fields:
        if name == "price" and not has_price:
            columns[name] = [_num(getattr(bar, "close", None)) for bar in bars]
        else:
            columns[name] = [_num(getattr(bar, name, None)) for bar in bars]
    return columns


def _length(context: dict) -> int:
    for series in context.values():
        return len(series)
    return 0


# -- the indicators ---------------------------------------------------------


def _sma(values, period: int):
    out = [None] * len(values)
    window: deque = deque(maxlen=period)
    for index, value in enumerate(values):
        if value is None:
            window.clear()
            continue
        window.append(value)
        if len(window) == period:
            out[index] = sum(window) / period
    return out


def _highest(values, period: int):
    out = [None] * len(values)
    window: deque = deque(maxlen=period)
    for index, value in enumerate(values):
        if value is None:
            window.clear()
            continue
        window.append(value)
        if len(window) == period:
            out[index] = max(window)
    return out


def _lowest(values, period: int):
    out = [None] * len(values)
    window: deque = deque(maxlen=period)
    for index, value in enumerate(values):
        if value is None:
            window.clear()
            continue
        window.append(value)
        if len(window) == period:
            out[index] = min(window)
    return out


def _ema(values, period: int):
    out = [None] * len(values)
    alpha = 2.0 / (period + 1.0)
    previous = None
    for index, value in enumerate(values):
        if value is None:
            previous = None
            continue
        previous = value if previous is None else alpha * value + (1 - alpha) * previous
        out[index] = previous
    return out


def _rsi(values, period: int):
    out = [None] * len(values)
    gains: list[float] = []
    losses: list[float] = []
    average_gain = average_loss = None
    previous = None
    for index, value in enumerate(values):
        if value is None:
            previous = None
            average_gain = average_loss = None
            gains.clear()
            losses.clear()
            continue
        if previous is None:
            previous = value
            continue
        change = value - previous
        previous = value
        gain, loss = max(0.0, change), max(0.0, -change)
        if average_gain is None:
            gains.append(gain)
            losses.append(loss)
            if len(gains) < period:
                continue
            average_gain = sum(gains) / period
            average_loss = sum(losses) / period
        else:
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        out[index] = _rsi_value(average_gain, average_loss)
    return out


def _rsi_value(gain: float, loss: float) -> float:
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _bollinger(values, period: int, deviations: float):
    """(middle, upper, lower), the same numbers the walk keeps."""
    size = len(values)
    middle = [None] * size
    upper = [None] * size
    lower = [None] * size
    window: deque = deque(maxlen=period)
    total = 0.0
    total_squares = 0.0
    for index, value in enumerate(values):
        if value is None:
            window.clear()
            total = total_squares = 0.0
            continue
        if len(window) == period:
            gone = window[0]
            total -= gone
            total_squares -= gone * gone
        window.append(value)
        total += value
        total_squares += value * value
        if len(window) == period:
            mean = total / period
            variance = max(0.0, total_squares / period - mean * mean)
            spread = variance ** 0.5 * deviations
            middle[index] = mean
            upper[index] = mean + spread
            lower[index] = mean - spread
    return middle, upper, lower


def _stdev_series(values, period: int):
    """Rolling standard deviation, the σ behind a z-score."""
    out = [None] * len(values)
    window: deque = deque(maxlen=period)
    total = 0.0
    total_squares = 0.0
    for index, value in enumerate(values):
        if value is None:
            window.clear()
            total = total_squares = 0.0
            continue
        if len(window) == period:
            gone = window[0]
            total -= gone
            total_squares -= gone * gone
        window.append(value)
        total += value
        total_squares += value * value
        if len(window) == period:
            mean = total / period
            out[index] = max(0.0, total_squares / period - mean * mean) ** 0.5
    return out


def _zscore(values, period: int):
    """How far the value sits from its own average, in deviations."""
    middle = _sma(values, period)
    spread = _stdev_series(values, period)
    return [
        None if value is None or mean is None or deviation in (None, 0)
        else (value - mean) / deviation
        for value, mean, deviation in zip(values, middle, spread)
    ]


def _log(value: float) -> float:
    import math

    return math.log(value) if value > 0 else 0.0


def _change(values, bars: int):
    out = [None] * len(values)
    for index in range(bars, len(values)):
        now, before = values[index], values[index - bars]
        if now is not None and before is not None:
            out[index] = now - before
    return out


def _shift(values, bars: int):
    out = [None] * len(values)
    for index in range(bars, len(values)):
        out[index] = values[index - bars]
    return out


def _pairwise(values, function):
    return [None if value is None else function(value) for value in values]


def _between(left, right, function):
    out = []
    for a, b in zip(left, right):
        out.append(None if a is None or b is None else function(a, b))
    return out


def _period(series, what: str) -> int:
    """A period argument: one number, the same on every bar."""
    for value in series:
        if value is not None:
            return max(1, int(value))
    raise ValueError(f"{what} has no period")


# -- the evaluator ----------------------------------------------------------


def _constant(value: float, length: int):
    return [value] * length


def _arity(node) -> int:
    return len(node.args)


def _call(node: Call, scope: dict):
    args = [_eval(argument, scope) for argument in node.args]
    name = node.func

    if name in ("abs", "sqrt", "log"):
        function = {"abs": abs, "sqrt": sqrt, "log": _log}[name]
        return _pairwise(args[0], function)
    if name in ("min", "max"):
        function = min if name == "min" else max
        return _between(args[0], args[1], function)
    if name == "sma":
        return _sma(args[0], _period(args[1], "sma"))
    if name == "stdev":
        return _stdev_series(args[0], _period(args[1], "stdev"))
    if name == "zscore":
        return _zscore(args[0], _period(args[1], "zscore"))
    if name == "ema":
        return _ema(args[0], _period(args[1], "ema"))
    if name == "rsi":
        return _rsi(args[0], _period(args[1], "rsi"))
    if name == "highest":
        return _highest(args[0], _period(args[1], "highest"))
    if name == "lowest":
        return _lowest(args[0], _period(args[1], "lowest"))
    if name == "change":
        return _change(args[0], _period(args[1], "change"))
    if name == "shift":
        return _shift(args[0], _period(args[1], "shift"))
    if name in ("bollinger_lower", "bollinger_middle", "bollinger_upper"):
        period = _period(args[1], name)
        deviations = _period_or_float(args[2], 2.0)
        middle, upper, lower = _bollinger(args[0], period, deviations)
        return {
            "bollinger_lower": lower,
            "bollinger_middle": middle,
            "bollinger_upper": upper,
        }[name]
    raise ValueError(f"no evaluator for {name}()")


def sqrt(value: float) -> float:
    return value ** 0.5 if value >= 0 else 0.0


def _period_or_float(series, default: float) -> float:
    for value in series:
        if value is not None:
            return float(value)
    return default


def _truth(value) -> bool:
    return value is not None and value > 0


def _compare(op: str, a, b):
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "==":
        return a == b
    return a != b


def _apply(op: str, a, b):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return None if b == 0 else a / b
    if op == "%":
        return None if b == 0 else a % b
    if op == "^":
        return a ** b
    return _compare(op, a, b)


# The ops that are a single built-in call, hoisted out of the per-element loop.
_SIMPLE_OP = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def _eval(node, scope: dict):
    if isinstance(node, Number):
        return _constant(node.value, _length(scope))
    if isinstance(node, Name):
        return list(scope[node.name])
    if isinstance(node, Unary):
        values = _eval(node.operand, scope)
        if node.op == "not":
            return [0.0 if value is None else (0.0 if _truth(value) else 1.0)
                    for value in values]
        return [None if value is None else -value for value in values]
    if isinstance(node, Binary):
        if node.op in ("and", "or"):
            left = _eval(node.left, scope)
            right = _eval(node.right, scope)
            if node.op == "and":
                return [1.0 if _truth(a) and _truth(b) else 0.0
                        for a, b in zip(left, right)]
            return [1.0 if _truth(a) or _truth(b) else 0.0
                    for a, b in zip(left, right)]
        left = _eval(node.left, scope)
        right = _eval(node.right, scope)
        simple = _SIMPLE_OP.get(node.op)
        if simple is not None:
            return [
                None if a is None or b is None else float(simple(a, b))
                for a, b in zip(left, right)
            ]
        if node.op == "/":
            return [
                None if a is None or b is None or b == 0 else a / b
                for a, b in zip(left, right)
            ]
        if node.op == "%":
            return [
                None if a is None or b is None or b == 0 else a % b
                for a, b in zip(left, right)
            ]
        out = []
        for a, b in zip(left, right):
            if a is None or b is None:
                out.append(None)
                continue
            result = _apply(node.op, a, b)
            out.append(None if result is None else float(result))
        return out
    if isinstance(node, Call):
        return _call(node, scope)
    if isinstance(node, Assignment):
        return _eval(node.value, scope)
    raise ValueError("cannot evaluate this node")  # pragma: no cover


def evaluate(formula: Formula, context: dict):
    """The condition's value per bar — a float, or None where unknown."""
    scope = dict(context)
    for assignment in formula.assignments:
        scope[assignment.name] = _eval(assignment.value, scope)
    if formula.condition is None:
        return [None] * _length(context)
    return _eval(formula.condition, scope)


def entry_signals(formula: Formula, bars, fields=ENTRY_FIELDS) -> list[int]:
    """The bars where an entry rule is true.

    `bars` is a list of bars, or a mapping of field name to a whole series (the
    column form the array-backed span carries). A vectorised NumPy pass over a
    gap-free series; the list walk is the reference and takes over whenever the
    fast path does not apply (a gap in a field, an unknown function, or no
    NumPy at all).
    """
    if formula is None or formula.condition is None:
        return []
    fast = _numpy_signals(formula, bars, fields)
    if fast is not None:
        return fast
    if isinstance(bars, dict):
        length = len(next(iter(bars.values()))) if bars else 0
        bars = [
            {name: bars[name][index] for name in fields if name in bars}
            for index in range(length)
        ]
    values = evaluate(formula, bar_context(bars, fields))
    return [index for index, value in enumerate(values) if _truth(value)]


def _numpy_signals(formula: Formula, bars, fields) -> list[int] | None:
    """The signals computed with NumPy, or None to fall back to the list walk."""
    if _np is None:
        return None
    if isinstance(bars, dict):
        arrays = {}
        for name in fields:
            if name not in bars:
                return None
            array = _np.asarray(bars[name], dtype=float)
            if _np.isnan(array).any():
                return None
            arrays[name] = array
    else:
        arrays = _numpy_context(bars, fields)
        if arrays is None:
            return None
    length = len(next(iter(arrays.values()))) if arrays else 0
    if length == 0:
        return []
    scope = dict(arrays)
    try:
        for assignment in formula.assignments:
            scope[assignment.name] = _eval_np(assignment.value, scope, length)
        values = _eval_np(formula.condition, scope, length)
    except (ValueError, TypeError, KeyError):
        return None
    return [int(index) for index in _np.nonzero(values > 0)[0]]


def _numpy_context(bars, fields) -> dict | None:
    """One array per field, built straight from the bars — no list in between.

    None to fall back to the list walk: a bar missing a field, a non-number, or
    a gap the rolling windows would treat differently.
    """
    from operator import attrgetter, methodcaller

    if not bars:
        return {name: _np.array([], dtype=float) for name in fields}
    if isinstance(bars[0], dict):
        getters = {name: methodcaller("get", name) for name in fields}
    else:
        has_price = hasattr(bars[0], "price")
        getters = {
            name: (
                attrgetter("close")
                if name == "price" and not has_price
                else attrgetter(name)
            )
            for name in fields
        }
    arrays: dict = {}
    count = len(bars)
    for name in fields:
        try:
            # attrgetter / methodcaller in a map: the field read runs in C, not
            # as a Python call per bar.
            array = _np.fromiter(
                map(getters[name], bars), dtype=float, count=count
            )
        except (TypeError, ValueError, AttributeError):
            return None
        if _np.isnan(array).any():
            return None  # a gap: the list walk resets on None; keep it there
        arrays[name] = array
    return arrays


def _eval_np(node, scope: dict, length: int):
    """A formula over NumPy arrays; NaN stands in for the list walk's None."""
    np = _np
    if isinstance(node, Number):
        return np.full(length, float(node.value))
    if isinstance(node, Name):
        return scope[node.name]
    if isinstance(node, Unary):
        values = _eval_np(node.operand, scope, length)
        if node.op == "not":
            # `not None` is falsy in the list walk, so an unknown stays 0.
            return np.where(np.isnan(values), 0.0, (values <= 0).astype(float))
        return -values
    if isinstance(node, Binary):
        left = _eval_np(node.left, scope, length)
        right = _eval_np(node.right, scope, length)
        if node.op in ("and", "or"):
            a, b = left > 0, right > 0
            return (
                np.logical_and(a, b) if node.op == "and" else np.logical_or(a, b)
            ).astype(float)
        fn = _SIMPLE_OP.get(node.op)
        if fn is not None and node.op in ("+", "-", "*"):
            return fn(left, right)
        if fn is not None:  # a comparison: unknown where either side is
            result = fn(left, right).astype(float)
            return np.where(np.isnan(left) | np.isnan(right), np.nan, result)
        with np.errstate(divide="ignore", invalid="ignore"):
            if node.op in ("/", "%"):
                product = left / right if node.op == "/" else np.mod(left, right)
                bad = (right == 0) | np.isnan(left) | np.isnan(right)
                return np.where(bad, np.nan, product)
            if node.op == "^":
                return np.power(left, right)
        raise ValueError(f"no numpy evaluator for {node.op!r}")
    if isinstance(node, Call):
        return _call_np(node, scope, length)
    if isinstance(node, Assignment):
        return _eval_np(node.value, scope, length)
    raise ValueError("cannot evaluate this node")


def _call_np(node, scope: dict, length: int):
    """A function node over arrays, vectorised where it can be."""
    np = _np
    name = node.func
    if name in _SEQUENTIAL or _np is None:
        # ema / rsi recur, and an unknown name is the caller's fallback.
        result = _call(node, scope)
        return np.array(
            [np.nan if value is None else float(value) for value in result],
            dtype=float,
        )
    args = [_eval_np(argument, scope, length) for argument in node.args]
    value = args[0]
    if name == "abs":
        return np.abs(value)
    if name == "sqrt":
        root = np.sqrt(np.where(value >= 0, value, 0.0))
        return np.where(np.isnan(value), np.nan, root)
    if name == "log":
        logged = np.log(np.where(value > 0, value, 1.0))
        return np.where(np.isnan(value), np.nan, np.where(value > 0, logged, 0.0))
    if name == "min":
        return np.minimum(value, args[1])
    if name == "max":
        return np.maximum(value, args[1])
    period = _np_period(args[1], name)
    if name == "sma":
        return _np_rolling_mean(value, period)
    if name == "highest":
        return _np_rolling_extreme(value, period, np.max)
    if name == "lowest":
        return _np_rolling_extreme(value, period, np.min)
    if name == "stdev":
        return _np_rolling_std(value, period)
    if name == "change":
        return _np_change(value, period)
    if name == "shift":
        return _np_shift(value, period)
    if name == "zscore":
        mean = _np_rolling_mean(value, period)
        spread = _np_rolling_std(value, period)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = (value - mean) / spread
        return np.where((spread == 0) | np.isnan(spread), np.nan, out)
    if name in ("bollinger_lower", "bollinger_middle", "bollinger_upper"):
        deviations = float(args[2][0]) if len(args) > 2 else 2.0
        middle = _np_rolling_mean(value, period)
        spread = _np_rolling_std(value, period) * deviations
        return {
            "bollinger_lower": middle - spread,
            "bollinger_middle": middle,
            "bollinger_upper": middle + spread,
        }[name]
    result = _call(node, scope)  # an unknown function: let the list walk speak
    return np.array(
        [np.nan if item is None else float(item) for item in result], dtype=float
    )


# ema and rsi recur bar to bar; there is no tidy vector form, so the list
# indicator runs and its result is lifted to an array.
_SEQUENTIAL = frozenset({"ema", "rsi"})


def _np_period(series, what: str) -> int:
    for value in series:
        if not _np.isnan(value):
            return max(1, int(value))
    raise ValueError(f"{what} has no period")


def _np_rolling_mean(values, period: int):
    np = _np
    size = len(values)
    out = np.full(size, np.nan)
    if period <= 0 or period > size:
        return out
    cumulative = np.cumsum(np.insert(values, 0, 0.0))
    out[period - 1 :] = (cumulative[period:] - cumulative[:-period]) / period
    return out


def _np_rolling_extreme(values, period: int, reduce):
    np = _np
    from numpy.lib.stride_tricks import sliding_window_view

    size = len(values)
    out = np.full(size, np.nan)
    if period <= 0 or period > size:
        return out
    windows = sliding_window_view(values, period)
    out[period - 1 :] = reduce(windows, axis=1)
    return out


def _np_rolling_std(values, period: int):
    np = _np
    size = len(values)
    out = np.full(size, np.nan)
    if period <= 0 or period > size:
        return out
    cumulative = np.cumsum(np.insert(values, 0, 0.0))
    squares = np.cumsum(np.insert(values * values, 0, 0.0))
    total = cumulative[period:] - cumulative[:-period]
    total_sq = squares[period:] - squares[:-period]
    mean = total / period
    variance = np.maximum(0.0, total_sq / period - mean * mean)
    out[period - 1 :] = np.sqrt(variance)
    return out


def _np_change(values, bars: int):
    np = _np
    out = np.full(len(values), np.nan)
    if 0 < bars < len(values):
        out[bars:] = values[bars:] - values[:-bars]
    return out


def _np_shift(values, bars: int):
    np = _np
    out = np.full(len(values), np.nan)
    if 0 < bars < len(values):
        out[bars:] = values[:-bars]
    return out


def names_used(formula: Formula) -> list:
    """Every name the formula mentions, fields and variables alike."""
    seen: list = []

    def walk(node) -> None:
        if isinstance(node, Name):
            if node.name not in seen:
                seen.append(node.name)
            return
        if isinstance(node, Call):
            for argument in node.args:
                walk(argument)
            return
        if isinstance(node, Unary):
            walk(node.operand)
            return
        if isinstance(node, Binary):
            walk(node.left)
            walk(node.right)
            return
        if isinstance(node, Assignment):
            walk(node.value)

    for assignment in formula.assignments:
        walk(assignment.value)
    if formula.condition is not None:
        walk(formula.condition)
    return seen


def watch_values(formula: Formula, bars, fields=ENTRY_FIELDS):
    """What the rule's names read on the last bar, and whether it holds there.

    The panel beside the editor shows a block's live value; this is where those
    come from — the fields and variables the rule mentions, read on the newest
    bar, with its result.
    """
    if formula is None or formula.condition is None or not bars:
        return {}, None
    context = bar_context(bars, fields)
    scope = dict(context)
    for assignment in formula.assignments:
        scope[assignment.name] = _eval(assignment.value, scope)
    condition = _eval(formula.condition, scope)
    wanted = [name for name in names_used(formula) if name in scope]
    values = {}
    for name in wanted:
        series = scope[name]
        if series:
            values[name] = series[-1]
    result = condition[-1] if condition else None
    return values, (None if result is None else _truth(result))


def evaluate_scalar(formula: Formula, values: dict) -> bool:
    """A rule against one bar's numbers — how an exit rule is checked."""
    if formula is None or formula.condition is None:
        return False
    context = {name: [float(value)] for name, value in values.items()}
    result = evaluate(formula, context)
    return bool(result) and _truth(result[0])


def simulate(
    bars,
    entry: Formula | None,
    exit_: Formula | None,
    tp: float = 2.0,
    sl: float = 1.0,
) -> tuple[list[int], list[int]]:
    """Walk the bars: open on an entry signal, close when the exit says so.

    One position at a time, and the exit sees the trade's own numbers — the
    price, what it was opened at, how long it has run, and its profit or loss
    as a percentage. `tp` and `sl` are what the rule's `tp` and `sl` read.
    """
    entries: list[int] = []
    exits: list[int] = []
    signals = set(entry_signals(entry, bars))
    open_trade = False
    entry_price = 0.0
    entry_index = 0

    for index, bar in enumerate(bars):
        price = _value(bar, "close")
        if price is None:
            continue
        if not open_trade:
            if index in signals:
                open_trade = True
                entry_price = price
                entry_index = index
                entries.append(index)
            continue
        if exit_ is None or exit_.condition is None:
            continue
        profit = (price / entry_price - 1.0) * 100.0 if entry_price else 0.0
        context = {
            "price": price,
            "entry": entry_price,
            "tp": tp,
            "sl": sl,
            "pnl": profit,
            "bars": index - entry_index,
        }
        if evaluate_scalar(exit_, context):
            exits.append(index)
            open_trade = False
    return entries, exits


# -- the whole thing, with something to compare it to -----------------------


def curve_return(curve) -> float:
    """Return since the start of a curve."""
    if not curve or curve[0] <= 0:
        return 0.0
    return curve[-1] / curve[0] - 1.0


def curve_sharpe(curve) -> float:
    """Mean over deviation of the per-bar returns, not annualised."""
    returns = [
        value / previous - 1.0
        for previous, value in zip(curve, curve[1:])
        if previous > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    deviation = variance ** 0.5
    return mean / deviation if deviation else 0.0


def curve_drawdown(curve, capital: float) -> float:
    """The worst peak-to-trough fall of a curve."""
    peak = capital
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


@dataclass
class Report:
    """One run: the curves to draw, and the numbers above them."""

    capital: float
    strategy: list
    random: list
    hold: list
    trades: int
    wins: int
    fees: float = 0.0
    reasons: dict = field(default_factory=dict)
    random_trades: int = 0
    random_wins: int = 0

    @property
    def reason_shares(self) -> list:
        """The exit reasons as (label, count, share) sorted most-appearing."""
        total = sum(self.reasons.values())
        if not total:
            return []
        ordered = sorted(
            self.reasons.items(),
            key=lambda item: (
                -item[1],
                REASON_ORDER.index(item[0])
                if item[0] in REASON_ORDER
                else len(REASON_ORDER),
            ),
        )
        return [
            (label, count, count / total) for label, count in ordered
        ]

    @property
    def pnl(self) -> float:
        return self.return_of(self.strategy)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def random_win_rate(self) -> float:
        return (
            self.random_wins / self.random_trades
            if self.random_trades
            else 0.0
        )

    def return_of(self, curve) -> float:
        return curve_return(curve)

    @property
    def sharpe(self) -> float:
        return curve_sharpe(self.strategy)

    @property
    def max_drawdown(self) -> float:
        return curve_drawdown(self.strategy, self.capital)


FEE = 0.0006

# Why a trade ended, in the words the results tile lists them under. The
# clause of the exit rule that fired names it: one that reads `tp`, `sl` or
# `bars` is take profit, stop loss or time; anything else is the rule's own
# condition; a trade still open at the last bar is end of data.
REASON_TAKE_PROFIT = "Take profit"
REASON_STOP_LOSS = "Stop loss"
REASON_TIME = "Time"
REASON_END = "End of data"
REASON_RULE = "Rule"

# The order the tile draws them in when two reasons tie on count.
REASON_ORDER = (
    REASON_TAKE_PROFIT,
    REASON_STOP_LOSS,
    REASON_TIME,
    REASON_RULE,
    REASON_END,
)


def _or_clauses(node) -> list:
    """The top-level `or` branches of a condition, left to right."""
    if isinstance(node, Binary) and node.op == "or":
        return _or_clauses(node.left) + _or_clauses(node.right)
    return [node]


def _names_in(node) -> set:
    found: set = set()

    def walk(current) -> None:
        if isinstance(current, Name):
            found.add(current.name)
            return
        if isinstance(current, Call):
            for argument in current.args:
                walk(argument)
            return
        if isinstance(current, Unary):
            walk(current.operand)
            return
        if isinstance(current, Binary):
            walk(current.left)
            walk(current.right)

    walk(node)
    return found


def _exit_reason(exit_, context: dict) -> str:
    """Which clause of the exit rule closed the trade, in words."""
    if exit_ is None or exit_.condition is None:
        return REASON_END
    scope = {name: [float(value)] for name, value in context.items()}
    for clause in _or_clauses(exit_.condition):
        values = _eval(clause, scope)
        if values and _truth(values[0]):
            names = _names_in(clause)
            if "tp" in names:
                return REASON_TAKE_PROFIT
            if "sl" in names:
                return REASON_STOP_LOSS
            if "bars" in names:
                return REASON_TIME
            # A clause written against pnl (say `pnl >= 2`) still takes a
            # profit or a loss: name it by the sign it closed on, so the
            # report shows Take profit / Stop loss rather than a bare Rule.
            pnl = context.get("pnl")
            if pnl is not None:
                return REASON_TAKE_PROFIT if pnl >= 0 else REASON_STOP_LOSS
            return REASON_RULE
    return REASON_RULE


def _walk(closes, signals, exit_, tp, sl, capital, fee):
    """Mark-to-market equity for one set of entries, one position at a time.

    Also returns what each trade ended by, and the fees the walk paid.
    """
    equity: list[float] = []
    results: list[float] = []
    reasons: list[str] = []
    fees = 0.0
    cash = capital
    quantity = 0.0
    entry_price = 0.0
    entry_index = 0

    for index, price in enumerate(closes):
        if price is None:
            equity.append(equity[-1] if equity else capital)
            continue
        if quantity > 0:
            profit = (price / entry_price - 1.0) * 100.0 if entry_price else 0.0
            context = {
                "price": price,
                "entry": entry_price,
                "tp": tp,
                "sl": sl,
                "pnl": profit,
                "bars": index - entry_index,
            }
            if exit_ is None or exit_.condition is None or evaluate_scalar(
                exit_, context
            ):
                notional = quantity * price
                fees += notional * fee
                cash += notional * (1.0 - fee)
                results.append(price / entry_price - 1.0 if entry_price else 0.0)
                reasons.append(
                    REASON_END if exit_ is None else _exit_reason(exit_, context)
                )
                quantity = 0.0
        elif index in signals and cash > 0:
            fees += cash * fee
            quantity = cash * (1.0 - fee) / price
            cash = 0.0
            entry_price = price
            entry_index = index
        equity.append(cash + quantity * price)

    # A trade still open at the last bar ends there.
    if quantity > 0:
        price = closes[-1]
        if price:
            notional = quantity * price
            fees += notional * fee
            results.append(price / entry_price - 1.0 if entry_price else 0.0)
            reasons.append(REASON_END)
    return equity, results, reasons, fees


def backtest(
    bars,
    entry: Formula | None,
    exit_: Formula | None,
    tp: float = 2.0,
    sl: float = 1.0,
    capital: float = 10_000.0,
    fee: float = FEE,
    seed: int = 7,
    entry_chance: float = 0.03,
    fields=ENTRY_FIELDS,
) -> Report:
    """The rule, a random-buy version of it, and buy and hold, over `bars`.

    All three start with the same capital. The random version opens on a coin
    flip with the same exits, so a rule that cannot beat it has no edge. Buy
    and hold puts the whole book in at the first bar and never sells.
    """
    import random

    closes = [_value(bar, "close") for bar in bars]
    first = next((value for value in closes if value), None)
    if first is None:
        return Report(capital, [], [], [], 0, 0)

    signals = set(entry_signals(entry, bars, fields))
    strategy, results, reasons, fees = _walk(
        closes, signals, exit_, tp, sl, capital, fee
    )

    rng = random.Random(seed)
    picks = {index for index in range(len(closes)) if rng.random() < entry_chance}
    random_curve, random_results, _, _ = _walk(
        closes, picks, exit_, tp, sl, capital, fee
    )

    hold = [
        capital * (value / first) if value else capital for value in closes
    ]

    wins = sum(1 for value in results if value > 0)
    random_wins = sum(1 for value in random_results if value > 0)
    counts: dict = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return Report(
        capital,
        strategy,
        random_curve,
        hold,
        len(results),
        wins,
        fees,
        counts,
        len(random_results),
        random_wins,
    )
