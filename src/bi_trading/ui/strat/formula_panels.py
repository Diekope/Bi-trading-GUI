"""The formula builder's two side cards and the canvas, built as functions of the builder.

Each function is a method of `FormulaBuilder` (it takes `self` and the class binds it
under its old name), kept here so `formula_builder.py` is the model and the wiring and
this file is what gets drawn: the blocks card, the formula canvas and the selected
block's card."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from bi_trading.engine.formula import FIELDS
from bi_trading.engine.formula_palettes import GROUP_KEYS, Item
from bi_trading.ui.autocomplete import attach_completer, vocabulary
from bi_trading.ui.cards import mono_font
from bi_trading.ui.strat.formula_chips import CallChip, FlowHolder, PaletteBlock

if TYPE_CHECKING:
    from bi_trading.ui.strat.formula_builder import FormulaBuilder


def blocks_card(self: FormulaBuilder) -> QWidget:
    """The sources: a search box, then one dashed group per kind."""
    box = QFrame(self)
    box.setObjectName("formulaPalette")
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    outer = QVBoxLayout(box)
    outer.setContentsMargins(8, 6, 8, 6)
    outer.setSpacing(6)

    title = QLabel("BLOCKS", box)
    title.setObjectName("panelTitle")
    outer.addWidget(title)

    self.search_edit = QLineEdit(box)
    self.search_edit.setObjectName("searchEdit")
    self.search_edit.setPlaceholderText("search a block…")
    self.search_edit.setClearButtonEnabled(True)
    self.search_edit.textChanged.connect(self._filter_blocks)
    outer.addWidget(self.search_edit)

    self.blocks = {}
    scroll = QScrollArea(box)
    scroll.setObjectName("blocksScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    # No scrollbar: the column is narrow, and the room the bar took is
    # better spent on the formula beside it. The wheel still scrolls.
    scroll.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    inner = QWidget()
    inner.setObjectName("blocksInner")
    column = QVBoxLayout(inner)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(8)
    # The names the rule defines, above the built-in kinds, so they can be
    # dragged into the condition like any other block.
    column.addWidget(self._variables_group(inner))
    for group, items in self.palette:  # type: ignore[attr-defined]
        key = GROUP_KEYS.get(group, "maths")
        column.addWidget(self._block_group(inner, group, items, key))
    column.addStretch(1)
    scroll.setWidget(inner)
    outer.addWidget(scroll, 1)
    return box


def variables_group(self: FormulaBuilder, parent: QWidget) -> QWidget:
    """The Variables group: the names this rule defines, filled later."""
    frame = QFrame(parent)
    frame.setObjectName("blockGroup")
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(6, 5, 6, 6)
    layout.setSpacing(4)
    caption = QLabel("VARIABLES", frame)
    caption.setObjectName("paletteTitle")
    layout.addWidget(caption)
    self.variables_holder = FlowHolder(frame, spacing=3)
    layout.addWidget(self.variables_holder)
    self.blocks["Variables"] = []
    frame.setVisible(False)  # shown once something is named
    self.variables_frame = frame
    return frame


def refresh_variables_blocks(self: FormulaBuilder) -> None:
    """Repopulate the Variables group with the rule's own names."""
    holder = getattr(self, "variables_holder", None)
    if holder is None:
        return
    for block in self.blocks.get("Variables", []):
        holder.flow.removeWidget(block)
        block.setParent(None)
        block.deleteLater()
    self.blocks["Variables"] = []
    names = self.defined_names()
    for name in names:
        item = Item(name, (name,), "a name the rule defines")
        block = PaletteBlock(item, holder)
        block.setProperty("group", "name")
        block.style().unpolish(block)
        block.style().polish(block)
        holder.flow.addWidget(block)
        self.blocks["Variables"].append(block)
    self.variables_frame.setVisible(bool(names))


def block_group(self: FormulaBuilder, parent: QWidget, title: str, items: tuple, key: str
) -> QWidget:
    """One dashed group: its caption, then its blocks, wrapping."""
    frame = QFrame(parent)
    frame.setObjectName("blockGroup")
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(6, 5, 6, 6)
    layout.setSpacing(4)

    caption = QLabel(title.upper(), frame)
    caption.setObjectName("paletteTitle")
    layout.addWidget(caption)

    holder = FlowHolder(frame, spacing=3)
    blocks: list[PaletteBlock] = []
    for item in items:
        block = PaletteBlock(item, holder)
        # The block wears its group's colour, whatever it holds.
        block.setProperty("group", key)
        block.style().unpolish(block)
        block.style().polish(block)
        holder.flow.addWidget(block)
        blocks.append(block)
    self.blocks[title] = blocks
    layout.addWidget(holder)
    return frame


def filter_blocks(self: FormulaBuilder, text: str) -> None:
    """Hide blocks whose label does not contain what was typed."""
    want = text.strip().lower()
    for blocks in self.blocks.values():
        for block in blocks:
            block.setVisible(not want or want in block.item.label.lower())
    for frame in self.findChildren(QFrame, "blockGroup"):
        visible = any(
            child.isVisible()
            for child in frame.findChildren(PaletteBlock)
        )
        frame.setVisible(visible or not want)


def number_row(self: FormulaBuilder, parent: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    self.number_edit = QLineEdit(parent)
    self.number_edit.setObjectName("numberEdit")
    self.number_edit.setPlaceholderText(
        "a number, e.g. 20 or 0.05"
    )
    self.number_edit.setToolTip(
        "type a value; Enter adds it, or fills the armed slot"
    )
    self.number_edit.returnPressed.connect(self.add_number)
    attach_completer(
        self.number_edit, vocabulary(self.fields, self.functions)
    )

    self.number_add = QPushButton("+  Add", parent)
    self.number_add.setObjectName("numberAdd")
    self.number_add.setCursor(Qt.CursorShape.PointingHandCursor)
    self.number_add.clicked.connect(self.add_number)

    self.reset_button = QPushButton("↺  Reset", parent)
    self.reset_button.setObjectName("formulaReset")
    self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.reset_button.setToolTip("clear every line")
    self.reset_button.clicked.connect(self.reset)

    row.addWidget(self.number_edit, 1)
    row.addWidget(self.number_add)
    row.addWidget(self.reset_button)
    return row


def formula_card(self: FormulaBuilder) -> QWidget:
    box = QFrame(self)
    box.setObjectName("formulaCard")
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(6)

    title = QLabel("FORMULA", box)
    title.setObjectName("panelTitle")
    layout.addWidget(title)

    # The lines sit under two headings inside the scroll area: the named
    # The named series sit under LET, which is always shown with its
    # `+ add variable`; the condition sits under BUY WHEN (EXIT WHEN on
    # the exit side).
    self.variables_heading = QLabel("Variables", box)
    self.variables_heading.setObjectName("formulaSection")
    self.condition_heading = QLabel(self.condition_label, box)
    self.condition_heading.setObjectName("formulaCondition")

    # The lines scroll in a box of their own, between the title and the number
    # row, which stay put: only the elements scroll, never the whole panel.
    self.strip_area = QWidget(box)
    self.strip_area.setObjectName("stripArea")
    self.strip_inner = self.strip_area
    self.strip_layout = QVBoxLayout(self.strip_area)
    self.strip_layout.setContentsMargins(0, 0, 0, 0)
    self.strip_layout.setSpacing(4)
    self.strip_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    strip_scroll = QScrollArea(box)
    strip_scroll.setObjectName("stripScroll")
    strip_scroll.setWidgetResizable(True)
    strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
    strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    strip_scroll.setMinimumHeight(60)
    strip_scroll.setWidget(self.strip_area)
    layout.addWidget(strip_scroll, 1)

    self.add_variable_button = QPushButton("+  Add variable", box)
    self.add_variable_button.setObjectName("addVariable")
    self.add_variable_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.add_variable_button.setToolTip(
        "name a series above the condition"
    )
    self.add_variable_button.clicked.connect(lambda: self.add_variable())

    self.add_line_button = QPushButton("+  add a line", box)
    self.add_line_button.setObjectName("addLine")
    self.add_line_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.add_line_button.setToolTip(
        "another line: the last one is the condition"
    )
    self.add_line_button.clicked.connect(lambda: self.add_strip())
    layout.addWidget(self.add_line_button)

    layout.addLayout(self._number_row(box))

    bottom = QHBoxLayout()
    bottom.setSpacing(8)
    # The formula as text, in a single line: as little height as the row
    # can take, and it scrolls sideways when the rule is long.
    self.preview_label = QLineEdit(box)
    self.preview_label.setObjectName("formulaPreview")
    self.preview_label.setFont(mono_font(9))
    self.preview_label.setReadOnly(True)
    self.preview_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.preview_label.setFrame(False)
    self.status = QLabel(box)
    self.status.setObjectName("formulaStatus")
    self.status.setProperty("state", "idle")
    bottom.addWidget(self.preview_label, 1)
    bottom.addWidget(self.status, 0, Qt.AlignmentFlag.AlignTop)
    layout.addLayout(bottom)

    self.error_label = QLabel(box)
    self.error_label.setObjectName("formulaError")
    self.error_label.setWordWrap(True)
    layout.addWidget(self.error_label)

    # The mock's amber line: a word in the rule that nothing here carries.
    self.warning_label = QLabel("", box)
    self.warning_label.setObjectName("formulaWarning")
    self.warning_label.setWordWrap(True)
    layout.addWidget(self.warning_label)
    return box


def selected_card(self: FormulaBuilder) -> QWidget:
    """The block that is selected, its parameters, and its live value."""
    box = QFrame(self)
    box.setObjectName("selectedCard")
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(6)

    title = QLabel("SELECTED BLOCK", box)
    title.setObjectName("panelTitle")
    layout.addWidget(title)

    # What the block is and what it reads right now, in a scroll area: in
    # a short tile the card can be smaller than its contents, and the
    # values stay readable wheel by wheel.
    scroll = QScrollArea(box)
    scroll.setObjectName("selectedScroll")
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    body.setObjectName("selectedBody")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(6)

    self.selected_holder = QWidget(body)
    self.selected_holder.setObjectName("selectedHolder")
    self.selected_layout = QVBoxLayout(self.selected_holder)
    self.selected_layout.setContentsMargins(0, 0, 0, 0)
    self.selected_layout.setSpacing(6)
    body_layout.addWidget(self.selected_holder)

    self.values_title = QLabel("LIVE VALUES", body)
    self.values_title.setObjectName("panelTitle")
    body_layout.addWidget(self.values_title)

    self.values_box = QWidget(body)
    self.values_box.setObjectName("valuesBox")
    self.values_layout = QVBoxLayout(self.values_box)
    self.values_layout.setContentsMargins(0, 0, 0, 0)
    self.values_layout.setSpacing(0)
    body_layout.addWidget(self.values_box)
    body_layout.addStretch(1)

    scroll.setWidget(body)
    layout.addWidget(scroll, 1)

    self._refresh_selected()
    return box


def clear_layout(self: FormulaBuilder, layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def refresh_selected(self: FormulaBuilder) -> None:
    """Rebuild the selected-block card and the live values under it."""
    if not hasattr(self, "selected_layout"):
        return
    self._clear_layout(self.selected_layout)
    self._clear_layout(self.values_layout)

    chip = self.selected
    if chip is None:
        hint = QLabel("pick a block in a line to see it here", self)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        self.selected_layout.addWidget(hint)
    else:
        name = chip.tokens()[0] if chip.tokens() else "—"
        badge = QLabel(str(name), self)
        badge.setObjectName("selectedName")
        self.selected_layout.addWidget(badge)

        if isinstance(chip, CallChip):
            # Its source, then one field per number it carries.
            label = QLabel("Source", self)
            label.setObjectName("fieldLabel")
            self.selected_layout.addWidget(label)
            source = QComboBox(self)
            source.setObjectName("sourceSelect")
            source.addItems(FIELDS)
            source.setCurrentText(chip.series)
            source.currentTextChanged.connect(
                lambda text, chip=chip: self._set_series(chip, text)
            )
            self.selected_layout.addWidget(source)
            for index, field in enumerate(chip.fields):
                number = QLabel(
                    "Window" if index == 0 else "Value", self
                )
                number.setObjectName("fieldLabel")
                self.selected_layout.addWidget(number)
                entry = QLineEdit(field.text(), self)
                entry.setObjectName("numberEdit")
                entry.setAlignment(Qt.AlignmentFlag.AlignRight)
                entry.textChanged.connect(
                    lambda text, field=field: field.setText(text)
                )
                self.selected_layout.addWidget(entry)
        elif chip.is_slot():
            hint = QLabel(
                "an empty slot: type a value to fill it", self
            )
            hint.setObjectName("hintLabel")
            hint.setWordWrap(True)
            self.selected_layout.addWidget(hint)

    # The live values: what the rule's own names read on the newest bar.
    if not self.values:
        empty = QLabel("no values yet — the report fills these", self)
        empty.setObjectName("hintLabel")
        empty.setWordWrap(True)
        self.values_layout.addWidget(empty)
        return
    for name, value in self.values.items():
        row = QWidget(self.values_box)
        row.setObjectName("valueRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 3, 0, 3)
        line.setSpacing(6)
        key = QLabel(name, row)
        key.setObjectName("valueKey")
        shown = QLabel(
            "—" if value is None else f"{value:,.4g}", row
        )
        shown.setObjectName("valueNumber")
        line.addWidget(key, 1)
        line.addWidget(shown)
        self.values_layout.addWidget(row)
    if self.result is not None:
        row = QWidget(self.values_box)
        row.setObjectName("valueRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 3, 0, 3)
        line.setSpacing(6)
        key = QLabel("result", row)
        key.setObjectName("valueKey")
        shown = QLabel("TRUE" if self.result else "FALSE", row)
        shown.setObjectName("valueResult")
        shown.setProperty("state", "on" if self.result else "off")
        line.addWidget(key, 1)
        line.addWidget(shown)
        self.values_layout.addWidget(row)


def set_series(self: FormulaBuilder, chip: CallChip, series: str) -> None:
    if chip.series != series:
        chip.series = series
        self._refresh()
        self.changed.emit()
