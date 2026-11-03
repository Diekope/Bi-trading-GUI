"""Application shell.

Canvas with a slim top bar (latency) over a horizontal splitter:

    Polymarket 5m BTC market  |  vertical splitter of market cards

Every split — horizontal and vertical — uses the same 8px transparent gap, so
all cards float on the canvas identically. The "+" button lives on the newest
card, and each card collapses its search row once a market is loaded.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QCheckBox,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import MarketCard
from lalala.feed import MarketFeed
from lalala.market_data import DEFAULT_MARKET, TIMEFRAMES, CandleSeries, Market
from lalala.panels import MAX_TILES
from lalala.polymarket_feed import PolymarketFeed
from lalala.polymarket_panel import PolymarketPanel
from lalala.theme import CANVAS, CARD_GAP

log = logging.getLogger(__name__)

# Latency colour thresholds, milliseconds.
FAST_MS = 120.0
OK_MS = 300.0


class MainWindow(QMainWindow):
    def __init__(self, autostart: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("lalala")
        self.setMinimumSize(620, 520)
        self.resize(1180, 760)

        self._markets: dict[str, Market] = {}
        self._watched: set[tuple[str, str]] = set()

        canvas = QWidget(self)
        canvas.setObjectName("canvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#canvas {{ background-color: {CANVAS}; }}")

        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(6)

        # -- top bar: venue latency --
        top_bar = QWidget(canvas)
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(2, 0, 2, 0)
        top_layout.setSpacing(10)
        top_layout.addStretch(1)

        # Chart overlays: one switch per indicator, applied to every card.
        self.volume_toggle = QCheckBox("Volume")
        self.volume_toggle.setObjectName("overlayToggle")
        self.volume_toggle.setToolTip("Volume bars under the candles")
        self.volume_toggle.setChecked(True)
        self.volume_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volume_toggle.toggled.connect(self._apply_overlays)

        self.bollinger_toggle = QCheckBox("Bollinger")
        self.bollinger_toggle.setObjectName("overlayToggle")
        self.bollinger_toggle.setToolTip("20-period, 2σ Bollinger bands")
        self.bollinger_toggle.setChecked(False)
        self.bollinger_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bollinger_toggle.toggled.connect(self._apply_overlays)

        top_layout.addWidget(self.volume_toggle)
        top_layout.addWidget(self.bollinger_toggle)
        top_layout.addSpacing(4)

        self.latency_label = QLabel("HL ● connecting…")
        self.latency_label.setObjectName("latencyLabel")
        self.latency_label.setToolTip(
            "WebSocket round-trip to api.hyperliquid.xyz"
        )
        top_layout.addWidget(self.latency_label)

        self.pm_latency_label = QLabel("PM —")
        self.pm_latency_label.setStyleSheet(
            "color: #6f6f76; font-size: 10px; background: transparent;"
        )
        self.pm_latency_label.setToolTip(
            "WebSocket round-trip to ws-subscriptions-clob.polymarket.com"
        )
        top_layout.addWidget(self.pm_latency_label)
        layout.addWidget(top_bar)

        # -- content --
        self.splitter = QSplitter(Qt.Orientation.Horizontal, canvas)
        self.splitter.setObjectName("cardSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(CARD_GAP)

        self.polymarket = PolymarketPanel(self.splitter)

        # Same gap as the horizontal split, but vertical.
        self.stack = QSplitter(Qt.Orientation.Vertical, self.splitter)
        self.stack.setObjectName("tileSplitter")
        self.stack.setChildrenCollapsible(False)
        self.stack.setHandleWidth(CARD_GAP)

        self.splitter.addWidget(self.polymarket)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([560, 560])

        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(canvas)
        self.installEventFilter(self)

        self.cards: list[MarketCard] = []
        self.main_card = self._new_card(DEFAULT_MARKET, closable=False)
        self.stack.addWidget(self.main_card)
        self.cards.append(self.main_card)
        self._update_add_buttons()
        self._update_close_buttons()

        self.add_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        self.add_shortcut.activated.connect(self.add_tile)

        # -- feed --
        self.feed = MarketFeed(self)
        self.feed.universe_ready.connect(self._on_universe)
        self.feed.mids_updated.connect(self._on_mids)
        self.feed.candles_updated.connect(self._on_candles)
        self.feed.older_candles.connect(self._on_older_candles)
        self.feed.history_failed.connect(self._on_history_failed)
        self.feed.latency.connect(self._on_latency)
        self.feed.connected.connect(self._on_connected)
        self.feed.error.connect(self._on_error)

        self._sync_watches()
        if autostart:
            self.feed.start()

        # -- polymarket feed (one five-minute BTC up/down market) --
        self.polymarket_feed = PolymarketFeed(self)
        self.polymarket_feed.market_ready.connect(self.polymarket.set_market)
        self.polymarket_feed.book_updated.connect(self.polymarket.apply_book)
        self.polymarket_feed.trade.connect(self.polymarket.apply_trade)
        self.polymarket_feed.status.connect(self.polymarket.set_status)
        self.polymarket_feed.history.connect(self.polymarket.set_history)
        self.polymarket_feed.latency.connect(self._on_pm_latency)
        self.polymarket_feed.error.connect(self._on_polymarket_error)
        if autostart:
            self.polymarket_feed.start()

    # -- cards -------------------------------------------------------------

    def _new_card(self, coin: str | None, *, closable: bool) -> MarketCard:
        card = MarketCard(coin, closable=closable, parent=self.stack)
        card.chart.set_show_volume(self.volume_toggle.isChecked())
        card.chart.set_show_bollinger(self.bollinger_toggle.isChecked())
        card.set_market_source(lambda: self._markets)
        card.market_changed.connect(
            lambda chosen, c=card: self._on_market_chosen(c, chosen)
        )
        card.interval_changed.connect(lambda _iv, c=card: self._on_interval_changed(c))
        card.history_requested.connect(self._on_card_history)
        card.add_requested.connect(self.add_tile)
        card.close_requested.connect(lambda c=card: self.remove_card(c))
        return card

    @property
    def tile_count(self) -> int:
        return max(0, len(self.cards) - 1)

    def add_tile(self) -> MarketCard | None:
        if self.tile_count >= MAX_TILES:
            return None
        card = self._new_card(None, closable=True)
        self.stack.addWidget(card)
        self.cards.append(card)
        self._update_add_buttons()
        self._update_close_buttons()
        self._rebalance()
        card.open_search()
        log.info("tile added (%d/%d)", self.tile_count, MAX_TILES)
        return card

    def remove_card(self, card: MarketCard) -> None:
        """Close any card, including the main one, as long as one survives."""
        if card not in self.cards or len(self.cards) == 1:
            return
        self.cards.remove(card)
        card.setParent(None)
        card.deleteLater()
        if card is self.main_card:
            # The topmost survivor takes over the main-card role.
            self.main_card = self.cards[0]
        self._update_add_buttons()
        self._update_close_buttons()
        self._rebalance()
        self._sync_watches()

    def _update_add_buttons(self) -> None:
        """The + button follows the newest card; hidden entirely at the cap."""
        at_cap = self.tile_count >= MAX_TILES
        for index, card in enumerate(self.cards):
            newest = index == len(self.cards) - 1
            card.add_button.setVisible(newest and not at_cap)
            remaining = MAX_TILES - self.tile_count
            card.add_button.setToolTip(
                f"Add a market tile — {remaining} left (⌘T)" if remaining else ""
            )

    def _apply_overlays(self, *_args) -> None:
        """Checkboxes are global: every card, current and future, follows them."""
        show_volume = self.volume_toggle.isChecked()
        show_bollinger = self.bollinger_toggle.isChecked()
        for card in self.cards:
            card.chart.set_show_volume(show_volume)
            card.chart.set_show_bollinger(show_bollinger)

    def _update_close_buttons(self) -> None:
        """Every card is closable while another one remains to inherit the view."""
        closable = len(self.cards) > 1
        for card in self.cards:
            card.close_button.setVisible(closable)

    def _rebalance(self) -> None:
        """Main card gets 1.5x a tile's height, so it stays the primary view."""
        total = self.stack.height()
        if total <= 0 or not self.cards:
            return
        if len(self.cards) == 1:
            self.stack.setSizes([total])
            return
        # Handles are between widgets, so they come out of the usable height;
        # otherwise the last card silently absorbs the remainder.
        handles = (len(self.cards) - 1) * self.stack.handleWidth()
        usable = max(1, total - handles)
        unit = usable / (1.5 + self.tile_count)
        main_height = max(1, int(unit * 1.5))
        each = max(1, int(unit))
        self.stack.setSizes([main_height] + [each] * self.tile_count)

    # -- card events -------------------------------------------------------

    def _on_market_chosen(self, card: MarketCard, coin: str) -> None:
        card.interval = card.timeframes.current()
        card.set_market(self._markets.get(coin))
        self._sync_watches()

    def _on_interval_changed(self, card: MarketCard) -> None:
        self._sync_watches()

    # -- feed --------------------------------------------------------------

    def _loaded_cards(self) -> list[MarketCard]:
        return [card for card in self.cards if card.market is not None]

    def _sync_watches(self) -> None:
        wanted = {(card.coin, card.interval) for card in self._loaded_cards() if card.coin}
        for coin, interval in wanted - self._watched:
            self.feed.watch_candles(coin, interval)
        for coin, interval in self._watched - wanted:
            self.feed.unwatch_candles(coin, interval)
        self._watched = wanted

    def _on_universe(self, markets: list[Market]) -> None:
        self._markets = {market.coin: market for market in markets}
        log.info("universe: %d markets", len(self._markets))
        if self.main_card.market is None:
            self.main_card.set_market(self._markets.get(DEFAULT_MARKET))
        self._sync_watches()

    def _on_mids(self, mids: dict[str, float]) -> None:
        for card in self.cards:
            price = mids.get(card.coin or "")
            if price is not None:
                card.apply_mid(price)
        btc = mids.get("BTC")
        if btc is not None:
            self.polymarket.set_btc(btc)

    def _on_candles(self, series: CandleSeries) -> None:
        for card in self.cards:
            card.apply_candles(series)

    def _on_card_history(self, coin: str, interval: str, before_ms: int) -> None:
        # The main card exists before the feed, so this indirection keeps the
        # wiring order irrelevant.
        feed = getattr(self, "feed", None)
        if feed is not None:
            feed.request_older(coin, interval, before_ms)

    def _on_older_candles(self, series: CandleSeries) -> None:
        for card in self.cards:
            card.apply_history(series)

    def _on_history_failed(self, coin: str, interval: str) -> None:
        for card in self.cards:
            card.apply_history_failure(coin, interval)

    def _on_latency(self, milliseconds: float) -> None:
        if milliseconds <= FAST_MS:
            color = "#3ddc84"
        elif milliseconds <= OK_MS:
            color = "#e0b341"
        else:
            color = "#ff5c5c"
        self.latency_label.setStyleSheet(
            f"#latencyLabel {{ color: {color}; font-size: 10px; }}"
        )
        self.latency_label.setText(f"HL ● {milliseconds:.0f} ms")

    def _on_pm_latency(self, milliseconds: float) -> None:
        if milliseconds <= FAST_MS:
            color = "#3ddc84"
        elif milliseconds <= OK_MS:
            color = "#e0b341"
        else:
            color = "#ff5c5c"
        self.pm_latency_label.setStyleSheet(
            f"color: {color}; font-size: 10px; background: transparent;"
        )
        self.pm_latency_label.setText(f"PM ● {milliseconds:.0f} ms")

    def _on_connected(self, is_connected: bool) -> None:
        if not is_connected:
            self.latency_label.setStyleSheet(
                "#latencyLabel { color: #6f6f76; font-size: 10px; }"
            )
            self.latency_label.setText("HL ● reconnecting…")

    @staticmethod
    def _on_error(message: str) -> None:
        log.warning("feed: %s", message)

    @staticmethod
    def _on_polymarket_error(message: str) -> None:
        log.warning("polymarket: %s", message)

    # -- window ------------------------------------------------------------

    def _focused_card(self) -> MarketCard:
        widget: QWidget | None = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, MarketCard):
                return widget
            widget = widget.parentWidget()
        return self.main_card

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Digits 1-6 switch the focused card's timeframe.

        The chart handles them itself while it has focus. Anything that
        reaches the window was already declined by the focus widget, so this
        never steals a digit from the search box.
        """
        if event.type() == QEvent.Type.KeyPress and not event.modifiers():
            key = event.key()
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_6:
                index = key - Qt.Key.Key_1
                if index < len(TIMEFRAMES):
                    self._focused_card().set_interval(TIMEFRAMES[index])
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._rebalance)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.feed.stop()
        self.polymarket_feed.stop()
        super().closeEvent(event)
