"""The hub's small, reusable pieces.

The little builders (`_label`, `_panel`, …) and the three paint-it-yourself
widgets — the mini equity curve, the countdown bar, and a saved-strategy row —
split out of `main_hub` so the window file is the window alone. `main_hub`
imports them back, so every name still lives there too.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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

from bi_trading.ui.palette import ACCENT, AMBER_DOT, BORDER, DOWN, INDIGO, TRACK, UP

log = logging.getLogger(__name__)

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
    "logs": '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    "warn": '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.4h.01"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
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
            for start, end in zip(scaled, scaled[1:], strict=False):
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
        painter.drawRoundedRect(QRectF(0, 0, width, height), 2, 2)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(
            QRectF(0, 0, max(2.0, width * self.fraction), height), 2, 2
        )


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


class VenueSwitch(QFrame):
    """One choice in the rail's venue switch: the venue's logo, and under it that
    venue's round trip, all inside the one box that lights when it is chosen."""

    clicked = Signal()

    def __init__(
        self, venue: str, caption: str, mark: QPixmap | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("venueSwitch")
        self.setProperty("venue", venue)
        self.setProperty("active", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        # The same box for every choice, its contents centred, so the three sit
        # at even steps down the rail.
        self.logo = QLabel()
        self.logo.setObjectName("venueLogo")
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if mark is not None:
            self.logo.setPixmap(mark)
        else:
            self.logo.setText(caption)
            self.logo.setObjectName("venueCaption")
        self.delay: QLabel | None = None
        column.addStretch(1)
        column.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        if mark is not None:
            self.delay = QLabel("—")
            self.delay.setObjectName("railMs")
            self.delay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(self.delay, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        self.setFixedSize(40, 48)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class StrategyTile(QFrame):
    """A saved strategy as a tile: name, what it runs on, and its result.

    The selected tile is outlined in amber. Click to open it in the builder.
    """

    clicked = Signal(str)

    def __init__(
        self, name: str, meta: str, badge: str, tone: str, selected: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.setObjectName("stile")
        self.setProperty("selected", "true" if selected else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("open this strategy in the builder")
        column = QVBoxLayout(self)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(3)
        title = _label(name, "stileName")
        title.setWordWrap(True)
        column.addWidget(title)
        column.addWidget(_label(meta, "stileMeta"))
        if badge:
            pnl = _label(badge, "stratPnl", rich=True)
            pnl.setStyleSheet(f"color: {tone}; background: transparent;")
            column.addWidget(pnl)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)


class NewTile(QFrame):
    """The dashed "new" tile that ends a list of tiles."""

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stileNew")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(56)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.addStretch(1)
        row.addWidget(_label(text, "stileNewText"))
        row.addStretch(1)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _pnl_badge(
    entry: str, exit_: str, timeframe: str, side: str = "long",
    short_entry: str = "",
) -> tuple[str, str]:
    """(glyph, colour) for a strategy's return, or ('', '') when unknown."""
    try:
        from bi_trading.ui.strat.strat_saved import strategy_pnl

        pnl = strategy_pnl(entry, exit_, timeframe, side, short_entry)
    except Exception:  # a status row must never take down the hub
        log.warning("could not score a saved strategy", exc_info=True)
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
    "NewTile",
    "StrategyRow",
    "StrategyTile",
    "VenueSwitch",
    "_accent",
    "_button",
    "_dot",
    "_label",
    "_panel",
    "_pnl_badge",
    "_rule",
    "_svg_icon",
]
