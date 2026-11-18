"""The drag-and-drop formula builder for the ENTRY RULES tile.

A formula is built from chips. A card holds the sources — rows of draggable
**blocks**, `Data`, `Indicators` and `Logic & Maths`, colour-coded by what they
are, then a box to type a number into. Under the card are the lines you drop
the blocks on. Each line is a strip of chips read left to right; the last line
is the condition, the ones above it are named series:

    [mid] [=] [sma] [(] [close] [,] [▢] [)]
    [close] [<] [mid]

An indicator drops in with its parentheses and comma already placed and an
empty **slot** — a dashed chip — where its period goes. Fill a slot by dragging
a number onto it, or by clicking it and typing a value in the number box. A
chip drags by its handle to reorder or move between lines, and its `×` takes it
off.

The chips are only an editor. The formula **text** is the truth: it is rebuilt
from the chips and handed to `bi_trading.engine.formula.parse`, so the same checker still
reports `line 2, column 9: unknown name 'clsoe'`.
"""

from __future__ import annotations


from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bi_trading.engine.formula import (
    ENTRY_FIELDS,
    Formula,
    NO_HISTORY,
    FUNCTIONS,
    FormulaError,
    parse,
    scan,
)
from bi_trading.engine.formula_palettes import (
    EXIT_PALETTES,
    Item,
    LOGIC_ITEMS,
    MIME,
    PALETTES,
    group_for_token,
)

from bi_trading.ui.strat.formula_chips import (  # noqa: F401
    CallChip,
    Chip,
    ChipStrip,
    DropZone,
    FlowHolder,
    FlowLayout,
    NameChip,
    PaletteBlock,
    _begin_drag,
    _decode,
    _single,
    drag_pixmap,
)
from bi_trading.ui.strat import formula_panels as _panels


class FormulaBuilder(QWidget):
    """The palette card, the lines, and the text they add up to."""

    changed = Signal()

    # Built by the functions in formula_panels.py, so named here for the type checker.
    search_edit: QLineEdit
    blocks: dict[str, list[PaletteBlock]]
    variables_holder: FlowHolder
    variables_frame: QFrame
    number_edit: QLineEdit
    number_add: QPushButton
    reset_button: QPushButton
    variables_heading: QLabel
    condition_heading: QLabel
    strip_area: QWidget
    strip_inner: QWidget
    strip_layout: QVBoxLayout
    add_variable_button: QPushButton
    add_line_button: QPushButton
    preview_label: QLineEdit
    status: QLabel
    error_label: QLabel
    warning_label: QLabel
    selected_holder: QWidget
    selected_layout: QVBoxLayout
    values_title: QLabel
    values_box: QWidget
    values_layout: QVBoxLayout

    def __init__(
        self,
        parent: QWidget | None = None,
        palettes: tuple | None = None,
        fields: tuple = ENTRY_FIELDS,
        functions: dict | None = None,
        condition_label: str = "BUY WHEN",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("formulaBuilder")
        # Named like the builder's other inputs; it shadows QWidget.palette(),
        # which nothing here calls.
        self.palette = PALETTES if palettes is None else palettes  # type: ignore[method-assign,assignment]
        self.fields = tuple(fields)
        self.functions = FUNCTIONS if functions is None else functions
        self.condition_label = condition_label
        self.strips: list[ChipStrip] = []
        self.active: ChipStrip | None = None
        self.armed: Chip | None = None
        self.selected: Chip | None = None
        self.values: dict = {}
        self.result = None
        self._parsed: Formula | None = None

        # Blocks on the left, small and fixed; the formula takes the slack in
        # the middle; the selected block is a rail on the right, pushed to the
        # edge the way the mock draws it.
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        blocks = self._blocks_card()
        # A fixed little rail, as in the mock: the formula gets the rest.
        blocks.setFixedWidth(200)
        root.addWidget(blocks, 0)

        formula = self._formula_card()
        formula.setMinimumWidth(156)
        root.addWidget(formula, 1)

        selected = self._selected_card()
        selected.setMinimumWidth(190)
        selected.setMaximumWidth(250)
        root.addWidget(selected, 0)

        self.blocks_card = blocks
        self.formula_card = formula
        self.selected_card = selected

        self.add_strip()

    # -- the blocks card ---------------------------------------------------

    # Moved to formula_panels.py; each is still a method of this class.
    _blocks_card = _panels.blocks_card
    _variables_group = _panels.variables_group
    _refresh_variables_blocks = _panels.refresh_variables_blocks
    _block_group = _panels.block_group
    _filter_blocks = _panels.filter_blocks
    _number_row = _panels.number_row
    _formula_card = _panels.formula_card
    _selected_card = _panels.selected_card
    _clear_layout = _panels.clear_layout
    _refresh_selected = _panels.refresh_selected
    _set_series = _panels.set_series



    def defined_names(self) -> list:
        """The names the rule's variable lines define, in order."""
        names: list[str] = []
        for strip in self.strips:
            for chip in strip.chips():
                if isinstance(chip, NameChip):
                    name = chip.token.strip()
                    if name and name not in names:
                        names.append(name)
        return names




    # -- the canvas --------------------------------------------------------


    # -- the selected block ------------------------------------------------





    def select_chip(self, chip: Chip | None) -> None:
        """Show a block in the card beside the formula."""
        self.selected = chip
        self._refresh_selected()

    def selected_name(self) -> str:
        if self.selected is None:
            return ""
        tokens = self.selected.tokens()
        return tokens[0] if tokens else ""

    def set_values(self, values: dict, result=None) -> None:
        """The last bar's numbers, pushed in by whoever ran the rule."""
        self.values = dict(values or {})
        self.result = result
        self._refresh_selected()

    # -- lines -------------------------------------------------------------

    def add_strip(self, tokens=None, at: int | None = None) -> ChipStrip:
        strip = ChipStrip(self, self)
        if tokens:
            strip.set_tokens(tokens)
        index = len(self.strips) if at is None else at
        self.strips.insert(index, strip)
        self.active = strip
        self._refresh()
        return strip

    def remove_strip(self, strip: ChipStrip) -> None:
        if strip not in self.strips or len(self.strips) <= 1:
            return
        self.strips.remove(strip)
        self.strip_layout.removeWidget(strip)
        strip.setParent(None)
        strip.deleteLater()
        if self.active is strip:
            self.active = self.strips[-1]
        self._refresh()
        self.changed.emit()

    def remove_active_strip(self) -> None:
        self.remove_strip(self.active or self.strips[-1])

    def set_active(self, strip: ChipStrip) -> None:
        self.active = strip

    def reset(self) -> None:
        """Clear every line back to a single empty one."""
        for strip in list(self.strips):
            self.strips.remove(strip)
            self.strip_layout.removeWidget(strip)
            strip.setParent(None)
            strip.deleteLater()
        self.add_strip()
        self._refresh()
        self.changed.emit()

    # -- chips -------------------------------------------------------------

    def start_chip_drag(self, chip: Chip, hotspot=None) -> None:
        strip = chip.strip
        if strip is None or chip.is_slot():
            return
        location = [self.strips.index(strip), strip.chips().index(chip)]
        if isinstance(chip, CallChip):
            # An indicator travels as one tile, numbers and all.
            _begin_drag(chip, [], source=location, hotspot=hotspot, call=chip.call())
        else:
            _begin_drag(chip, [chip.token], source=location, hotspot=hotspot)

    def remove_chip(self, chip: Chip) -> None:
        if chip.strip is None:
            return
        chip.strip.remove_chip(chip)
        if self.selected is chip:
            self.select_chip(None)
        self._refresh()
        self.changed.emit()

    def contents_changed(self) -> None:
        """A chip changed in place (an indicator's number); re-read it."""
        self._refresh()
        self.changed.emit()

    def drop_tokens(self, payload: dict, strip: ChipStrip, index: int) -> None:
        tokens = payload.get("tokens") or []
        call = payload.get("call")
        source = payload.get("from")
        if source:
            source_strip, source_index = source
            self._remove_at(source_strip, source_index)
            if source_strip == self.strips.index(strip) and source_index < index:
                index -= 1
        if call:
            if isinstance(call, dict):
                spec = (
                    call.get("func", ""),
                    call.get("series", "close"),
                    tuple(call.get("params") or ()),
                    call.get("label", call.get("func", "")),
                )
            else:
                spec = tuple(call)
            strip.add_call_chip(spec, index)
        else:
            for offset, token in enumerate(tokens):
                strip.add_chip(token, index + offset)
        self.active = strip
        self._refresh()
        self.changed.emit()

    def _remove_at(self, strip_index: int, chip_index: int) -> None:
        strip = self.strips[strip_index]
        chips = strip.chips()
        if 0 <= chip_index < len(chips):
            strip.remove_chip(chips[chip_index])

    # -- slots -------------------------------------------------------------

    def arm_slot(self, chip: Chip) -> None:
        self.armed = chip
        for strip in self.strips:
            for other in strip.chips():
                other.set_armed(other is chip)
        self.active = chip.strip
        self.number_edit.setPlaceholderText("value for the slot")
        self.number_edit.setFocus()

    def _disarm(self) -> None:
        self.armed = None
        for strip in self.strips:
            for chip in strip.chips():
                chip.set_armed(False)
        self.number_edit.setPlaceholderText("a number, e.g. 20 or 0.05")

    def fill_slot(self, chip: Chip, token: str, mime=None) -> None:
        if mime is not None:
            payload = _decode(mime)
            if payload and payload.get("from"):
                self._remove_at(*payload["from"])
        chip.set_token(token)
        self._disarm()
        self._refresh()
        self.changed.emit()

    # -- the number box ----------------------------------------------------

    def add_number(self) -> None:
        text = self.number_edit.text().strip()
        if not text:
            return
        if self.armed is not None and self.armed.token is None:
            self.fill_slot(self.armed, text)
        else:
            strip = self.active or self.strips[-1]
            strip.add_chip(text)
            self.active = strip
            self._refresh()
            self.changed.emit()
        self.number_edit.clear()

    # -- the formula -------------------------------------------------------

    def formula_text(self) -> str:
        return "\n".join(
            strip.text() for strip in self.strips if strip.tokens()
        )

    def error(self) -> str:
        return self.error_label.text()

    def warning(self) -> str:
        return self.warning_label.text()

    def missing_names(self) -> list:
        """Names in the formula that nothing here carries, in order."""
        return [
            name for name in self._used_names() if name in NO_HISTORY
        ]

    def _used_names(self) -> list:
        seen: list = []
        for strip in self.strips:
            for chip in strip.chips():
                for token in chip.tokens():
                    if token in NO_HISTORY and token not in seen:
                        seen.append(token)
        return seen

    def parsed(self):
        return self._parsed

    def _display_for(self, func: str) -> str:
        """A friendly name for a function, matching the palette block."""
        for _, items in self.palette:  # type: ignore[attr-defined]
            for entry in items:
                if entry.call and entry.call[0] == func:
                    return entry.call[3]
        return func

    def _plan(self, tokens: list) -> list:
        """Group a flat token run into chips: calls stay one tile.

        `sma(close, 20)` becomes one call chip; anything that is not a plain
        `func(series, number…)` is left as individual tokens.
        """
        plan: list = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if (
                token in self.functions
                and index + 3 < len(tokens)
                and tokens[index + 1] == "("
            ):
                cursor = index + 2
                args: list = []
                matched = True
                while cursor < len(tokens):
                    piece = tokens[cursor]
                    if piece == ")":
                        break
                    if piece == ",":
                        cursor += 1
                        continue
                    if piece in ("(", ")"):
                        matched = False
                        break
                    args.append(piece)
                    cursor += 1
                if (
                    matched
                    and cursor < len(tokens)
                    and tokens[cursor] == ")"
                    and len(args) >= 2
                ):
                    plan.append(
                        (
                            "call",
                            (token, args[0], tuple(args[1:]), self._display_for(token)),
                        )
                    )
                    index = cursor + 1
                    continue
            plan.append(("token", token))
            index += 1
        return plan

    def set_formula(self, text: str) -> None:
        """Replace the lines with those of `text`. Raises on a bad character."""
        tokens = [token for token in scan(text) if token.kind != "newline"]
        for strip in list(self.strips):
            self.strips.remove(strip)
            self.strip_layout.removeWidget(strip)
            strip.setParent(None)
            strip.deleteLater()
        if not tokens:
            self.add_strip()
            self._refresh()
            self.changed.emit()
            return
        lines: dict[int, list[str]] = {}
        order: list[int] = []
        for token in tokens:
            if token.line not in lines:
                lines[token.line] = []
                order.append(token.line)
            lines[token.line].append(token.text)
        for line in order:
            strip = self.add_strip()
            plan = self._plan(lines[line])
            for position, (kind, payload) in enumerate(plan):
                if kind == "call":
                    strip.add_call_chip(payload)
                elif (
                    position == 0
                    and len(plan) > 1
                    and plan[1] == ("token", "=")
                ):
                    strip.add_name_chip(payload)
                elif kind == "token" and payload == "=":
                    # The assignment's `=` is a fixture, not a token to move.
                    strip.add_chip("=", fixed=True)
                else:
                    strip.add_chip(payload)
        self._refresh()
        self.changed.emit()

    def _arrange_strips(self) -> None:
        """Put the headings and the lines in order: LET, then the condition."""
        while self.strip_layout.count():
            item = self.strip_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(self.strip_inner)

        # LET is always shown, with its `+ Add variable`; the condition sits
        # under the BUY WHEN / EXIT WHEN heading, last.
        self.strip_layout.addWidget(self.variables_heading)
        for strip in self.strips[:-1]:
            self.strip_layout.addWidget(strip)
        self.strip_layout.addWidget(self.add_variable_button)
        self.strip_layout.addWidget(self.condition_heading)
        if self.strips:
            self.strip_layout.addWidget(self.strips[-1])

    def add_variable(self) -> ChipStrip:
        """Add a named series above the condition: `name =`.

        The line is just the name field and the fixed `=`: nothing else to
        fill. The name takes the cursor, and the series goes on the line by
        dragging a block onto it.
        """
        index = max(0, len(self.strips) - 1)
        strip = self.add_strip(at=index)
        name = strip.add_name_chip("")
        strip.add_chip("=", fixed=True)
        self._refresh()
        name.focus_name()
        return strip

    def _refresh(self) -> None:
        self._refresh_warning()
        self._refresh_variables_blocks()
        # The strips carry no caption of their own: the headings above them
        # say LET and BUY WHEN / EXIT WHEN.
        for strip in self.strips:
            strip.caption.setText("")
            strip.caption.hide()
            strip.remove_button.setVisible(len(self.strips) > 1)
        self._arrange_strips()

        text = self.formula_text()
        self.preview_label.setText(text if text else "— drop a block onto a line")
        # Show the start of the rule, not its tail.
        self.preview_label.setCursorPosition(0)
        self.add_line_button.setEnabled(len(self.strips) < 6)
        self.add_variable_button.setEnabled(len(self.strips) < 6)

        if any(strip.has_empty_slots() for strip in self.strips):
            self._parsed = None
            self._set_state("error")
            self.error_label.setText("fill the empty slot before this can be read")
            return
        if not text.strip():
            self._parsed = None
            self._set_state("idle")
            self.error_label.setText("")
            return
        try:
            self._parsed = parse(text, self.fields, self.functions)
        except FormulaError as exc:
            self._parsed = None
            self._set_state("error")
            self.error_label.setText(str(exc))
        else:
            self._set_state("ok")
            self.error_label.setText("")

    def _refresh_warning(self) -> None:
        missing = self.missing_names()
        if missing:
            names = ", ".join(missing)
            self.warning_label.setText(
                f"⚠ {names}: no history in a backtest"
            )
        else:
            self.warning_label.setText("")

    def _set_state(self, state: str) -> None:
        self.status.setText(
            {"ok": "✓ valid", "error": "✗ not valid"}.get(state, "— empty")
        )
        if self.status.property("state") == state:
            return
        self.status.setProperty("state", state)
        style = self.status.style()
        style.unpolish(self.status)
        style.polish(self.status)


__all__ = [
    "EXIT_PALETTES",
    "LOGIC_ITEMS",
    "MIME",
    "PALETTES",
    "Chip",
    "ChipStrip",
    "CallChip",
    "DropZone",
    "FlowHolder",
    "FlowLayout",
    "FormulaBuilder",
    "Item",
    "NameChip",
    "PaletteBlock",
    "drag_pixmap",
    "group_for_token",
]
