"""Autofill: the words a rule may use, offered as you type."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from lalala.ui.autocomplete import (  # noqa: E402
    KEYWORDS,
    CodeEdit,
    attach_completer,
    vocabulary,
)
from lalala.engine.formula import ENTRY_FIELDS, FUNCTIONS  # noqa: E402
from lalala.ui.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_the_vocabulary_is_the_fields_the_functions_and_the_keywords() -> None:
    words = vocabulary(ENTRY_FIELDS, FUNCTIONS)
    assert "close" in words
    assert "volume" in words
    assert "sma" in words
    assert all(word in words for word in KEYWORDS)
    # No repeats, even where a name is both a field and a function.
    assert len(words) == len(set(words))


def test_a_line_edit_gets_a_completer(app: QApplication) -> None:
    edit = QLineEdit()
    completer = attach_completer(edit, ["close", "volume", "sma"])
    assert edit.completer() is completer

    completer.setCompletionPrefix("cl")
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "close"
    edit.deleteLater()


def test_the_code_edit_completes_the_word_under_the_cursor(
    app: QApplication,
) -> None:
    edit = CodeEdit(["close", "closed", "volume", "sma"])
    edit.setPlainText("clo")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    edit.completer.setCompletionPrefix(edit._prefix())

    assert edit._prefix() == "clo"
    model = edit.completer.completionModel()
    shown = [model.index(i, 0).data() for i in range(model.rowCount())]
    assert shown == ["close", "closed"]

    edit._insert("close")
    assert edit.toPlainText() == "close"
    edit.deleteLater()


def test_inserting_replaces_the_word_not_appends(app: QApplication) -> None:
    edit = CodeEdit(["volume"])
    edit.setPlainText("mid = sma(close, 20)\ncl")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    edit._insert("close")
    assert edit.toPlainText() == "mid = sma(close, 20)\nclose"
    edit.deleteLater()
