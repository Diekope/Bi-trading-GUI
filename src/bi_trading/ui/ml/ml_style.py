"""What the two ML views share: their stylesheet and a few painted widgets.

They follow the hub's design (`ml_strategy` and `model_builder` mockups): hub
palette, 10px panels, amber for the active thing, mono for numbers.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bi_trading.ui.palette import (
    ACCENT,
    AMBER_DOT,
    BORDER,
    CANVAS,
    DOWN_SOFT,
    INNER,
    MONO,
    MUTED,
    PANEL,
    SOFT,
    TEXT,
    TRACK,
    UP,
)

__all__ = [
    "CurveChart",
    "ImportanceBars",
    "ML_QSS",
    "SplitBar",
    "Stepper",
    "field",
    "number_field",
]

ML_QSS = f"""
#mlRoot {{ background-color: {CANVAS}; color: {TEXT}; }}
QFrame#mlPanel {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QFrame#mlInner {{ background-color: {INNER}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#mlRule {{ background-color: {BORDER}; border: none; }}
QLabel {{ background: transparent; color: {TEXT}; }}
QLabel#mlH1 {{ font-size: 18px; font-weight: 600; }}
QLabel#mlH2 {{ font-size: 11px; font-weight: 600; letter-spacing: 2px; color: #e2e2e5; }}
QLabel#mlGroup {{ font-size: 10px; font-weight: 600; letter-spacing: 1.2px; color: {MUTED}; }}
QLabel#mlCaption {{ font-size: 11px; color: {MUTED}; }}
QLabel#mlLabel {{ font-size: 11px; color: {MUTED}; }}
QLabel#mlBody {{ font-size: 12px; color: {SOFT}; }}
QLabel#mlMono {{ font-family: {MONO}; font-size: 12px; color: {TEXT}; }}
QLabel#mlMonoMuted {{ font-family: {MONO}; font-size: 11px; color: {MUTED}; }}
QLabel#mlWarn {{ font-family: {MONO}; font-size: 12px; color: {AMBER_DOT}; }}
QLabel#mlError {{ font-size: 12px; color: {DOWN_SOFT}; }}
QLabel#mlTag {{
    font-size: 10px; color: {MUTED}; border: 1px solid #2a2b31; border-radius: 4px;
    padding: 1px 6px; background: {TRACK};
}}
QLabel#mlChip {{
    font-family: {MONO}; font-size: 11px; color: #a3a8ff; background: #181a30;
    border: 1px solid #33366b; border-radius: 5px; padding: 3px 7px;
}}
QLabel#mlLayerName {{ font-family: {MONO}; font-size: 12px; font-weight: 600; color: {ACCENT}; }}

QLineEdit#mlField, QComboBox#mlCombo, QPlainTextEdit#mlCode {{
    background-color: {TRACK}; border: 1px solid #2a2b31; border-radius: 6px;
    color: {TEXT}; font-size: 12px; padding: 5px 8px;
    selection-background-color: {ACCENT}; selection-color: {CANVAS};
}}
QLineEdit#mlNum {{
    background-color: {TRACK}; border: 1px solid #2a2b31; border-radius: 6px;
    color: {TEXT}; font-family: {MONO}; font-size: 12px; padding: 5px 8px;
    selection-background-color: {ACCENT}; selection-color: {CANVAS};
}}
QLineEdit#mlField:focus, QLineEdit#mlNum:focus, QComboBox#mlCombo:focus {{ border-color: {ACCENT}; }}
QLineEdit#mlNum[invalid="true"] {{ border-color: {DOWN_SOFT}; }}
QPlainTextEdit#mlCode {{ font-family: {MONO}; font-size: 12px; }}
QComboBox#mlCombo::drop-down {{ border: none; width: 16px; }}
QComboBox#mlCombo QAbstractItemView {{
    background-color: {PANEL}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; selection-color: {CANVAS};
}}

QPushButton#mlPrimary {{
    background: #231f10; border: 1px solid #4a3f1a; color: {ACCENT};
    border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 500;
}}
QPushButton#mlPrimary:hover {{ border-color: {ACCENT}; }}
QPushButton#mlPrimary:disabled {{ color: #6f6748; border-color: #3a3318; }}
QPushButton#mlGhost {{
    background: {TRACK}; border: 1px solid #2a2b31; color: {SOFT};
    border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 500;
}}
QPushButton#mlGhost:hover {{ border-color: #4a3b1a; color: {TEXT}; }}
QPushButton#mlGhost:disabled {{ color: #5d5f66; }}
QPushButton#mlSoft {{
    background: {TRACK}; border: 1px dashed #3a3b42; color: {ACCENT};
    border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 500;
}}
QPushButton#mlSoft:hover {{ border-color: {ACCENT}; }}
QPushButton#mlMini {{
    background: {TRACK}; border: 1px solid #2a2b31; color: {SOFT};
    border-radius: 5px; padding: 2px 8px; font-size: 11px;
}}
QPushButton#mlMini:hover {{ border-color: #4a3b1a; color: {TEXT}; }}
QPushButton#mlSeg {{
    font-size: 11px; font-weight: 500; padding: 4px 10px; border-radius: 5px;
    border: 1px solid #2a2b31; background: {TRACK}; color: {MUTED};
}}
QPushButton#mlSeg:checked {{ border-color: #4a3f1a; color: {ACCENT}; background: #231f10; }}
QPushButton#mlSeg:hover {{ color: {TEXT}; }}
QPushButton#mlLayerChip {{
    font-family: {MONO}; font-size: 11px; padding: 3px 8px; border-radius: 5px;
    border: 1px solid #2a2b31; background: {TRACK}; color: {TEXT};
}}
QPushButton#mlLayerChip:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}

QCheckBox#mlCheck {{ color: {SOFT}; font-size: 12px; spacing: 7px; background: transparent; }}
QCheckBox#mlCheck::indicator {{
    width: 14px; height: 14px; border: 1px solid #3a3b40; border-radius: 3px; background: {TRACK};
}}
QCheckBox#mlCheck::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox#mlCheck:disabled {{ color: #5d5f66; }}

QFrame#mlModelRow {{
    border: 1px solid {BORDER}; border-radius: 6px; background: #1a1b20;
}}
QFrame#mlModelRow[selected="true"] {{ border-color: {ACCENT}; background: #1d1b12; }}
QRadioButton#mlRadio {{ color: {TEXT}; font-size: 12px; spacing: 8px; background: transparent; }}
QRadioButton#mlRadio::indicator {{
    width: 12px; height: 12px; border: 1px solid #3a3b40; border-radius: 7px; background: {TRACK};
}}
QRadioButton#mlRadio::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QFrame#mlLayerRow {{ border: 1px solid {BORDER}; border-radius: 8px; background: #1a1b20; }}
QFrame#mlLayerRow[selected="true"] {{ border-color: {ACCENT}; background: #1d1b12; }}
QFrame#mlFixedRow {{ border: 1px solid {BORDER}; border-radius: 8px; background: {INNER}; }}

QProgressBar {{ background: {TRACK}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QTableWidget#mlTable {{
    background: transparent; border: none; color: {TEXT};
    font-family: {MONO}; font-size: 12px; gridline-color: transparent;
}}
QTableWidget#mlTable::item {{ padding: 6px; border-bottom: 1px solid #1f2024; }}
QHeaderView::section {{
    background: transparent; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 6px; font-size: 11px; font-weight: 500;
}}
QScrollArea {{ background: transparent; border: none; }}
"""


def field(value: str = "", *, mono: bool = True, width: int | None = None) -> QLineEdit:
    edit = QLineEdit(value)
    edit.setObjectName("mlNum" if mono else "mlField")
    if mono:
        edit.setAlignment(Qt.AlignmentFlag.AlignRight)
    if width is not None:
        edit.setFixedWidth(width)
    return edit


def number_field(value: float, width: int | None = None) -> QLineEdit:
    """A right-aligned mono field; the caller reads it with `read_number`."""
    return field(f"{value:g}", width=width)


# -- painted widgets ------------------------------------------------------------


class SplitBar(QWidget):
    """Train / valid / test as one bar, widths in proportion."""

    COLORS = ("#8d93f0", ACCENT, UP)

    def __init__(self, parts: tuple[tuple[str, float], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.parts = parts
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        x = 0.0
        total = sum(share for _, share in self.parts) or 1.0
        for index, (text, share) in enumerate(self.parts):
            width = self.width() * share / total
            rect = QRectF(x, 0, max(0.0, width - 2), self.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.COLORS[index % 3]))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor("#101114"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            x += width


class ImportanceBars(QWidget):
    """Feature importance: label, a bar, the number (0 to 100)."""

    ROW = 22

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items: list[tuple[str, float]] = []
        self.setMinimumHeight(self.ROW)

    def set_items(self, items: list[tuple[str, float]], limit: int = 6) -> None:
        self.items = list(items)[:limit]
        self.setMinimumHeight(max(1, len(self.items)) * self.ROW)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mono = QFont(self.font())
        mono.setFamily("JetBrains Mono")
        mono.setPixelSize(11)
        painter.setFont(mono)
        label_w, value_w = 120, 34
        track = QRectF(label_w + 8, 0, self.width() - label_w - value_w - 16, 8)
        for row, (name, value) in enumerate(self.items):
            top = row * self.ROW
            painter.setPen(QColor(TEXT))
            painter.drawText(
                QRectF(0, top, label_w, self.ROW),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, label_w),
            )
            bar = QRectF(track.left(), top + (self.ROW - 8) / 2, track.width(), 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(TRACK))
            painter.drawRoundedRect(bar, 4, 4)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(
                QRectF(bar.left(), bar.top(), max(0.0, bar.width() * value / 100.0), 8), 4, 4
            )
            painter.setPen(QColor(MUTED))
            painter.drawText(
                QRectF(self.width() - value_w, top, value_w, self.ROW),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                f"{value:.0f}",
            )


class CurveChart(QWidget):
    """The strategy's return (amber) over buy and hold (grey, dashed), as percent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.strategy: list[float] = []
        self.hold: list[float] = []
        self.setMinimumHeight(70)

    def set_curves(self, strategy: list[float], hold: list[float]) -> None:
        self.strategy, self.hold = list(strategy), list(hold)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = float(self.width()), float(self.height())
        values = [0.0, *self.strategy, *self.hold]
        low, high = min(values), max(values)
        if high - low < 1e-9:
            high, low = high + 1.0, low - 1.0
        pad = 4.0

        def y_of(value: float) -> float:
            return pad + (high - value) / (high - low) * (height - 2 * pad)

        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawLine(QPointF(0, y_of(0.0)), QPointF(width, y_of(0.0)))
        for series, color, dashed, thickness in (
            (self.hold, "#c9cad0", True, 1.2),
            (self.strategy, ACCENT, False, 2.0),
        ):
            if len(series) < 2:
                continue
            pen = QPen(QColor(color), thickness)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            step = width / (len(series) - 1)
            painter.drawPolyline(
                QPolygonF([QPointF(i * step, y_of(v)) for i, v in enumerate(series)])
            )


class Stepper(QWidget):
    """The six-step strip: a circle and a name per step, hairlines between."""

    def __init__(self, names: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.names = names
        self.states = ["todo"] * len(names)
        self.setFixedHeight(40)

    def set_states(self, states: list[str]) -> None:
        if states != self.states:
            self.states = list(states)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        widths = [24 + 8 + metrics.horizontalAdvance(name) for name in self.names]
        free = self.width() - sum(widths) - 28
        gap = max(14.0, free / max(1, len(self.names) - 1))
        x = 14.0
        centre = self.height() / 2
        colors = {
            "done": (UP, "#13211a", TEXT),
            "current": (ACCENT, "#231f10", ACCENT),
            "todo": (MUTED, TRACK, MUTED),
        }
        mono = QFont(self.font())
        mono.setFamily("JetBrains Mono")
        mono.setPixelSize(11)
        mono.setBold(True)
        for index, name in enumerate(self.names):
            state = self.states[index]
            edge, fill, ink = colors[state]
            circle = QRectF(x, centre - 11, 22, 22)
            painter.setPen(QPen(QColor(edge), 1))
            painter.setBrush(QColor(fill))
            painter.drawEllipse(circle)
            painter.setFont(mono)
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, "✓" if state == "done" else str(index + 1))
            painter.setFont(font)
            painter.setPen(QColor(ink))
            painter.drawText(
                QRectF(x + 30, 0, widths[index], self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                name,
            )
            x += widths[index]
            if index < len(self.names) - 1:
                painter.setPen(QPen(QColor(BORDER), 1))
                painter.drawLine(QPointF(x + 8, centre), QPointF(x + gap - 8, centre))
                x += gap


class SegmentedChoice(QWidget):
    """A row of mutually exclusive small buttons; emits the picked key."""

    picked = Signal(str)

    def __init__(self, options: tuple[tuple[str, str], ...], current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options:
            button = QPushButton(text)
            button.setObjectName("mlSeg")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.pick(k, True))
            row.addWidget(button)
            self.buttons[key] = button
        self.pick(current, False)

    def pick(self, key: str, emit: bool = True) -> None:
        for name, button in self.buttons.items():
            button.setChecked(name == key)
        self.current = key
        if emit:
            self.picked.emit(key)


def read_number(edit: QLineEdit, default: float, low: float, high: float) -> float:
    """The field as a number clamped to its range; the field is flagged when it is not one."""
    text = edit.text().strip().replace(",", ".")
    try:
        value = float(text)
        bad = False
    except ValueError:
        value, bad = default, True
    clamped = min(high, max(low, value))
    bad = bad or clamped != value
    if bool(edit.property("invalid")) != bad:
        edit.setProperty("invalid", bad)
        edit.style().unpolish(edit)
        edit.style().polish(edit)
    return clamped


def panel(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("mlPanel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)
    if title:
        label = QLabel(title.upper())
        label.setObjectName("mlH2")
        layout.addWidget(label)
    return frame, layout


def clear(layout) -> None:
    """Remove everything from a layout and let the widgets go."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.deleteLater()


def label(text: str, name: str = "mlLabel", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, name: str = "mlGhost") -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("mlRule")
    line.setFixedHeight(1)
    return line


__all__ += ["SegmentedChoice", "button", "clear", "label", "panel", "read_number", "rule"]
