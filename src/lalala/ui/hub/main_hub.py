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

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
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

from lalala.ui.palette import (  # noqa: E402
    ACCENT,
    AMBER_DOT,
    BORDER,
    CANVAS,
    DOWN,
    DOWN_SOFT,
    DOWN_SOFT_BG,
    FAINT,
    HL_DOT,
    HOVER,
    INNER,
    MONO,
    MUTED,
    PANEL,
    PM_DOT,
    SOFT,
    TEXT,
    TRACK,
    UP,
    UP_BRIGHT,
    WELL,
)

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
QLabel#railBalance {{ font-family: {MONO}; font-size: 9px; color: {MUTED}; }}

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

# Section icons live with the widgets they build; the rail re-uses them.
from lalala.ui.hub.hub_widgets import (  # noqa: E402
    EquityCurve,
    ProgressBar,
    StrategyRow,
    _accent,
    _button,
    _dot,
    _label,
    _panel,
    _pnl_badge,
    _rule,
    _svg_icon,
)

# Bottom rail entries that have no view yet: (icon key, label).
RAIL_EXTRAS: tuple[tuple[str, str], ...] = (
    ("settings", "Settings"),
)


def _money_short(value: float) -> str:
    """A balance small enough for the 56px rail: `$1.2k`, `$250`, `$12k`."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"${value / 1_000:.0f}k"
    if value >= 1_000:
        return f"${value / 1_000:.1f}k"
    return f"${value:,.0f}"



# -- the window --------------------------------------------------------------


class MainHubWindow(QMainWindow):
    """The hub shell: a folded rail over a stack of rebuildable views."""

    def __init__(self, autostart: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("lalala")
        self.setMinimumSize(880, 600)
        self.resize(1280, 820)

        from lalala.state.settings import load_window_geometry

        saved_geometry = load_window_geometry()
        if saved_geometry:
            self.restoreGeometry(QByteArray.fromBase64(saved_geometry.encode()))

        self._key = "home"
        self._nav_buttons: dict[str, list[QPushButton]] = {}
        self._view: QWidget | None = None
        self._latency_labels: dict[str, QLabel] = {}
        self._rail_balances: dict[str, QLabel] = {}
        self._market = None  # the live Polymarket market, for the Live card
        self._last_pm: int | None = None
        self._last_hl: float | None = None
        self._btc_price: float | None = None
        self._balance_wired = False
        self._online = autostart

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
        from lalala.data.feed import MarketFeed
        from lalala.data.polymarket_feed import PolymarketFeed
        from lalala.state.settings import Settings

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
        from lalala.state.positions import store

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

        # Balances move on their own; a slow poll keeps the cards honest.
        self._balances_clock = QTimer(self)
        self._balances_clock.setInterval(30_000)
        self._balances_clock.timeout.connect(self._refresh_balances)
        self._balances_clock.start()

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
            from lalala.ui.main_window import MainWindow

            # Share our feeds: the terminal and the rail then read one set of
            # sockets, and their latencies agree.
            return MainWindow(
                feed=self.feed,
                polymarket_feed=self.polymarket_feed,
                show_top_bar=False,
            )
        if key == "builder":
            from lalala.ui.strat.strat_builder import StrategyBuilderWindow

            window = StrategyBuilderWindow()
            if strategy:
                window.load_strategy(strategy)
            return window
        if key == "backtest":
            from lalala.ui.strat.strat_window import StratWindow

            return StratWindow()
        if key == "settings":
            from lalala.ui.hub.settings_view import SettingsView

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
        balance = _label("—", "railBalance")
        balance.setToolTip(f"{name} balance")
        box.addWidget(balance, 0, Qt.AlignmentFlag.AlignHCenter)
        self._rail_balances[key] = balance
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
        from lalala.data.polymarket_data import format_countdown

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
            ("Hyperliquid balance", "—", "not connected"),
            ("Polymarket balance", "—", "not connected"),
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

        from lalala.state import runs, strategies

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
        self._refresh_balances()

    def _refresh_position(self) -> None:
        """The Home card's open position, read from the shared store."""
        values = getattr(self, "_stat_values", None)
        if not values or "Open position" not in values:
            return

        from lalala.state.positions import change, store

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

    # -- provider balances -------------------------------------------------

    @staticmethod
    def _side_for(venue: str) -> str:
        """The current side for a venue: the paper position's, or flat."""
        from lalala.state.positions import store

        position = store().get()
        if position is None:
            return "flat"
        return str(position.get("side", "flat")).lower()

    def _refresh_balances(self) -> None:
        """Ask each connected venue for its balance; show the side meanwhile."""
        from lalala.state.orders import config_for, service

        connected = [
            venue
            for venue, card in (
                ("hyperliquid", "Hyperliquid balance"),
                ("polymarket", "Polymarket balance"),
            )
            if config_for(venue) is not None and card in self._stat_values
        ]
        for venue, card in (
            ("hyperliquid", "Hyperliquid balance"),
            ("polymarket", "Polymarket balance"),
        ):
            value = self._stat_values.get(card)
            sub = self._stat_subs.get(card)
            if value is None or sub is None:
                continue
            rail = self._rail_balances.get(self._rail_key(venue))
            if venue in connected:
                sub.setText(f"USDC · {self._side_for(venue)}")
            else:
                value.setText("—")
                sub.setText("not connected")
                if rail is not None:
                    rail.setText("—")
        if not connected:
            return

        if not self._online:
            # Headless (tests): keep the labels, skip the network.
            for venue in connected:
                self._stat_values[self._balance_card(venue)].setText("—")
            return

        svc = service()
        if not self._balance_wired:
            svc.balance_ready.connect(self._on_balance)
            svc.balance_failed.connect(self._on_balance_failed)
            self._balance_wired = True
        for venue in connected:
            card = self._balance_card(venue)
            self._stat_values[card].setText("…")
            rail = self._rail_balances.get(self._rail_key(venue))
            if rail is not None:
                rail.setText("…")
            svc.request_balance(venue)

    @staticmethod
    def _rail_key(venue: str) -> str:
        return "hl" if venue == "hyperliquid" else "pm"

    def _balance_card(self, venue: str) -> str:
        return "Hyperliquid balance" if venue == "hyperliquid" else "Polymarket balance"

    def _on_balance(self, venue: str, free: float) -> None:
        card = self._balance_card(venue)
        if card in self._stat_values:
            self._stat_values[card].setText(f"${free:,.2f}")
            self._stat_subs[card].setText(f"USDC · {self._side_for(venue)}")
        rail = self._rail_balances.get(self._rail_key(venue))
        if rail is not None:
            rail.setText(_money_short(free))

    def _on_balance_failed(self, venue: str, reason: str) -> None:
        card = self._balance_card(venue)
        if card not in self._stat_values:
            return
        self._stat_values[card].setText("—")
        self._stat_subs[card].setText(reason[:48])
        rail = self._rail_balances.get(self._rail_key(venue))
        if rail is not None:
            rail.setText("—")

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

        from lalala.state import strategies

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
        from lalala.state.settings import save_window_geometry

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
    from lalala.ui.theme import apply_dark_theme

    apply_dark_theme(app)

    window = MainHubWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
