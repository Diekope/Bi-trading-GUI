"""Application shell.

Canvas with a slim top bar (latency) over a horizontal splitter:

    Polymarket 5m BTC market  |  vertical splitter of market cards

Every split — horizontal and vertical — uses the same 8px transparent gap, so
all cards float on the canvas identically. The "+" button lives on the newest
card, and each card collapses its search row once a market is loaded.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import MarketCard
from lalala.feed import MarketFeed
from lalala.market_data import (
    TIMEFRAMES,
    CandleSeries,
    Market,
    bollinger_bands,
)
from lalala.polymarket_data import PolymarketMarket, window_price_points
from lalala.polymarket_feed import PolymarketFeed
from lalala.polymarket_panel import VIEW_MS, PolymarketPanel
from lalala.strategy_bar import StrategyBar
from lalala.theme import CANVAS, CARD_GAP

log = logging.getLogger(__name__)

# Latency colour thresholds, milliseconds.
FAST_MS = 120.0
OK_MS = 300.0


def _stake(text: str) -> float:
    """Dollars from the stake field: `$20`, `20`, `1,000` all read."""
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return max(0.0, float(cleaned))
    except ValueError:
        return 0.0


class MainWindow(QMainWindow):
    def __init__(
        self,
        autostart: bool = True,
        feed: MarketFeed | None = None,
        polymarket_feed: PolymarketFeed | None = None,
        show_top_bar: bool = True,
    ) -> None:
        super().__init__()
        # A shell (the hub) can hand us feeds it already runs, so both read the
        # same sockets; then we do not start or stop them ourselves.
        self._owns_feed = feed is None
        self._owns_polymarket = polymarket_feed is None
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
        self.top_bar = top_bar
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(2, 0, 2, 0)
        top_layout.setSpacing(10)
        self.status_label = QLabel("Live · BTC 5m · Polymarket + Hyperliquid")
        self.status_label.setObjectName("gl")
        top_layout.addWidget(self.status_label)
        top_layout.addStretch(1)

        self.latency_label = QLabel("HL ● connecting…")
        self.latency_label.setObjectName("latencyLabel")
        self.latency_label.setToolTip(
            "WebSocket round-trip to api.hyperliquid.xyz"
        )
        self.pm_latency_label = QLabel("PM ● —")
        self.pm_latency_label.setObjectName("latencyLabel")
        self.pm_latency_label.setToolTip("Round-trip to the Polymarket feed")
        top_layout.addWidget(self.pm_latency_label)
        top_layout.addWidget(self.latency_label)

        # The hub carries a rail exit; the standalone terminal gets the same
        # affordance in its top bar, in the same light red.
        self.quit_button = QPushButton("Quit")
        self.quit_button.setObjectName("topBarQuit")
        self.quit_button.setToolTip("Quit lalala")
        self.quit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quit_button.clicked.connect(self.close)
        top_layout.addWidget(self.quit_button)
        # Embedded in the hub, the rail already shows the title and the venue
        # latencies, so the strip is hidden there.
        top_bar.setVisible(show_top_bar)
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

        # The bar under it: the armed strategy, its reading, and the two bets.
        self.strategy_bar = StrategyBar(canvas)
        self.strategy_bar.bet.connect(self._place_bet)
        self._bet_wired = False
        layout.addWidget(self.strategy_bar)
        self.setCentralWidget(canvas)
        self.installEventFilter(self)

        self.cards: list[MarketCard] = []
        # Only BTC: one card, fixed, with no search and no tiles to add.
        self.main_card = self._new_card("BTC", closable=False)
        self.stack.addWidget(self.main_card)
        self.cards.append(self.main_card)

        # -- feed --
        self.feed = feed if feed is not None else MarketFeed(self)
        self.feed.universe_ready.connect(self._on_universe)
        self.feed.mids_updated.connect(self._on_mids)
        self.feed.bbo_updated.connect(self._on_bbo)
        # The Polymarket panel tracks BTC continuously, so its BBO subscription
        # does not depend on which cards are open.
        self.feed.watch_bbo("BTC")
        self.feed.candles_updated.connect(self._on_candles)
        self.feed.older_candles.connect(self._on_older_candles)
        self.feed.history_failed.connect(self._on_history_failed)
        self.feed.window_candles.connect(self._on_window_candles)
        self.feed.latency.connect(self._on_latency)
        self.feed.connected.connect(self._on_connected)
        self.feed.error.connect(self._on_error)

        self._sync_watches()
        if autostart and self._owns_feed:
            self.feed.start()
        # A shared feed may have loaded its universe before this window existed.
        if not self._owns_feed:
            snapshot = self.feed.markets()
            if snapshot:
                self._on_universe(snapshot)

        # -- polymarket feed (one five-minute BTC up/down market) --
        self.polymarket_feed = (
            polymarket_feed if polymarket_feed is not None else PolymarketFeed(self)
        )
        self.polymarket_feed.market_ready.connect(self._on_polymarket_market)
        self.polymarket_feed.book_updated.connect(self.polymarket.apply_book)
        self.polymarket_feed.trade.connect(self.polymarket.apply_trade)
        self.polymarket_feed.status.connect(self.polymarket.set_status)
        self.polymarket_feed.latency.connect(self._on_pm_latency)
        self.polymarket_feed.error.connect(self._on_polymarket_error)
        if autostart and self._owns_polymarket:
            self.polymarket_feed.start()
        # Likewise, adopt the window already on show in a shared feed.
        if not self._owns_polymarket:
            shared = self.polymarket_feed.market()
            if shared is not None:
                self._on_polymarket_market(shared)
                # The feed's own "live" status was emitted before we listened.
                self.polymarket.set_status("live")

    # -- cards -------------------------------------------------------------

    def _new_card(self, coin: str | None, *, closable: bool) -> MarketCard:
        card = MarketCard(coin, closable=closable, parent=self.stack)
        card.set_market_source(lambda: self._markets)
        card.interval_changed.connect(lambda _iv, c=card: self._on_interval_changed(c))
        card.history_requested.connect(self._on_card_history)
        return card

    # -- card events -------------------------------------------------------

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
            self.main_card.set_market(self._markets.get("BTC"))
        self._sync_watches()

    def _on_mids(self, mids: dict[str, float]) -> None:
        for card in self.cards:
            price = mids.get(card.coin or "")
            if price is not None:
                card.apply_mid(price)
        btc = mids.get("BTC")
        if btc is not None:
            self.polymarket.set_btc(btc)

    def _on_bbo(self, coin: str, mid: float) -> None:
        if coin == "BTC":
            self.polymarket.set_btc(mid)

    def _on_polymarket_market(self, market: PolymarketMarket) -> None:
        self.polymarket.set_market(market)
        # The window's bars give the chart its target (the open) and fill the
        # left of the line before live sampling begins.
        self.feed.request_window("BTC", market.start_ms, VIEW_MS)

    def _on_window_candles(self, series: CandleSeries) -> None:
        market = self.polymarket.market
        if market is None:
            return
        target, points = window_price_points(
            series.candles, market.start_ms, VIEW_MS
        )
        if target is not None:
            self.polymarket.set_window_prices(target, points)

    def _on_candles(self, series: CandleSeries) -> None:
        for card in self.cards:
            card.apply_candles(series)
        self._refresh_strategy_bar()

    def _refresh_strategy_bar(self) -> None:
        """The strategy's reading on the newest bar, and the two sides' prices."""
        bar = getattr(self, "strategy_bar", None)
        if bar is None:
            return
        candles = getattr(self.main_card.chart, "_candles", ())
        close = candles[-1].c if candles else None
        band = None
        if len(candles) >= 20:
            bands = bollinger_bands(candles[-20:])
            last = bands[-1] if bands else None
            band = last[2] if last else None
        bar.set_reading(close, band)
        bar.set_bets(
            self.polymarket.up_tile.price, self.polymarket.down_tile.price
        )

    # -- betting -----------------------------------------------------------

    def _bet_price(self, outcome) -> float | None:
        """The ask you would pay: the live book first, Gamma's quote after."""
        book = self.polymarket.books.get(outcome.token_id)
        if book is not None and book.best_ask is not None:
            return float(book.best_ask)
        if outcome.best_ask is not None:
            return float(outcome.best_ask)
        if outcome.mid is not None:
            return float(outcome.mid)
        return None

    def _place_bet(self, side: str) -> None:
        """A Polymarket bet: real when armed and connected, dry run otherwise."""
        from lalala.orders import armed, config_for, service
        from lalala.settings import Settings

        bar = self.strategy_bar
        market = self.polymarket.market
        if market is None or len(market.outcomes) < 2:
            bar.set_status("no market yet")
            return
        outcome = market.outcomes[0 if side == "up" else 1]
        price = self._bet_price(outcome)
        if not price or price <= 0:
            bar.set_status("no price yet")
            return

        trading = Settings.load().trading
        stake = _stake(bar.bet_size())
        if stake <= 0:
            bar.set_status("enter a stake")
            return
        if trading.max_stake > 0 and stake > trading.max_stake:
            stake = trading.max_stake
            bar.size.setText(f"${stake:,.0f}")

        if config_for("polymarket") is None:
            bar.set_status("not connected — connect in Settings")
            return
        if not armed():
            bar.set_status("dry run — arm live orders in Settings")
            return
        if trading.confirm_orders:
            answer = QMessageBox.question(
                self,
                "Place a real bet",
                f"Buy {stake / price:g} {outcome.name} shares for ${stake:,.0f} "
                f"at {price * 100:.0f}¢?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        from lalala.venues.base import Instrument, OrderRequest

        order = OrderRequest(
            instrument=Instrument(
                venue="polymarket", symbol=outcome.token_id, tick=0.01, size_step=0.01
            ),
            side="buy",
            price=round(price, 2),
            size=round(stake / price, 2),
        )
        bar.set_status("sending…")
        svc = service()
        if not self._bet_wired:
            svc.placed.connect(self._on_bet_placed)
            svc.failed.connect(self._on_bet_failed)
            self._bet_wired = True
        svc.submit("polymarket", order, config_for("polymarket"))

    def _on_bet_placed(self, venue: str, summary: str) -> None:
        if venue == "polymarket":
            self.strategy_bar.set_status(f"filled · {summary}", "ok")

    def _on_bet_failed(self, venue: str, reason: str) -> None:
        if venue == "polymarket":
            self.strategy_bar.set_status(reason, "error")

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
        self.polymarket.set_latency(milliseconds, color)
        label = getattr(self, "pm_latency_label", None)
        if label is not None:
            label.setText(f"PM ● {milliseconds:.0f} ms")
            label.setStyleSheet(
                f"#latencyLabel {{ color: {color}; font-size: 10px; }}"
            )

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

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._owns_feed:
            self.feed.stop()
        if self._owns_polymarket:
            self.polymarket_feed.stop()
        super().closeEvent(event)
