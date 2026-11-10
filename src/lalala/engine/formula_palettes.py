"""The formula builder's palettes: the sources you drag from.

Pure data and one classifier, split out of `formula_builder` so that module is
the widgets alone. The builder re-exports everything here, so
`from lalala.ui.strat.formula_builder import PALETTES` still works.
"""

from __future__ import annotations

from dataclasses import dataclass

from lalala.engine.formula import ENTRY_FIELDS, EXIT_FIELDS, FUNCTIONS

MIME = "application/x-lalala-chip"
HANDLE = "⠿"
LOGIC_WORDS = ("and", "or", "not")
# The palette groups, and the colour each of its blocks wears — so a block is
# coloured by where it sits, not by what it happens to hold.
GROUP_KEYS = {
    "Data": "data",
    "Indicators": "indicator",
    "Maths": "maths",
    "Logic": "logic",
    "Trade": "data",
}
# The maths functions: they live in Maths, so they wear its colour.
MATHS_FUNCS = frozenset({"abs", "log"})
# Names that read as "the bar" or "the trade": both are data, coloured alike.
DATA_NAMES = frozenset(ENTRY_FIELDS) | frozenset(EXIT_FIELDS)


@dataclass(frozen=True)
class Item:
    """One draggable source.

    A plain item drops the tokens it carries — a field, an operator, a number.
    A `call` item is an indicator: it drops as a single tile that knows its
    function, the series it reads and its own numbers.
    """

    label: str
    tokens: tuple = ()
    note: str = ""
    call: tuple | None = None  # (func, series, params, label)
    missing: bool = False      # named, but nothing here carries it


MATHS_ITEMS: tuple = (
    Item("+", ("+",)),
    Item("−", ("-",)),
    Item("×", ("*",)),
    Item("÷", ("/",)),
    Item("%", ("%",)),
    Item("^", ("^",)),
    Item("(", ("(",)),
    Item(")", (")",)),
    Item(",", (",",)),
    Item("=", ("=",), "assigns the line above to a name"),
    Item("<", ("<",)),
    Item("<=", ("<=",)),
    Item(">", (">",)),
    Item(">=", (">=",)),
    Item("==", ("==",)),
    Item("!=", ("!=",)),
    Item("abs", note="abs(close)", call=("abs", "close", (), "abs")),
    Item("log", note="log(close)", call=("log", "close", (), "log")),
)

LOGIC_ITEMS: tuple = (
    Item("AND", ("and",)),
    Item("OR", ("or",)),
    Item("NOT", ("not",)),
)


PALETTES: tuple = (
    (
        "Data",
        (
            Item("close", ("close",), "the bar's closing price"),
            Item("price", ("price",), "the market price — the bar's close"),
            Item("open", ("open",)),
            Item("high", ("high",)),
            Item("low", ("low",)),
            Item("volume", ("volume",)),
            Item("model_p", ("model_p",), "a model's probability — no history here",
                 missing=True),
            Item("spread", ("spread",), "the bid/ask spread — no history here",
                 missing=True),
            Item("liquidity", ("liquidity",), "book depth — no history here",
                 missing=True),
            Item("days_left", ("days_left",), "time to expiry — no history here",
                 missing=True),
        ),
    ),
    (
        "Indicators",
        (
            Item("SMA", note="sma(close, period)", call=("sma", "close", ("20",), "SMA")),
            Item("EMA", note="ema(close, period)", call=("ema", "close", ("20",), "EMA")),
            Item("RSI", note="rsi(close, period)", call=("rsi", "close", ("14",), "RSI")),
            Item("Highest", note="highest(high, period)", call=("highest", "high", ("20",), "Highest")),
            Item("Lowest", note="lowest(low, period)", call=("lowest", "low", ("20",), "Lowest")),
            Item("Change", note="change(close, bars)", call=("change", "close", ("1",), "Change")),
            Item("Shift", note="shift(close, bars)", call=("shift", "close", ("1",), "Shift")),
            Item("Boll low", note="bollinger_lower(close, period, dev)", call=("bollinger_lower", "close", ("20", "2"), "Boll low")),
            Item("Boll mid", note="bollinger_middle(close, period, dev)", call=("bollinger_middle", "close", ("20", "2"), "Boll mid")),
            Item("Boll up", note="bollinger_upper(close, period, dev)", call=("bollinger_upper", "close", ("20", "2"), "Boll up")),
            Item("σ", note="stdev(close, period)", call=("stdev", "close", ("20",), "σ")),
            Item("zscore", note="zscore(close, period)", call=("zscore", "close", ("20",), "zscore")),
        ),
    ),
    ("Maths", MATHS_ITEMS),
    ("Logic", LOGIC_ITEMS),
)

# An exit rule sees the open trade, not the bar, and takes no indicators.
EXIT_PALETTES: tuple = (
    (
        "Trade",
        (
            Item("price", ("price",), "the close while the trade is open"),
            Item("entry", ("entry",), "the price the trade was opened at"),
            Item("PNL", ("pnl",), "the open trade's profit or loss, in %"),
            Item("TP", ("tp",), "the take-profit threshold, in %"),
            Item("SL", ("sl",), "the stop-loss threshold, in %"),
            Item("bars", ("bars",), "bars the trade has been open"),
        ),
    ),
    ("Maths", MATHS_ITEMS),
    ("Logic", LOGIC_ITEMS),
)


def group_for_token(token) -> str:
    """Which colour a chip wears: data, indicator, logic or maths."""
    if token in (None, ""):
        return ""
    if token in DATA_NAMES:
        return "data"
    if token in FUNCTIONS:
        return "indicator"
    if token in LOGIC_WORDS:
        return "logic"
    return "maths"


__all__ = [
    "DATA_NAMES",
    "EXIT_PALETTES",
    "GROUP_KEYS",
    "HANDLE",
    "Item",
    "LOGIC_ITEMS",
    "LOGIC_WORDS",
    "MATHS_FUNCS",
    "MATHS_ITEMS",
    "MIME",
    "PALETTES",
    "group_for_token",
]
