"""The Rules tab: conditions in groups, the way the mock draws them.

A rule is a few comparisons over the bar (or the open trade), gathered into
groups. Each group joins its rows with **All (AND)** or **Any (OR)**, and the
groups themselves are joined with AND — the same shape the formula language
gives `a and b and (c or d)`.

This page is another way to write the same formula as the Formula and Code
tabs. It reads any formula whose condition is a flat AND / OR of comparisons,
keeping `name = …` lines verbatim above it. A condition it cannot break into
rows is kept as one raw expression, so switching tabs never rewrites the rule.

The right rail mirrors the mock's **Signal options**, but those controls are
disabled: confirmation bars, cooldown and maximum entries are not part of the
backtest yet.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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


class ConditionRow(QFrame):
    """One comparison: an operand, an operator and a value."""

    changed = Signal()
    removed = Signal(object)

    def __init__(self, choices: list, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("conditionRow")
        self._loading = False
        self._raw = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.left = self._combo(choices, "condition")
        self.op = QComboBox(self)
        self.op.setObjectName("conditionOp")
        self.op.addItems(COMPARISONS)
        self.op.setFixedWidth(62)
        self.op.setCursor(Qt.CursorShape.PointingHandCursor)
        self.right = self._combo(choices, "value")
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

        self.left.editTextChanged.connect(self._touched)
        self.right.editTextChanged.connect(self._touched)
        self.op.currentIndexChanged.connect(self._touched)

    def _combo(self, choices: list, placeholder: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setObjectName("conditionOperand")
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItems(choices)
        combo.setCurrentText("")
        if combo.lineEdit() is not None:
            combo.lineEdit().setPlaceholderText(placeholder)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        return combo

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


class ConditionGroup(QFrame):
    """A dashed box: its logic, its rows, and a way to add one more."""

    changed = Signal()
    removed = Signal(object)

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
    """The condition groups, the formula they make, and the signal rail."""

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
        self.assignments: list[str] = []
        self.groups: list[ConditionGroup] = []
        self._loading = False

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

        # Right: the mock's signal rail, shown disabled — the backtest does
        # not model any of it yet.
        rail = QFrame(self)
        rail.setObjectName("formulaCard")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail.setFixedWidth(250)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(12, 10, 12, 10)
        rail_layout.setSpacing(8)

        rail_title = QLabel("SIGNAL OPTIONS", rail)
        rail_title.setObjectName("panelTitle")
        rail_layout.addWidget(rail_title)

        side = QComboBox(rail)
        side.addItems(("YES", "NO", "Either, from the signal"))
        side.setEnabled(False)
        self.side_combo = side
        self._rail_field(rail_layout, "Side to buy", side, rail)

        bars = QLineEdit("1", rail)
        bars.setObjectName("numberEdit")
        bars.setAlignment(Qt.AlignmentFlag.AlignRight)
        bars.setEnabled(False)
        self.confirmation_edit = bars
        self._rail_field(rail_layout, "Confirmation (bars)", bars, rail)

        cooldown = QLineEdit("6", rail)
        cooldown.setObjectName("numberEdit")
        cooldown.setAlignment(Qt.AlignmentFlag.AlignRight)
        cooldown.setEnabled(False)
        self.cooldown_edit = cooldown
        self._rail_field(rail_layout, "Cooldown after exit (h)", cooldown, rail)

        entries = QLineEdit("2", rail)
        entries.setObjectName("numberEdit")
        entries.setAlignment(Qt.AlignmentFlag.AlignRight)
        entries.setEnabled(False)
        self.entries_edit = entries
        self._rail_field(rail_layout, "Max entries per market", entries, rail)

        together = QCheckBox("One position at a time", rail)
        together.setObjectName("signalOption")
        together.setChecked(True)
        together.setEnabled(False)
        self.together = together
        rail_layout.addWidget(together)

        note = QLabel(
            "signal options are not part of the backtest yet", rail
        )
        note.setObjectName("railNote")
        note.setWordWrap(True)
        rail_layout.addWidget(note)
        rail_layout.addStretch(1)

        root.addWidget(rail, 0)

        self.add_group()
        self._refresh_preview()

    # -- the rail ----------------------------------------------------------

    @staticmethod
    def _rail_field(layout, caption: str, widget: QWidget, parent: QWidget) -> None:
        label = QLabel(caption, parent)
        label.setObjectName("railLabel")
        layout.addWidget(label)
        layout.addWidget(widget)

    # -- the groups --------------------------------------------------------

    def add_group(self, logic: str = "and", rows: list | None = None) -> ConditionGroup:
        group = ConditionGroup(self.choices, self)
        group.set_logic(logic)
        group.changed.connect(self._group_changed)
        group.removed.connect(self.remove_group)
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
        self._refresh_preview()
        self.changed.emit()

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
            self.assignments = []

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
                    self.assignments = [
                        f"{item.name} = {expression_text(item.value)}"
                        for item in formula.assignments
                    ]
                    groups = condition_groups(formula.condition)
                    if not groups:
                        self.add_group()
                    for logic, rows in groups:
                        self.add_group(logic, rows)
        finally:
            self._loading = False
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
    "ConditionGroup",
    "ConditionRow",
    "RulesPage",
    "condition_groups",
    "expression_text",
]
