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

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
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
from lalala.formula import (
    ENTRY_FIELDS,
    EXIT_FIELDS,
    EXIT_FUNCTIONS,
    FIELDS,
    FUNCTIONS,
    FormulaError,
)
from lalala.formula_builder import (
    EXIT_PALETTES,
    PALETTES,
    FlowHolder,
    FormulaBuilder,
)
from lalala.panels import Card

# A rule usually starts from a ready-made one. The presets are shown as a
# gallery, this many to a row at most.
PRESETS_PER_ROW = 4

# The three ways a rule can be reached, in the order they appear: start from a
# ready-made rule, drag one up, or write it as code.
RULES_MODES = (
    ("rules", "Rules"),
    ("formula", "Formula"),
    ("code", "Code"),
)


@dataclass(frozen=True)
class Preset:
    """A ready-made rule: a name, a line about it, and the formula."""

    label: str
    text: str
    note: str = ""
    badge: str = ""


# Whole rules to start from, one set per tile. They are ordinary formulas —
# picking one just fills the tile, and it can be edited from there.
ENTRY_PRESETS: tuple = (
    Preset(
        "Bollinger reversion",
        "close < bollinger_lower(close, 20, 2)",
        "Below the lower band.",
        "Entry 1",
    ),
    Preset(
        "SMA above",
        "close > sma(close, 20)",
        "Above the average.",
    ),
    Preset(
        "Breakout",
        "close >= highest(high, 20)",
        "A new 20-bar high.",
    ),
    Preset(
        "RSI dip",
        "rsi(close, 14) < 30",
        "An oversold close.",
    ),
    Preset(
        "Volume spike",
        "volume > 2 * sma(volume, 50)",
        "Twice the volume.",
    ),
    Preset(
        "Dip + volume",
        "band = bollinger_lower(close, 20, 2)\n"
        "close < band and volume > sma(volume, 20)",
        "A dip, with volume.",
    ),
)

EXIT_PRESETS: tuple = (
    Preset(
        "Take profit",
        "pnl >= tp",
        "Up by the target.",
    ),
    Preset(
        "Stop loss",
        "pnl <= 0 - sl",
        "Down by the stop.",
    ),
    Preset(
        "TP or SL",
        "pnl >= tp or pnl <= 0 - sl",
        "Target or stop.",
        "Exit 1",
    ),
    Preset(
        "Time stop",
        "bars >= 90",
        "Open too long.",
    ),
    Preset(
        "Target, stop or time",
        "pnl >= tp or pnl <= 0 - sl or bars >= 90",
        "Whichever comes first.",
    ),
)


class PageStack(QStackedWidget):
    """A stack of pages whose size hints follow the page on show.

    A plain `QStackedWidget` reports the largest hint over *all* its pages
    whether or not they are visible, so the tall formula page would inflate
    the tile's minimum while the presets page was the one on screen.
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


class PresetCard(QFrame):
    """A ready-made rule as a card: a title, a line about it, and a badge.

    Clicking it fills the tile. `text()` and `click()` mirror a button, so a
    card and a pill are used the same way.
    """

    clicked = Signal()

    def __init__(self, preset: Preset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.setObjectName("presetCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(preset.text)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.setMinimumWidth(110)
        self.setMinimumHeight(62)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(3)

        self.label = QLabel(preset.label, self)
        self.label.setObjectName("presetTitle")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout.addWidget(self.label)

        if preset.badge:
            self.badge = QLabel(preset.badge, self)
            self.badge.setObjectName("presetBadge")
            self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.badge.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            layout.addWidget(self.badge)

        if preset.note:
            self.note = QLabel(preset.note, self)
            self.note.setObjectName("presetNote")
            self.note.setWordWrap(True)
            self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.note.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            layout.addWidget(self.note)

    def text(self) -> str:
        return self.preset.label

    def click(self) -> None:
        self.clicked.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()


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
        presets: tuple | None = None,
    ) -> None:
        super().__init__(parent)
        self.palettes = PALETTES if palettes is None else palettes
        self.fields = tuple(fields)
        self.functions = FUNCTIONS if functions is None else functions
        self.placeholder = placeholder
        self.presets = ENTRY_PRESETS if presets is None else presets

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

        # One page per mode: ready-made rules, the tiles, and the code. All
        # three reach the same formula.
        self.pages = PageStack(self)
        self.pages.setObjectName("entryPages")
        self.pages.addWidget(self._presets_page())
        self.pages.addWidget(self._formula_page())
        self.pages.addWidget(self._code_page())
        self.body.addWidget(self.pages, 1)
        self.pages.setCurrentIndex(0)
        self.pages.currentChanged.connect(self._pages_changed)

        # The synchronisation guard and the last code that was accepted.
        self._syncing = False
        self._accepted = ""

    # -- the pages ---------------------------------------------------------

    def _presets_page(self) -> QWidget:
        """The ready-made rules, as a gallery of at most four to a row."""
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        hint = QLabel(
            "pick a rule to load it into the editor — it is editable from there",
            page,
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # A grid, four columns wide. Rows with fewer cards keep their column,
        # so the run starts at the left edge rather than being centred.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self.preset_holder = grid
        self.preset_buttons: list[PresetCard] = []
        for index, preset in enumerate(self.presets):
            card = PresetCard(preset, page)
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            card.clicked.connect(
                lambda _checked=False, text=preset.text: self._use_preset(text)
            )
            grid.addWidget(card, index // PRESETS_PER_ROW, index % PRESETS_PER_ROW)
            self.preset_buttons.append(card)
        for column in range(PRESETS_PER_ROW):
            grid.setColumnStretch(column, 1)
        rows = (len(self.presets) + PRESETS_PER_ROW - 1) // PRESETS_PER_ROW
        grid.setRowStretch(rows, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        return page

    def _use_preset(self, text: str) -> None:
        """Load a ready-made rule and go straight to where it can be edited."""
        self.set_text(text)
        self.set_mode("formula")

    def _formula_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.formula = FormulaBuilder(
            page, palettes=self.palettes, fields=self.fields,
            functions=self.functions,
        )
        self.formula.changed.connect(self._formula_changed)
        layout.addWidget(self.formula, 1)
        return page

    def _code_page(self) -> QWidget:
        """The code on the left, its vocabulary and its values on the right."""
        page = QWidget(self)
        page.setObjectName("entryPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # The code itself, in a card.
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
        layout.addWidget(code_card, 62)

        # The vocabulary, and what it reads right now.
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(8)

        vocab = QFrame(page)
        vocab.setObjectName("selectedCard")
        vocab.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        vocab_layout = QVBoxLayout(vocab)
        vocab_layout.setContentsMargins(10, 8, 10, 8)
        vocab_layout.setSpacing(4)
        vocab_title = QLabel("VARIABLES", vocab)
        vocab_title.setObjectName("panelTitle")
        vocab_layout.addWidget(vocab_title)
        for name in self.fields:
            vocab_layout.addWidget(
                self._variable_row(vocab, name, "float")
            )
        for name in sorted(self.functions):
            vocab_layout.addWidget(
                self._variable_row(vocab, f"{name}()", "function")
            )
        vocab_layout.addStretch(1)
        side.addWidget(vocab, 3)

        values_card = QFrame(page)
        values_card.setObjectName("selectedCard")
        values_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        values_layout = QVBoxLayout(values_card)
        values_layout.setContentsMargins(10, 8, 10, 8)
        values_layout.setSpacing(4)
        values_title = QLabel("VALUES", values_card)
        values_title.setObjectName("panelTitle")
        values_layout.addWidget(values_title)
        self.code_values = QWidget(values_card)
        self.code_values.setObjectName("valuesBox")
        self.code_values_layout = QVBoxLayout(self.code_values)
        self.code_values_layout.setContentsMargins(0, 0, 0, 0)
        self.code_values_layout.setSpacing(0)
        values_layout.addWidget(self.code_values)
        values_layout.addStretch(1)
        side.addWidget(values_card, 2)
        layout.addLayout(side, 38)
        return page

    def _variable_row(self, parent: QWidget, name: str, kind: str) -> QWidget:
        row = QWidget(parent)
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

    def _refresh_code_values(self) -> None:
        """The newest bar's numbers, under the vocabulary."""
        if not hasattr(self, "code_values_layout"):
            return
        while self.code_values_layout.count():
            item = self.code_values_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        values, result = self.formula.values, self.formula.result
        for name, value in values.items():
            shown = "—" if value is None else f"{value:,.4g}"
            self.code_values_layout.addWidget(
                self._variable_row(self.code_values, name, shown)
            )
        if result is not None:
            row = QWidget(self.code_values)
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

    def set_values(self, values, result=None) -> None:
        """What the rule reads on the newest bar, for both panels."""
        self.formula.set_values(values, result)
        self._refresh_code_values()

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


__all__ = [
    "ENTRY_PRESETS",
    "EXIT_PRESETS",
    "PRESETS_PER_ROW",
    "RULES_MODES",
    "PageStack",
    "Preset",
    "PresetCard",
    "RulesTile",
]
