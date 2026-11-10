"""Completion for the places a rule is typed: the code editor and the slots.

The vocabulary is the same one the tiles offer — the bar's own words and the
functions — plus the words the language joins them with (`and`, `or`, `not`).
A `QLineEdit` gets a plain `QCompleter`; the code editor is a `QPlainTextEdit`
subclass that gives itself one too, since Qt wires completers only for line
edits.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCompleter, QLineEdit, QPlainTextEdit

# The word under the cursor: a name, not a number.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")

KEYWORDS = ("and", "or", "not")


def vocabulary(fields, functions) -> list:
    """Names worth suggesting: the fields, the functions, the keywords."""
    words = [str(name) for name in fields]
    for name in sorted(functions):
        if name not in words:
            words.append(name)
    for word in KEYWORDS:
        if word not in words:
            words.append(word)
    return words


def attach_completer(edit: QLineEdit, words) -> QCompleter:
    """Give a line edit a popup completer. Returns it, for tests."""
    completer = QCompleter([str(word) for word in words], edit)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    popup = completer.popup()
    if popup is not None:
        popup.setObjectName("completionPopup")
    edit.setCompleter(completer)
    return completer


class CodeEdit(QPlainTextEdit):
    """The code editor, with a completion popup of the rule's vocabulary.

    Qt gives a text edit no completer, so this follows the usual recipe: it
    sets up a `QCompleter` over its own viewport and drives it from the key
    presses, offering the words that start with the one under the cursor.
    """

    def __init__(self, words, parent=None) -> None:
        super().__init__(parent)
        self._words = [str(word) for word in words]
        self.completer = QCompleter(self._words, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self.completer.activated.connect(self._insert)
        popup = self.completer.popup()
        if popup is not None:
            popup.setObjectName("completionPopup")

    # -- the word under the cursor -----------------------------------------

    def _prefix(self) -> str:
        cursor = self.textCursor()
        before = self.toPlainText()[: cursor.position()]
        match = _WORD.search(before)
        return match.group() if match is not None else ""

    def _insert(self, word: str) -> None:
        if not word:
            return
        cursor = self.textCursor()
        column = cursor.positionInBlock()
        before = cursor.block().text()[:column]
        match = _WORD.search(before)
        if match is not None:
            start = column - len(match.group())
            base = cursor.block().position()
            cursor.setPosition(base + start)
            cursor.setPosition(
                base + column, QTextCursor.MoveMode.KeepAnchor
            )
            cursor.removeSelectedText()
        cursor.insertText(word)
        self.setTextCursor(cursor)

    # -- the keys ----------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        popup = self.completer.popup()
        if popup.isVisible():
            if event.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Tab,
                Qt.Key.Key_Escape,
                Qt.Key.Key_Backtab,
            ):
                # Let the completer take it: it activated() the choice.
                event.ignore()
                return

        super().keyPressEvent(event)

        prefix = self._prefix()
        if len(prefix) < 1:
            popup.hide()
            return
        if prefix != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(prefix)
            self.completer.popup().setCurrentIndex(
                self.completer.completionModel().index(0, 0)
            )
        rect = self.cursorRect()
        rect.setWidth(
            self.completer.popup().sizeHintForColumn(0)
            + self.completer.popup().verticalScrollBar().sizeHint().width()
        )
        self.completer.complete(rect)


__all__ = [
    "KEYWORDS",
    "CodeEdit",
    "attach_completer",
    "vocabulary",
]
