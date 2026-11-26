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
    QCheckBox,
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

from bi_trading.ui.shortcuts import CONTEXT_OF_VIEW, bind_help  # noqa: E402
from bi_trading.ui.palette import (  # noqa: E402
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
QLabel#stat {{ font-size: 18px; font-weight: 600; color: #ffffff; }}
QLabel#mono {{ font-family: {MONO}; font-size: 12px; color: {SOFT}; }}
QLabel#monoMuted {{ font-family: {MONO}; font-size: 11px; color: {MUTED}; }}
QLabel#section {{ font-size: 10px; font-weight: 600; letter-spacing: 1px; color: {MUTED}; }}
QLabel#formula {{ font-family: {MONO}; font-size: 12px; color: {SOFT}; }}
QLabel#big {{ font-family: {MONO}; font-size: 20px; font-weight: 600; }}
QLabel#tileName {{ font-family: {MONO}; font-size: 11px; }}
QLabel#tileValue {{ font-family: {MONO}; font-size: 18px; font-weight: 600; }}
/* The strip above every screen: its name, and the venues' round trips. */
QLabel#topTitle {{ font-size: 12px; font-weight: 600; color: {TEXT}; }}
QFrame#venueSwitch {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
}}
QFrame#venueSwitch:hover {{ background: {HOVER}; }}
QFrame#venueSwitch[active="true"] {{ background: #231f10; border-color: #4a3f1a; }}
QLabel#venueLogo {{ background: transparent; border: none; }}
QLabel#venueCaption {{
    background: transparent; font-size: 15px; font-weight: 700; color: {SOFT};
}}
QFrame#venueTag[venue="pm"] {{ border-color: #243a7a; }}
QFrame#venueTag[venue="hl"] {{ border-color: #1f5a4c; }}
QFrame#venueTag {{ background: {INNER}; border: 1px solid {BORDER}; border-radius: 4px; }}
QFrame#topChip {{ background: transparent; border: 1px solid {BORDER}; border-radius: 6px; }}
QLabel#chipValue {{ font-family: {MONO}; font-size: 11px; color: {TEXT}; }}
QLabel#liveBadge {{
    font-family: {MONO}; font-size: 10px; font-weight: 700; letter-spacing: 1px; color: {DOWN};
    background: #2a1414; border: 1px solid #5a2626; border-radius: 4px; padding: 1px 8px;
}}
QFrame#modeSwitch {{ background: transparent; border: 1px solid {BORDER}; border-radius: 6px; }}
QLabel#modePaper, QLabel#modeLive {{
    font-family: {MONO}; font-size: 10px; font-weight: 700; letter-spacing: 1px;
    color: {MUTED}; padding: 4px 12px; border-radius: 5px;
}}
QLabel#modePaper[on="true"] {{ color: {AMBER_DOT}; background: #2a1d0c; }}
QLabel#modeLive[on="true"] {{ color: {DOWN}; background: #2a1414; }}
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

QFrame#stile {{ background: {INNER}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#stile:hover {{ border-color: #3a3b41; }}
QFrame#stile[selected="true"] {{ background: #231f10; border-color: {ACCENT}; }}
QFrame#stileNew {{ background: transparent; border: 1px dashed #4a3f1a; border-radius: 8px; }}
QFrame#stileNew:hover {{ border-color: {ACCENT}; }}
QWidget#liveBlock {{ background: transparent; }}
QLabel#stileName {{ font-size: 13px; font-weight: 600; color: {TEXT}; }}
QLabel#stileMeta {{ font-size: 11px; color: {MUTED}; }}
QLabel#stileNewText {{ font-size: 12px; color: {ACCENT}; }}
QFrame#stratRow {{ background: transparent; border-radius: 6px; }}
QFrame#stratRow:hover {{ background: {HOVER}; }}
/* Names are interface (Inter); only the return beside them is a number. */
QLabel#stratName {{ font-size: 12px; color: {SOFT}; }}
QLabel#stratPnl {{ font-family: {MONO}; font-size: 12px; }}
"""

from bi_trading.ui.qss_hub import BAR_PART  # noqa: E402

QSS = QSS + BAR_PART

# Sidebar sections, in order. "home" is the hub itself.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("home", "Home"),
    ("live", "Live"),
    ("builder", "Strategy builder"),
    ("backtest", "Backtest engine"),
    ("ml", "ML strategy builder"),
)

# What the strip above a screen calls it.
TITLES: dict[str, str] = {
    "home": "Home",
    "live": "Live",
    "builder": "Strategy builder",
    "backtest": "Backtest",
    "ml": "ML strategy builder",
    "logs": "Logs",
    "settings": "Settings",
}

# A venue round trip slower than this (ms) is logged as a warning.
LATENCY_LIMIT_MS = 250
# The venues whose round trip the rail reports: (key, name, dot colour).
VENUES: tuple[tuple[str, str, str], ...] = (
    ("pm", "Polymarket", PM_DOT),
    ("hl", "Hyperliquid", HL_DOT),
)

# Section icons live with the widgets they build; the rail re-uses them.
from bi_trading.ui.venue_icons import has_logo, venue_mark, venue_pixmap  # noqa: E402
from bi_trading.ui.hub.hub_widgets import (  # noqa: E402
    EquityCurve,
    ProgressBar,
    NewTile,
    StrategyRow,
    StrategyTile,
    VenueSwitch,
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
    ("logs", "Logs"),
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


def _body_of(outer: QVBoxLayout) -> QVBoxLayout:
    """The layout of the card's body: the third thing in a `_part`."""
    item = outer.itemAt(2)
    widget = item.widget() if item is not None else None
    layout = widget.layout() if widget is not None else None
    assert isinstance(layout, QVBoxLayout)
    return layout


class MainHubWindow(QMainWindow):
    """The hub shell: a folded rail over a stack of rebuildable views."""

    def __init__(self, autostart: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("bi-trading")
        self.setMinimumSize(880, 600)
        self.resize(1280, 820)

        from bi_trading.state.settings import load_window_geometry

        saved_geometry = load_window_geometry()
        if saved_geometry:
            self.restoreGeometry(QByteArray.fromBase64(saved_geometry.encode()))

        from bi_trading.state import venue as venue_state

        self._venue = venue_state.current()
        self._venue_buttons: dict[str, QPushButton] = {}
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
        self._slow: dict[str, bool] = {}
        self._up: dict[str, bool] = {}
        self._seen_up: set[str] = set()
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
        # The content column: a strip with the screen's name, then the screen.
        content = QWidget(root)
        content.setObjectName("hubStack")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self._top_bar())
        column.addWidget(self.stack, 1)
        self.grid.addWidget(content, 0, 1)
        self.grid.setColumnStretch(0, 0)
        self.grid.setColumnStretch(1, 1)
        self.grid.setRowStretch(0, 1)

        self.setCentralWidget(root)
        self._apply_venue()
        for number, venue in enumerate(("pm", "hl", "both"), start=1):
            shortcut = QShortcut(QKeySequence(f"Alt+{number}"), self)
            shortcut.activated.connect(lambda v=venue: self._set_venue(v))

        # -- feeds: the rail's latencies and the Live card read from these --
        from bi_trading.data.feed import MarketFeed
        from bi_trading.data.polymarket_feed import PolymarketFeed
        from bi_trading.state.settings import Settings

        self.feed = MarketFeed(self)
        self.feed.latency.connect(self._on_hl_latency)
        self.feed.connected.connect(self._on_hl_connected)
        self.feed.mids_updated.connect(self._on_mids)
        self.feed.book_updated.connect(self._on_hl_book)
        self.feed.track("BTC")
        self.polymarket_feed = PolymarketFeed(self)
        self.polymarket_feed.latency.connect(self._on_pm_latency)
        self.polymarket_feed.status.connect(self._on_pm_status)
        self.polymarket_feed.market_ready.connect(self._on_pm_market)
        self.polymarket_feed.book_updated.connect(self._on_pm_book)
        if autostart:
            self.feed.start()
            self.polymarket_feed.start()

        # The trade form moved a paper position: keep the Home card in step.
        from bi_trading.state.positions import store

        store().changed.connect(self._refresh_position)

        start = Settings.load().general.start_page
        start = start if start in ("live", "builder", "backtest", "ml") else "home"
        self._open(start)

        # Cmd+1…4 jump between the views, Cmd+, opens Settings.
        for keys, target in (
            ("Ctrl+1", "home"),
            ("Ctrl+2", "live"),
            ("Ctrl+3", "builder"),
            ("Ctrl+4", "backtest"),
            ("Ctrl+5", "logs"),
            ("Ctrl+6", "ml"),
            ("Ctrl+,", "settings"),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(
                lambda t=target: self._open(t)
            )

        bind_help(self, lambda: CONTEXT_OF_VIEW.get(self._key, "Everywhere"))

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
        from bi_trading.state import venue as venue_state

        if key in ("builder", "backtest") and not venue_state.has_strategies(self._venue):
            key = "home"   # strategy work is per venue; "both" has none
        self._key = key
        self._destroy_view()
        self.screen_title.setText(TITLES.get(key, key.title()))
        self._clear_extras()
        self._sync_mode()

        if key == "home":
            self._refresh_strategies()
            self._refresh_models()
            self._refresh_stats()
            self.stack.setCurrentWidget(self.home)
        else:
            view = self._build_view(key, strategy)
            if view is None:
                self.stack.setCurrentWidget(self.home)
                key = "home"
            else:
                view.setMinimumSize(320, 240)
                if key in ("live", "builder", "backtest"):
                    # These views keep their own 8px canvas margin; next to the
                    # hub's it doubled the space left of the content.
                    inner = view.centralWidget().layout() if hasattr(view, "centralWidget") else None
                    if inner is not None:
                        m = inner.contentsMargins()
                        inner.setContentsMargins(0, m.top(), m.right(), m.bottom())
                self._view = view
                self.stack.addWidget(view)
                self.stack.setCurrentWidget(view)
                if key == "live" and self._venue != "pm":
                    self._live_toggles(view)

        self._highlight(key)

    def _set_venue(self, venue: str) -> None:
        """Switch the venue: remembered, and every screen follows."""
        from bi_trading.state import venue as venue_state

        if venue not in venue_state.VENUES or venue == self._venue:
            return
        self._venue = venue
        venue_state.save(venue)
        self._apply_venue()
        self._open(self._key)

    def _apply_venue(self) -> None:
        """Everything that reads the venue: the switch, the tag, the rail entries."""
        from bi_trading.state import venue as venue_state

        for name, button in self._venue_buttons.items():
            button.setProperty("active", "true" if name == self._venue else "false")
            style = button.style()
            style.unpolish(button)
            style.polish(button)
        layout = self.venue_tag.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        shown = ("pm", "hl") if self._venue == "both" else (self._venue,)
        for index, key in enumerate(shown):
            if index:
                layout.addWidget(_label("+", "caption"))
            layout.addWidget(venue_mark(key, 16))
        self.venue_tag.setToolTip(venue_state.NAMES[self._venue])
        self.venue_tag.setProperty("venue", self._venue)
        style = self.venue_tag.style()
        style.unpolish(self.venue_tag)
        style.polish(self.venue_tag)
        strategies = venue_state.has_strategies(self._venue)
        for key in ("builder", "backtest"):
            for button in self._nav_buttons.get(key, []):
                button.setVisible(strategies)
        self._apply_home_venue()

    def _apply_home_venue(self) -> None:
        """Home shows what the venue has: its balance, its market, its Live block."""
        venue = self._venue
        frames = getattr(self, "_stat_frames", None)
        if frames is None:
            return
        for title, shown in (
            ("Next market", venue != "hl"),
            ("Hyperliquid balance", venue != "pm"),
            ("Polymarket balance", venue != "hl"),
            ("Active strategy", venue != "both"),
            ("Last backtest", venue != "both"),
        ):
            frames[title].setVisible(shown)
        text = {
            "pm": "Watch the Polymarket 5m market and the BTC chart, and place bets.",
            "hl": "Watch the Hyperliquid market and the order book, and place trades.",
            "both": "Watch both venues and place bets or trades.",
        }[venue]
        self._live_desc.setText(text)
        self._live_pm.setVisible(venue != "hl")
        self._live_hl.setVisible(venue != "pm")
        for card in (self._builder_frame, self._backtest_frame):
            card.setVisible(venue != "both")
        self._create_button.setVisible(venue != "both")

    def _top_bar(self) -> QWidget:
        """The strip above every screen: its name and the venues it covers on the
        left, the screen's own controls beside them (Live: the chart overlays),
        and on the right the live account value and which mode orders go in."""
        bar = QWidget()
        bar.setObjectName("hubStack")
        row = QHBoxLayout(bar)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)
        self.screen_title = _label(TITLES["home"], "topTitle")
        row.addWidget(self.screen_title)
        # The venues this screen covers, as their logos; filled by `_apply_venue`.
        self.venue_tag = QFrame()
        self.venue_tag.setObjectName("venueTag")
        tag_row = QHBoxLayout(self.venue_tag)
        tag_row.setContentsMargins(6, 3, 6, 3)
        tag_row.setSpacing(6)
        row.addWidget(self.venue_tag)
        row.addStretch(1)
        # A screen's own controls live here while it is open.
        self.top_extras = QHBoxLayout()
        self.top_extras.setContentsMargins(0, 0, 0, 0)
        self.top_extras.setSpacing(14)
        row.addLayout(self.top_extras)

        chip = QFrame()
        chip.setObjectName("topChip")
        inside = QHBoxLayout(chip)
        inside.setContentsMargins(8, 4, 10, 4)
        inside.setSpacing(8)
        inside.addWidget(_label("LIVE", "liveBadge"))
        self.live_value = _label("—", "chipValue")
        self.live_value.setToolTip("Hyperliquid account value (read only)")
        inside.addWidget(self.live_value)
        row.addWidget(chip)

        switch = QFrame()
        switch.setObjectName("modeSwitch")
        modes = QHBoxLayout(switch)
        modes.setContentsMargins(2, 2, 2, 2)
        modes.setSpacing(2)
        self.mode_paper = _label("PAPER", "modePaper")
        self.mode_live = _label("LIVE", "modeLive")
        for label in (self.mode_paper, self.mode_live):
            modes.addWidget(label)
        switch.setToolTip("Where orders go. Change it in Settings: Place real orders.")
        row.addWidget(switch)
        self._sync_mode()
        # The account value is read off the rail, which the balance poll keeps.
        self._chip_clock = QTimer(self)
        self._chip_clock.setInterval(1000)
        self._chip_clock.timeout.connect(self._sync_live_chip)
        self._chip_clock.start()
        return bar

    def _sync_live_chip(self) -> None:
        rail = self._rail_balances.get("hl")
        if rail is not None and self.live_value.text() != rail.text():
            self.live_value.setText(rail.text())

    def _sync_mode(self) -> None:
        """PAPER or LIVE, by whether real orders are switched on in Settings."""
        from bi_trading.state.orders import armed

        live = armed()
        for label, on in ((self.mode_paper, not live), (self.mode_live, live)):
            label.setProperty("on", "true" if on else "false")
            style = label.style()
            style.unpolish(label)
            style.polish(label)

    def _live_toggles(self, live) -> None:
        """The chart overlays sit in the top bar on Live, as the design has them;
        the card's own switches stay, hidden, and follow these."""
        card = live.main_card
        for caption, toggle in (
            ("Volume", card.volume_toggle), ("Bollinger", card.bollinger_toggle),
        ):
            box = QCheckBox(caption)
            box.setObjectName("overlayToggle")
            box.setCursor(Qt.CursorShape.PointingHandCursor)
            box.setChecked(toggle.isChecked())
            box.toggled.connect(toggle.setChecked)
            toggle.setVisible(False)
            self.top_extras.addWidget(box)

    def _clear_extras(self) -> None:
        while self.top_extras.count():
            item = self.top_extras.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

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
            from bi_trading.ui.main_window import MainWindow

            # Share our feeds: the terminal and the rail then read one set of
            # sockets, and their latencies agree.
            return MainWindow(
                feed=self.feed,
                polymarket_feed=self.polymarket_feed,
                show_top_bar=False,
                venue=self._venue,
            )
        if key == "builder":
            from bi_trading.ui.strat.strat_builder import StrategyBuilderWindow

            window = StrategyBuilderWindow()
            if strategy:
                window.load_strategy(strategy)
            return window
        if key == "backtest" and self._venue == "pm":
            # Polymarket bets on five-minute markets; it has its own engine.
            from bi_trading.ui.strat.strat_pm import PolymarketBacktestWindow

            pm_backtest = PolymarketBacktestWindow()
            pm_backtest.open_builder = lambda: self._open("builder")  # type: ignore[method-assign]
            return pm_backtest
        if key == "backtest":
            from bi_trading.ui.strat.strat_window import StratWindow

            backtest = StratWindow()
            backtest.open_builder = lambda: self._open("builder")  # type: ignore[method-assign]
            if strategy:
                backtest.pick_strategy(strategy, run=True)
            return backtest
        if key == "ml":
            from bi_trading.ui.ml.ml_builder import MLBuilderView

            ml = MLBuilderView()
            ml.open_builder.connect(lambda name: self._open("builder", name or None))
            ml.open_backtest.connect(lambda name: self._open("backtest", name))
            ml.open_model_builder.connect(lambda name: self._open("model", name or None))
            if strategy:
                ml.load_saved(strategy)
            return ml
        if key == "model":
            from bi_trading.ui.ml.model_builder import ModelBuilderView

            model = ModelBuilderView()
            if strategy:
                model.load(strategy)

            def back(name: str = "") -> None:
                self._open("ml")
                if name and isinstance(self._view, QWidget) and hasattr(self._view, "use_architecture"):
                    self._view.use_architecture(name)  # type: ignore[attr-defined]

            model.closed.connect(back)
            model.use_requested.connect(back)
            return model
        if key == "logs":
            from bi_trading.ui.hub.logs_view import LogsView

            logs = LogsView()
            logs.open_live.connect(lambda: self._open("live"))
            return logs
        if key == "settings":
            from bi_trading.ui.hub.settings_view import SettingsView

            view = SettingsView(pm_ms=self._last_pm, hl_ms=self._last_hl)
            self.polymarket_feed.latency.connect(view.set_pm_latency)
            self.feed.latency.connect(view.set_hl_latency)
            return view
        return None

    def _highlight(self, key: str) -> None:
        key = "ml" if key == "model" else key  # the model builder lives under ML
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
        # Which venue every screen is about: Polymarket, Hyperliquid, or both.
        for venue, caption, tip in (
            ("pm", "PM", "Polymarket"),
            ("hl", "HL", "Hyperliquid"),
            ("both", "⇄", "Both venues"),
        ):
            # The venues are shown by their own marks, with their round trip under
            # each, inside the box that lights when the venue is chosen.
            mark = venue_pixmap(venue, 20) if venue != "both" else None
            switch = VenueSwitch(venue, caption, mark)
            switch.setProperty("active", "true" if venue == self._venue else "false")
            switch.setToolTip(f"{tip} (Alt+{('pm', 'hl', 'both').index(venue) + 1})")
            switch.clicked.connect(lambda v=venue: self._set_venue(v))
            self._venue_buttons[venue] = switch
            if switch.delay is not None:
                switch.delay.setToolTip(f"Round trip to {tip}")
                self._latency_labels[venue] = switch.delay
            column.addWidget(switch, 0, Qt.AlignmentFlag.AlignHCenter)
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

        # The balances are still read here, but no longer drawn on the rail.
        for key, name, _color in VENUES:
            balance = _label("—", "railBalance")
            balance.setToolTip(f"{name} balance")
            self._rail_balances[key] = balance

        quit_button = self._rail_icon(
            "quit",
            "Quit bi-trading",
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

    def _show_delay(self, key: str, milliseconds: float) -> None:
        """The round trip under a venue's mark: green when quick, amber, then red."""
        label = self._latency_labels.get(key)
        if label is None:
            return
        label.setText(f"{milliseconds:.0f}ms")
        colour = UP if milliseconds <= 120 else AMBER_DOT if milliseconds <= LATENCY_LIMIT_MS else DOWN
        label.setStyleSheet(f"color: {colour};")

    def _on_hl_latency(self, milliseconds: float) -> None:
        self._last_hl = milliseconds
        self._show_delay("hl", milliseconds)
        self._watch_latency("hyperliquid", "Hyperliquid", milliseconds)

    def _on_pm_latency(self, milliseconds: int) -> None:
        self._last_pm = int(milliseconds)
        self._show_delay("pm", float(milliseconds))
        self._watch_latency("polymarket", "Polymarket", float(milliseconds))

    def _watch_latency(self, source: str, name: str, milliseconds: float) -> None:
        """One warning when a venue's round trip crosses the limit, one when it recovers."""
        slow = milliseconds > LATENCY_LIMIT_MS
        if slow == self._slow.get(source, False):
            return
        self._slow[source] = slow
        from bi_trading.state.events import event_log

        if slow:
            event_log().record(
                "warn", source, "LATENCY",
                f"High latency {milliseconds:.0f} ms (limit {LATENCY_LIMIT_MS} ms)",
                latency_ms=milliseconds,
            )
        else:
            event_log().record(
                "info", source, "LATENCY",
                f"{name} latency back to {milliseconds:.0f} ms",
                latency_ms=milliseconds,
            )

    def _on_hl_connected(self, up: bool) -> None:
        self._note_connection("hyperliquid", "Hyperliquid", up)

    def _on_pm_status(self, status: str) -> None:
        if status in ("reconnecting", "closed"):
            self._note_connection("polymarket", "Polymarket", False, status)
        elif status == "live":
            self._note_connection("polymarket", "Polymarket", True)

    def _note_connection(
        self, source: str, name: str, up: bool, status: str = ""
    ) -> None:
        """Log a connection coming or going, once per change."""
        if self._up.get(source) == up:
            return
        known = source in self._up
        self._up[source] = up
        if not known and not up:
            return  # not connected yet is not news
        from bi_trading.state.events import event_log

        if up:
            word = "reconnected" if source in self._seen_up else "connected"
            self._seen_up.add(source)
            event_log().record("info", "system", "CONNECTION", f"{name} {word}")
        else:
            event_log().record(
                "warn", "system", "CONNECTION", f"{name} {status or 'disconnected'}"
            )

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
        from bi_trading.data.polymarket_data import format_countdown

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

        create = self._create_button = _button("Create a strategy", "btn")
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
        self._stat_frames: dict[str, QFrame] = {}
        for title, value, sub in cards:
            frame, value_label, sub_label = self._stat_card(title, value, sub)
            self._stat_frames[title] = frame
            self._stat_values[title] = value_label
            self._stat_subs[title] = sub_label
            row.addWidget(frame, 1)
        return row

    @staticmethod
    def _stat_card(
        title: str, value: str, sub: str
    ) -> tuple[QFrame, QLabel, QLabel]:
        frame, layout = _panel()
        caption = _label(title, "caption")
        name = title.split(" ")[0]
        if has_logo(name):  # a venue's card carries its mark beside the title
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(6)
            head.addWidget(venue_mark(name, 14))
            head.addWidget(caption)
            head.addStretch(1)
            layout.addLayout(head)
        else:
            layout.addWidget(caption)
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

        from bi_trading.state import runs, strategies

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
                f"{span} · {run.trade_count:,} trades"
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

        from bi_trading.state.positions import change, store

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
        from bi_trading.state.positions import store

        position = store().get()
        if position is None:
            return "flat"
        return str(position.get("side", "flat")).lower()

    def _refresh_balances(self) -> None:
        """Ask each connected venue for its balance; show the side meanwhile."""
        from bi_trading.state.orders import config_for, is_testnet, service

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
                network = " · TESTNET" if is_testnet(venue) else ""
                sub.setText(f"USDC · {self._side_for(venue)}{network}")
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
        self._builder_frame = self._builder_card()
        self._backtest_frame = self._backtest_card()
        row.addWidget(self._builder_frame, 1)
        row.addWidget(self._backtest_frame, 1)
        row.addWidget(self._ml_card(), 1)
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

    def _actions(
        self, target: str, primary: str, ghosts: tuple[str, ...], wide: bool = False
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        first = _button(primary, "btn")
        first.clicked.connect(lambda: self._open(target))
        row.addWidget(first, 1 if wide else 0)
        for text in ghosts:
            button = _button(text, "ghost")
            button.clicked.connect(lambda: self._open(target))
            row.addWidget(button)
        if not wide:
            row.addStretch(1)
        return row

    def _live_card(self) -> QFrame:
        frame, outer = self._part(
            "Live",
            "Watch the Polymarket 5m market and the BTC chart, and place bets "
            "or trades.",
        )
        self._live_desc = outer.itemAt(1).widget()
        body = _body_of(outer)
        # Two blocks side by side; the venue shows one, or both.
        holder = QHBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        holder.setSpacing(18)
        body.addLayout(holder, 1)
        self._live_hl = self._hl_block()
        pm_block = QWidget()
        pm_block.setObjectName("liveBlock")
        self._live_pm = pm_block
        body = QVBoxLayout(pm_block)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        body.addWidget(_label("POLYMARKET · BTC 5M", "section"))

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
        holder.addWidget(pm_block, 1)
        holder.addWidget(self._live_hl, 1)

        outer.addLayout(self._actions("live", "Open live", (), wide=True))
        return frame

    def _hl_block(self) -> QWidget:
        """The Hyperliquid half of the Live card: bid and ask, the spread, BTC."""
        block = QWidget()
        block.setObjectName("liveBlock")
        body = QVBoxLayout(block)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        body.addWidget(_label("HYPERLIQUID · BTC PERP", "section"))
        tiles = QHBoxLayout()
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(8)
        bid_tile, self._bid_value = self._outcome_tile("BID", "—", UP, UP_BRIGHT, True)
        ask_tile, self._ask_value = self._outcome_tile("ASK", "—", DOWN, DOWN_SOFT, False)
        tiles.addWidget(bid_tile, 1)
        tiles.addWidget(ask_tile, 1)
        body.addLayout(tiles)
        spread = QHBoxLayout()
        spread.setContentsMargins(0, 0, 0, 0)
        spread.addWidget(_label("spread", "caption"))
        spread.addStretch(1)
        self._spread_value = _label("—", "mono")
        spread.addWidget(self._spread_value)
        body.addLayout(spread)
        body.addWidget(_rule())
        coin = QFrame()
        coin.setObjectName("stile")
        coin.setProperty("selected", "true")
        row = QHBoxLayout(coin)
        row.setContentsMargins(12, 8, 12, 8)
        row.addWidget(_label("BTC", "mono"))
        row.addStretch(1)
        self._hl_btc = _label("—", "mono")
        row.addWidget(self._hl_btc)
        body.addWidget(coin)
        body.addStretch(1)
        return block

    def _on_hl_book(self, book) -> None:
        """Keep the Home card's bid and ask current."""
        if book.coin != "BTC" or not hasattr(self, "_bid_value"):
            return
        bid, ask = book.best_bid, book.best_ask
        if bid is None or ask is None:
            return
        self._bid_value.setText(f"{bid.px:,.1f}")
        self._ask_value.setText(f"{ask.px:,.1f}")
        self._spread_value.setText(f"{ask.px - bid.px:,.1f}")

    def _builder_card(self) -> QFrame:
        frame, outer = self._part(
            "Strategy builder",
            "Create strategies with blocks, formulas or code, and set their "
            "entry and exit rules.",
        )
        body = _body_of(outer)

        body.addWidget(_label("STRATEGIES", "section"))
        self._strategy_box = QGridLayout()
        self._strategy_box.setContentsMargins(0, 0, 0, 0)
        self._strategy_box.setHorizontalSpacing(8)
        self._strategy_box.setVerticalSpacing(8)
        body.addLayout(self._strategy_box)
        body.addWidget(_rule())
        self._formula_head = _label("ENTRY FORMULA", "section")
        body.addWidget(self._formula_head)

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

        from bi_trading.state import strategies

        saved = list(reversed(strategies.load()))  # most recent first
        shown = saved[:4]
        for index, strategy in enumerate(shown):
            badge, tone = _pnl_badge(
                strategy.entry, strategy.exit, strategy.timeframe,
                strategy.side, strategy.short_entry, strategy.model,
            )
            meta = f"{strategy.timeframe} · {strategy.side}" + (
                " · selected" if index == 0 else ""
            )
            tile = StrategyTile(strategy.name, meta, badge, tone, selected=index == 0)
            tile.clicked.connect(self._open_saved)
            # A lone last tile takes the whole line, as the design has it.
            lone = index == len(shown) - 1 and len(shown) % 2 == 1
            line, column = divmod(index, 2)
            if lone:
                box.addWidget(tile, line, 0, 1, 2)
            else:
                box.addWidget(tile, line, column)
        new = NewTile("+ New strategy")
        new.clicked.connect(lambda: self._open("builder"))
        box.addWidget(new, (len(shown) + 1) // 2, 0, 1, 2)
        box.setColumnStretch(0, 1)
        box.setColumnStretch(1, 1)
        if len(saved) > 4:
            box.addWidget(
                _label(f"+{len(saved) - 4} more", "monoMuted"),
                (len(shown) + 1) // 2 + 1, 0, 1, 2,
            )
        if not saved:
            self._formula_head.setText("ENTRY FORMULA")
            self._formula_label.setText("write a rule to see it here")
            return
        self._formula_head.setText(f"ENTRY FORMULA · {saved[0].name}")
        self._formula_label.setText(saved[0].entry.replace("\n", " ") or "—")

    def _open_saved(self, name: str) -> None:
        self._open("builder", strategy=name)

    def _backtest_card(self) -> QFrame:
        frame, outer = self._part(
            "Backtest engine",
            "Replay a strategy on history, candle by candle, then review every "
            "result.",
        )
        body = _body_of(outer)

        body.addWidget(EquityCurve())
        body.addWidget(_label("2017 → 2026 · 1m · 196,496 bars", "monoMuted"))
        body.addWidget(_rule())
        body.addLayout(self._row("PnL", "−0.42%", _accent("●", AMBER_DOT)))
        body.addLayout(self._row("Win rate", "44%", _accent("●", AMBER_DOT)))
        body.addLayout(self._row("Max DD", "−2.72%", _accent("▲", UP)))
        body.addStretch(1)

        outer.addLayout(self._actions("backtest", "Open engine", ("Run",)))
        return frame

    def _ml_card(self) -> QFrame:
        frame, outer = self._part(
            "ML strategies",
            "Train a model on the candles, then trade what it predicts.",
        )
        body = _body_of(outer)
        self._model_box = QVBoxLayout()
        self._model_box.setContentsMargins(0, 0, 0, 0)
        self._model_box.setSpacing(4)
        body.addLayout(self._model_box)
        body.addStretch(1)
        self._refresh_models()
        outer.addLayout(self._actions("ml", "Open ML builder", ()))
        return frame

    def _refresh_models(self) -> None:
        """The saved ML strategies, each with its model's return on its test part."""
        box = getattr(self, "_model_box", None)
        if box is None:
            return
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        from bi_trading.state import strategies

        saved = [s for s in reversed(strategies.load()) if s.model]
        if not saved:
            box.addWidget(_label("no ML strategies yet", "monoMuted"))
            return
        for strategy in saved[:4]:
            badge, tone = _pnl_badge(
                strategy.entry, strategy.exit, strategy.timeframe,
                strategy.side, strategy.short_entry, strategy.model,
            )
            row = StrategyRow(strategy.name, badge, tone)
            row.clicked.connect(lambda name: self._open("ml", strategy=name))
            box.addWidget(row)
        if len(saved) > 4:
            box.addWidget(_label(f"+{len(saved) - 4} more", "monoMuted"))

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
        from bi_trading.state.settings import save_window_geometry

        try:
            geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        except RuntimeError:  # a window that never showed has nothing to save
            geometry = ""
        if geometry:
            save_window_geometry(geometry)
        super().closeEvent(event)


def run(argv: list[str] | None = None) -> int:
    """Start the hub shell. Returns the Qt exit code."""
    from bi_trading.logs import install_qt_handler, setup
    from bi_trading.state.settings import ensure_file

    # A file, never the console: this is a GUI, not a command. Without this a
    # dropped socket or a failed balance check printed its whole traceback over
    # the terminal the hub was launched from.
    setup()
    install_qt_handler()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    ensure_file()
    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("bi-trading")
    app.setOrganizationName("bi-trading")

    # The hub paints its own chrome, but the embedded views expect the app
    # theme; applying it keeps those sections looking like the rest of the app.
    from bi_trading.ui.theme import apply_theme

    apply_theme(app)

    window = MainHubWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
