"""Run a formula over bars. No Qt.

`lalala.formula` says whether a formula holds up; this says what it does. Each
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

from collections import deque
from dataclasses import dataclass

from lalala.formula import (
    EXIT_FIELDS,
    FIELDS,
    FUNCTIONS,
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
    "Report",
    "backtest",
    "bar_context",
    "entry_signals",
    "evaluate",
    "evaluate_scalar",
    "simulate",
]


# -- reading the bars -------------------------------------------------------


def _value(bar, name: str):
    if isinstance(bar, dict):
        raw = bar.get(name)
    else:
        raw = getattr(bar, name, None)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def bar_context(bars, fields=FIELDS) -> dict:
    """One series per field, in the order the bars were given."""
    return {name: [_value(bar, name) for bar in bars] for name in fields}


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
    name = node.func
    return len(node.args)


def _call(node: Call, scope: dict):
    args = [_eval(argument, scope) for argument in node.args]
    name = node.func

    if name in ("abs", "sqrt"):
        function = abs if name == "abs" else sqrt
        return _pairwise(args[0], function)
    if name in ("min", "max"):
        function = min if name == "min" else max
        return _between(args[0], args[1], function)
    if name == "sma":
        return _sma(args[0], _period(args[1], "sma"))
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


def entry_signals(formula: Formula, bars, fields=FIELDS) -> list[int]:
    """The bars where an entry rule is true."""
    if formula is None or formula.condition is None:
        return []
    values = evaluate(formula, bar_context(bars, fields))
    return [index for index, value in enumerate(values) if _truth(value)]


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


@dataclass
class Report:
    """One run: the curves to draw, and the numbers above them."""

    capital: float
    strategy: list
    random: list
    hold: list
    trades: int
    wins: int

    @property
    def pnl(self) -> float:
        return self.return_of(self.strategy)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    def return_of(self, curve) -> float:
        if not curve or curve[0] <= 0:
            return 0.0
        return curve[-1] / curve[0] - 1.0

    @property
    def sharpe(self) -> float:
        """Mean over deviation of the per-bar book returns, not annualised."""
        returns = [
            curve / previous - 1.0
            for previous, curve in zip(self.strategy, self.strategy[1:])
            if previous > 0
        ]
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        deviation = variance ** 0.5
        return mean / deviation if deviation else 0.0

    @property
    def max_drawdown(self) -> float:
        peak = self.capital
        worst = 0.0
        for value in self.strategy:
            peak = max(peak, value)
            if peak > 0:
                worst = min(worst, value / peak - 1.0)
        return worst


FEE = 0.0006


def _walk(closes, signals, exit_, tp, sl, capital, fee):
    """Mark-to-market equity for one set of entries, one position at a time."""
    equity: list[float] = []
    results: list[float] = []
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
                cash += quantity * price * (1.0 - fee)
                results.append(price / entry_price - 1.0 if entry_price else 0.0)
                quantity = 0.0
        elif index in signals and cash > 0:
            quantity = cash * (1.0 - fee) / price
            cash = 0.0
            entry_price = price
            entry_index = index
        equity.append(cash + quantity * price)
    return equity, results


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
    fields=FIELDS,
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
    strategy, results = _walk(closes, signals, exit_, tp, sl, capital, fee)

    rng = random.Random(seed)
    picks = {index for index in range(len(closes)) if rng.random() < entry_chance}
    random_curve, _ = _walk(closes, picks, exit_, tp, sl, capital, fee)

    hold = [
        capital * (value / first) if value else capital for value in closes
    ]

    wins = sum(1 for value in results if value > 0)
    return Report(capital, strategy, random_curve, hold, len(results), wins)
