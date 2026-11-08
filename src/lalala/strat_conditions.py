"""The Rules tab: conditions in groups, the way the mock draws them.

A rule is a few comparisons over the bar (or the open trade), gathered into
groups. Each group joins its rows with **All (AND)** or **Any (OR)**, and the
groups themselves are joined with AND — the same shape the formula language
gives `a and b and (c or d)`.

This page is another way to write the same formula as the Formula and Code
tabs. It reads any formula whose condition is a flat AND / OR of comparisons,
keeping the `name = …` lines as **LET** rows above it. A condition it cannot
break into rows is kept as one raw expression, so switching tabs never
rewrites the rule.

The right rail is a **Variables** column: the fields and the indicators, each a
click away from the operand box that has the cursor. (The mock put signal
options there — side, confirmation, cooldown — but the backtest models none of
them.)
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.formula import (
    ENTRY_FIELDS,
    Binary,
    Call,
    FormulaError,
    Name,
    Number,
    Unary,
    parse,
)

COMPARISONS = ("<", "<=", ">", ">=", "==", "!=")

# Called on a bar, offered as ready expressions beside the plain fields.
INDICATORS = (
    "sma(close, 20)",
    "ema(close, 30)",
    "rsi(close, 14)",
    "bollinger_lower(close, 20, 2)",
    "bollinger_middle(close, 20, 2)",
    "bollinger_upper(close, 20, 2)",
    "highest(high, 20)",
    "lowest(low, 20)",
)

_PRECEDENCE = {
    "or": 1,
    "and": 2,
    "not": 3,
    "<": 4, "<=": 4, ">": 4, ">=": 4, "==": 4, "!=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
    "^": 7,
}


def _number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def expression_text(node, parent: int = 0) -> str:
    """Write a parsed expression back as source, with only needed brackets."""
    if isinstance(node, Number):
        return _number(node.value)
    if isinstance(node, Name):
        return node.name
    if isinstance(node, Call):
        args = ", ".join(expression_text(arg) for arg in node.args)
        return f"{node.func}({args})"
    if isinstance(node, Unary):
        inner = expression_text(node.operand, _PRECEDENCE["not"])
        text = f"-{inner}" if node.op == "-" else f"not {inner}"
        return f"({text})" if parent > _PRECEDENCE["not"] else text
    if isinstance(node, Binary):
        prec = _PRECEDENCE.get(node.op, 9)
        left = expression_text(node.left, prec)
        right = expression_text(node.right, prec + (0 if node.op == "^" else 1))
        text = f"{left} {node.op} {right}"
        return f"({text})" if prec < parent else text
    return ""


def _split(node, op: str) -> list:
    """Flatten a chain of the same binary operator."""
    if isinstance(node, Binary) and node.op == op:
        return _split(node.left, op) + _split(node.right, op)
    return [node]


def _row_for(node) -> dict:
    """One row: a comparison, or a raw expression kept whole."""
    if isinstance(node, Binary) and node.op in COMPARISONS:
        return {
            "left": expression_text(node.left),
            "op": node.op,
            "right": expression_text(node.right),
            "raw": False,
        }
    return {
        "left": expression_text(node),
        "op": "<",
        "right": "",
        "raw": True,
    }


def condition_groups(condition) -> list:
    """Break a condition into (logic, rows) groups joined with AND."""
    if condition is None:
        return []
    if isinstance(condition, Binary) and condition.op == "or":
        return [("or", [_row_for(term) for term in _split(condition, "or")])]

    terms = (
        _split(condition, "and")
        if isinstance(condition, Binary) and condition.op == "and"
        else [condition]
    )
    groups: list = []
    loose: list = []
    for term in terms:
        if isinstance(term, Binary) and term.op == "or":
            groups.append(("or", [_row_for(item) for item in _split(term, "or")]))
        else:
            loose.append(term)
    if loose:
        groups.insert(0, ("and", [_row_for(term) for term in loose]))
    return groups


def _choices(fields, functions) -> list:
    """What the operand boxes offer: the bar's words, then indicators."""
    choices = list(fields)
    if "sma" in functions:
        choices.extend(
            item for item in INDICATORS if item not in choices
        )
    return choices


def _operand_combo(parent, choices, placeholder: str) -> QComboBox:
    """An editable box that offers the vocabulary but takes anything typed."""
    combo = QComboBox(parent)
    combo.setObjectName("conditionOperand")
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.addItems(list(choices))
    combo.setCurrentText("")
    if combo.lineEdit() is not None:
        combo.lineEdit().setPlaceholderText(placeholder)
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    return combo


class ConditionRow(QFrame):
    """One comparison: an operand, an operator and a value."""

    changed = Signal()
    removed = Signal(object)
    activated = Signal(object)

    def __init__(self, choices: list, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("conditionRow")
        self._loading = False
        self._raw = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.left = _operand_combo(self, choices, "condition")
        self.op = QComboBox(self)
        self.op.setObjectName("conditionOp")
        self.op.addItems(COMPARISONS)
        self.op.setFixedWidth(62)
        self.op.setCursor(Qt.CursorShape.PointingHandCursor)
        self.right = _operand_combo(self, choices, "value")
        self.remove = QPushButton("×", self)
        self.remove.setObjectName("removeCondition")
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip("remove this condition")
        self.remove.setFixedWidth(24)
        self.remove.clicked.connect(lambda: self.removed.emit(self))

        row.addWidget(self.left, 3)
        row.addWidget(self.op, 0)
        row.addWidget(self.right, 3)
        row.addWidget(self.remove, 0)

        # Tell the page which operand box has the cursor, so the variables
        # rail knows where an inserted name should land. Focus may land on the
        # combo itself or on its line edit, depending on the platform.
        for combo in (self.left, self.right):
            combo.installEventFilter(self)
            line = combo.lineEdit()
            if line is not None:
                line.installEventFilter(self)

        self.left.editTextChanged.connect(self._touched)
        self.right.editTextChanged.connect(self._touched)
        self.op.currentIndexChanged.connect(self._touched)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.FocusIn:
            for combo in (self.left, self.right):
                if obj is combo or obj is combo.lineEdit():
                    self.activated.emit(combo)
                    break
        return super().eventFilter(obj, event)

    def set_parts(self, left: str, op: str, right: str, raw: bool = False) -> None:
        self._loading = True
        try:
            self._raw = raw
            self.left.setCurrentText(left)
            index = self.op.findText(op)
            self.op.setCurrentIndex(index if index >= 0 else 0)
            self.right.setCurrentText(right)
            self.op.setVisible(not raw)
            self.right.setVisible(not raw)
        finally:
            self._loading = False

    def value(self) -> str | None:
        left = self.left.currentText().strip()
        if self._raw:
            return left or None
        right = self.right.currentText().strip()
        if not left or not right:
            return None
        return f"{left} {self.op.currentText()} {right}"

    def _touched(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()


class AssignmentRow(QFrame):
    """One named series above the condition: `name = expression`."""

    changed = Signal()
    removed = Signal(object)
    activated = Signal(object)

    def __init__(self, choices: list, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("conditionRow")
        self._loading = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.name = QLineEdit(self)
        self.name.setObjectName("assignName")
        self.name.setPlaceholderText("name")
        self.name.setFixedWidth(96)
        self.equals = QLabel("=", self)
        self.equals.setObjectName("assignEquals")
        self.value = _operand_combo(self, choices, "expression")
        self.remove = QPushButton("×", self)
        self.remove.setObjectName("removeCondition")
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip("remove this variable")
        self.remove.setFixedWidth(24)
        self.remove.clicked.connect(lambda: self.removed.emit(self))

        row.addWidget(self.name, 0)
        row.addWidget(self.equals, 0)
        row.addWidget(self.value, 1)
        row.addWidget(self.remove, 0)

        # Focus on the name or the expression tells the rail where to insert.
        for widget in (self.name, self.value):
            widget.installEventFilter(self)
        line = self.value.lineEdit()
        if line is not None:
            line.installEventFilter(self)

        self.name.textChanged.connect(self._touched)
        self.value.editTextChanged.connect(self._touched)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.FocusIn and (
            obj is self.value or obj is self.value.lineEdit()
        ):
            self.activated.emit(self.value)
        return super().eventFilter(obj, event)

    def set_parts(self, name: str, value: str) -> None:
        self._loading = True
        try:
            self.name.setText(name)
            self.value.setCurrentText(value)
        finally:
            self._loading = False

    def line(self) -> str | None:
        name = self.name.text().strip()
        value = self.value.currentText().strip()
        if not name or not value:
            return None
        return f"{name} = {value}"

    def _touched(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()


class ConditionGroup(QFrame):
    """A dashed box: its logic, its rows, and a way to add one more."""

    changed = Signal()
    removed = Signal(object)
    activated = Signal(object)

    def __init__(self, choices: list, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("conditionGroup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.choices = choices
        self.rows: list[ConditionRow] = []

        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 10)
        column.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self.caption = QLabel("GROUP 1", self)
        self.caption.setObjectName("groupCaption")
        head.addWidget(self.caption)
        self.logic = QComboBox(self)
        self.logic.setObjectName("groupLogic")
        self.logic.addItems(("All (AND)", "Any (OR)"))
        self.logic.setFixedWidth(120)
        self.logic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logic.currentIndexChanged.connect(self._logic_changed)
        head.addWidget(self.logic)
        head.addStretch(1)
        self.remove = QPushButton("×", self)
        self.remove.setObjectName("removeCondition")
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip("remove this group")
        self.remove.setFixedWidth(24)
        self.remove.clicked.connect(lambda: self.removed.emit(self))
        head.addWidget(self.remove)
        column.addLayout(head)

        self.rows_box = QVBoxLayout()
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(6)
        column.addLayout(self.rows_box)

        self.add_button = QPushButton("+  Add condition", self)
        self.add_button.setObjectName("addCondition")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_row)
        column.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)

    def logic_key(self) -> str:
        return "or" if self.logic.currentIndex() == 1 else "and"

    def set_logic(self, key: str) -> None:
        self.logic.setCurrentIndex(1 if key == "or" else 0)

    def add_row(self, parts: dict | None = None) -> ConditionRow:
        row = ConditionRow(self.choices, self)
        if parts:
            row.set_parts(
                parts.get("left", ""), parts.get("op", "<"),
                parts.get("right", ""), bool(parts.get("raw")),
            )
        row.changed.connect(self.changed)
        row.removed.connect(self.remove_row)
        row.activated.connect(self.activated)
        self.rows_box.addWidget(row)
        self.rows.append(row)
        return row

    def remove_row(self, row: ConditionRow) -> None:
        if row not in self.rows:
            return
        self.rows.remove(row)
        self.rows_box.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        if not self.rows:
            self.add_row()
        self.changed.emit()

    def text(self) -> str | None:
        pieces = [value for row in self.rows if (value := row.value())]
        if not pieces:
            return None
        joined = f" {self.logic_key()} ".join(pieces)
        return f"({joined})" if len(pieces) > 1 else joined

    def _logic_changed(self, *_args) -> None:
        self.changed.emit()


class RulesPage(QWidget):
    """The condition groups, the formula they make, and the variables rail."""

    changed = Signal()

    def __init__(
        self,
        parent=None,
        fields=ENTRY_FIELDS,
        functions: dict | None = None,
        condition_label: str = "BUY WHEN",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("entryPage")
        self.fields = tuple(fields)
        self.functions = dict(functions or {})
        self.condition_label = condition_label
        self.choices = _choices(self.fields, self.functions)
        self.assignment_rows: list[AssignmentRow] = []
        self.groups: list[ConditionGroup] = []
        self._loading = False
        self._picker_names: list[str] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Left: the conditions, in a card, with the preview pinned under them.
        card = QFrame(self)
        card.setObjectName("formulaCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        # First the named series (the formula's `name = …` lines), then the
        # condition itself: the same order the language reads them in.
        let_title = QLabel("LET", card)
        let_title.setObjectName("panelTitle")
        card_layout.addWidget(let_title)
        self.assign_box = QVBoxLayout()
        self.assign_box.setContentsMargins(0, 0, 0, 0)
        self.assign_box.setSpacing(6)
        card_layout.addLayout(self.assign_box)
        add_var = QPushButton("+  Add variable", card)
        add_var.setObjectName("addVariable")
        add_var.setCursor(Qt.CursorShape.PointingHandCursor)
        add_var.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        add_var.clicked.connect(lambda: self.add_assignment())
        card_layout.addWidget(add_var, 0, Qt.AlignmentFlag.AlignLeft)

        title = QLabel("CONDITIONS", card)
        title.setObjectName("panelTitle")
        card_layout.addWidget(title)

        scroll = QScrollArea(card)
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("conditionsInner")
        self.groups_box = QVBoxLayout(inner)
        self.groups_box.setContentsMargins(0, 0, 0, 0)
        self.groups_box.setSpacing(8)
        self.groups_box.addStretch(1)
        scroll.setWidget(inner)
        card_layout.addWidget(scroll, 1)

        add_group = QPushButton("+  Add group", card)
        add_group.setObjectName("addGroup")
        add_group.setCursor(Qt.CursorShape.PointingHandCursor)
        add_group.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        add_group.clicked.connect(lambda: self.add_group())
        card_layout.addWidget(add_group, 0, Qt.AlignmentFlag.AlignLeft)

        self.preview = QFrame(card)
        self.preview.setObjectName("conditionPreview")
        self.preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        preview_layout = QVBoxLayout(self.preview)
        preview_layout.setContentsMargins(10, 8, 10, 8)
        preview_layout.setSpacing(4)
        self.preview_text = QLabel(self.preview)
        self.preview_text.setObjectName("conditionText")
        self.preview_text.setWordWrap(True)
        self.preview_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.preview_status = QLabel("— empty", self.preview)
        self.preview_status.setObjectName("conditionStatus")
        preview_layout.addWidget(self.preview_text)
        preview_layout.addWidget(self.preview_status)
        card_layout.addWidget(self.preview)

        root.addWidget(card, 1)

        # Right: the variables. The mock had signal options here, but the
        # backtest models none of them, so the rail holds what the rule can
        # actually use: click a name to drop it into the operand box that has
        # the cursor.
        rail = QFrame(self)
        rail.setObjectName("formulaCard")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail.setFixedWidth(250)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(12, 10, 12, 10)
        rail_layout.setSpacing(8)

        rail_title = QLabel("VARIABLES", rail)
        rail_title.setObjectName("panelTitle")
        rail_layout.addWidget(rail_title)

        hint = QLabel("click one to drop it where the cursor is", rail)
        hint.setObjectName("railNote")
        hint.setWordWrap(True)
        rail_layout.addWidget(hint)

        picker_scroll = QScrollArea(rail)
        picker_scroll.setObjectName("pageScroll")
        picker_scroll.setWidgetResizable(True)
        picker_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.picker_inner = QWidget()
        self.picker_inner.setObjectName("conditionsInner")
        self.picker_layout = QVBoxLayout(self.picker_inner)
        self.picker_layout.setContentsMargins(0, 0, 0, 0)
        self.picker_layout.setSpacing(2)
        self.picker_layout.addStretch(1)
        self.variable_buttons: dict[str, QPushButton] = {}
        self._rebuild_picker()
        picker_scroll.setWidget(self.picker_inner)
        rail_layout.addWidget(picker_scroll, 1)

        root.addWidget(rail, 0)

        self.active_operand: QComboBox | None = None

        self.add_group()
        self._refresh_preview()

    # -- the variables rail ------------------------------------------------

    def _defined_names(self) -> list[str]:
        """The names the LET rows define, in order."""
        names: list[str] = []
        for row in self.assignment_rows:
            name = row.name.text().strip()
            if name and name not in names:
                names.append(name)
        return names

    def _rebuild_picker(self) -> None:
        """Refill the rail: the vocabulary first, then the created names."""
        for button in self.variable_buttons.values():
            self.picker_layout.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self.variable_buttons = {}
        self._picker_names = self._defined_names()
        names = list(self.choices)
        names += [name for name in self._picker_names if name not in names]
        for name in names:
            button = QPushButton(name, self.picker_inner)
            button.setObjectName("variablePick")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"insert {name}")
            if name in self._picker_names:
                button.setProperty("defined", True)
            button.clicked.connect(
                lambda _checked=False, text=name: self.insert_variable(text)
            )
            self.picker_layout.insertWidget(
                self.picker_layout.count() - 1, button
            )
            self.variable_buttons[name] = button

    def _operand_activated(self, combo) -> None:
        self.active_operand = combo

    def insert_variable(self, name: str) -> None:
        """Put `name` in the operand box that last had the cursor.

        It replaces whatever is there: picking a variable fills the box, it
        does not run on the end of what was typed.
        """
        combo = self.active_operand
        if combo is None:
            if self.assignment_rows:
                combo = self.assignment_rows[-1].value
            elif self.groups and self.groups[-1].rows:
                combo = self.groups[-1].rows[-1].left
        if combo is None:
            return
        combo.setCurrentText(name)
        combo.setFocus()

    # -- the groups --------------------------------------------------------

    def add_group(self, logic: str = "and", rows: list | None = None) -> ConditionGroup:
        group = ConditionGroup(self.choices, self)
        group.set_logic(logic)
        group.changed.connect(self._group_changed)
        group.removed.connect(self.remove_group)
        group.activated.connect(self._operand_activated)
        for parts in rows or [None]:
            group.add_row(parts)
        self.groups_box.insertWidget(len(self.groups), group)
        self.groups.append(group)
        self._renumber()
        return group

    def remove_group(self, group: ConditionGroup) -> None:
        if group not in self.groups:
            return
        self.groups.remove(group)
        self.groups_box.removeWidget(group)
        group.setParent(None)
        group.deleteLater()
        if not self.groups:
            self.add_group()
        self._renumber()
        self._group_changed()

    def _renumber(self) -> None:
        for index, group in enumerate(self.groups, 1):
            group.caption.setText(f"GROUP {index}")

    def _group_changed(self) -> None:
        if self._loading:
            return
        if self._defined_names() != self._picker_names:
            self._rebuild_picker()
        self._refresh_preview()
        self.changed.emit()

    # -- the named series --------------------------------------------------

    def add_assignment(self, name: str = "", value: str = "") -> AssignmentRow:
        row = AssignmentRow(self.choices, self)
        if name or value:
            row.set_parts(name, value)
        row.changed.connect(self._group_changed)
        row.removed.connect(self.remove_assignment)
        row.activated.connect(self._operand_activated)
        self.assign_box.addWidget(row)
        self.assignment_rows.append(row)
        self._rebuild_picker()
        return row

    def remove_assignment(self, row: AssignmentRow) -> None:
        if row not in self.assignment_rows:
            return
        self.assignment_rows.remove(row)
        self.assign_box.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._group_changed()

    @property
    def assignments(self) -> list[str]:
        """The `name = …` lines the LET rows add up to."""
        return [
            line
            for row in self.assignment_rows
            if (line := row.line()) is not None
        ]

    # -- the formula -------------------------------------------------------

    def text(self) -> str:
        pieces = [text for group in self.groups if (text := group.text())]
        condition = " and ".join(pieces)
        lines = list(self.assignments)
        if condition:
            lines.append(condition)
        return "\n".join(lines)

    def set_text(self, text: str) -> None:
        """Read a formula into rows; keep anything odd as one raw expression."""
        self._loading = True
        try:
            for group in list(self.groups):
                self.groups_box.removeWidget(group)
                group.setParent(None)
                group.deleteLater()
            self.groups = []
            for row in list(self.assignment_rows):
                self.assign_box.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
            self.assignment_rows = []

            source = (text or "").strip()
            if not source:
                self.add_group()
            else:
                try:
                    formula = parse(source, self.fields, self.functions)
                except FormulaError:
                    raw = self.add_group()
                    raw.rows[0].set_parts(source, "<", "", raw=True)
                else:
                    for item in formula.assignments:
                        self.add_assignment(
                            item.name, expression_text(item.value)
                        )
                    groups = condition_groups(formula.condition)
                    if not groups:
                        self.add_group()
                    for logic, rows in groups:
                        self.add_group(logic, rows)
        finally:
            self._loading = False
        self._rebuild_picker()
        self._refresh_preview()

    def set_status(self, error: str = "", result=None) -> None:
        """Say whether the rows make a valid rule, and what the newest bar said."""
        if error:
            self.preview_status.setText(f"✗ {error}")
            self._set_status_state("error")
            return
        if not self.text().strip():
            self.preview_status.setText("— empty")
            self._set_status_state("idle")
            return
        tail = ""
        if result is not None:
            tail = " · newest bar " + ("TRUE" if result else "FALSE")
        self.preview_status.setText(f"✓ valid{tail}")
        self._set_status_state("ok")

    def _set_status_state(self, state: str) -> None:
        if self.preview_status.property("state") == state:
            return
        self.preview_status.setProperty("state", state)
        style = self.preview_status.style()
        style.unpolish(self.preview_status)
        style.polish(self.preview_status)

    def _refresh_preview(self) -> None:
        text = self.text().strip()
        self.preview_text.setText(text or "— add a condition")
        if not text:
            self.preview_status.setText("— empty")
            self._set_status_state("idle")


__all__ = [
    "COMPARISONS",
    "INDICATORS",
    "AssignmentRow",
    "ConditionGroup",
    "ConditionRow",
    "RulesPage",
    "condition_groups",
    "expression_text",
]
