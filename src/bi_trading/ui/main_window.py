"""Application shell.

Canvas with a slim top bar (latency) over a horizontal splitter:

    Polymarket 5m BTC market  |  vertical splitter of market cards

Every split — horizontal and vertical — uses the same 8px transparent gap, so
all cards float on the canvas identically. The "+" button lives on the newest
card, and each card collapses its search row once a market is loaded.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
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

from bi_trading.ui.cards import MarketCard
from bi_trading.data.feed import MarketFeed
from bi_trading.data.market_data import (
    TIMEFRAMES,
    CandleSeries,
    Market,
    bollinger_bands,
)
from bi_trading.data.polymarket_data import PolymarketMarket, window_price_points
from bi_trading.data.polymarket_feed import PolymarketFeed
from bi_trading.ui.polymarket_panel import VIEW_MS, PolymarketPanel
from bi_trading.state.settings import load_choice, save_choice
from bi_trading.ui.strategy_bar import StrategyBar
from bi_trading.ui.theme import CANVAS, CARD_GAP
from bi_trading.venues.runner import AsyncRunner

log = logging.getLogger(__name__)

# Latency colour thresholds, milliseconds.
FAST_MS = 120.0
OK_MS = 300.0


# How far above the ask a bet may pay: room for the book to move while the
# order is on its way. A bet fills at the best offers, never above this.
BET_ROOM = 0.03
MIN_STAKE = 1.0
SETTLE_EVERY_MS = 15_000   # how often finished real bets ask Polymarket for their result


def _bet_cap(ask: float, tick: float = 0.01) -> float:
    """The highest price a bet will pay: the ask plus `BET_ROOM`, on the tick
    grid and under a dollar."""
    tick = tick if tick and tick > 0 else 0.01
    cap = min(0.99, ask + BET_ROOM)
    return round(round(cap / tick) * tick, 4)


def _winner_of(future) -> str:
    """A settlement lookup's answer, or "" if it failed or is not out yet."""
    try:
        return future.result() or ""
    except Exception:  # a network blip: the next tick asks again
        return ""


def _sell_floor(bid: float, tick: float = 0.01) -> float:
    """The lowest price a sell accepts: the bid less `BET_ROOM`, on the tick grid,
    and never under one tick."""
    tick = tick if tick and tick > 0 else 0.01
    floor = max(tick, bid - BET_ROOM)
    return round(round(floor / tick) * tick, 4)


def _stake(text: str) -> float:
    """Dollars from the stake field: `$20`, `20`, `1,000` all read."""
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return max(0.0, float(cleaned))
    except ValueError:
        return 0.0


class MainWindow(QMainWindow):
    _settled = Signal(str, str)   # a window and the side Polymarket settled it on

    def __init__(
        self,
        autostart: bool = True,
        feed: MarketFeed | None = None,
        polymarket_feed: PolymarketFeed | None = None,
        show_top_bar: bool = True,
        venue: str = "both",
    ) -> None:
        super().__init__()
        # `pm` and `hl` show one venue as a screen of its own; `both` the two
        # side by side, as the terminal always was.
        self.venue = venue if venue in ("pm", "hl", "both") else "both"
        # A shell (the hub) can hand us feeds it already runs, so both read the
        # same sockets; then we do not start or stop them ourselves.
        self._owns_feed = feed is None
        self._owns_polymarket = polymarket_feed is None
        self.setWindowTitle("bi-trading")
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
        self.quit_button.setToolTip("Quit bi-trading")
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

        # Each venue is a column: its card, and the bar that trades it under it.
        self._pm_column = QWidget(self.splitter)
        pm_layout = self._pm_layout = QVBoxLayout(self._pm_column)
        pm_layout.setContentsMargins(0, 0, 0, 0)
        pm_layout.setSpacing(CARD_GAP)
        pm_layout.addWidget(self.polymarket, 1)
        self._hl_column = QWidget(self.splitter)
        hl_layout = self._hl_layout = QVBoxLayout(self._hl_column)
        hl_layout.setContentsMargins(0, 0, 0, 0)
        hl_layout.setSpacing(CARD_GAP)
        hl_layout.addWidget(self.stack, 1)
        self.splitter.addWidget(self._pm_column)
        self.splitter.addWidget(self._hl_column)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([560, 560])
        from bi_trading.ui.layout_memory import remember_splitter

        remember_splitter(self.splitter, "terminal.columns")

        layout.addWidget(self.splitter, 1)

        # The bar under it: the armed strategy, its reading, and the two bets.
        self.strategy_bar = StrategyBar(canvas)
        # Bars of history before the signal counts, the same setting the
        # backtest uses (0 is off). Read once: this runs on every tick.
        self._warmup = _read_warmup()
        self._signal_on = False  # the strategy's signal last tick, to log a change
        self.strategy_bar.bet.connect(self._place_bet)
        self.strategy_bar.sell.connect(self._sell)
        self._bet_wired = False
        # Auto-bet starts from the setting (off by default) and bets on its own
        # only while the box is ticked; see state/autobet.py for the rules.
        from bi_trading.state.autobet import AutoBet
        from bi_trading.state.events import event_log

        self._autobet = AutoBet(event_log())
        self._official: dict[str, str] = {}     # window -> the side Polymarket settled on
        self._asked: set[str] = set()           # windows being asked about right now
        # A manual bet's token -> (window, side, window end), noted when it is
        # sent so its fill can be tracked to the window's resolution.
        self._manual_orders: dict[str, tuple[str, str, int]] = {}
        self._settler: AsyncRunner | None = None
        self._settle_timer = QTimer(self)
        self._settle_timer.setInterval(SETTLE_EVERY_MS)
        self._settle_timer.timeout.connect(self._settle_real)
        self._settle_timer.start()
        self._settled.connect(self._on_settled)
        self._ml_side: str | None = None
        self._ml_cache: tuple | None = None
        self._ml_status = ""
        self._ml_item: Any = None   # the picked ML strategy, read when it is picked
        self.strategy_bar.picker.currentTextChanged.connect(self._on_strategy_picked)
        self._refresh_ml_choices()
        self.strategy_bar.auto.setChecked(_read_auto_bet())
        self.strategy_bar.auto.toggled.connect(self._on_auto_toggled)
        # The bets go under the Polymarket card; the strategy keeps its own row.
        pm_layout.addWidget(self.strategy_bar.bet_bar)
        layout.addWidget(self.strategy_bar)
        self.setCentralWidget(canvas)
        self.installEventFilter(self)

        self.cards: list[MarketCard] = []
        # Only BTC: one card, fixed, with no search and no tiles to add.
        self.main_card = self._new_card("BTC", closable=False)
        self.stack.addWidget(self.main_card)
        self.cards.append(self.main_card)
        # ...and the order bar under the Hyperliquid card.
        hl_layout.addWidget(self.main_card.trade_form.bar)
        # The timeframe it was left on, and kept from now on.
        self.main_card.restore_interval(load_choice("terminal.timeframe"))

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
        self._arrange()

    # -- one venue at a time -------------------------------------------------

    def _arrange(self) -> None:
        """Lay the screen out for its venue. Both venues' widgets always exist (the
        feeds and the strategy read them); a single-venue screen just shows the
        ones it needs."""
        if self.venue == "pm":
            self._arrange_pm()
        elif self.venue == "hl":
            self._arrange_hl()
        self.strategy_bar.set_venue(self.venue)

    def _arrange_pm(self) -> None:
        from bi_trading.ui.pm_detail import PmDetail

        self._pm_layout.removeWidget(self.strategy_bar.bet_bar)
        self._hl_column.hide()    # alive, and still feeds the strategy's reading
        market = lambda: self.polymarket.market  # noqa: E731
        self.pm_detail = PmDetail(
            self.polymarket,
            ask=lambda: (
                self._bet_price(market().outcomes[0])
                if market() is not None and len(market().outcomes) == 2 else None
            ),
            bets=self._paper_rows,
        )
        self.splitter.addWidget(self.pm_detail)
        self.splitter.setSizes([560, 0, 600])   # the hidden column keeps its slot

    def _arrange_hl(self) -> None:
        from bi_trading.ui.hl_panels import OrderBookCard, PositionsCard, TradeCard

        form = self.main_card.trade_form
        self._hl_layout.removeWidget(form.bar)
        self._pm_column.hide()
        self.book_card = OrderBookCard()
        right = QWidget(self.splitter)
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CARD_GAP)
        column.addWidget(self.book_card, 1)
        column.addWidget(PositionsCard(form))
        column.addWidget(TradeCard(form, "BTC"))
        self.splitter.addWidget(right)
        self.splitter.setSizes([0, 800, 380])   # the hidden column keeps its slot
        self.feed.track("BTC")
        self.feed.book_updated.connect(self._on_book)
        self.feed.latency.connect(self.book_card.set_latency)

    def _on_book(self, book) -> None:
        if book.coin == "BTC" and hasattr(self, "book_card"):
            self.book_card.set_book(book, 1)

    def _paper_rows(self) -> list[tuple[str, str, str, str, str]]:
        """The open bets as (side, stake, entry, now / result, tone) table rows."""
        rows = []
        market = self.polymarket.market
        for bet in self._autobet.open:
            now = None
            if market is not None and len(market.outcomes) == 2:
                outcome = market.outcomes[0 if bet.side == "up" else 1]
                book = self.polymarket.books.get(outcome.token_id)
                bid = (
                    book.best_bid if book is not None and book.best_bid is not None
                    else outcome.best_bid
                )
                now = float(bid) if bid is not None else (
                    float(outcome.mid) if outcome.mid is not None else None
                )
            text, tone = "—", ""
            if now is not None and bet.price > 0:
                pnl = bet.shares * now - bet.stake
                text = f"{now * 100:.1f}¢ {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f}"
                tone = "up" if pnl >= 0 else "down"
            rows.append(
                (bet.side.upper(), f"${bet.stake:,.0f}", f"{bet.price * 100:.1f}¢", text, tone)
            )
        return rows

    # -- cards -------------------------------------------------------------

    def _new_card(self, coin: str | None, *, closable: bool) -> MarketCard:
        card = MarketCard(coin, closable=closable, parent=self.stack)
        card.set_market_source(lambda: self._markets)
        card.interval_changed.connect(lambda _iv, c=card: self._on_interval_changed(c))
        card.history_requested.connect(self._on_card_history)
        return card

    # -- card events -------------------------------------------------------

    def _on_interval_changed(self, card: MarketCard) -> None:
        if card is self.main_card:
            save_choice("terminal.timeframe", card.interval)
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
        # A new window: settle the bets of the one that just ended, from BTC
        # against that window's opening target (read before the panel rolls).
        self._resolve_bets(market.slug)
        self.polymarket.set_market(market)
        if self._bet_wired:
            self._show_held()
        # The window's bars give the chart its target (the open) and fill the
        # left of the line before live sampling begins.
        self.feed.request_window("BTC", market.start_ms, VIEW_MS)

    def _resolve_bets(self, current_slug: str) -> None:
        self._autobet.resolve(
            current_slug, self.polymarket.btc_price, self.polymarket.target,
            self._official, int(time.time() * 1000),
        )

    def _settle_real(self) -> None:
        """Ask Polymarket how its finished windows settled, for the real bets
        still waiting on it. Public data, so it needs no key and no arming."""
        market = self.polymarket.market
        slug = market.slug if market is not None else ""
        pending = [w for w in self._autobet.awaiting(slug) if w not in self._asked]
        if not pending:
            if self._autobet.open:
                self._resolve_bets(slug)    # the grace period may have run out
            return
        if self._settler is None:
            self._settler = AsyncRunner("settle").start()
        from bi_trading.data.polymarket_feed import fetch_winner

        for window in pending:
            self._asked.add(window)
            future = self._settler.submit(fetch_winner(window))
            def deliver(done, window: str = window) -> None:
                self._settled.emit(window, _winner_of(done))

            future.add_done_callback(deliver)

    def _on_settled(self, window: str, side: str) -> None:
        self._asked.discard(window)
        if side:
            self._official[window] = side
            market = self.polymarket.market
            self._resolve_bets(market.slug if market is not None else "")

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
        if bar.ml_name():
            self._refresh_ml(bar)
            return
        candles = getattr(self.main_card.chart, "_candles", ())
        close = candles[-1].c if candles else None
        band = None
        if len(candles) >= 20:
            bands = bollinger_bands(candles[-20:])
            last = bands[-1] if bands else None
            band = last[2] if last else None
        warming = len(candles) < self._warmup
        holds = bar.set_reading(close, band, warming=warming)
        if holds and not self._signal_on and close is not None and band is not None:
            from bi_trading.state.events import event_log

            event_log().record(
                "info", "strategy", "SIGNAL",
                f"Bollinger reversion · close {close:,.1f} < band {band:,.1f}",
                "auto", strategy="Bollinger reversion",
                why=["close < band", f"close {close:,.1f} · band {band:,.1f}", "→ TRUE"],
            )
        rose = holds and not self._signal_on
        self._signal_on = holds
        if rose and bar.auto_bet():
            self._auto_bet()
        bar.set_bets(
            self.polymarket.up_tile.price, self.polymarket.down_tile.price
        )

    # -- an ML strategy on the live chart ------------------------------------

    def _refresh_ml_choices(self) -> None:
        from bi_trading.state import strategies

        saved = [s for s in strategies.load() if s.model]
        self.strategy_bar.set_ml_choices([s.name for s in saved])
        name = self.strategy_bar.ml_name()
        self._ml_item = next((s for s in saved if s.name == name), None)

    def _on_strategy_picked(self, text: str) -> None:
        """A strategy was picked: an ML one moves the chart to its timeframe."""
        self._ml_side = None
        self._ml_cache = None
        self._ml_status = ""
        self._refresh_ml_choices()      # the file is read here, not on every tick
        name = self.strategy_bar.ml_name()
        if not name:
            return
        from bi_trading.ml import store
        from bi_trading.ml.live import horizon_note
        from bi_trading.ml.train import MLError

        item = self._ml_item
        try:
            trained = store.load_model(item.model) if item else None
        except MLError as exc:
            self.strategy_bar.set_status(str(exc), "error")
            return
        if trained is None:
            return
        if self.main_card.interval != trained.config.timeframe:
            self.main_card.set_interval(trained.config.timeframe)
        note = horizon_note(trained)
        self.strategy_bar.set_status(note or f"{name}: reading {trained.config.timeframe} bars")

    def _refresh_ml(self, bar: StrategyBar) -> None:
        """The saved model's call on the newest closed bar, and a bet if it fires."""
        from bi_trading.ml import live, store
        from bi_trading.ml.train import MLError
        from bi_trading.state.events import event_log

        name = bar.ml_name()
        candles = getattr(self.main_card.chart, "_candles", ())
        close = candles[-1].c if candles else None
        item = self._ml_item
        if item is None:
            bar.set_ml_reading(close, None, None, "gone")
            self._say_ml(f"{name} is not saved any more")
            return
        try:
            trained = store.load_model(item.model)
        except MLError as exc:
            bar.set_ml_reading(close, None, None, "error")
            self._say_ml(str(exc), error=True)
            return
        config = trained.config
        if self.main_card.interval != config.timeframe:
            bar.set_ml_reading(close, None, None, f"needs {config.timeframe}")
            self._say_ml(f"{name} reads {config.timeframe} bars, the chart is on {self.main_card.interval}", error=True)
            return
        # The model's answer only changes when a bar closes: score once per bar.
        key = (item.model, trained.trained_at, candles[-1].t if candles else 0, len(candles))
        new_bar = self._ml_cache is None or self._ml_cache[0] != key
        if new_bar:
            try:
                call = live.live_call(trained, candles, int(time.time() * 1000))
            except MLError as exc:
                bar.set_ml_reading(close, None, None, "error")
                self._say_ml(str(exc), error=True)
                return
            self._ml_cache = (key, call)
        assert self._ml_cache is not None
        call = self._ml_cache[1]

        market = self.polymarket.market
        asks: list[float | None] = [None, None]
        if market is not None and len(market.outcomes) >= 2 and market.is_open():
            asks = [self._bet_price(market.outcomes[0]), self._bet_price(market.outcomes[1])]
        decision = live.decide(call.p, config.up, config.down, config.min_edge, asks[0], asks[1])
        side = decision.side
        # A call is a call on this window only if its horizon is the window.
        if side is not None and market is not None:
            reason = live.window_reason(trained, call.stamp, market.start_ms)
            if reason:
                side, decision = None, live.Decision(reason=reason)
        if side == "up" and item.side == "short" or side == "down" and item.side == "long":
            side, decision = None, live.Decision(reason=f"{item.side} strategy: no {side} bets")
        bar.set_ml_reading(close, call.p, side, call.reason)
        if call.p is None:
            self._say_ml(call.reason)
        elif side is None:
            self._say_ml(decision.reason)
        # A call fires when the side turns on, and again for every new bar that
        # still calls it: the model answers once per bar, and the bet is at most one
        # per window anyway.
        rose = side is not None and (side != self._ml_side or new_bar)
        self._ml_side = side
        if rose and side is not None:
            edge = f" · edge {decision.edge:+.2f}" if decision.edge is not None else ""
            event_log().record(
                "info", "strategy", "SIGNAL",
                f"{name} · P(up) {call.p:.2f} → {side.upper()}{edge}",
                "auto", strategy=name,
                why=[f"P(up) {call.p:.2f}", f"thresholds {config.down:.2f} / {config.up:.2f}", f"→ {side.upper()}"],
            )
            if bar.auto_bet():
                self._auto_bet(side)
        bar.set_bets(self.polymarket.up_tile.price, self.polymarket.down_tile.price)

    def _say_ml(self, text: str, error: bool = False) -> None:
        """Show a reason on the bar once, not on every tick."""
        if text != self._ml_status:
            self._ml_status = text
            self.strategy_bar.set_status(text, "error" if error else "info")

    # -- betting -----------------------------------------------------------

    def _bet_price(self, outcome) -> float | None:
        """The ask you would pay, from the best source there is.

        The live book first. Without one (the stream is reconnecting, or the
        window just opened) Gamma's quote for the outcome; Gamma only quotes a
        bid and ask for the first token, so the other side's ask is what the
        first one's bid leaves of a dollar; and last, the outcome's own price.
        """
        book = self.polymarket.books.get(outcome.token_id)
        if book is not None and book.best_ask is not None:
            return float(book.best_ask)
        if outcome.best_ask is not None:
            return float(outcome.best_ask)
        market = self.polymarket.market
        if market is not None and len(market.outcomes) == 2:
            first, second = market.outcomes
            other = first if outcome is second or outcome == second else second
            other_book = self.polymarket.books.get(other.token_id)
            other_bid = (
                other_book.best_bid if other_book is not None and other_book.best_bid is not None
                else other.best_bid
            )
            if other_bid is not None and 0 < other_bid < 1:
                return round(1.0 - float(other_bid), 4)
        if outcome.mid is not None:
            return float(outcome.mid)
        if outcome.price and outcome.price > 0:
            return float(outcome.price)
        return None

    def _place_bet(self, side: str) -> None:
        """A Polymarket bet: real when armed and connected, dry run otherwise."""
        from bi_trading.state.orders import armed, config_for, service
        from bi_trading.state.settings import Settings

        bar = self.strategy_bar
        market = self.polymarket.market
        if market is None or len(market.outcomes) < 2:
            bar.set_status("no market yet")
            return
        if not market.is_open():
            bar.set_status("this five-minute window has ended — wait for the next")
            return
        if not market.accepting_orders:
            bar.set_status("this market is not taking orders right now")
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
            bar.size_field.setText(f"${stake:,.0f}")
        if stake < MIN_STAKE:
            bar.set_status(f"the smallest bet is ${MIN_STAKE:g}")
            return

        if config_for("polymarket") is None:
            bar.set_status("not connected — connect in Settings")
            return
        if not armed():
            bar.set_status("dry run — arm live orders in Settings")
            return
        tick = market.tick_size or 0.01
        cap = _bet_cap(price, tick)
        if trading.confirm_orders:
            answer = QMessageBox.question(
                self,
                "Place a real bet",
                f"Bet ${stake:,.2f} on {outcome.name}?\n\nIt buys at the best "
                f"prices on offer (now {price * 100:.0f}¢), up to "
                f"{cap * 100:.0f}¢ a share.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        from bi_trading.venues.base import Instrument, OrderRequest

        order = OrderRequest(
            instrument=Instrument(
                venue="polymarket", symbol=outcome.token_id, tick=tick, size_step=0.01
            ),
            side="buy",
            price=cap,
            size=0.0,
            notional=stake,
        )
        bar.set_status("sending…")
        svc = service()
        self._hook_service(svc)
        self._manual_orders[outcome.token_id] = (market.slug, side, market.end_ms)
        while len(self._manual_orders) > 20:
            self._manual_orders.pop(next(iter(self._manual_orders)))
        svc.submit("polymarket", order, config_for("polymarket") or {})  # a manual bet

    def _hook_service(self, svc) -> None:
        """Listen to the order service once."""
        if self._bet_wired:
            return
        svc.placed.connect(self._on_bet_placed)
        svc.failed.connect(self._on_bet_failed)
        svc.filled.connect(self._on_filled)
        svc.holdings_changed.connect(self._show_held)
        self._bet_wired = True

    def _on_filled(self, venue: str, token: str, side: str, shares: float, dollars: float) -> None:
        if venue != "polymarket":
            return
        if side == "sell":
            self._autobet.sold(token, shares, dollars)
        elif not self._autobet.fill(token, shares, dollars):
            # Not an auto-bet's fill: a bet the user placed. Keep it, at the
            # venue's own stake and price, so its window closes it with the pnl.
            from bi_trading.state.autobet import Bet

            meta = self._manual_orders.get(token)
            if meta is not None and shares > 0 and dollars > 0:
                slug, bet_side, end_ms = meta
                self._autobet.track_manual(Bet(
                    slug, bet_side, dollars / shares, dollars, "manual",
                    paper=False, end_ms=end_ms, token=token, filled=True,
                    origin="manual",
                ))

    def _show_held(self) -> None:
        from bi_trading.state.orders import service

        market = self.polymarket.market
        if market is None or len(market.outcomes) < 2 or not market.is_open():
            self.strategy_bar.set_held(0.0, 0.0)
            return
        svc = service()
        self.strategy_bar.set_held(
            svc.held(market.outcomes[0].token_id),
            svc.held(market.outcomes[1].token_id),
        )

    def _sell(self, side: str) -> None:
        """Sell everything held of a side, at once, at the best bids.

        No confirm dialog: a sell only ever closes what a bet opened, and the
        point of it is speed. The floor is a few cents under the bid, so a book
        that moves a little still fills it.
        """
        from bi_trading.state.orders import config_for, service
        from bi_trading.venues.base import Instrument, OrderRequest

        bar = self.strategy_bar
        market = self.polymarket.market
        if market is None or len(market.outcomes) < 2 or not market.is_open():
            bar.set_status("nothing to sell in this window")
            return
        outcome = market.outcomes[0 if side == "up" else 1]
        svc = service()
        shares = svc.held(outcome.token_id)
        config = config_for("polymarket")
        if shares <= 0 or config is None:
            bar.set_status(f"no {side.upper()} shares held")
            return
        book = self.polymarket.books.get(outcome.token_id)
        bid = book.best_bid if book is not None and book.best_bid is not None else outcome.best_bid
        tick = market.tick_size or 0.01
        floor = _sell_floor(float(bid) if bid else 0.0, tick)
        order = OrderRequest(
            instrument=Instrument(
                venue="polymarket", symbol=outcome.token_id, tick=tick, size_step=0.01
            ),
            side="sell", price=floor, size=round(shares, 2), market=True,
        )
        bar.set_status("selling…")
        self._hook_service(svc)
        svc.submit("polymarket", order, config)

    def _on_auto_toggled(self, on: bool) -> None:
        from bi_trading.state.events import event_log

        name = self.strategy_bar.strategy()
        event_log().record(
            "info", "strategy", "ARMED" if on else "DISARMED",
            f"{name} armed · auto-bet on" if on else f"{name} auto-bet off",
            "manual", name,
        )

    def _auto_bet(self, side: str = "up") -> None:
        """The signal fired with Auto-bet on: bet `side`, within the rules.

        Real only when live orders are armed and Polymarket is connected, with no
        confirm dialog (it cannot wait for one); otherwise a paper bet.
        """
        import datetime

        from bi_trading.state.autobet import Bet, plan
        from bi_trading.state.events import event_log
        from bi_trading.state.orders import armed, config_for, service
        from bi_trading.state.settings import Settings

        bar = self.strategy_bar
        market = self.polymarket.market
        if market is None or len(market.outcomes) < 2:
            return
        if not market.is_open() or not market.accepting_orders:
            return
        outcome = market.outcomes[0 if side == "up" else 1]  # Bollinger calls UP only
        trading = Settings.load().trading
        today = event_log().counts()["pnl"]
        chosen = plan(
            stake=_stake(bar.bet_size()), max_stake=trading.max_stake,
            daily_loss_limit=trading.daily_loss_limit, today_pnl=today,
            window=market.slug, last_window=self._autobet.last_window,
            price=self._bet_price(outcome),
        )
        name = bar.strategy()
        self._autobet.check_limit(
            today, trading.daily_loss_limit, datetime.date.today().isoformat()
        )
        if not chosen.go:
            bar.set_status(f"auto-bet skipped — {chosen.reason}")
            return
        price = self._bet_price(outcome) or 0.0
        bet = Bet(market.slug, side, price, chosen.stake, name,
                  paper=True, end_ms=market.end_ms, token=outcome.token_id)
        if not (armed() and config_for("polymarket") is not None):
            self._autobet.place_paper(bet)
            bar.set_status(f"auto-bet (paper): ${chosen.stake:,.2f} on {side.upper()}", "ok")
            return

        from bi_trading.venues.base import Instrument, OrderRequest

        tick = market.tick_size or 0.01
        order = OrderRequest(
            instrument=Instrument(
                venue="polymarket", symbol=outcome.token_id, tick=tick, size_step=0.01
            ),
            side="buy", price=_bet_cap(price, tick), size=0.0, notional=chosen.stake,
        )
        bet.paper = False
        self._autobet.track_real(bet)
        bar.set_status("auto-bet sending…")
        svc = service()
        self._hook_service(svc)
        svc.submit("polymarket", order, config_for("polymarket") or {},
                   origin="auto", strategy=name)

    def _on_bet_placed(self, venue: str, summary: str) -> None:
        if venue == "polymarket":
            self.strategy_bar.set_status(summary, "ok")

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
        self._refresh_ml_choices()
        # Sign in to Polymarket now, when live orders are on, so the first bet
        # does not pay for it. A no-op for a dry run.
        from bi_trading.state.orders import armed

        if armed():
            from bi_trading.state.orders import service

            service().warm("polymarket")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._settle_timer.stop()
        if self._settler is not None:
            self._settler.stop()
        if self._owns_feed:
            self.feed.stop()
        if self._owns_polymarket:
            self.polymarket_feed.stop()
        super().closeEvent(event)


def _read_warmup() -> int:
    from bi_trading.state.settings import Settings

    try:
        return max(0, int(Settings.load().backtest.warmup))
    except (OSError, ValueError, TypeError):  # a missing or unreadable file
        log.debug("could not read the warm-up setting", exc_info=True)
        return 0


def _read_auto_bet() -> bool:
    from bi_trading.state.settings import Settings

    try:
        return bool(Settings.load().trading.auto_bet)
    except (OSError, ValueError, TypeError):
        return False
