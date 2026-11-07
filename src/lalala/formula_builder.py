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
from the chips and handed to `lalala.formula.parse`, so the same checker still
reports `line 2, column 9: unknown name 'clsoe'`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from lalala.cards import mono_font
from lalala.formula import (
    ENTRY_FIELDS,
    EXIT_FIELDS,
    FIELDS,
    NO_HISTORY,
    FUNCTIONS,
    FormulaError,
    parse,
    scan,
    tokens_to_text,
)
from lalala.theme import BORDER, TEXT_FAINT

MIME = "application/x-lalala-chip"
HANDLE = "⠿"
LOGIC_WORDS = ("and", "or", "not")
# Names that read as "the bar" or "the trade": both are data, coloured alike.
DATA_NAMES = frozenset(ENTRY_FIELDS) | frozenset(EXIT_FIELDS)


@dataclass(frozen=True)
class Item:
    """One draggable source.

    A plain item drops the tokens it carries — a field, an operator, a number.
    A `call` item is an indicator: it drops as a single tile that knows its
    function, the series it reads and its own numbers.
    """

    label: str
    tokens: tuple = ()
    note: str = ""
    call: tuple | None = None  # (func, series, params, label)
    missing: bool = False      # named, but nothing here carries it


LOGIC_ITEMS: tuple = (
    Item("AND", ("and",)),
    Item("OR", ("or",)),
    Item("NOT", ("not",)),
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
    Item("log", ("log",), "natural log"),
    Item("<", ("<",)),
    Item("<=", ("<=",)),
    Item(">", (">",)),
    Item(">=", (">=",)),
    Item("==", ("==",)),
    Item("!=", ("!=",)),
)


PALETTES: tuple = (
    (
        "Data",
        (
            Item("close", ("close",), "the bar's closing price"),
            Item("open", ("open",)),
            Item("high", ("high",)),
            Item("low", ("low",)),
            Item("volume", ("volume",)),
            Item("model_p", ("model_p",), "a model's probability — no history here",
                 missing=True),
            Item("spread", ("spread",), "the bid/ask spread — no history here",
                 missing=True),
            Item("liquidity", ("liquidity",), "book depth — no history here",
                 missing=True),
            Item("days_left", ("days_left",), "time to expiry — no history here",
                 missing=True),
        ),
    ),
    (
        "Indicators",
        (
            Item("SMA", note="sma(close, period)", call=("sma", "close", ("20",), "SMA")),
            Item("EMA", note="ema(close, period)", call=("ema", "close", ("20",), "EMA")),
            Item("RSI", note="rsi(close, period)", call=("rsi", "close", ("14",), "RSI")),
            Item("Highest", note="highest(high, period)", call=("highest", "high", ("20",), "Highest")),
            Item("Lowest", note="lowest(low, period)", call=("lowest", "low", ("20",), "Lowest")),
            Item("Change", note="change(close, bars)", call=("change", "close", ("1",), "Change")),
            Item("Shift", note="shift(close, bars)", call=("shift", "close", ("1",), "Shift")),
            Item("Boll low", note="bollinger_lower(close, period, dev)", call=("bollinger_lower", "close", ("20", "2"), "Boll low")),
            Item("Boll mid", note="bollinger_middle(close, period, dev)", call=("bollinger_middle", "close", ("20", "2"), "Boll mid")),
            Item("Boll up", note="bollinger_upper(close, period, dev)", call=("bollinger_upper", "close", ("20", "2"), "Boll up")),
            Item("σ", note="stdev(close, period)", call=("stdev", "close", ("20",), "σ")),
            Item("zscore", note="zscore(close, period)", call=("zscore", "close", ("20",), "zscore")),
        ),
    ),
    ("Logic & Maths", LOGIC_ITEMS),
)

# An exit rule sees the open trade, not the bar, and takes no indicators.
EXIT_PALETTES: tuple = (
    (
        "Trade",
        (
            Item("price", ("price",), "the close while the trade is open"),
            Item("entry", ("entry",), "the price the trade was opened at"),
            Item("PNL", ("pnl",), "the open trade's profit or loss, in %"),
            Item("TP", ("tp",), "the take-profit threshold, in %"),
            Item("SL", ("sl",), "the stop-loss threshold, in %"),
            Item("bars", ("bars",), "bars the trade has been open"),
        ),
    ),
    ("Logic & Maths", LOGIC_ITEMS),
)


def group_for_token(token) -> str:
    """Which colour a chip wears: data, indicator, logic or maths."""
    if token in (None, ""):
        return ""
    if token in DATA_NAMES:
        return "data"
    if token in FUNCTIONS:
        return "indicator"
    if token in LOGIC_WORDS:
        return "logic"
    return "maths"


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


def drag_pixmap(widget: QWidget):
    """The picture a drag carries: the widget itself, no bigger."""
    return widget.grab()


def _begin_drag(widget: QWidget, tokens: list, source=None, hotspot=None, call=None) -> None:
    """Start a drag; `source` marks an internal move, `call` an indicator tile.

    The drag carries a picture of the widget itself, so what is being moved is
    visible under the cursor — the block, not a blank rectangle.
    """
    data = QMimeData()
    payload: dict = {"tokens": list(tokens), "from": source}
    if call is not None:
        payload["call"] = {
            "func": call[0],
            "series": call[1],
            "params": list(call[2]),
            "label": call[3],
        }
    data.setData(MIME, json.dumps(payload).encode("utf-8"))
    drag = QDrag(widget)
    drag.setMimeData(data)
    picture = drag_pixmap(widget)
    drag.setPixmap(picture)
    if hotspot is not None:
        drag.setHotSpot(
            QPoint(
                max(0, min(hotspot.x(), picture.width() - 1)),
                max(0, min(hotspot.y(), picture.height() - 1)),
            )
        )
    drag.exec(
        Qt.DropAction.CopyAction if source is None else Qt.DropAction.MoveAction
    )


class FlowLayout(QLayout):
    """A layout that wraps its items onto the next row when the width runs out.

    A formula line can be longer than the tile is wide; wrapping keeps every
    chip visible instead of clipping the tail.
    """

    def __init__(self, parent=None, margin: int = 0, spacing: int = 4) -> None:
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

    def _visible(self) -> list:
        return [
            item
            for item in self._items
            if item.widget() is None or not item.widget().isHidden()
        ]

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._visible():
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

    def _rows(self, inner_width: int) -> list:
        """Group the visible items into rows that fit `inner_width`."""
        rows: list = []
        current: list = []
        width = 0
        spacing = self.spacing()
        for item in self._visible():
            hint = item.sizeHint()
            if current and width + hint.width() > inner_width + 1:
                rows.append((current, width - spacing))
                current, width = [], 0
            current.append((item, hint))
            width += hint.width() + spacing
        if current:
            rows.append((current, width - spacing))
        return rows

    def _layout(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        inner = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        spacing = self.spacing()
        y = inner.y()
        rows = self._rows(inner.width())
        for items, _total in rows:
            x = inner.x()
            height = 0
            for item, hint in items:
                if apply:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + spacing
                height = max(height, hint.height())
            y += height + spacing
        if rows:
            y -= spacing
        return y - rect.y() + margins.bottom()


class PaletteBlock(QFrame):
    """One block in a palette row: a thing you drag out, never into."""

    def __init__(self, item: Item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._press: QPoint | None = None
        self.setObjectName("paletteBlock")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty(
            "group",
            "indicator" if item.call else group_for_token(item.tokens[0]),
        )
        self.setProperty("missing", bool(item.missing))
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(item.note or f"drag {item.label} onto a line")

        self.handle = QLabel(HANDLE, self)
        self.handle.setObjectName("dragHandle")
        self.label = QLabel(item.label, self)
        self.label.setObjectName("blockLabel")
        for child in (self.handle, self.label):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 2, 9, 2)
        layout.setSpacing(4)
        layout.addWidget(self.handle)
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
        hotspot = self._press
        self._press = None
        if self.item.call is not None:
            _begin_drag(self, [], hotspot=hotspot, call=self.item.call)
        else:
            _begin_drag(self, list(self.item.tokens), hotspot=hotspot)


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

        self.handle = QLabel(HANDLE, self)
        self.handle.setObjectName("dragHandle")
        self.label = QLabel(self)
        self.label.setObjectName("chipLabel")
        self.remove_button = QPushButton("×", self)
        self.remove_button.setObjectName("chipRemove")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setToolTip("take this off the line")
        self.remove_button.clicked.connect(lambda: builder.remove_chip(self))
        for child in (self.handle, self.label):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)
        self._layout = layout
        layout.addWidget(self.handle)
        layout.addWidget(self.label)
        layout.addWidget(self.remove_button)
        self._apply()

    # -- state -------------------------------------------------------------

    def is_slot(self) -> bool:
        return self.token is None

    def tokens(self) -> list:
        """The formula tokens this chip stands for."""
        return [self.token]

    def set_token(self, token) -> None:
        self.token = token
        self._apply()

    def set_armed(self, armed: bool) -> None:
        if bool(self.property("armed")) == armed:
            return
        self.setProperty("armed", armed)
        self._repolish()

    def group(self) -> str:
        return group_for_token(self.token)

    def _apply(self) -> None:
        slot = self.token is None
        self.label.setText("▢" if slot else str(self.token))
        self.setProperty("slot", slot)
        self.setProperty("group", self.group())
        self.handle.setVisible(not slot)
        self.remove_button.setVisible(not slot)
        self.setAcceptDrops(slot)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if slot
            else Qt.CursorShape.OpenHandCursor
        )
        self.setToolTip(
            "empty slot — drop a number in, or click it and type one"
            if slot
            else "drag by the handle · × takes it off"
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
        if self._press is None or self.is_slot():
            return
        moved = (event.position().toPoint() - self._press).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        hotspot = self._press
        self._press = None
        self.builder.start_chip_drag(self, hotspot)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._press is not None and self.is_slot():
            # A click, not a drag, on a slot: arm it for the number box.
            self.builder.arm_slot(self)
        self._press = None

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


class CallChip(Chip):
    """An indicator as a single tile, with its own numbers inside it.

    One tile stands for the whole call — `SMA` with a field for its period
    reads as `sma(close, 20)`. Nothing else is added alongside it.
    """

    def __init__(
        self,
        func: str,
        series: str,
        params,
        label: str,
        builder: "FormulaBuilder",
        parent=None,
    ) -> None:
        self.func = func
        self.series = series
        self.param_values = [str(value) for value in params]
        self.display = label
        super().__init__(None, builder, parent)
        self.label.setText(label)

        layout = self.layout()
        self.fields: list[QLineEdit] = []
        for value in self.param_values:
            field = QLineEdit(value, self)
            field.setObjectName("chipField")
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setFixedWidth(34)
            field.setToolTip("the period or deviation this indicator uses")
            field.textChanged.connect(self._on_param)
            self.fields.append(field)
            # Before the remove button, which is the last thing in the row.
            layout.insertWidget(layout.count() - 1, field)

    # -- state -------------------------------------------------------------

    def is_slot(self) -> bool:
        return False

    def group(self) -> str:
        return "indicator"

    def tokens(self) -> list:
        tokens = [self.func, "(", self.series]
        for value in self.param_values:
            tokens += [",", value]
        tokens.append(")")
        return tokens

    def call(self) -> tuple:
        return (self.func, self.series, tuple(self.param_values), self.display)

    def _on_param(self, _text: str) -> None:
        for index, field in enumerate(self.fields):
            self.param_values[index] = field.text()
        self.builder.contents_changed()

    def _apply(self) -> None:
        # Not a slot, and coloured as an indicator whatever it holds.
        self.setProperty("slot", False)
        self.setProperty("group", "indicator")
        self.handle.setVisible(True)
        self.remove_button.setVisible(True)
        self.setAcceptDrops(False)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("drag by the handle · edit the numbers in place")
        self._repolish()


class DropZone(QWidget):
    """The blank run of a line: the chips' flow, and the dashed hint."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.empty = True
        self.flow = FlowLayout(self, margin=0, spacing=4)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.sync_height()

    def sync_height(self) -> None:
        """Hold just the height the flow wraps to at the width we have.

        `heightForWidth` does not survive the chain of nested layouts between
        here and the tile, so the height is pinned instead: the parent layout
        then has a number to lay out with, and a new width re-pins it.
        """
        if self.width() <= 0:
            return
        wanted = self.flow.heightForWidth(self.width())
        if self.minimumHeight() != wanted:
            self.setFixedHeight(wanted)

    def set_empty(self, empty: bool) -> None:
        if empty != self.empty:
            self.empty = empty
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.empty:
            return
        painter = QPainter(self)
        pen = QPen(QColor(BORDER), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 11, 11)
        painter.setFont(mono_font(9))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "drag a block here")


class FlowHolder(QWidget):
    """A row of blocks that pins its height to what it wraps to."""

    def __init__(self, parent=None, spacing: int = 5) -> None:
        super().__init__(parent)
        self.setObjectName("paletteBlocks")
        self.flow = FlowLayout(self, margin=0, spacing=spacing)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.sync_height()

    def sync_height(self) -> None:
        """Hold just the height the row wraps to at the width we have."""
        if self.width() <= 0:
            return
        wanted = self.flow.heightForWidth(self.width())
        if self.minimumHeight() != wanted:
            self.setFixedHeight(wanted)

    def sizeHint(self) -> QSize:  # noqa: N802
        width = self.width() or 240
        return QSize(width, max(1, self.flow.heightForWidth(width)))


class ChipStrip(QFrame):
    """A line: a caption, a run of chips, and a way to take the line away."""

    def __init__(self, builder: "FormulaBuilder", parent=None) -> None:
        super().__init__(parent)
        self.builder = builder
        self.setObjectName("chipStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(34)
        self._chips: list[Chip] = []

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(8)

        self.caption = QLabel("", self)
        self.caption.setObjectName("stripCaption")
        self.caption.setFixedWidth(30)
        row.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignVCenter)

        self.zone = DropZone(self)
        self._flow = self.zone.flow
        row.addWidget(self.zone, 1)

        self.remove_button = QPushButton("×", self)
        self.remove_button.setObjectName("stripRemove")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setToolTip("take this line away")
        self.remove_button.clicked.connect(lambda: builder.remove_strip(self))
        row.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignVCenter)

    # -- contents ----------------------------------------------------------

    def chips(self) -> list[Chip]:
        return list(self._chips)

    def tokens(self) -> list:
        result: list = []
        for chip in self._chips:
            result.extend(chip.tokens())
        return result

    def text(self) -> str:
        return tokens_to_text(self.tokens())

    def has_empty_slots(self) -> bool:
        return any(chip.is_slot() for chip in self._chips)

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)

    def add_chip(self, token, index: int | None = None) -> Chip:
        chip = Chip(token, self.builder, self.zone)
        return self._place(chip, index)

    def add_call_chip(self, spec, index: int | None = None) -> CallChip:
        """An indicator as one tile: its numbers live inside it."""
        func, series, params, label = spec
        chip = CallChip(func, series, params, label, self.builder, self.zone)
        return self._place(chip, index)

    def _place(self, chip, index: int | None):
        chip.strip = self
        at = len(self._chips) if index is None else max(0, min(index, len(self._chips)))
        self._chips.insert(at, chip)
        self._flow.insertWidget(at, chip)
        self.zone.set_empty(False)
        self.zone.sync_height()
        return chip

    def remove_chip(self, chip: Chip) -> None:
        if chip not in self._chips:
            return
        self._chips.remove(chip)
        self._flow.removeWidget(chip)
        chip.setParent(None)
        chip.deleteLater()
        self.zone.set_empty(not self._chips)
        self.zone.sync_height()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.zone.sync_height()

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
            self._set_target(True)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if _decode(event.mimeData()) is not None:
            self._set_target(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_target(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_target(False)
        payload = _decode(event.mimeData())
        if payload is None:
            return
        index = self._insert_index(event.position().toPoint())
        self.builder.drop_tokens(payload, self, index)
        event.acceptProposedAction()

    def _set_target(self, active: bool) -> None:
        if bool(self.property("target")) == active:
            return
        self.setProperty("target", active)
        style = self.style()
        style.unpolish(self)
        style.polish(self)


class FormulaBuilder(QWidget):
    """The palette card, the lines, and the text they add up to."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        palettes: tuple | None = None,
        fields: tuple = ENTRY_FIELDS,
        functions: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("formulaBuilder")
        self.palette = PALETTES if palettes is None else palettes
        self.fields = tuple(fields)
        self.functions = FUNCTIONS if functions is None else functions
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

    # -- the palette card --------------------------------------------------

    def _palettes(self) -> QWidget:
        box = QFrame(self)
        box.setObjectName("formulaPalette")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(5)

        self.blocks: dict[str, list[PaletteBlock]] = {}
        for title, items in self.palette:
            outer.addLayout(self._palette_row(box, title, items))

        rule = QFrame(box)
        rule.setObjectName("paletteRule")
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)
        outer.addWidget(rule)

        outer.addLayout(self._number_row(box))
        return box

    def _palette_row(
        self, parent: QWidget, title: str, items: tuple
    ) -> QHBoxLayout:
        """A caption, then the blocks of one group, side by side and wrapping."""
        row = QHBoxLayout()
        row.setSpacing(10)
        caption = QLabel(title.upper(), parent)
        caption.setObjectName("paletteTitle")
        caption.setFixedWidth(72)
        row.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)

        holder = FlowHolder(parent, spacing=4)
        blocks: list[PaletteBlock] = []
        for item in items:
            block = PaletteBlock(item, holder)
            holder.flow.addWidget(block)
            blocks.append(block)
        self.blocks[title] = blocks
        row.addWidget(holder, 1)
        return row

    def _number_row(self, parent: QWidget) -> QHBoxLayout:
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

    # -- the canvas --------------------------------------------------------

    def _canvas(self) -> QWidget:
        box = QWidget(self)
        box.setObjectName("formulaCanvas")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        # The lines hug their content: any slack goes to the bottom of the
        # tile, not into a gap between the lines and the buttons.
        self.strip_layout = QVBoxLayout()
        self.strip_layout.setContentsMargins(0, 0, 0, 0)
        self.strip_layout.setSpacing(4)
        layout.addLayout(self.strip_layout, 0)

        self.add_line_button = QPushButton("+  add a line", box)
        self.add_line_button.setObjectName("addLine")
        self.add_line_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_line_button.setToolTip(
            "another line: the last one is the condition"
        )
        self.add_line_button.clicked.connect(lambda: self.add_strip())
        layout.addWidget(self.add_line_button)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.preview_label = QLabel(box)
        self.preview_label.setObjectName("formulaPreview")
        self.preview_label.setFont(mono_font(9))
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
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
        layout.addStretch(1)
        return box

    # -- lines -------------------------------------------------------------

    def add_strip(self, tokens=None, at: int | None = None) -> ChipStrip:
        strip = ChipStrip(self, self)
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
        for _, items in self.palette:
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
            for kind, payload in self._plan(lines[line]):
                if kind == "call":
                    strip.add_call_chip(payload)
                else:
                    strip.add_chip(payload)
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        self._refresh_warning()
        # Series lines read "LET", the last line reads "IF".
        for index, strip in enumerate(self.strips):
            last = index == len(self.strips) - 1
            strip.set_caption("IF" if last else "LET")
            strip.remove_button.setVisible(len(self.strips) > 1)

        text = self.formula_text()
        self.preview_label.setText(text if text else "— drop a block onto a line")
        self.add_line_button.setEnabled(len(self.strips) < 6)

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
    "PaletteBlock",
    "drag_pixmap",
    "group_for_token",
]
