"""The Code tab's syntax colours."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QTextDocument  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.engine.formula import ENTRY_FIELDS, FUNCTIONS  # noqa: E402
from lalala.ui.syntax import FormulaHighlighter, defined_names  # noqa: E402
from lalala.ui.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_defined_names_reads_the_assignments() -> None:
    text = "band = bollinger_lower(close, 20, 2)\nclose < band and edge > 0"
    assert defined_names(text) == ["band"]


def _runs(document: QTextDocument) -> dict[str, str]:
    """Every coloured run, as word -> colour name."""
    runs: dict[str, str] = {}
    block = document.firstBlock()
    while block.isValid():
        text = block.text()
        for run in block.layout().formats():
            word = text[run.start : run.start + run.length]
            runs[word] = run.format.foreground().color().name()
        block = block.next()
    return runs


def test_the_highlighter_colours_each_kind(app: QApplication) -> None:
    document = QTextDocument()
    document.setPlainText("band = sma(close, 20)\nclose < band and not volume")
    highlighter = FormulaHighlighter(document, ENTRY_FIELDS, FUNCTIONS)
    highlighter.set_defined(["band"])
    highlighter.rehighlight()

    runs = _runs(document)
    assert runs["sma"] == "#5fe39a"      # a function
    assert runs["close"] == "#9db4ff"    # a field
    assert runs["band"] == "#ef8fc0"     # a defined name
    assert runs["and"] == "#e0b341"      # a keyword
    assert runs["20"] == "#6fd6e6"       # a number
