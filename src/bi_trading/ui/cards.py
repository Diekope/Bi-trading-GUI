"""Trading widgets: candlestick chart, timeframe pills, market card.

The chart is hand-painted and supports panning and zooming: wheel to zoom,
drag to grab the trail on either axis (or use the arrow keys to pan), and
double-click to snap back to the live edge and the fitted price range.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bi_trading.data.market_data import (
    DEFAULT_TIMEFRAME,
    TIMEFRAMES,
    CandleSeries,
    Market,
    format_price,
    search_markets,
)
from bi_trading.ui.trade_form import TradeForm
from bi_trading.ui.panels import Card

from bi_trading.ui.candle_chart import (  # noqa: F401
    BOLLINGER_PERIOD,
    CandleChart,
    format_axis_time,
)
from bi_trading.ui.typefaces import (  # noqa: F401
    _FONTS,
    mono_font,
    ui_font,
)


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Timeframes(QWidget):
    """Exclusive 1m … 1h pills."""

    changed = Signal(str)

    def __init__(self, current: str = DEFAULT_TIMEFRAME, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._buttons: dict[int, str] = {}
        for index, interval in enumerate(TIMEFRAMES):
            button = QPushButton(interval)
            button.setObjectName("tfButton")
            button.setToolTip(f"{interval} — press {index + 1}")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(interval == current)
            self.group.addButton(button, index)
            self._buttons[index] = interval
            layout.addWidget(button)
        layout.addStretch(1)

        self.group.idClicked.connect(self._on_clicked)

    def _on_clicked(self, index: int) -> None:
        self.changed.emit(self._buttons[index])

    def current(self) -> str:
        return self._buttons.get(self.group.checkedId(), DEFAULT_TIMEFRAME)

    def set_current(self, interval: str) -> None:
        for index, value in self._buttons.items():
            if value == interval:
                self.group.button(index).setChecked(True)
                return


class MarketSearch(QWidget):
    """Inline type-ahead search.

    Results render *inside* the card rather than in a popup window: a popup
    grabs the keyboard on macOS after the first keystroke, which is what made
    the old search unusable past one character.
    """

    chosen = Signal(str)
    MAX_RESULTS = 6

    def __init__(
        self,
        markets: Callable[[], list[Market] | dict[str, Market]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._markets = markets

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Search — btc, gold, oil, spy, apple…")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumHeight(24)

        self.results = QListWidget(self)
        self.results.setObjectName("marketResults")
        self.results.setMaximumHeight(132)
        self.results.setVisible(False)

        layout.addWidget(self.edit)
        layout.addWidget(self.results)

        self.edit.textEdited.connect(self._refresh)
        self.edit.installEventFilter(self)
        self.results.itemClicked.connect(self._on_item_clicked)

    # -- QLineEdit passthroughs -------------------------------------------

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:  # noqa: N802
        self.edit.setText(text)

    def selectAll(self) -> None:  # noqa: N802
        self.edit.selectAll()

    def setFocus(self, reason: Qt.FocusReason = Qt.FocusReason.OtherFocusReason) -> None:  # noqa: N802
        self.edit.setFocus(reason)

    # -- behaviour ---------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            obj is self.edit
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
        ):
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.results.count():
                row = self.results.currentRow()
                if key == Qt.Key.Key_Down:
                    row = 0 if row < 0 else row + 1
                else:
                    row = self.results.count() - 1 if row < 0 else row - 1
                self.results.setCurrentRow(max(0, min(self.results.count() - 1, row)))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.results.currentItem()
                coin = item.data(Qt.ItemDataRole.UserRole) if item else None
                if coin:
                    self._choose(coin)
                else:
                    matches = search_markets(self._markets(), self.text(), limit=1)
                    if matches:
                        self._choose(matches[0].coin)
                return True
            if key == Qt.Key.Key_Escape:
                self.results.setVisible(False)
                return False
        return super().eventFilter(obj, event)

    def _refresh(self, text: str) -> None:
        self.results.clear()
        results = search_markets(self._markets(), text, limit=self.MAX_RESULTS)

        if not results:
            query = text.strip()
            if len(query) >= 2:
                hint = QListWidgetItem(f"no Hyperliquid market for “{query}”")
                hint.setFlags(Qt.ItemFlag.NoItemFlags)
                self.results.addItem(hint)
                self.results.setVisible(True)
            else:
                self.results.setVisible(False)
            return

        for market in results:
            item = QListWidgetItem(market.coin)
            item.setData(Qt.ItemDataRole.UserRole, market.coin)
            if market.is_hip3:
                item.setToolTip("HIP-3 market")
            self.results.addItem(item)
        self.results.setCurrentRow(0)
        self.results.setVisible(True)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        coin = item.data(Qt.ItemDataRole.UserRole)
        if coin:
            self._choose(coin)

    def _choose(self, coin: str) -> None:
        self.results.setVisible(False)
        self.edit.blockSignals(True)
        self.edit.setText(coin)
        self.edit.blockSignals(False)
        self.chosen.emit(coin)


class MarketCard(Card):
    """A floating market panel: header, optional search, timeframe pills, chart."""

    market_changed = Signal(str)
    interval_changed = Signal(str)
    # before_ms is a Python int on purpose: Signal(int) is a 32-bit C int.
    history_requested = Signal(str, str, object)   # coin, interval, before ms
    add_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        coin: str | None = None,
        *,
        closable: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.coin = coin
        self.interval = DEFAULT_TIMEFRAME
        self.market: Market | None = None
        self._sz_decimals = 0
        self._has_mids = False

        # -- header --
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.name = ClickableLabel(coin or "—")
        self.name.setToolTip("Change market")
        name_font = self.name.font()
        name_font.setPointSize(12)
        name_font.setWeight(QFont.Weight.DemiBold)
        self.name.setFont(name_font)

        self.badge = QLabel("XYZ")
        self.badge.setFont(mono_font(8))
        self.badge.setStyleSheet(
            "color: #8a8a90; background: #1a1a1f;"
            " border: 1px solid #25262a;"
            " border-radius: 3px; padding: 1px 4px;"
        )
        self.badge.setVisible(False)

        self.price = QLabel("—")
        self.price.setFont(mono_font(13, bold=True))
        self.price.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.add_button = QPushButton("+")
        self.add_button.setObjectName("addTile")
        self.add_button.setFixedSize(18, 18)
        self.add_button.setToolTip("Add a market tile")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setVisible(False)
        self.add_button.clicked.connect(self.add_requested)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("closeTile")
        self.close_button.setFixedSize(16, 16)
        self.close_button.setToolTip("Close")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setVisible(closable)
        self.close_button.clicked.connect(self.close_requested)

        header.addWidget(self.name)
        header.addWidget(self.badge)
        header.addStretch(1)

        # Overlays, in the card as the mock draws them.
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
        header.addWidget(self.volume_toggle)
        header.addWidget(self.bollinger_toggle)
        header.addSpacing(2)

        header.addWidget(self.price)
        header.addWidget(self.add_button)
        header.addWidget(self.close_button)

        # -- search (collapses once a market is loaded) --
        self.search = MarketSearch(self._no_markets)
        self.search.chosen.connect(self._on_search_chosen)

        # -- timeframes + chart --
        self.timeframes = Timeframes(self.interval)
        self.timeframes.setVisible(False)
        self.timeframes.changed.connect(self._on_interval_changed)

        self.chart = CandleChart()
        self.chart.set_precision(self._sz_decimals)
        self.chart.set_interval(self.interval)
        self.chart.history_requested.connect(self._on_history_requested)
        self.chart.interval_selected.connect(self.set_interval)

        self.body.addLayout(header)
        self.body.addWidget(self.search)
        self.body.addWidget(self.timeframes)
        self.body.addWidget(self.chart, 1)

        # The trade form under the chart, as the mock draws it.
        self.trade_form = TradeForm()
        self.trade_form.setVisible(coin is not None)
        self.body.addWidget(self.trade_form)

        self.name.clicked.connect(self.open_search)
        self.set_placeholder("search a market above")
        # A card born with a coin is already loaded; only fresh tiles search.
        self.search.setVisible(coin is None)
        self.timeframes.setVisible(coin is not None)

    # -- state -------------------------------------------------------------

    def _apply_overlays(self, *_args) -> None:
        """The card's own overlay switches drive its chart."""
        self.chart.set_show_volume(self.volume_toggle.isChecked())
        self.chart.set_show_bollinger(self.bollinger_toggle.isChecked())

    def _no_markets(self) -> list[Market]:
        return []

    def set_market_source(
        self, provider: Callable[[], list[Market] | dict[str, Market]]
    ) -> None:
        self.search._markets = provider

    def open_search(self) -> None:
        self.search.blockSignals(True)
        self.search.setText(self.coin or "")
        self.search.blockSignals(False)
        self.search.setVisible(True)
        self.search.setFocus()
        self.search.selectAll()

    def set_placeholder(self, text: str) -> None:
        self.chart.set_placeholder(text)

    def set_market(self, market: Market | None) -> None:
        self.market = market
        if market is not None:
            self.coin = market.coin
            self._sz_decimals = market.sz_decimals
        self._has_mids = False
        self.name.setText(market.coin if market else "—")
        self.badge.setVisible(bool(market and market.is_hip3))
        self.chart.set_precision(self._sz_decimals)
        self.search.setVisible(market is None)
        self.timeframes.setVisible(market is not None)
        self.trade_form.setVisible(market is not None)
        if market is None:
            self.chart.set_series(())
            self.set_placeholder("search a market above")
            self.price.setText("—")
            self.trade_form.set_price(None)

    def apply_mid(self, price: float) -> None:
        self._has_mids = True
        self.price.setText(format_price(price, self._sz_decimals))
        self.trade_form.set_price(price)

    def apply_candles(self, series: CandleSeries) -> None:
        if series.coin != self.coin or series.interval != self.interval:
            return
        # Merge rather than replace: a reconcile carries only the last few
        # hundred bars, and the chart may be holding pages panned back to.
        self.chart.merge_series(series.candles)
        self.set_placeholder("waiting for candles…")
        if series.candles:
            self.trade_form.set_price(series.candles[-1].c)
        last = series.last_price
        if last is not None and not self._has_mids:
            self.price.setText(format_price(last, self._sz_decimals))

    # -- slots -------------------------------------------------------------

    def _on_search_chosen(self, coin: str) -> None:
        # The search bar collapses on selection; the name label re-opens it.
        self.search.setVisible(False)
        self.market_changed.emit(coin)

    def set_interval(self, interval: str) -> None:
        """Switch timeframe from a pill or the 1-6 keys."""
        if interval not in TIMEFRAMES:
            return
        self.timeframes.set_current(interval)
        self.interval = interval
        self.chart.set_interval(interval)
        self.chart.set_series(())
        self.set_placeholder("loading…")
        self.interval_changed.emit(interval)

    def restore_interval(self, interval: str) -> None:
        """Start on `interval` without announcing it: nothing is loaded yet."""
        if interval in TIMEFRAMES:
            self.timeframes.set_current(interval)
            self.interval = interval
            self.chart.set_interval(interval)

    def _on_interval_changed(self, interval: str) -> None:
        self.set_interval(interval)

    # -- history -----------------------------------------------------------

    def _on_history_requested(self, before_ms: int) -> None:
        if self.coin:
            self.history_requested.emit(self.coin, self.interval, before_ms)

    def apply_history(self, series: CandleSeries) -> None:
        if series.coin != self.coin or series.interval != self.interval:
            return
        self.chart.add_history(series.candles)

    def apply_history_failure(self, coin: str, interval: str) -> None:
        if coin == self.coin and interval == self.interval:
            self.chart.cancel_history_request()
