"""The hub's small, reusable pieces.

The little builders (`_label`, `_panel`, …) and the three paint-it-yourself
widgets — the mini equity curve, the countdown bar, and a saved-strategy row —
split out of `main_hub` so the window file is the window alone. `main_hub`
imports them back, so every name still lives there too.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lalala.ui.palette import ACCENT, AMBER_DOT, BORDER, DOWN, INDIGO, TRACK, UP

# Section icons, from lateral.html (24x24 stroke paths), keyed by section.
ICONS: dict[str, str] = {
    "home": '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "builder": (
        '<path d="M4 6h8M18 6h2M4 12h2M12 12h8M4 18h10M20 18h0"/>'
        '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/>'
        '<circle cx="17" cy="18" r="2"/>'
    ),
    "backtest": '<path d="M4 12a8 8 0 1 0 2.5-5.8M4 4v5h5M12 8v4l3 2"/>',
    "live": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "settings": (
        '<circle cx="12" cy="12" r="3.1"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 '
        '2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 '
        '2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 '
        '2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 '
        '2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 '
        '2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 '
        '2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 '
        '2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 '
        '2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
    ),
    "quit": '<path d="M12 3v9"/><path d="M6.6 5.6a8 8 0 1 0 10.8 0"/>',
}


# -- small builders ----------------------------------------------------------


def _label(text: str, name: str = "", *, rich: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    if rich:
        label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _rule(width: int | None = None) -> QFrame:
    line = QFrame()
    line.setObjectName("rule")
    line.setFixedHeight(1)
    if width is not None:
        line.setFixedWidth(width)
    return line


def _dot(color: str, size: int = 10) -> QFrame:
    dot = QFrame()
    dot.setFixedSize(size, size)
    dot.setStyleSheet(
        f"background-color: {color}; border: none; border-radius: {size // 2}px;"
    )
    return dot


def _button(text: str, name: str = "ghost") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _panel(*, inner: bool = False) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("inner" if inner else "panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(5)
    return frame, layout


def _accent(text: str, color: str, size: int = 9) -> str:
    """A coloured glyph (dot / arrow) glued in front of a value, as rich text."""
    return f'<span style="color:{color};font-size:{size}px">{text}</span>'


def _svg_icon(name: str, color: str, size: int = 20) -> QIcon:
    """Render one of the rail's stroke icons, in `color`, to a QIcon."""
    body = ICONS[name]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"'
        f' width="{size}" height="{size}" fill="none" stroke="{color}"'
        ' stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )
    renderer = QSvgRenderer(svg.encode())
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# -- raw widgets -------------------------------------------------------------


class EquityCurve(QWidget):
    """The backtest card's mini equity curve: amber strategy over indigo hold."""

    AMBER = ((0, 60), (30, 52), (60, 40), (90, 32), (120, 24), (150, 28),
             (180, 20), (210, 36), (240, 56), (260, 64))
    INDIGO = ((0, 60), (40, 68), (80, 76), (120, 84), (160, 92), (200, 96),
              (260, 104))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = float(self.width()), float(self.height())

        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawLine(QPointF(0, height * 0.5), QPointF(width, height * 0.5))

        for points, color, pen_width in (
            (self.INDIGO, INDIGO, 1),
            (self.AMBER, ACCENT, 2),
        ):
            painter.setPen(QPen(QColor(color), pen_width))
            scaled = [
                QPointF(x / 260.0 * width, y / 120.0 * height) for x, y in points
            ]
            for start, end in zip(scaled, scaled[1:]):
                painter.drawLine(start, end)


class ProgressBar(QWidget):
    """A 4px track with an amber fill, for the Live card's countdown."""

    def __init__(self, fraction: float = 0.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fraction = max(0.0, min(1.0, fraction))
        self.setFixedHeight(4)

    def set_fraction(self, fraction: float) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = float(self.width()), float(self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TRACK))
        painter.drawRoundedRect(0, 0, width, height, 2, 2)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(0, 0, max(2.0, width * self.fraction), height, 2, 2)


class StrategyRow(QFrame):
    """A saved strategy in the builder card: click to open it loaded."""

    clicked = Signal(str)

    def __init__(
        self, name: str, badge: str, tone: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.setObjectName("stratRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("open this strategy in the builder")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 5, 6, 5)
        row.setSpacing(6)
        row.addWidget(_label(name, "stratName"))
        row.addStretch(1)
        if badge:
            pnl = _label(badge, "stratPnl", rich=True)
            pnl.setStyleSheet(f"color: {tone}; background: transparent;")
            row.addWidget(pnl)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)


def _pnl_badge(
    entry: str, exit_: str, timeframe: str, side: str = "long",
    short_entry: str = "",
) -> tuple[str, str]:
    """(glyph, colour) for a strategy's return, or ('', '') when unknown."""
    try:
        from lalala.ui.strat.strat_saved import strategy_pnl

        pnl = strategy_pnl(entry, exit_, timeframe, side, short_entry)
    except Exception:  # noqa: BLE001 - a status row must never take down the hub
        pnl = None
    if pnl is None:
        return "", ""
    if pnl >= 0.05:
        return f"{_accent('▲', UP)} +{pnl:.2f}%", UP
    if pnl <= -0.05:
        return f"{_accent('▼', DOWN)} −{abs(pnl):.2f}%", DOWN
    return f"{_accent('●', AMBER_DOT)} {pnl:+.2f}%", AMBER_DOT


__all__ = [
    "ICONS",
    "EquityCurve",
    "ProgressBar",
    "StrategyRow",
    "_accent",
    "_button",
    "_dot",
    "_label",
    "_panel",
    "_pnl_badge",
    "_rule",
    "_svg_icon",
]
