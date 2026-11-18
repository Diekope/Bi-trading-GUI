"""The pieces a formula is built from: palette blocks, chips, strips and drop zones.

The drag and drop plumbing, the wrapping flow layout, and the chips themselves. The
builder card (`formula_builder`) arranges them."""

from __future__ import annotations

from typing import TYPE_CHECKING

import json
from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
    QWidgetItem,
)
from bi_trading.engine.formula import tokens_to_text
from bi_trading.engine.formula_palettes import (
    HANDLE,
    Item,
    MATHS_FUNCS,
    MIME,
    group_for_token,
)
from bi_trading.ui.cards import mono_font
from bi_trading.ui.theme import BORDER, TEXT_FAINT

if TYPE_CHECKING:
    from bi_trading.ui.strat.formula_builder import FormulaBuilder


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
        layout.setContentsMargins(5, 1, 7, 1)
        layout.setSpacing(3)
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

    def __init__(
        self, token, builder: FormulaBuilder, parent=None, fixed: bool = False
    ) -> None:
        super().__init__(parent)
        self.token = token
        self.builder = builder
        self.fixed = fixed
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
        self.setProperty("fixed", self.fixed)
        self.handle.setVisible(not slot and not self.fixed)
        self.remove_button.setVisible(not slot and not self.fixed)
        self.setAcceptDrops(slot)
        self.setCursor(
            Qt.CursorShape.ArrowCursor
            if self.fixed
            else (
                Qt.CursorShape.PointingHandCursor
                if slot
                else Qt.CursorShape.OpenHandCursor
            )
        )
        self.setToolTip(
            ""
            if self.fixed
            else (
                "empty slot — drop a number in, or click it and type one"
                if slot
                else "drag by the handle · × takes it off"
            )
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
        if self._press is None or self.is_slot() or self.fixed:
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
        elif self._press is not None:
            # A click on any other chip shows it in the card beside the rule.
            self.builder.select_chip(self)
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


class NameChip(Chip):
    """The name of a named series — the one token you type free-hand.

    Every other token is dragged from the palette; a name cannot be, so this
    chip carries a small text field: type the name, then drop the series it
    stands for onto the line after the `=`.
    """

    def __init__(self, token, builder: FormulaBuilder, parent=None) -> None:
        super().__init__(token, builder, parent)
        self.edit = QLineEdit(str(token or ""), self)
        self.edit.setObjectName("chipNameEdit")
        self.edit.setPlaceholderText("name")
        self.edit.setFixedWidth(78)
        self._layout.replaceWidget(self.label, self.edit)
        self.label.hide()
        self.edit.textChanged.connect(self._on_name)
        self.handle.setVisible(False)
        self.remove_button.setVisible(False)

    def _on_name(self, text: str) -> None:
        self.token = text.strip()
        self.builder.contents_changed()

    def is_slot(self) -> bool:
        return False

    def tokens(self) -> list:
        return [self.token] if self.token else []

    def _apply(self) -> None:
        # The name is shown in its text field, not in the label.
        self.setProperty("slot", False)
        self.setProperty("group", "name")
        self.setAcceptDrops(False)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self._repolish()

    def focus_name(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()


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
        builder: FormulaBuilder,
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
            assert isinstance(layout, QBoxLayout)
            layout.insertWidget(layout.count() - 1, field)

    # -- state -------------------------------------------------------------

    def is_slot(self) -> bool:
        return False

    def group(self) -> str:
        return "maths" if self.func in MATHS_FUNCS else "indicator"

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

    def __init__(self, builder: FormulaBuilder, parent=None) -> None:
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

    def add_chip(self, token, index: int | None = None, fixed: bool = False) -> Chip:
        chip = Chip(token, self.builder, self.zone, fixed=fixed)
        return self._place(chip, index)

    def add_name_chip(self, token="", index: int | None = None) -> NameChip:
        """The editable name of a named series, at the head of a line."""
        chip = NameChip(token, self.builder, self.zone)
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
