"""Completion for the places a rule is typed: the code editor and the slots.

The vocabulary is the same one the tiles offer — the bar's own words and the
functions — plus the words the language joins them with (`and`, `or`, `not`).
A `QLineEdit` gets a plain `QCompleter`; a `QPlainTextEdit` gets a small popup
of its own, since Qt gives text edits no completer.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCompleter, QLineEdit, QListWidget

# The word under the cursor, for the text-edit popup: a name, not a number.
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


class TextEditCompleter(QObject):
    """A completion popup for a `QPlainTextEdit`.

    Qt has no completer for text edits, so this watches the editor's keys: it
    offers the words that start with the one under the cursor, and inserts the
    chosen one where that word was.
    """

    def __init__(self, edit, words) -> None:
        super().__init__(edit)
        self.edit = edit
        self.words = [str(word) for word in words]
        self.popup = QListWidget(edit)
        self.popup.setObjectName("completionPopup")
        self.popup.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup.itemClicked.connect(lambda item: self.insert(item.text()))
        edit.installEventFilter(self)

    # -- the keys ----------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is not self.edit:
            return super().eventFilter(obj, event)
        kind = event.type()

        if kind == QEvent.Type.FocusOut:
            self.popup.hide()
            return False

        if kind != QEvent.Type.KeyPress:
            return False

        key = event.key()
        if self.popup.isVisible():
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                item = self.popup.currentItem()
                if item is not None:
                    self.insert(item.text())
                    return True
            if key == Qt.Key.Key_Escape:
                self.popup.hide()
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                step = -1 if key == Qt.Key.Key_Up else 1
                row = self.popup.currentRow() + step
                row = max(0, min(row, self.popup.count() - 1))
                self.popup.setCurrentRow(row)
                return True

        # The key itself is handled by the editor; refresh once it has been.
        QTimer.singleShot(0, self.refresh)
        return False

    # -- the popup ---------------------------------------------------------

    def refresh(self) -> None:
        cursor = self.edit.textCursor()
        before = self.edit.toPlainText()[: cursor.position()]
        match = _WORD.search(before)
        if match is None:
            self.popup.hide()
            return
        prefix = match.group()
        items = [
            word
            for word in self.words
            if word.lower().startswith(prefix.lower()) and word != prefix
        ]
        if not items:
            self.popup.hide()
            return
        self.popup.clear()
        self.popup.addItems(items)
        self.popup.setCurrentRow(0)
        rect = self.edit.cursorRect()
        self.popup.move(self.edit.viewport().mapToGlobal(rect.bottomLeft()))
        self.popup.show()

    def insert(self, word: str) -> None:
        cursor = self.edit.textCursor()
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
        self.edit.setTextCursor(cursor)
        self.popup.hide()
        self.edit.setFocus()


__all__ = [
    "KEYWORDS",
    "TextEditCompleter",
    "attach_completer",
    "vocabulary",
]
