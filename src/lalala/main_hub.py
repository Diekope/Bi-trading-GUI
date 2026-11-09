"""Main hub: a clean window built raw from `MainHub.dc.html`.

A slim, always-folded sidebar on the left and, on the right, the Home view — a
header, four status cards, and three "part" cards (Live, Strategy builder,
Backtest engine).

The sidebar is the icon rail of `lateral.html`: a brand dot, the section icons,
a settings gear, and the venue latencies, each with a dot in its own element's
colour and the *real* round trip read from a live feed. Clicking a section (or a
card button) rebuilds that section's window *inside the same window*: the
previous view is destroyed and a fresh one takes its place, so no second
top-level window is ever spawned. Clicking a saved strategy opens the builder
window with that strategy loaded.
"""

from __future__ import annotations

import sys
import time

from PySide6.QtCore import QByteArray, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# -- the mock's palette ------------------------------------------------------

CANVAS = "#0f1013"
PANEL = "#17181c"
INNER = "#141519"
WELL = "#101114"
HOVER = "#1b1c21"
BORDER = "#25262b"
TRACK = "#1d1e23"
TEXT = "#e8e8ea"
SOFT = "#c9cad0"
MUTED = "#8b8d95"
FAINT = "#a9abb2"
ACCENT = "#f2c94c"
UP = "#3ddc84"
UP_BRIGHT = "#5fe39a"
DOWN = "#ff6b6b"
DOWN_SOFT = "#ff8a8a"
DOWN_SOFT_BG = "#2c1a1a"
AMBER_DOT = "#ffa94d"
INDIGO = "#6c72e8"

# One dot per connected venue, in that venue's own colour (from lateral.html).
PM_DOT = "#2d5bff"
HL_DOT = "#97fce4"

MONO = '"JetBrains Mono"'

QSS = f"""
#hubRoot {{ background-color: {CANVAS}; color: {TEXT}; }}
#hubStack {{ background-color: {CANVAS}; }}
QFrame#panel {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#inner {{ background-color: {INNER}; border: none; border-radius: 8px; }}
QFrame#well {{ background-color: {WELL}; border: none; border-radius: 6px; }}
QFrame#rule {{ background-color: {BORDER}; border: none; }}
QFrame#chip {{ background-color: #13211a; border: 1px solid #1f4a33; border-radius: 5px; }}
QLabel#chipText {{ font-family: {MONO}; font-size: 11px; color: {UP_BRIGHT}; }}

QLabel {{ background: transparent; color: {TEXT}; }}
QLabel#brand {{ font-size: 15px; font-weight: 600; }}
QLabel#h1 {{ font-size: 18px; font-weight: 600; }}
QLabel#h2 {{ font-size: 11px; font-weight: 600; letter-spacing: 2px; color: #e2e2e5; }}
QLabel#caption {{ font-size: 11px; color: {MUTED}; }}
QLabel#desc {{ font-size: 13px; color: {FAINT}; }}
QLabel#stat {{ font-family: {MONO}; font-size: 15px; font-weight: 600; color: #ffffff; }}
QLabel#mono {{ font-family: {MONO}; font-size: 12px; color: {SOFT}; }}
QLabel#monoMuted {{ font-family: {MONO}; font-size: 11px; color: {MUTED}; }}
QLabel#section {{ font-size: 10px; font-weight: 600; letter-spacing: 1px; color: {MUTED}; }}
QLabel#formula {{ font-family: {MONO}; font-size: 12px; color: {SOFT}; }}
QLabel#big {{ font-family: {MONO}; font-size: 20px; font-weight: 600; }}
QLabel#tileName {{ font-family: {MONO}; font-size: 11px; }}
QLabel#tileValue {{ font-family: {MONO}; font-size: 18px; font-weight: 600; }}
QLabel#railMs {{ font-family: {MONO}; font-size: 10px; color: {SOFT}; }}

/* The folded rail: icons only, one column, as lateral.html draws it. */
QFrame#rail {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QPushButton#railIcon {{ background: transparent; border: none; border-radius: 8px; }}
QPushButton#railIcon:hover {{ background: {HOVER}; }}
QPushButton#railIcon[active="true"] {{ background: #231f10; }}
/* The exit: a light red of its own, so it never reads as a section. */
QPushButton#railQuit {{ background: transparent; border: none; border-radius: 8px; }}
QPushButton#railQuit:hover {{ background: {DOWN_SOFT_BG}; }}

QPushButton#btn {{
    background: #231f10; border: 1px solid #4a3f1a; color: {ACCENT};
    border-radius: 6px; padding: 9px 14px; font-size: 13px; font-weight: 500;
}}
QPushButton#btn:hover {{ border-color: {ACCENT}; }}
QPushButton#ghost {{
    background: {TRACK}; border: 1px solid #2a2b31; color: {SOFT};
    border-radius: 6px; padding: 8px 12px; font-size: 13px; font-weight: 500;
}}
QPushButton#ghost:hover {{ border-color: #4a3b1a; color: {TEXT}; }}

QFrame#stratRow {{ background: transparent; border-radius: 6px; }}
QFrame#stratRow:hover {{ background: {HOVER}; }}
/* Names are interface (Inter); only the return beside them is a number. */
QLabel#stratName {{ font-size: 12px; color: {SOFT}; }}
QLabel#stratPnl {{ font-family: {MONO}; font-size: 12px; }}
"""

# Sidebar sections, in order. "home" is the hub itself.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("home", "Home"),
    ("live", "Live"),
    ("builder", "Strategy builder"),
    ("backtest", "Backtest engine"),
)

# The venues whose round trip the rail reports: (key, name, dot colour).
VENUES: tuple[tuple[str, str, str], ...] = (
    ("pm", "Polymarket", PM_DOT),
    ("hl", "Hyperliquid", HL_DOT),
)

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

# Bottom rail entries that have no view yet: (icon key, label).
RAIL_EXTRAS: tuple[tuple[str, str], ...] = (
    ("settings", "Settings"),
)


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


def _pnl_badge(entry: str, exit_: str, timeframe: str) -> tuple[str, str]:
    """(glyph, colour) for a strategy's return, or ('', '') when unknown."""
    try:
        from lalala.strat_saved import strategy_pnl

        pnl = strategy_pnl(entry, exit_, timeframe)
    except Exception:  # noqa: BLE001 - a status row must never take down the hub
        pnl = None
    if pnl is None:
        return "", ""
    if pnl >= 0.05:
        return f"{_accent('▲', UP)} +{pnl:.2f}%", UP
    if pnl <= -0.05:
        return f"{_accent('▼', DOWN)} −{abs(pnl):.2f}%", DOWN
    return f"{_accent('●', AMBER_DOT)} {pnl:+.2f}%", AMBER_DOT


# -- the window --------------------------------------------------------------


class MainHubWindow(QMainWindow):
    """The hub shell: a folded rail over a stack of rebuildable views."""

    def __init__(self, autostart: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("lalala")
        self.setMinimumSize(880, 600)
        self.resize(1280, 820)

        from lalala.settings import load_window_geometry

        saved_geometry = load_window_geometry()
        if saved_geometry:
            self.restoreGeometry(QByteArray.fromBase64(saved_geometry.encode()))

        self._key = "home"
        self._nav_buttons: dict[str, list[QPushButton]] = {}
        self._view: QWidget | None = None
        self._latency_labels: dict[str, QLabel] = {}
        self._market = None  # the live Polymarket market, for the Live card
        self._last_pm: int | None = None
        self._last_hl: float | None = None
        self._btc_price: float | None = None

        root = QWidget(self)
        root.setObjectName("hubRoot")
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root.setStyleSheet(QSS)

        self.grid = QGridLayout(root)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(8)
        self.grid.addWidget(self._rail(), 0, 0)

        self.home = self._home()
        self.stack = QStackedWidget(root)
        self.stack.setObjectName("hubStack")
        self.stack.addWidget(self.home)
        self.grid.addWidget(self.stack, 0, 1)
        self.grid.setColumnStretch(0, 0)
        self.grid.setColumnStretch(1, 1)
        self.grid.setRowStretch(0, 1)

        self.setCentralWidget(root)

        # -- feeds: the rail's latencies and the Live card read from these --
        from lalala.feed import MarketFeed
        from lalala.polymarket_feed import PolymarketFeed
        from lalala.settings import Settings

        self.feed = MarketFeed(self)
        self.feed.latency.connect(self._on_hl_latency)
        self.feed.mids_updated.connect(self._on_mids)
        self.polymarket_feed = PolymarketFeed(self)
        self.polymarket_feed.latency.connect(self._on_pm_latency)
        self.polymarket_feed.market_ready.connect(self._on_pm_market)
        self.polymarket_feed.book_updated.connect(self._on_pm_book)
        if autostart:
            self.feed.start()
            self.polymarket_feed.start()

        # The trade form moved a paper position: keep the Home card in step.
        from lalala.positions import store

        store().changed.connect(self._refresh_position)

        start = Settings.load().general.start_page
        self._open(start if start in ("live", "builder", "backtest") else "home")

        # Cmd+1…4 jump between the views, Cmd+, opens Settings.
        for keys, target in (
            ("Ctrl+1", "home"),
            ("Ctrl+2", "live"),
            ("Ctrl+3", "builder"),
            ("Ctrl+4", "backtest"),
            ("Ctrl+,", "settings"),
        ):
            QShortcut(
                QKeySequence(keys), self, activated=lambda t=target: self._open(t)
            )

        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._tick_countdown)
        self._clock.start()

    # -- navigation --------------------------------------------------------

    def _open(self, key: str, strategy: str | None = None) -> None:
        """Swap the content area to `key`, rebuilding that view from scratch."""
        self._key = key
        self._destroy_view()

        if key == "home":
            self._refresh_strategies()
            self._refresh_stats()
            self.stack.setCurrentWidget(self.home)
        else:
            view = self._build_view(key, strategy)
            if view is None:
                self.stack.setCurrentWidget(self.home)
                key = "home"
            else:
                view.setMinimumSize(320, 240)
                self._view = view
                self.stack.addWidget(view)
                self.stack.setCurrentWidget(view)

        self._highlight(key)

    def _destroy_view(self) -> None:
        if self._view is None:
            return
        view, self._view = self._view, None
        view.close()  # the live terminal stops its feeds here
        self.stack.removeWidget(view)
        view.setParent(None)
        view.deleteLater()

    def _build_view(self, key: str, strategy: str | None) -> QWidget | None:
        if key == "live":
            from lalala.main_window import MainWindow

            # Share our feeds: the terminal and the rail then read one set of
            # sockets, and their latencies agree.
            return MainWindow(
                feed=self.feed,
                polymarket_feed=self.polymarket_feed,
                show_top_bar=False,
            )
        if key == "builder":
            from lalala.strat_builder import StrategyBuilderWindow

            window = StrategyBuilderWindow()
            if strategy:
                window.load_strategy(strategy)
            return window
        if key == "backtest":
            from lalala.strat_window import StratWindow

            return StratWindow()
        if key == "settings":
            from lalala.settings_view import SettingsView

            view = SettingsView(pm_ms=self._last_pm, hl_ms=self._last_hl)
            self.polymarket_feed.latency.connect(view.set_pm_latency)
            self.feed.latency.connect(view.set_hl_latency)
            return view
        return None

    def _highlight(self, key: str) -> None:
        for name, buttons in self._nav_buttons.items():
            active = name == key
            for button in buttons:
                if button.property("active") == active:
                    continue
                button.setProperty("active", "true" if active else "false")
                style = button.style()
                style.unpolish(button)
                style.polish(button)

    # -- the sidebar rail --------------------------------------------------

    def _rail(self) -> QFrame:
        """The folded rail: icons and latency dots, per lateral.html."""
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(56)
        column = QVBoxLayout(rail)
        column.setContentsMargins(8, 12, 8, 12)
        column.setSpacing(8)

        brand = QHBoxLayout()
        brand.addStretch(1)
        brand.addWidget(_dot(ACCENT))
        brand.addStretch(1)
        column.addLayout(brand)
        column.addWidget(self._rail_rule(), 0, Qt.AlignmentFlag.AlignHCenter)

        for key, name in SECTIONS:
            column.addWidget(
                self._rail_icon(key, name), 0, Qt.AlignmentFlag.AlignHCenter
            )
        column.addStretch(1)
        for key, name in RAIL_EXTRAS:
            column.addWidget(
                self._rail_icon(key, name), 0, Qt.AlignmentFlag.AlignHCenter
            )
        column.addWidget(self._rail_rule(), 0, Qt.AlignmentFlag.AlignHCenter)

        for key, name, color in VENUES:
            self._rail_latency(column, key, name, color)

        column.addWidget(self._rail_rule(), 0, Qt.AlignmentFlag.AlignHCenter)
        quit_button = self._rail_icon(
            "quit",
            "Quit lalala",
            section=False,
            color=DOWN_SOFT,
            object_name="railQuit",
        )
        quit_button.clicked.connect(self.close)
        column.addWidget(quit_button, 0, Qt.AlignmentFlag.AlignHCenter)
        return rail

    @staticmethod
    def _rail_rule() -> QFrame:
        line = QFrame()
        line.setObjectName("rule")
        line.setFixedSize(28, 1)
        return line

    def _rail_icon(
        self,
        key: str,
        name: str,
        *,
        section: bool = True,
        color: str = SOFT,
        object_name: str = "railIcon",
    ) -> QPushButton:
        button = QPushButton()
        button.setObjectName(object_name)
        button.setFixedSize(40, 40)
        button.setIconSize(QPixmap(20, 20).size())
        button.setProperty("active", "false")
        button.setToolTip(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(_svg_icon(key, color))
        if section:
            button.clicked.connect(lambda _=False, k=key: self._open(k))
            self._nav_buttons.setdefault(key, []).append(button)
        return button

    def _rail_latency(
        self, column: QVBoxLayout, key: str, name: str, color: str
    ) -> None:
        # A bare layout, not a QWidget: a wrapper would paint the app's canvas
        # colour and show as a dark box behind the dot.
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        tip = f"Round trip to {name}"
        dot = _dot(color, 8)
        dot.setToolTip(tip)
        box.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
        value = _label("—", "railMs")
        value.setToolTip(tip)
        box.addWidget(value, 0, Qt.AlignmentFlag.AlignHCenter)
        self._latency_labels[key] = value
        column.addLayout(box)

    def _on_hl_latency(self, milliseconds: float) -> None:
        self._last_hl = milliseconds
        self._latency_labels["hl"].setText(f"{milliseconds:.0f}ms")

    def _on_pm_latency(self, milliseconds: int) -> None:
        self._last_pm = int(milliseconds)
        self._latency_labels["pm"].setText(f"{int(milliseconds)}ms")

    # -- live data for the Live card ---------------------------------------

    def _on_mids(self, mids: dict) -> None:
        btc = mids.get("BTC")
        if btc is not None:
            self._btc_price = btc
            if hasattr(self, "_btc_value"):
                self._btc_value.setText(f"{btc:,.1f}")
            self._refresh_position()

    def _on_pm_market(self, market) -> None:
        self._market = market
        if not hasattr(self, "_up_value"):
            return
        for label, outcome in (
            (self._up_value, market.outcomes[0]),
            (self._down_value, market.outcomes[1]),
        ):
            price = outcome.mid if outcome.mid is not None else outcome.price
            label.setText(f"{price * 100:.0f}¢")
        self._tick_countdown()

    def _on_pm_book(self, book) -> None:
        market = self._market
        if market is None or book.mid is None or not hasattr(self, "_up_value"):
            return
        cents = f"{book.mid * 100:.0f}¢"
        if book.token_id == market.outcomes[0].token_id:
            self._up_value.setText(cents)
        elif book.token_id == market.outcomes[1].token_id:
            self._down_value.setText(cents)

    def _tick_countdown(self) -> None:
        market = self._market
        if market is None or not hasattr(self, "_close_value"):
            return
        from lalala.polymarket_data import format_countdown

        now_ms = time.time() * 1000
        left = format_countdown((market.end_ms - now_ms) / 1000)
        self._close_value.setText(left)
        if "Next market" in getattr(self, "_stat_values", {}):
            self._stat_values["Next market"].setText(left)
        span = market.end_ms - market.start_ms
        if span > 0:
            self._progress.set_fraction((now_ms - market.start_ms) / span)

    # -- the home view -----------------------------------------------------

    def _home(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self._header())
        column.addLayout(self._stats())
        column.addLayout(self._parts(), 1)
        return holder

    def _header(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setContentsMargins(16, 12, 16, 12)
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        titles.addWidget(_label("Home", "h1"))
        titles.addWidget(_label("Pick a part to work on.", "caption"))
        row.addLayout(titles)
        row.addStretch(1)

        create = _button("Create a strategy", "btn")
        create.clicked.connect(lambda: self._open("builder"))
        row.addWidget(create)
        return panel

    def _stats(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        cards = (
            ("Active strategy", "—", "—"),
            ("Last backtest", "—", "—"),
            ("Open position", "—", "no position"),
            ("Next market", "—", "Polymarket BTC 5m"),
        )
        self._stat_values: dict[str, QLabel] = {}
        self._stat_subs: dict[str, QLabel] = {}
        for title, value, sub in cards:
            frame, value_label, sub_label = self._stat_card(title, value, sub)
            self._stat_values[title] = value_label
            self._stat_subs[title] = sub_label
            row.addWidget(frame, 1)
        return row

    @staticmethod
    def _stat_card(
        title: str, value: str, sub: str
    ) -> tuple[QFrame, QLabel, QLabel]:
        frame, layout = _panel()
        layout.addWidget(_label(title, "caption"))
        value_label = _label(value, "stat", rich=True)
        layout.addWidget(value_label)
        sub_label = _label(sub, "caption")
        layout.addWidget(sub_label)
        return frame, value_label, sub_label

    def _refresh_stats(self) -> None:
        """Fill the four status cards from real state, not the mock's numbers."""
        values = getattr(self, "_stat_values", None)
        if not values:
            return

        from lalala import runs, strategies

        saved = strategies.load()
        if saved:
            latest = saved[-1]
            values["Active strategy"].setText(latest.name)
            self._stat_subs["Active strategy"].setText(
                f"armed · {latest.timeframe}"
            )
        else:
            values["Active strategy"].setText("—")
            self._stat_subs["Active strategy"].setText("none saved")

        kept = runs.load()
        if kept:
            run = kept[-1]
            years = run.years
            span = f"{years[0]} → {years[-1]}" if years else "—"
            values["Last backtest"].setText(run.name)
            self._stat_subs["Last backtest"].setText(
                f"{span} · {len(run.trades):,} trades"
            )
        else:
            values["Last backtest"].setText("—")
            self._stat_subs["Last backtest"].setText("no run yet")

        self._refresh_position()

    def _refresh_position(self) -> None:
        """The Home card's open position, read from the shared store."""
        values = getattr(self, "_stat_values", None)
        if not values or "Open position" not in values:
            return

        from lalala.positions import change, store

        position = store().get()
        value = values["Open position"]
        sub = self._stat_subs["Open position"]
        if position is None:
            value.setText("—")
            sub.setText("no position")
            return

        side = str(position.get("side", ""))
        leverage = int(position.get("leverage", 1))
        sub.setText(f"{side} {leverage}× · BTC")
        pnl = change(position, self._btc_price)
        if pnl is None:
            value.setText("—")
            return
        arrow = "▲" if pnl >= 0 else "▼"
        sign = "+" if pnl >= 0 else "−"
        colour = UP if pnl >= 0 else DOWN
        value.setText(
            f'<span style="color:{colour}">{arrow}{sign}${abs(pnl):,.2f}</span>'
        )

    def _parts(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._live_card(), 1)
        row.addWidget(self._builder_card(), 1)
        row.addWidget(self._backtest_card(), 1)
        return row

    # -- part cards --------------------------------------------------------

    @staticmethod
    def _part(title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        frame, outer = _panel()
        outer.setContentsMargins(18, 18, 18, 16)
        outer.setSpacing(12)
        outer.addWidget(_label(title.upper(), "h2"))
        desc = _label(description, "desc")
        desc.setWordWrap(True)
        desc.setMinimumHeight(36)
        outer.addWidget(desc)

        inner, body = _panel(inner=True)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(10)
        outer.addWidget(inner, 1)
        return frame, outer

    @staticmethod
    def _row(left: str, right: str, glyph: str | None = None) -> QHBoxLayout:
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(_label(left, "mono"))
        line.addStretch(1)
        shown = f"{glyph} {right}" if glyph else right
        line.addWidget(_label(shown, "mono", rich=glyph is not None))
        return line

    def _actions(self, target: str, primary: str, ghosts: tuple[str, ...]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        first = _button(primary, "btn")
        first.clicked.connect(lambda: self._open(target))
        row.addWidget(first)
        for text in ghosts:
            button = _button(text, "ghost")
            button.clicked.connect(lambda: self._open(target))
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _live_card(self) -> QFrame:
        frame, outer = self._part(
            "Live",
            "Watch the Polymarket 5m market and the BTC chart, and place bets "
            "or trades.",
        )
        body: QVBoxLayout = outer.itemAt(2).widget().layout()

        tiles = QHBoxLayout()
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(8)
        up_tile, self._up_value = self._outcome_tile("UP", "36¢", UP, UP_BRIGHT, True)
        down_tile, self._down_value = self._outcome_tile(
            "DOWN", "64¢", DOWN, DOWN_SOFT, False
        )
        tiles.addWidget(up_tile, 1)
        tiles.addWidget(down_tile, 1)
        body.addLayout(tiles)

        clock = QHBoxLayout()
        clock.setContentsMargins(0, 0, 0, 0)
        clock.addWidget(_label("closes in", "caption"))
        clock.addStretch(1)
        self._close_value = _label("—", "big")
        clock.addWidget(self._close_value)
        body.addLayout(clock)
        self._progress = ProgressBar(0.0)
        body.addWidget(self._progress)
        body.addWidget(_rule())

        btc_row = QHBoxLayout()
        btc_row.setContentsMargins(0, 0, 0, 0)
        btc_row.addWidget(_label("BTC", "mono"))
        btc_row.addStretch(1)
        self._btc_value = _label("—", "mono")
        btc_row.addWidget(self._btc_value)
        body.addLayout(btc_row)
        body.addStretch(1)

        outer.addLayout(self._actions("live", "Open live", ()))
        return frame

    def _builder_card(self) -> QFrame:
        frame, outer = self._part(
            "Strategy builder",
            "Create strategies with blocks, formulas or code, and set their "
            "entry and exit rules.",
        )
        body: QVBoxLayout = outer.itemAt(2).widget().layout()

        body.addWidget(_label("STRATEGIES", "section"))
        self._strategy_box = QVBoxLayout()
        self._strategy_box.setContentsMargins(0, 0, 0, 0)
        self._strategy_box.setSpacing(2)
        body.addLayout(self._strategy_box)
        body.addWidget(_rule())
        body.addWidget(_label("ENTRY FORMULA", "section"))

        self._formula_well = QFrame()
        self._formula_well.setObjectName("well")
        well_row = QHBoxLayout(self._formula_well)
        well_row.setContentsMargins(10, 9, 10, 9)
        self._formula_label = _label("", "formula")
        well_row.addWidget(self._formula_label)
        well_row.addStretch(1)
        body.addWidget(self._formula_well)

        chip = QFrame()
        chip.setObjectName("chip")
        chip_row = QHBoxLayout(chip)
        chip_row.setContentsMargins(7, 3, 7, 3)
        chip_row.addWidget(_label("✓ valid", "chipText"))
        chip_holder = QHBoxLayout()
        chip_holder.setContentsMargins(0, 0, 0, 0)
        chip_holder.addWidget(chip)
        chip_holder.addStretch(1)
        body.addLayout(chip_holder)
        body.addStretch(1)

        outer.addLayout(self._actions("builder", "Open builder", ("+ New",)))
        return frame

    def _refresh_strategies(self) -> None:
        """Re-read the saved strategies into the builder card's list."""
        box = getattr(self, "_strategy_box", None)
        if box is None:
            return
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        from lalala import strategies

        saved = list(reversed(strategies.load()))  # most recent first
        if not saved:
            box.addWidget(_label("no saved strategies yet", "monoMuted"))
            self._formula_label.setText("write a rule to see it here")
            return

        for strategy in saved[:4]:
            badge, tone = _pnl_badge(
                strategy.entry, strategy.exit, strategy.timeframe
            )
            row = StrategyRow(strategy.name, badge, tone)
            row.clicked.connect(self._open_saved)
            box.addWidget(row)

        if len(saved) > 4:
            box.addWidget(_label(f"+{len(saved) - 4} more", "monoMuted"))
        self._formula_label.setText(saved[0].entry.replace("\n", " ") or "—")

    def _open_saved(self, name: str) -> None:
        self._open("builder", strategy=name)

    def _backtest_card(self) -> QFrame:
        frame, outer = self._part(
            "Backtest engine",
            "Replay a strategy on history, candle by candle, then review every "
            "result.",
        )
        body: QVBoxLayout = outer.itemAt(2).widget().layout()

        body.addWidget(EquityCurve())
        body.addWidget(_label("2017 → 2026 · 1m · 196,496 bars", "monoMuted"))
        body.addWidget(_rule())
        body.addLayout(self._row("PnL", "−0.42%", _accent("●", AMBER_DOT)))
        body.addLayout(self._row("Win rate", "44%", _accent("●", AMBER_DOT)))
        body.addLayout(self._row("Max DD", "−2.72%", _accent("▲", UP)))
        body.addStretch(1)

        outer.addLayout(self._actions("backtest", "Open engine", ("Run",)))
        return frame

    @staticmethod
    def _outcome_tile(
        name: str, price: str, border: str, color: str, filled: bool
    ) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {border}; border-radius: 6px; "
            f"background: {'#13211a' if filled else INNER}; }}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        label = _label(name, "tileName")
        label.setStyleSheet(f"color: {color}; border: none;")
        value = _label(price, "tileValue")
        value.setStyleSheet(f"color: {color}; border: none;")
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(value)
        return frame, value

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        self._destroy_view()
        self.feed.stop()
        self.polymarket_feed.stop()
        from lalala.settings import save_window_geometry

        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        except Exception:  # a window that never showed has nothing to save
            geometry = ""
        if geometry:
            save_window_geometry(geometry)
        super().closeEvent(event)


def run(argv: list[str] | None = None) -> int:
    """Start the hub shell. Returns the Qt exit code."""
    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("lalala")
    app.setOrganizationName("lalala")

    # The hub paints its own chrome, but the embedded views expect the app
    # theme; applying it keeps those sections looking like the rest of the app.
    from lalala.theme import apply_dark_theme

    apply_dark_theme(app)

    window = MainHubWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
