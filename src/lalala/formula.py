"""A small formula language for entry and exit rules. No Qt, no candle data.

A formula is a list of lines. All but the last define named series; the last is
the condition, evaluated on each bar:

    mid = sma(close, 20)
    close < bollinger_lower(close, 20, 2) and volume > 2 * sma(volume, 50)

The names are the bar's own fields — `open`, `high`, `low`, `close`, `volume` —
plus anything a line above defined. Values are series: every expression is a
number per bar, and the condition is a truth per bar.

Operators, loosest first: `or`, `and`, `not`, the comparisons
(`< <= > >= == !=`), then `+ -`, `* / %`, a right-associative `^`, and a unary
minus. Parentheses group. `#` starts a comment.

This module only parses and checks a formula. It says whether the syntax is
sound, whether every name is known and every function is called with the right
number of arguments. It does not evaluate anything, and it does not know what a
series looks like — that is the walk's job, later.

Errors carry a line and column so the editor can point at the character:

    line 2, column 9: unknown name 'clsoe'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "FIELDS",
    "FUNCTIONS",
    "HINT",
    "Assignment",
    "Binary",
    "Call",
    "Formula",
    "FormulaError",
    "Name",
    "Number",
    "Token",
    "Unary",
    "parse",
    "scan",
    "tokens_to_text",
]

# The fields every bar carries.
FIELDS = ("open", "high", "low", "close", "volume")

# name -> (min arguments, max arguments). A `series` argument is any
# expression; a period is a number of bars.
FUNCTIONS: dict[str, tuple[int, int]] = {
    "abs": (1, 1),
    "sqrt": (1, 1),
    "min": (2, 2),
    "max": (2, 2),
    "sma": (2, 2),          # sma(series, period)
    "ema": (2, 2),          # ema(series, period)
    "rsi": (2, 2),          # rsi(series, period)
    "highest": (2, 2),      # highest(series, period)
    "lowest": (2, 2),       # lowest(series, period)
    "change": (2, 2),       # change(series, bars)
    "shift": (2, 2),        # shift(series, bars)
    "bollinger_lower": (3, 3),   # bollinger_lower(series, period, deviations)
    "bollinger_middle": (3, 3),
    "bollinger_upper": (3, 3),
}

# A one-line crib the editor can show under the text.
HINT = (
    "fields: open high low close volume  ·  "
    "functions: sma ema rsi highest lowest change shift "
    "bollinger_lower bollinger_middle bollinger_upper abs min max sqrt  ·  "
    "one condition, optionally after `name = …` lines"
)

_COMPARISONS = ("<=", ">=", "==", "!=", "<", ">")
_KEYWORDS = ("and", "or", "not")


class FormulaError(Exception):
    """A formula that does not parse, or does not check out."""

    def __init__(self, message: str, line: int = 1, column: int = 1) -> None:
        self.message = message
        self.line = max(1, int(line))
        self.column = max(1, int(column))
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"line {self.line}, column {self.column}: {self.message}"


# -- the tree ---------------------------------------------------------------


@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class Name:
    name: str
    # Where it appeared, for error messages. Not part of equality: two parsed
    # trees should compare equal on their shape, not on their coordinates.
    line: int = field(default=1, compare=False, repr=False)
    column: int = field(default=1, compare=False, repr=False)


@dataclass(frozen=True)
class Call:
    func: str
    args: tuple
    line: int = field(default=1, compare=False, repr=False)
    column: int = field(default=1, compare=False, repr=False)


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Assignment:
    name: str
    value: object
    line: int = field(default=1, compare=False, repr=False)
    column: int = field(default=1, compare=False, repr=False)


@dataclass(frozen=True)
class Formula:
    """A parsed, checked formula: named series, then the condition."""

    source: str = ""
    assignments: tuple = ()
    condition: object | None = None

    @property
    def empty(self) -> bool:
        return self.condition is None and not self.assignments

    @property
    def series_names(self) -> tuple:
        return tuple(assignment.name for assignment in self.assignments)


# -- the scanner ------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str  # "number" | "name" | "op" | "newline"
    text: str
    pos: int
    line: int
    column: int


_TOKEN = re.compile(
    r"(?P<space>[ \t\f\v]+)"
    r"|(?P<comment>\#[^\n]*)"
    r"|(?P<newline>\r\n|\r|\n|;)"
    r"|(?P<number>\d+\.\d*|\.\d+|\d+)"
    r"|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<op><=|>=|==|!=|<|>|\+|-|\*|/|%|\^|=|\(|\)|,)"
)


def _linecol(text: str, pos: int) -> tuple[int, int]:
    line = text.count("\n", 0, pos) + 1
    column = pos - text.rfind("\n", 0, pos)
    return line, column


def scan(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    for match in _TOKEN.finditer(text):
        if match.start() != pos:
            line, column = _linecol(text, pos)
            raise FormulaError(
                f"unexpected character {text[pos]!r}", line, column
            )
        pos = match.end()
        if match.lastgroup in ("space", "comment"):
            continue
        line, column = _linecol(text, match.start())
        tokens.append(
            Token(match.lastgroup, match.group(), match.start(), line, column)
        )
    if pos != len(text):
        line, column = _linecol(text, pos)
        raise FormulaError(f"unexpected character {text[pos]!r}", line, column)
    return tokens


# -- the parser -------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: list[Token], text: str) -> None:
        self.tokens = tokens
        self.text = text
        self.i = 0

    # -- cursor ------------------------------------------------------------

    def _peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _next(self) -> Token | None:
        tok = self._peek()
        if tok is not None:
            self.i += 1
        return tok

    def _end(self) -> tuple[int, int]:
        return _linecol(self.text, len(self.text))

    def _failure(self, message: str) -> FormulaError:
        tok = self._peek()
        if tok is None:
            line, column = self._end()
        else:
            line, column = tok.line, tok.column
        return FormulaError(message, line, column)

    def _is_keyword(self, word: str) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == "name" and tok.text == word

    def _is_op(self, text: str) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == "op" and tok.text == text

    def _expect_op(self, text: str) -> Token:
        if not self._is_op(text):
            raise self._failure(f"expected {text!r}")
        return self._next()

    # -- grammar -----------------------------------------------------------

    def program(self) -> tuple[list, list]:
        statements: list[tuple[Token, object]] = []
        while self._peek() is not None:
            if self._peek().kind == "newline":
                self._next()
                continue
            statements.append(self.statement())
            # A statement ends at a newline: two expressions on one line mean
            # an operator (or a newline) is missing.
            tok = self._peek()
            if tok is not None and tok.kind != "newline":
                raise self._failure(
                    f"unexpected {tok.text!r} — expected an operator or a "
                    "new line"
                )
        return statements

    def statement(self) -> tuple[Token, object]:
        first = self._peek()
        node = self.expression()
        # `name = expr` is the only assignment shape.
        if isinstance(node, Name) and self._is_op("="):
            self._next()
            value = self.expression()
            node = Assignment(
                node.name, value, line=first.line, column=first.column
            )
        return first, node

    def expression(self) -> object:
        return self.or_expr()

    def or_expr(self) -> object:
        node = self.and_expr()
        while self._is_keyword("or"):
            self._next()
            node = Binary("or", node, self.and_expr())
        return node

    def and_expr(self) -> object:
        node = self.not_expr()
        while self._is_keyword("and"):
            self._next()
            node = Binary("and", node, self.not_expr())
        return node

    def not_expr(self) -> object:
        if self._is_keyword("not"):
            self._next()
            return Unary("not", self.not_expr())
        return self.comparison()

    def comparison(self) -> object:
        node = self.additive()
        tok = self._peek()
        if tok is not None and tok.kind == "op" and tok.text in _COMPARISONS:
            self._next()
            return Binary(tok.text, node, self.additive())
        return node

    def additive(self) -> object:
        node = self.multiplicative()
        while self._peek() is not None and self._peek().kind == "op" and (
            self._peek().text in ("+", "-")
        ):
            op = self._next().text
            node = Binary(op, node, self.multiplicative())
        return node

    def multiplicative(self) -> object:
        node = self.unary()
        while self._peek() is not None and self._peek().kind == "op" and (
            self._peek().text in ("*", "/", "%")
        ):
            op = self._next().text
            node = Binary(op, node, self.unary())
        return node

    def unary(self) -> object:
        if self._is_op("-"):
            self._next()
            return Unary("-", self.unary())
        if self._is_op("+"):
            self._next()
            return self.unary()
        return self.power()

    def power(self) -> object:
        node = self.primary()
        if self._is_op("^"):
            self._next()
            return Binary("^", node, self.unary())
        return node

    def primary(self) -> object:
        tok = self._peek()
        if tok is None:
            raise self._failure("unexpected end of formula")
        if tok.kind == "number":
            self._next()
            return Number(float(tok.text))
        if tok.kind == "name":
            self._next()
            if tok.text in _KEYWORDS:
                raise FormulaError(
                    f"{tok.text!r} cannot be used as a name",
                    tok.line,
                    tok.column,
                )
            if self._is_op("("):
                return self.call(tok)
            return Name(tok.text, line=tok.line, column=tok.column)
        if tok.kind == "op" and tok.text == "(":
            self._next()
            node = self.expression()
            self._expect_op(")")
            return node
        raise FormulaError(
            f"unexpected {tok.text!r}", tok.line, tok.column
        )

    def call(self, name_tok: Token) -> object:
        self._expect_op("(")
        args: list = []
        if not self._is_op(")"):
            args.append(self.expression())
            while self._is_op(","):
                self._next()
                args.append(self.expression())
        self._expect_op(")")
        return Call(
            name_tok.text,
            tuple(args),
            line=name_tok.line,
            column=name_tok.column,
        )


# -- the checks -------------------------------------------------------------


def _check(node: object, scope: set[str]) -> None:
    if isinstance(node, Number):
        return
    if isinstance(node, Name):
        if node.name in scope:
            return
        if node.name in FUNCTIONS:
            raise FormulaError(
                f"{node.name!r} is a function — call it, e.g. "
                f"{node.name}(close, 20)",
                node.line,
                node.column,
            )
        raise FormulaError(f"unknown name {node.name!r}", node.line, node.column)
    if isinstance(node, Call):
        if node.func not in FUNCTIONS:
            hint = ""
            if node.func in FIELDS:
                hint = f" — {node.func!r} is a field, not a function"
            raise FormulaError(
                f"unknown function {node.func!r}{hint}", node.line, node.column
            )
        low, high = FUNCTIONS[node.func]
        count = len(node.args)
        if not low <= count <= high:
            wanted = f"{low}" if low == high else f"{low} to {high}"
            raise FormulaError(
                f"{node.func}() takes {wanted} argument(s), got {count}",
                node.line,
                node.column,
            )
        for arg in node.args:
            _check(arg, scope)
        return
    if isinstance(node, Unary):
        _check(node.operand, scope)
        return
    if isinstance(node, Binary):
        _check(node.left, scope)
        _check(node.right, scope)
        return
    if isinstance(node, Assignment):
        _check(node.value, scope)
        return
    raise FormulaError("internal: unknown node")  # pragma: no cover


def _validate(formula: Formula) -> None:
    scope: set[str] = set(FIELDS)
    for assignment in formula.assignments:
        if assignment.name in FIELDS:
            raise FormulaError(
                f"{assignment.name!r} is a field and cannot be reassigned",
                assignment.line,
                assignment.column,
            )
        if assignment.name in FUNCTIONS:
            raise FormulaError(
                f"{assignment.name!r} is a function and cannot be a name",
                assignment.line,
                assignment.column,
            )
        if assignment.name in scope:
            raise FormulaError(
                f"{assignment.name!r} is already defined",
                assignment.line,
                assignment.column,
            )
        _check(assignment.value, scope)
        scope.add(assignment.name)
    if formula.condition is not None:
        _check(formula.condition, scope)


def parse(text: str) -> Formula:
    """Parse and check `text`. Raises `FormulaError` if it does not hold up."""
    tokens = scan(text)
    parser = _Parser(tokens, text)
    statements = parser.program()
    if not statements:
        return Formula()

    heads, last = statements[:-1], statements[-1]
    assignments: list[Assignment] = []
    for tok, node in heads:
        if not isinstance(node, Assignment):
            raise FormulaError(
                "only the last line can be the condition", tok.line, tok.column
            )
        assignments.append(node)

    last_tok, last_node = last
    if isinstance(last_node, Assignment):
        raise FormulaError(
            "the last line must be the condition, not an assignment",
            last_tok.line,
            last_tok.column,
        )

    formula = Formula(
        source=text, assignments=tuple(assignments), condition=last_node
    )
    _validate(formula)
    return formula


def tokens_to_text(tokens) -> str:
    """Join chip tokens back into formula text.

    A `None` token is an unfilled slot and contributes nothing, so the text
    will not parse until it is filled. Spacing is tidied so the result reads
    like the formula was typed: no gap inside `f(x)`, one after a comma.
    """
    parts = [str(token) for token in tokens if token not in (None, "")]
    text = " ".join(parts)
    text = text.replace("( ", "(").replace(" )", ")").replace(" ,", ",")
    text = text.replace(" (", "(")
    text = text.replace(",", ", ")
    return re.sub(r"[ \t]+", " ", text).strip()
