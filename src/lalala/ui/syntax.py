"""Syntax colours for the Code tab, matched to the tiles' groups.

Keywords wear the amber of the Logic/palette accent, function names the
green of the Logic group, the bar's own words an indigo, numbers a cyan, and
a `#` comment fades out. The vocabulary comes from the tile, so the entry and
exit editors colour their own words.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from lalala.ui.theme import ACCENT, TEXT_FAINT

# The words the language joins with, and the shapes of the other tokens.
KEYWORDS = ("and", "or", "not")
_WORD = QRegularExpression(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = QRegularExpression(r"\d+(?:\.\d+)?")
_COMMENT = QRegularExpression(r"#[^\n]*")
_ASSIGN = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=", re.MULTILINE)

FUNCTION_COLOR = "#5fe39a"
FIELD_COLOR = "#9db4ff"
NUMBER_COLOR = "#6fd6e6"
VARIABLE_COLOR = "#ef8fc0"


def defined_names(text: str) -> list:
    """The names `text` assigns to, in order, for the variable colour."""
    names: list[str] = []
    for match in _ASSIGN.finditer(text):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names


def _format(color: str, bold: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.DemiBold)
    return fmt


class FormulaHighlighter(QSyntaxHighlighter):
    """Colour a formula's code: keywords, functions, words and numbers."""

    def __init__(self, document, fields=(), functions=()) -> None:
        super().__init__(document)
        self.fields = {str(name) for name in fields}
        self.functions = {str(name) for name in functions}
        self.defined: set[str] = set()
        self._keyword = _format(ACCENT, bold=True)
        self._function = _format(FUNCTION_COLOR)
        self._field = _format(FIELD_COLOR)
        self._variable = _format(VARIABLE_COLOR)
        self._number = _format(NUMBER_COLOR)
        self._comment = _format(TEXT_FAINT)
        self._word = _WORD
        self._number_re = _NUMBER
        self._comment_re = _COMMENT

    def set_defined(self, names) -> None:
        """The names the code defines, coloured like the variable chips."""
        names = {str(name) for name in names}
        if names == self.defined:
            return
        self.defined = names
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        # Numbers first, then words, then the comment over everything.
        iterator = self._number_re.globalMatch(text)
        while iterator.hasNext():
            match = iterator.next()
            self.setFormat(
                match.capturedStart(), match.capturedLength(), self._number
            )

        iterator = self._word.globalMatch(text)
        while iterator.hasNext():
            match = iterator.next()
            word = match.captured()
            if word in self.functions:
                fmt = self._function
            elif word in KEYWORDS:
                fmt = self._keyword
            elif word in self.defined:
                fmt = self._variable
            elif word in self.fields:
                fmt = self._field
            else:
                continue
            self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

        iterator = self._comment_re.globalMatch(text)
        while iterator.hasNext():
            match = iterator.next()
            self.setFormat(
                match.capturedStart(), match.capturedLength(), self._comment
            )


__all__ = [
    "FIELD_COLOR",
    "FUNCTION_COLOR",
    "KEYWORDS",
    "NUMBER_COLOR",
    "VARIABLE_COLOR",
    "FormulaHighlighter",
    "defined_names",
]
