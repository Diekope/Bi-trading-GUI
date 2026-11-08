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
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import mono_font
from lalala.formula import (
    ENTRY_FIELDS,
    EXIT_FIELDS,
    EXIT_FUNCTIONS,
    FIELDS,
    FIELD_NOTES,
    FUNCTIONS,
    FUNCTION_NOTES,
    FormulaError,
)
from lalala.formula_builder import (
    EXIT_PALETTES,
    PALETTES,
    FlowHolder,
    FormulaBuilder,
)
from lalala.panels import Card
from lalala.strat_conditions import RulesPage

# The three ways a rule can be reached, in the order they appear: the grouped
# conditions, the drag-and-drop tiles, or the code.
RULES_MODES = (
    ("rules", "Rules"),
    ("formula", "Formula"),
    ("code", "Code"),
)


class PageStack(QStackedWidget):
    """A stack of pages whose size hints follow the page on show.

    A plain `QStackedWidget` reports the largest hint over *all* its pages
    whether or not they are visible, so a tall page would inflate the tile's
    minimum while a shorter one was the one on screen.
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


class VariableRow(QFrame):
    """One word in the vocabulary: its name, its kind, and a click."""

    clicked = Signal(str)

    def __init__(self, name: str, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.setObjectName("valueRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selectable", True)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"select {name} to see what it is")

        line = QHBoxLayout(self)
        line.setContentsMargins(2, 2, 2, 2)
        line.setSpacing(6)
        key = QLabel(name, self)
        key.setObjectName("valueKey")
        shown = QLabel(kind, self)
        shown.setObjectName("groupLabel")
        line.addWidget(key, 1)
        line.addWidget(shown)

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)


class RulesTile(Card):
    """A titled tile holding one formula, written with tiles or as code."""

    changed = Signal()
    mode_changed = Signal(str)

    def __init__(
        self,
        title: str = "ENTRY RULES",
        parent: QWidget | None = None,
        palettes: tuple | None = None,
        fields: tuple = ENTRY_FIELDS,
        functions: dict | None = None,
        placeholder: str = "mid = sma(close, 20)\nclose < mid",
        header: bool = True,
        condition_label: str = "BUY WHEN",
    ) -> None:
        super().__init__(parent)
        self.palettes = PALETTES if palettes is None else palettes
        self.fields = tuple(fields)
        self.functions = FUNCTIONS if functions is None else functions
        self.placeholder = placeholder
        self.condition_label = condition_label

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        self.title = QLabel(title, self)
        self.title.setObjectName("tileTitle")
        header_row.addWidget(self.title)
        header_row.addStretch(1)

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
            header_row.addWidget(button)
        self.modes.idClicked.connect(self._pick_mode)
        if header:
            self.body.addLayout(header_row)
        else:
            # The tile is inset in a switcher that owns the header: the title
            # and the pills are not shown here, but the group still drives
            # `mode()` and `set_mode()`.
            self.title.hide()
            for button in self.mode_buttons.values():
                button.hide()

        # One page per mode: the grouped conditions, the tiles, and the code.
        # All three reach the same formula.
        self.pages = PageStack(self)
        self.pages.setObjectName("entryPages")
        self.conditions = RulesPage(
            fields=self.fields,
            functions=self.functions,
            condition_label=self.condition_label,
        )
        self.conditions.changed.connect(self._conditions_changed)
        self.pages.addWidget(self.conditions)
        self.pages.addWidget(self._formula_page())
        self.pages.addWidget(self._code_page())
        self.body.addWidget(self.pages, 1)
        self.pages.setCurrentIndex(0)
        self.pages.currentChanged.connect(self._pages_changed)

        # The synchronisation guard and the last code that was accepted.
        self._syncing = False
        self._accepted = ""
        self._last_result = None

    # -- the pages ---------------------------------------------------------

    def _scroll_page(self, content: QWidget) -> QWidget:
        """Wrap a page's content so it scrolls instead of growing the tile."""
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        scroll = QScrollArea(page)
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        return page

    def _formula_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.formula = FormulaBuilder(
            page, palettes=self.palettes, fields=self.fields,
            functions=self.functions, condition_label=self.condition_label,
        )
        self.formula.changed.connect(self._formula_changed)
        return self._scroll_page(self.formula)

    def _code_page(self) -> QWidget:
        """The code on the left, its vocabulary and its values on the right."""
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # The code itself, in a card, taking the width the right rail leaves.
        code_card = QFrame(page)
        code_card.setObjectName("formulaCard")
        code_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        code_layout = QVBoxLayout(code_card)
        code_layout.setContentsMargins(10, 8, 10, 8)
        code_layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel("formula.txt", code_card)
        title.setObjectName("panelTitle")
        head.addWidget(title)
        head.addStretch(1)
        note = QLabel("the code the tiles stand for — editable", code_card)
        note.setObjectName("groupLabel")
        head.addWidget(note)
        code_layout.addLayout(head)

        self.code_edit = QPlainTextEdit(code_card)
        self.code_edit.setObjectName("codeEdit")
        self.code_edit.setFont(mono_font(9))
        self.code_edit.setTabChangesFocus(True)
        self.code_edit.setPlaceholderText(self.placeholder)
        self.code_edit.setToolTip(
            "one condition, optionally after `name = …` lines"
        )
        self.code_edit.textChanged.connect(self._code_edited)
        code_layout.addWidget(self.code_edit, 1)

        self.code_error = QLabel("", code_card)
        self.code_error.setObjectName("formulaError")
        self.code_error.setWordWrap(True)
        self.code_note = QLabel(
            "edit it and the tiles follow; a line the language cannot read is "
            "refused",
            code_card,
        )
        self.code_note.setObjectName("hintLabel")
        self.code_note.setWordWrap(True)
        code_layout.addWidget(self.code_error)
        code_layout.addWidget(self.code_note)
        layout.addWidget(code_card, 1)

        # The right rail: the vocabulary over the values, as in the mock.
        # Each list scrolls in place, so the code beside them stays put.
        rail = QWidget(page)
        rail.setObjectName("codeRail")
        rail.setFixedWidth(250)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(8)

        vocab, vocab_scroll = self._list_card(rail, "VARIABLES", bar=False)
        self.vocab_card = vocab
        self.selected_variable: str | None = None
        self.vocab_rows: dict[str, VariableRow] = {}
        vocab_inner = QWidget()
        vocab_inner.setObjectName("listInner")
        vocab_layout = QVBoxLayout(vocab_inner)
        vocab_layout.setContentsMargins(0, 0, 0, 0)
        vocab_layout.setSpacing(0)
        for name in self.fields:
            row = VariableRow(name, "float", vocab_inner)
            row.clicked.connect(self._select_variable)
            self.vocab_rows[name] = row
            vocab_layout.addWidget(row)
        for name in sorted(self.functions):
            label = f"{name}()"
            row = VariableRow(label, "function", vocab_inner)
            row.clicked.connect(self._select_variable)
            self.vocab_rows[label] = row
            vocab_layout.addWidget(row)
        vocab_layout.addStretch(1)
        vocab_scroll.setWidget(vocab_inner)

        values_card, values_scroll = self._list_card(rail, "VALUES")
        self.values_card = values_card
        self.code_values = QWidget()
        self.code_values.setObjectName("valuesBox")
        self.code_values_layout = QVBoxLayout(self.code_values)
        self.code_values_layout.setContentsMargins(0, 0, 0, 0)
        self.code_values_layout.setSpacing(0)
        values_scroll.setWidget(self.code_values)

        rail_layout.addWidget(vocab, 3)
        rail_layout.addWidget(values_card, 2)
        layout.addWidget(rail, 0)

        # The page itself does not scroll: the two lists scroll in place, so
        # the code above stays put while you read the vocabulary.
        return page

    def _list_card(
        self, parent: QWidget, title: str, bar: bool = True
    ) -> tuple:
        """A card with a caption and a scroll area for a list of rows.

        `bar=False` hides the scrollbar: the wheel still walks the list and
        the width it would have taken goes to the row text.
        """
        card = QFrame(parent)
        card.setObjectName("selectedCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)
        heading = QLabel(title, card)
        heading.setObjectName("panelTitle")
        card_layout.addWidget(heading)

        scroll = QScrollArea(card)
        scroll.setObjectName("listScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        if not bar:
            scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        card_layout.addWidget(scroll, 1)
        return card, scroll

    def _variable_row(self, parent: QWidget, name: str, kind: str) -> QWidget:
        row = QWidget(parent)
        row.setObjectName("valueRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 2, 0, 2)
        line.setSpacing(6)
        key = QLabel(name, row)
        key.setObjectName("valueKey")
        shown = QLabel(kind, row)
        shown.setObjectName("groupLabel")
        line.addWidget(key, 1)
        line.addWidget(shown)
        return row

    def _select_variable(self, name: str) -> None:
        """Show what the picked word is and what it reads right now."""
        self.selected_variable = (
            None if self.selected_variable == name else name
        )
        for key, row in self.vocab_rows.items():
            row.set_selected(key == self.selected_variable)
        self._refresh_code_values()

    def _describe_variable(self, name: str) -> tuple[str, str]:
        if name.endswith("()"):
            base = name[:-2]
            return base, FUNCTION_NOTES.get(
                base, "a function the rule may call"
            )
        return name, FIELD_NOTES.get(name, "a word the rule may use")

    def _refresh_code_values(self) -> None:
        """The newest bar's numbers, or the picked variable's description."""
        if not hasattr(self, "code_values_layout"):
            return
        while self.code_values_layout.count():
            item = self.code_values_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        values, result = self.formula.values, self.formula.result
        selected = getattr(self, "selected_variable", None)
        if selected:
            name, note = self._describe_variable(selected)
            kind = "function" if selected.endswith("()") else "float"
            self.code_values_layout.addWidget(
                self._variable_row(self.code_values, name, kind)
            )
            caption = QLabel(note, self.code_values)
            caption.setObjectName("variableNote")
            caption.setWordWrap(True)
            self.code_values_layout.addWidget(caption)
            if name in values:
                value = values[name]
                shown = "—" if value is None else f"{value:,.4g}"
                self.code_values_layout.addWidget(
                    self._variable_row(self.code_values, "value", shown)
                )
        else:
            for name, value in values.items():
                shown = "—" if value is None else f"{value:,.4g}"
                self.code_values_layout.addWidget(
                    self._variable_row(self.code_values, name, shown)
                )
        if result is not None:
            row = QWidget(self.code_values)
            row.setObjectName("valueRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 2, 0, 2)
            key = QLabel("result", row)
            key.setObjectName("valueKey")
            shown = QLabel("TRUE" if result else "FALSE", row)
            shown.setObjectName("valueResult")
            shown.setProperty("state", "on" if result else "off")
            line.addWidget(key, 1)
            line.addWidget(shown)
            self.code_values_layout.addWidget(row)
        self.code_values_layout.addStretch(1)

    def set_values(self, values, result=None) -> None:
        """What the rule reads on the newest bar, for both panels."""
        self._last_result = result
        self.formula.set_values(values, result)
        self._refresh_code_values()
        self.conditions.set_status(self.error(), result)

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
        if mode == "formula":
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

    def reset_draft(self) -> None:
        """Back to one empty line, and the rules page."""
        self.formula.reset()
        self.set_mode("rules")

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
        if self._syncing:
            return
        # The Formula and Code tabs are canonical: redraw the rows from them.
        self.conditions.set_text(self.formula.formula_text())
        self.conditions.set_status(self.error(), self._last_result)
        self.changed.emit()
        self._sync_code()

    def _conditions_changed(self) -> None:
        """The rows changed: make their formula the one every tab shows."""
        if self._syncing:
            return
        text = self.conditions.text()
        self._syncing = True
        refused = ""
        try:
            try:
                self.formula.set_formula(text)
            except FormulaError as exc:
                # A character the language cannot read: keep the last good
                # formula, and let the checker name the problem.
                refused = str(exc)
        finally:
            self._syncing = False
        if refused:
            self.conditions.set_status(refused, self._last_result)
            return
        self.conditions.set_status(self.error(), self._last_result)
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


class RulesSwitcher(Card):
    """One tile holding both rules, switched by their titles.

    ENTRY RULES and EXIT RULES are two `RulesTile`s, but only one is shown at
    a time: their titles are the switch, and the Rules / Formula / Code pills
    belong to whichever side is showing. That way either rule gets the whole
    width instead of the two of them squeezing into it.
    """

    side_changed = Signal(str)
    mode_changed = Signal(str)

    SIDES = (("entry", "ENTRY RULES"), ("exit", "EXIT RULES"))

    def __init__(
        self,
        entry: RulesTile,
        exit_: RulesTile,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.exit = exit_
        self.current_side = "entry"

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        # The two titles are the switch: one checked, the other a quiet
        # invitation to the other rule.
        self.sides = QButtonGroup(self)
        self.sides.setExclusive(True)
        self.side_buttons: dict[str, QPushButton] = {}
        for index, (key, label) in enumerate(self.SIDES):
            button = QPushButton(label, self)
            button.setObjectName("sideButton")
            button.setProperty("side", key)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.sides.addButton(button, index)
            self.side_buttons[key] = button
            header.addWidget(button)
        self.sides.idClicked.connect(self._pick_side)

        header.addStretch(1)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for index, (key, label) in enumerate(RULES_MODES):
            button = QPushButton(label, self)
            button.setObjectName("modeButton")
            button.setProperty("mode", key)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mode_group.addButton(button, index)
            self.mode_buttons[key] = button
            header.addWidget(button)
        self.mode_group.idClicked.connect(self._pick_mode)
        self.body.addLayout(header)

        # The two rules share the card; only one is on top. They are inset:
        # the switcher's own card is the surface, so they do not draw a second
        # border inside it.
        self.stack = QStackedWidget(self)
        self.stack.setObjectName("rulesStack")
        for tile in (entry, exit_):
            tile.setProperty("inset", True)
            tile.body.setContentsMargins(0, 0, 0, 0)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
            self.stack.addWidget(tile)
        self.stack.setCurrentWidget(entry)
        self.body.addWidget(self.stack, 1)

        entry.mode_changed.connect(self._side_mode_changed)
        exit_.mode_changed.connect(self._side_mode_changed)

    def tile(self) -> RulesTile:
        """The rule currently on top."""
        return self.entry if self.current_side == "entry" else self.exit

    def side(self) -> str:
        return self.current_side

    def set_side(self, key: str) -> None:
        for index, (name, _) in enumerate(self.SIDES):
            if name == key:
                self.sides.button(index).setChecked(True)
                self._pick_side(index)
                return

    def _pick_side(self, index: int) -> None:
        if not 0 <= index < len(self.SIDES):
            return
        key = self.SIDES[index][0]
        self.current_side = key
        self.stack.setCurrentWidget(self.tile())
        # Each side keeps its own mode; the pills follow it.
        self._check_mode(self.tile().mode())
        self.side_changed.emit(key)

    def _pick_mode(self, index: int) -> None:
        if not 0 <= index < len(RULES_MODES):
            return
        self.tile().set_mode(RULES_MODES[index][0])

    def _check_mode(self, mode: str) -> None:
        for index, (key, _) in enumerate(RULES_MODES):
            if key == mode:
                button = self.mode_group.button(index)
                if button is not None and not button.isChecked():
                    button.setChecked(True)
                return

    def _side_mode_changed(self, mode: str) -> None:
        if self.sender() is self.tile():
            self._check_mode(mode)
        self.mode_changed.emit(mode)


__all__ = [
    "RULES_MODES",
    "PageStack",
    "RulesSwitcher",
    "RulesTile",
]
