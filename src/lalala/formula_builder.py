"""The drag-and-drop formula builder for the ENTRY RULES tile.

A formula is built from chips. A subtile holds the sources — three lists of
things to drag, `Data`, `Indicators`, `Logic & Maths`, and a box to type a
number into — and under it the lines you drop them on. Each line is a strip of
chips read left to right; the last line is the condition, the ones above it are
named series:

    [mid] [=] [sma] [(] [close] [,] [▢] [)]
    [close] [<] [mid]

An indicator drops in with its parentheses and comma already placed and an
empty **slot** — a dashed chip — where its period goes. Fill a slot by dragging
a number chip onto it, or by clicking it and typing a value in the number box.

The chips are only an editor. The formula **text** is the truth: it is rebuilt
from the chips and handed to `lalala.formula.parse`, so the same checker still
reports `line 2, column 9: unknown name 'clsoe'`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from lalala.formula import FormulaError, parse, scan, tokens_to_text
from lalala.cards import mono_font

MIME = "application/x-lalala-chip"
_NUMBER = re.compile(r"\d+\.\d*|\.\d+|\d+")


@dataclass(frozen=True)
class Item:
    """One draggable source. A `None` token is an empty slot."""

    label: str
    tokens: tuple
    note: str = ""


PALETTES: tuple = (
    (
        "Data",
        (
            Item("close", ("close",), "the bar's closing price"),
            Item("open", ("open",)),
            Item("high", ("high",)),
            Item("low", ("low",)),
            Item("volume", ("volume",)),
        ),
    ),
    (
        "Indicators",
        (
            Item("SMA", ("sma", "(", "close", ",", None, ")"), "sma(close, period)"),
            Item("EMA", ("ema", "(", "close", ",", None, ")"), "ema(close, period)"),
            Item("RSI", ("rsi", "(", "close", ",", None, ")"), "rsi(close, period)"),
            Item("Highest", ("highest", "(", "high", ",", None, ")"), "highest(high, period)"),
            Item("Lowest", ("lowest", "(", "low", ",", None, ")"), "lowest(low, period)"),
            Item("Change", ("change", "(", "close", ",", None, ")"), "change(close, bars)"),
            Item("Shift", ("shift", "(", "close", ",", None, ")"), "shift(close, bars)"),
            Item("Boll low", ("bollinger_lower", "(", "close", ",", None, ",", None, ")"), "bollinger_lower(close, period, dev)"),
            Item("Boll mid", ("bollinger_middle", "(", "close", ",", None, ",", None, ")"), "bollinger_middle(close, period, dev)"),
            Item("Boll up", ("bollinger_upper", "(", "close", ",", None, ",", None, ")"), "bollinger_upper(close, period, dev)"),
        ),
    ),
    (
        "Logic & Maths",
        (
            Item("and", ("and",)),
            Item("or", ("or",)),
            Item("not", ("not",)),
            Item("=", ("=",), "assigns the line above to a name"),
            Item("(", ("(",)),
            Item(")", (")",)),
            Item(",", (",",)),
            Item("+", ("+",)),
            Item("−", ("-",)),
            Item("×", ("*",)),
            Item("÷", ("/",)),
            Item("%", ("%",)),
            Item("^", ("^",)),
            Item("<", ("<",)),
            Item("<=", ("<=",)),
            Item(">", (">",)),
            Item(">=", (">=",)),
            Item("==", ("==",)),
            Item("!=", ("!=",)),
        ),
    ),
)


def _decode(mime) -> dict | None:
    if mime is None or not mime.hasFormat(MIME):
        return None
    try:
        return json.loads(bytes(mime.data(MIME).data()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):  # pragma: no cover - defensive
        return None


def _single(mime) -> str | None:
    payload = _decode(mime)
    if not payload:
        return None
    tokens = payload.get("tokens") or []
    if len(tokens) == 1 and tokens[0] is not None:
        return tokens[0]
    return None


def _begin_drag(widget: QWidget, tokens: list, source=None) -> None:
    """Start a drag carrying `tokens`; `source` marks an internal chip move."""
    data = QMimeData()
    data.setData(
        MIME,
        json.dumps({"tokens": list(tokens), "from": source}).encode("utf-8"),
    )
    drag = QDrag(widget)
    drag.setMimeData(data)
    drag.exec(
        Qt.DropAction.CopyAction if source is None else Qt.DropAction.MoveAction
    )


class FlowLayout(QLayout):
    """A layout that wraps its items onto the next row when the width runs out.

    A formula line can be longer than the tile is wide; wrapping keeps every
    chip visible instead of clipping the tail.
    """

    def __init__(self, parent=None, margin: int = 0, spacing: int = 3) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def addWidget(self, widget) -> None:  # noqa: N802
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def insertWidget(self, index: int, widget) -> None:  # noqa: N802
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))

    def removeWidget(self, widget) -> None:  # noqa: N802
        for index, item in enumerate(self._items):
            if item.widget() is widget:
                self.takeAt(index)
                return

    def _layout(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        inner = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        spacing = self.spacing()
        x, y, row = inner.x(), inner.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > inner.right() + 1 and row > 0:
                x, y, row = inner.x(), y + row + spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + spacing
            row = max(row, hint.height())
        return y + row - rect.y() + margins.bottom()


class PaletteBlock(QFrame):
    """One block in a palette row: a thing you drag out, never into."""

    def __init__(self, item: Item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._press: QPoint | None = None
        self.setObjectName("paletteBlock")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(item.note or f"drag {item.label} onto a line")

        self.label = QLabel(item.label, self)
        self.label.setObjectName("paletteBlockLabel")
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 2, 7, 2)
        layout.addWidget(self.label)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None:
            return
        moved = (event.position().toPoint() - self._press).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        self._press = None
        _begin_drag(self, list(self.item.tokens))


class Chip(QFrame):
    """One token on a line. A `None` token is an empty slot to be filled."""

    def __init__(self, token, builder: "FormulaBuilder", parent=None) -> None:
        super().__init__(parent)
        self.token = token
        self.builder = builder
        self.strip = None
        self._press: QPoint | None = None
        self.setObjectName("formulaChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.label = QLabel(self)
        self.label.setObjectName("chipLabel")
        # The frame wants the mouse, not the label inside it.
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 6, 1)
        layout.addWidget(self.label)
        self._apply()

    # -- state -------------------------------------------------------------

    def set_token(self, token) -> None:
        self.token = token
        self._apply()

    def set_armed(self, armed: bool) -> None:
        if bool(self.property("armed")) == armed:
            return
        self.setProperty("armed", armed)
        self._repolish()

    def _apply(self) -> None:
        self.label.setText("▢" if self.token is None else str(self.token))
        self.setProperty("slot", self.token is None)
        self.setAcceptDrops(self.token is None)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self.token is None
            else Qt.CursorShape.OpenHandCursor
        )
        self.setToolTip(
            "empty slot — drop a number in, or click it and type one"
            if self.token is None
            else "drag to move · double-click to remove"
        )
        self._repolish()

    def _repolish(self) -> None:
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    # -- dragging ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None or self.token is None:
            return
        moved = (event.position().toPoint() - self._press).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        self._press = None
        self.builder.start_chip_drag(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._press is not None and self.token is None:
            # A click, not a drag, on a slot: arm it for the number box.
            self.builder.arm_slot(self)
        self._press = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.token is not None:
            self.builder.remove_chip(self)

    # -- dropping into a slot ---------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self.token is None and _single(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self.token is None and _single(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        token = _single(event.mimeData())
        if self.token is None and token is not None:
            self.builder.fill_slot(self, token, event.mimeData())
            event.acceptProposedAction()


class ChipStrip(QFrame):
    """A line of chips: the drop target, read left to right."""

    def __init__(self, builder: "FormulaBuilder", parent=None) -> None:
        super().__init__(parent)
        self.builder = builder
        self.setObjectName("chipStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(30)
        self._chips: list[Chip] = []
        self._layout = FlowLayout(self, margin=4, spacing=3)
        policy = QSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    # -- contents ----------------------------------------------------------

    def chips(self) -> list[Chip]:
        return list(self._chips)

    def tokens(self) -> list:
        return [chip.token for chip in self._chips]

    def text(self) -> str:
        return tokens_to_text(self.tokens())

    def has_empty_slots(self) -> bool:
        return any(chip.token is None for chip in self._chips)

    def add_chip(self, token, index: int | None = None) -> Chip:
        chip = Chip(token, self.builder, self)
        chip.strip = self
        at = len(self._chips) if index is None else max(0, min(index, len(self._chips)))
        self._chips.insert(at, chip)
        self._layout.insertWidget(at, chip)
        return chip

    def remove_chip(self, chip: Chip) -> None:
        if chip not in self._chips:
            return
        self._chips.remove(chip)
        self._layout.removeWidget(chip)
        chip.setParent(None)
        chip.deleteLater()

    def set_tokens(self, tokens) -> None:
        for chip in list(self._chips):
            self.remove_chip(chip)
        for token in tokens:
            self.add_chip(token)

    def _insert_index(self, point: QPoint) -> int:
        # Reading order: the first chip whose centre is below, or to the right
        # on the same row.
        for index, chip in enumerate(self._chips):
            centre = chip.geometry().center()
            if point.y() < centre.y() - chip.height() // 2:
                return index
            if (
                abs(point.y() - centre.y()) <= chip.height() // 2
                and point.x() < centre.x()
            ):
                return index
        return len(self._chips)

    # -- dropping ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.builder.set_active(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _decode(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if _decode(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        payload = _decode(event.mimeData())
        if payload is None:
            return
        index = self._insert_index(event.position().toPoint())
        self.builder.drop_tokens(payload, self, index)
        event.acceptProposedAction()


class FormulaBuilder(QWidget):
    """The palettes, the lines, and the text they add up to."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("formulaBuilder")
        self.strips: list[ChipStrip] = []
        self.active: ChipStrip | None = None
        self.armed: Chip | None = None
        self._parsed = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.addWidget(self._palettes())
        root.addWidget(self._canvas(), 1)

        self.add_strip()

    # -- the palette subtile ----------------------------------------------

    def _palettes(self) -> QWidget:
        box = QFrame(self)
        box.setObjectName("formulaPalette")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # The rows scroll if there is not room for all of them, so a block is
        # never cut off.
        scroll = QScrollArea(box)
        scroll.setObjectName("paletteScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("paletteInner")
        rows = QVBoxLayout(inner)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(5)

        self.blocks: dict[str, list[PaletteBlock]] = {}
        for title, items in PALETTES:
            rows.addLayout(self._palette_row(inner, title, items))
        rows.addLayout(self._number_row(inner))
        rows.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        return box

    def _palette_row(
        self, parent: QWidget, title: str, items: tuple
    ) -> QHBoxLayout:
        """A caption, then the blocks of one group, side by side and wrapping."""
        row = QHBoxLayout()
        row.setSpacing(8)
        caption = QLabel(title, parent)
        caption.setObjectName("paletteTitle")
        caption.setFixedWidth(84)
        row.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)

        holder = QWidget(parent)
        holder.setObjectName("paletteBlocks")
        flow = FlowLayout(holder, margin=0, spacing=4)
        blocks: list[PaletteBlock] = []
        for item in items:
            block = PaletteBlock(item, holder)
            flow.addWidget(block)
            blocks.append(block)
        self.blocks[title] = blocks
        row.addWidget(holder, 1)
        return row

    def _number_row(self, parent: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        caption = QLabel("Number", parent)
        caption.setObjectName("paletteTitle")
        caption.setFixedWidth(84)
        row.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)

        self.number_edit = QLineEdit(parent)
        self.number_edit.setObjectName("numberEdit")
        self.number_edit.setPlaceholderText("20")
        self.number_edit.setFixedWidth(72)
        self.number_edit.setToolTip(
            "type a value; Enter adds it, or fills the armed slot"
        )
        self.number_edit.returnPressed.connect(self.add_number)
        self.number_add = QPushButton("Add", parent)
        self.number_add.setObjectName("numberAdd")
        self.number_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.number_add.clicked.connect(self.add_number)
        row.addWidget(self.number_edit)
        row.addWidget(self.number_add)
        row.addStretch(1)
        return row

    # -- the canvas --------------------------------------------------------

    def _canvas(self) -> QWidget:
        box = QWidget(self)
        box.setObjectName("formulaCanvas")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        caption = QLabel("formula", box)
        caption.setObjectName("paletteTitle")
        tools.addWidget(caption)
        tools.addStretch(1)
        self.add_line_button = QPushButton("+ line", box)
        self.drop_line_button = QPushButton("− line", box)
        for button in (self.add_line_button, self.drop_line_button):
            button.setObjectName("lineButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            tools.addWidget(button)
        self.add_line_button.clicked.connect(lambda: self.add_strip())
        self.drop_line_button.clicked.connect(self.remove_active_strip)
        layout.addLayout(tools)

        self.strip_area = QScrollArea(box)
        self.strip_area.setObjectName("stripArea")
        self.strip_area.setWidgetResizable(True)
        self.strip_area.setFrameShape(QFrame.Shape.NoFrame)
        self.strip_area.setMinimumHeight(64)
        holder = QWidget()
        holder.setObjectName("stripHolder")
        self.strip_layout = QVBoxLayout(holder)
        self.strip_layout.setContentsMargins(0, 0, 0, 0)
        self.strip_layout.setSpacing(4)
        self.strip_layout.addStretch(1)
        self.strip_area.setWidget(holder)
        layout.addWidget(self.strip_area, 1)

        self.preview_label = QLabel(box)
        self.preview_label.setObjectName("formulaPreview")
        self.preview_label.setFont(mono_font(9))
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.error_label = QLabel(box)
        self.error_label.setObjectName("formulaError")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.error_label)
        return box

    # -- lines -------------------------------------------------------------

    def add_strip(self, tokens=None, at: int | None = None) -> ChipStrip:
        strip = ChipStrip(self, self.strip_area.widget())
        if tokens:
            strip.set_tokens(tokens)
        index = len(self.strips) if at is None else at
        self.strips.insert(index, strip)
        self.strip_layout.insertWidget(index, strip)
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
        self.changed.emit()
        self._refresh()

    def remove_active_strip(self) -> None:
        self.remove_strip(self.active or self.strips[-1])

    def set_active(self, strip: ChipStrip) -> None:
        self.active = strip

    # -- chips -------------------------------------------------------------

    def start_chip_drag(self, chip: Chip) -> None:
        strip = chip.strip
        if strip is None or chip.token is None:
            return
        _begin_drag(
            chip,
            [chip.token],
            source=[self.strips.index(strip), strip.chips().index(chip)],
        )

    def remove_chip(self, chip: Chip) -> None:
        if chip.strip is None:
            return
        chip.strip.remove_chip(chip)
        self.changed.emit()
        self._refresh()

    def drop_tokens(self, payload: dict, strip: ChipStrip, index: int) -> None:
        tokens = payload.get("tokens") or []
        source = payload.get("from")
        if source:
            source_strip, source_index = source
            self._remove_at(source_strip, source_index)
            if source_strip == self.strips.index(strip) and source_index < index:
                index -= 1
        for offset, token in enumerate(tokens):
            strip.add_chip(token, index + offset)
        self.active = strip
        self.changed.emit()
        self._refresh()

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
        self.number_edit.setPlaceholderText("20")

    def fill_slot(self, chip: Chip, token: str, mime=None) -> None:
        if mime is not None:
            payload = _decode(mime)
            if payload and payload.get("from"):
                self._remove_at(*payload["from"])
        chip.set_token(token)
        self._disarm()
        self.changed.emit()
        self._refresh()

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
            self.changed.emit()
            self._refresh()
        self.number_edit.clear()

    # -- the formula -------------------------------------------------------

    def formula_text(self) -> str:
        return "\n".join(
            strip.text() for strip in self.strips if strip.tokens()
        )

    def error(self) -> str:
        return self.error_label.text()

    def parsed(self):
        return self._parsed

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
            return
        lines: dict[int, list[str]] = {}
        order: list[int] = []
        for token in tokens:
            if token.line not in lines:
                lines[token.line] = []
                order.append(token.line)
            lines[token.line].append(token.text)
        for line in order:
            self.add_strip(lines[line])
        self.changed.emit()
        self._refresh()

    def _refresh(self) -> None:
        text = self.formula_text()
        self.preview_label.setText(text if text else "— drop items onto a line below")
        self.drop_line_button.setEnabled(len(self.strips) > 1)
        if any(strip.has_empty_slots() for strip in self.strips):
            self._parsed = None
            self.error_label.setText("fill the empty slot before this can be read")
            return
        if not text.strip():
            self._parsed = None
            self.error_label.setText("")
            return
        try:
            self._parsed = parse(text)
        except FormulaError as exc:
            self._parsed = None
            self.error_label.setText(str(exc))
        else:
            self.error_label.setText("")


__all__ = [
    "MIME",
    "PALETTES",
    "Chip",
    "ChipStrip",
    "FlowLayout",
    "FormulaBuilder",
    "Item",
    "PaletteBlock",
]
