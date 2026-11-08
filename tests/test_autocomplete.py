"""Autofill: the words a rule may use, offered as you type."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit  # noqa: E402

from lalala.autocomplete import (  # noqa: E402
    KEYWORDS,
    TextEditCompleter,
    attach_completer,
    vocabulary,
)
from lalala.formula import ENTRY_FIELDS, FUNCTIONS  # noqa: E402
from lalala.theme import apply_dark_theme  # noqa: E402


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

    edit.setText("cl")
    completer.setCompletionPrefix("cl")
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "close"
    edit.deleteLater()


def test_the_text_edit_popup_offers_the_word_under_the_cursor(
    app: QApplication,
) -> None:
    edit = QPlainTextEdit()
    edit.resize(200, 80)
    completer = TextEditCompleter(edit, ["close", "closed", "volume", "sma"])
    edit.setPlainText("clo")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    completer.refresh()
    assert completer.popup.isVisible()
    assert [completer.popup.item(i).text() for i in range(completer.popup.count())] == [
        "close",
        "closed",
    ]

    completer.insert("close")
    assert edit.toPlainText() == "close"
    assert not completer.popup.isVisible()
    edit.deleteLater()


def test_the_text_edit_popup_stays_quiet_without_a_word(
    app: QApplication,
) -> None:
    edit = QPlainTextEdit()
    completer = TextEditCompleter(edit, ["close", "volume"])
    edit.setPlainText("12 + ")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    completer.refresh()
    assert not completer.popup.isVisible()
    edit.deleteLater()
