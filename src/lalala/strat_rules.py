"""One rules tile: a title with Formulas/Code tabs over a single formula.

Both the entry tile and the exit tile are one of these. Each owns its own
formula and its own drag-and-drop builder; nothing is shared between them.

**Formulas** is the drag-and-drop builder. **Code** is the same formula as
text: it is filled from the tiles, and it can be typed in directly. Whatever
is written there is scanned, checked and rebuilt into tiles, so the two views
never disagree. A line the language cannot even read — a stray character — is
**refused**: the previous code is put back and the reason is shown, rather than
leaving the two views out of step.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import mono_font
from lalala.formula import FormulaError
from lalala.formula_builder import FormulaBuilder
from lalala.panels import Card

# The two ways a rule can be written, in the order they appear.
RULES_MODES = (("formulas", "Formulas"), ("code", "Code"))


class PageStack(QStackedWidget):
    """A stack of pages whose size hints follow the page on show.

    A plain `QStackedWidget` reports the largest hint over *all* its pages
    whether or not they are visible, so the tall formula page would inflate
    the tile's minimum while the code page was the one on screen.
    """

    def _current(self):
        widget = self.currentWidget()
        return widget if widget is not None else None

    def minimumSizeHint(self):  # noqa: N802
        current = self._current()
        return (
            current.minimumSizeHint()
            if current is not None
            else super().minimumSizeHint()
        )

    def sizeHint(self):  # noqa: N802
        current = self._current()
        return current.sizeHint() if current is not None else super().sizeHint()


class RulesTile(Card):
    """A titled tile holding one formula, written with tiles or as code."""

    changed = Signal()
    mode_changed = Signal(str)

    def __init__(self, title: str = "ENTRY RULES", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        self.title = QLabel(title, self)
        self.title.setObjectName("tileTitle")
        header.addWidget(self.title)
        header.addStretch(1)

        self.modes = QButtonGroup(self)
        self.modes.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for index, (key, label) in enumerate(RULES_MODES):
            button = QPushButton(label, self)
            button.setObjectName("modeButton")
            button.setProperty("mode", key)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.modes.addButton(button, index)
            self.mode_buttons[key] = button
            header.addWidget(button)
        self.modes.idClicked.connect(self._pick_mode)
        self.body.addLayout(header)

        # One page per mode; both edit the one formula.
        self.pages = PageStack(self)
        self.pages.setObjectName("entryPages")
        self.pages.addWidget(self._formula_page())
        self.pages.addWidget(self._code_page())
        self.body.addWidget(self.pages, 1)
        self.pages.setCurrentIndex(0)
        self.pages.currentChanged.connect(self._pages_changed)

        # The synchronisation guard and the last code that was accepted.
        self._syncing = False
        self._accepted = ""

    # -- the pages ---------------------------------------------------------

    def _formula_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.formula = FormulaBuilder(page)
        self.formula.changed.connect(self._formula_changed)
        layout.addWidget(self.formula, 1)
        return page

    def _code_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.code_edit = QPlainTextEdit(page)
        self.code_edit.setObjectName("codeEdit")
        self.code_edit.setFont(mono_font(9))
        self.code_edit.setTabChangesFocus(True)
        self.code_edit.setMinimumHeight(96)
        self.code_edit.setPlaceholderText("mid = sma(close, 20)\nclose < mid")
        self.code_edit.setToolTip(
            "one condition, optionally after `name = …` lines"
        )
        self.code_edit.textChanged.connect(self._code_edited)

        self.code_error = QLabel("", page)
        self.code_error.setObjectName("formulaError")
        self.code_error.setWordWrap(True)
        self.code_note = QLabel(
            "the code the tiles stand for — edit it and the tiles follow", page
        )
        self.code_note.setObjectName("hintLabel")
        self.code_note.setWordWrap(True)

        layout.addWidget(self.code_edit, 1)
        layout.addWidget(self.code_error)
        layout.addWidget(self.code_note)
        return page

    # -- mode --------------------------------------------------------------

    def mode(self) -> str:
        for index, (key, _) in enumerate(RULES_MODES):
            button = self.modes.button(index)
            if button is not None and button.isChecked():
                return key
        return RULES_MODES[0][0]

    def set_mode(self, mode: str) -> None:
        for index, (key, _) in enumerate(RULES_MODES):
            if key == mode:
                self.modes.button(index).setChecked(True)
                self._pick_mode(index)
                return

    def _pick_mode(self, index: int) -> None:
        if not 0 <= index < len(RULES_MODES):
            return
        self.pages.setCurrentIndex(index)
        mode = RULES_MODES[index][0]
        if mode == "formulas":
            self.formula.number_edit.setFocus()
        elif mode == "code":
            self._sync_code()
            self.code_edit.setFocus()
        self.mode_changed.emit(mode)

    def _pages_changed(self) -> None:
        self.pages.updateGeometry()
        self.updateGeometry()

    # -- the formula -------------------------------------------------------

    def text(self) -> str:
        """The formula the tiles add up to."""
        return self.formula.formula_text()

    def set_text(self, text: str) -> None:
        self.formula.set_formula(text)
        self._sync_code()

    def error(self) -> str:
        """The checker's message, or "" when the formula is fine."""
        return self.formula.error()

    def parsed(self):
        """The parsed formula, or None while it is empty or invalid."""
        return self.formula.parsed()

    def code(self) -> str:
        return self.code_edit.toPlainText()

    def set_code(self, text: str) -> None:
        self.code_edit.setPlainText(text)

    def _formula_changed(self) -> None:
        self.changed.emit()
        self._sync_code()

    def _code_edited(self) -> None:
        """The code was typed in; rebuild the tiles to match."""
        if self._syncing:
            return
        text = self.code_edit.toPlainText()
        self._syncing = True
        try:
            self.formula.set_formula(text)
        except FormulaError as exc:
            # The language cannot read this at all. Refuse it: put the last
            # good code back, so the tiles and the code stay in step.
            self._syncing = False
            self._refuse(str(exc))
            return
        self._syncing = False
        self._accepted = text
        self.code_error.setText(self.formula.error())

    def _refuse(self, message: str) -> None:
        self._syncing = True
        self.code_edit.setPlainText(self._accepted)
        self._syncing = False
        self.code_error.setText(f"refused — {message}")

    def _sync_code(self) -> None:
        """Show the builder's text in the code view, and its verdict."""
        if self._syncing:
            return
        text = self.formula.formula_text()
        if self.code_edit.toPlainText() != text:
            self._syncing = True
            self.code_edit.setPlainText(text)
            self._syncing = False
        self._accepted = text
        self.code_error.setText(self.formula.error())


__all__ = ["RULES_MODES", "PageStack", "RulesTile"]
