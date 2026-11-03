"""Trading widgets: candlestick chart, timeframe pills, market card.

The chart is hand-painted and supports panning and zooming: wheel to zoom,
drag or arrow keys to pan, double-click to snap back to the live edge.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.market_data import (
    DEFAULT_TIMEFRAME,
    TIMEFRAMES,
    Candle,
    CandleSeries,
    Market,
    bollinger_bands,
    format_price,
    search_markets,
)
from lalala.panels import Card
from lalala.theme import ACCENT, BAND, BORDER, DOWN, TEXT_FAINT, TEXT_MUTED, UP


def format_axis_time(stamp_ms: int, interval: str) -> str:
    """Time-axis label for a candle open time."""
    moment = datetime.fromtimestamp(stamp_ms / 1000)
    if interval == "1h":
        return moment.strftime("%d %b %H:%M")
    return moment.strftime("%H:%M")


def mono_font(points: int = 12, bold: bool = False) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(points)
    font.setBold(bold)
    return font


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CandleChart(QWidget):
    """OHLC candles with a viewport that can be zoomed and panned.

    `_visible` is how many candles are on screen; `_offset` is how many candles
    sit to the right of the viewport (0 = pinned to the live edge).
    """

    GUTTER = 56          # right-hand price axis
    TIME_AXIS = 16       # bottom time axis
    MIN_VISIBLE = 8
    DEFAULT_VISIBLE = 80
    ZOOM_STEP = 1.12     # one wheel notch; deliberately gentle
    DRAG_GAIN = 0.75     # candles travelled per slot dragged
    PRICE_ZOOM_STEP = 1.10
    MIN_PRICE_ZOOM = 0.2
    MAX_PRICE_ZOOM = 20.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Deliberately small: the card minimum is derived from this, and four
        # stacked cards must still fit inside the window's minimum height.
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(
            "Wheel: zoom time · wheel over the price axis: stretch prices · "
            "drag or ← →: pan · double-click: reset"
        )

        self._candles: tuple[Candle, ...] = ()
        self._visible = self.DEFAULT_VISIBLE
        self._offset = 0
        self._price_zoom = 1.0
        self._precision = 2
        self._interval = DEFAULT_TIMEFRAME
        self._show_volume = True
        self._show_bollinger = False
        self._placeholder = "search a market"
        self._drag_x: float | None = None
        self._drag_offset = 0

    # -- data --------------------------------------------------------------

    def set_precision(self, sz_decimals: int) -> None:
        self._precision = sz_decimals
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def set_interval(self, interval: str) -> None:
        """Only affects how the time axis is labelled."""
        self._interval = interval
        self.update()

    def set_show_volume(self, enabled: bool) -> None:
        self._show_volume = bool(enabled)
        self.update()

    def set_show_bollinger(self, enabled: bool) -> None:
        self._show_bollinger = bool(enabled)
        self.update()

    @property
    def show_volume(self) -> bool:
        return self._show_volume

    @property
    def show_bollinger(self) -> bool:
        return self._show_bollinger

    def set_series(self, candles: tuple[Candle, ...]) -> None:
        if not candles:
            # A new market or interval starts from the default vertical scale.
            self._price_zoom = 1.0
        self._candles = tuple(candles)
        self._clamp()
        self.update()

    @property
    def candle_count(self) -> int:
        return len(self._candles)

    @property
    def visible_count(self) -> int:
        """Requested window, capped by what history actually exists.

        Kept separate from `_visible` so a series that starts with a handful of
        bars can grow back into the normal window instead of latching at the
        minimum for the rest of the session.
        """
        total = len(self._candles)
        if total == 0:
            return self._visible
        return max(1, min(self._visible, total))

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def price_zoom(self) -> float:
        """1.0 is the natural range; higher stretches prices apart."""
        return self._price_zoom

    @property
    def is_live(self) -> bool:
        """True when the viewport is pinned to the newest candle."""
        return self._offset == 0

    def _visible_bounds(self) -> tuple[int, int]:
        if not self._candles:
            return (0, 0)
        end = max(1, len(self._candles) - self._offset)
        start = max(0, end - self.visible_count)
        return (start, end)

    def visible_candles(self) -> tuple[Candle, ...]:
        start, end = self._visible_bounds()
        return self._candles[start:end]

    # -- navigation --------------------------------------------------------

    def zoom(self, direction: int) -> None:
        """direction > 0 zooms in (fewer candles), < 0 zooms out."""
        if not self._candles or direction == 0:
            return
        if direction > 0:
            self._visible = max(self.MIN_VISIBLE, int(self._visible / self.ZOOM_STEP))
        else:
            # Always widen by at least one candle, so a gentle step never sticks.
            self._visible = max(self._visible + 1, int(self._visible * self.ZOOM_STEP) + 1)
        self._clamp()
        self.update()

    def pan(self, candles: int) -> None:
        """Positive moves back in time."""
        if not self._candles or candles == 0:
            return
        self._offset += candles
        self._clamp()
        self.update()

    def zoom_price(self, direction: int) -> None:
        """direction > 0 stretches the price range apart (fewer prices shown)."""
        if not self._candles or direction == 0:
            return
        factor = self.PRICE_ZOOM_STEP if direction > 0 else 1 / self.PRICE_ZOOM_STEP
        self._price_zoom = min(
            self.MAX_PRICE_ZOOM, max(self.MIN_PRICE_ZOOM, self._price_zoom * factor)
        )
        self.update()

    def reset_view(self) -> None:
        self._visible = self.DEFAULT_VISIBLE
        self._offset = 0
        self._price_zoom = 1.0
        self._clamp()
        self.update()

    def _clamp(self) -> None:
        total = len(self._candles)
        self._visible = max(self.MIN_VISIBLE, self._visible)
        self._offset = max(0, min(self._offset, max(0, total - self.visible_count)))

    # -- interaction -------------------------------------------------------

    def _axis_at(self, x: float, y: float) -> str:
        """Which axis, if any, the pointer is over: "price", "time" or ""."""
        if x >= self.width() - self.GUTTER:
            return "price"
        if y >= self.height() - self.TIME_AXIS:
            return "time"
        return ""

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return

        notches = max(1, int(abs(steps)))
        direction = 1 if steps > 0 else -1
        axis = self._axis_at(event.position().x(), event.position().y())

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.pan(int(-steps * 2))
        elif axis == "price":
            # Next to the price labels: stretch or squash the vertical range
            # without touching how much history is on screen.
            for _ in range(notches):
                self.zoom_price(direction)
        else:
            # Over the plot or the time axis: zoom the time range.
            for _ in range(notches):
                self.zoom(direction)
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._axis_at(event.position().x(), event.position().y()):
                # Pressing an axis is not a pan; leave the drag alone.
                event.accept()
                return
            self._drag_x = event.position().x()
            self._drag_offset = self._offset
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_x = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_x is None:
            axis = self._axis_at(event.position().x(), event.position().y())
            if axis == "price":
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif axis == "time":
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._drag_x is None or not self._candles:
            super().mouseMoveEvent(event)
            return
        slot = max(1.0, (self.width() - self.GUTTER) / max(1, len(self.visible_candles())))
        shift = int((event.position().x() - self._drag_x) / slot * self.DRAG_GAIN)
        self._offset = self._drag_offset + shift
        self._clamp()
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.reset_view()
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.pan(step if key == Qt.Key.Key_Left else -step)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.zoom(1 if key == Qt.Key.Key_Up else -1)
        elif key == Qt.Key.Key_Home:
            self.pan(len(self._candles))
        elif key in (Qt.Key.Key_End, Qt.Key.Key_0):
            self.reset_view()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        candles = self.visible_candles()
        if not candles:
            painter.setPen(QColor(TEXT_FAINT))
            painter.setFont(mono_font(9))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            painter.end()
            return

        full = QRectF(self.rect().adjusted(1, 4, -self.GUTTER, -self.TIME_AXIS))
        if full.width() < 4 or full.height() < 8:
            painter.end()
            return

        # Volume gets a strip at the bottom of the plot when there is room.
        volume_height = 0.0
        if self._show_volume and any(c.v > 0 for c in candles) and full.height() >= 90:
            volume_height = max(20.0, full.height() * 0.20)
        gap = 6.0 if volume_height else 0.0
        price_height = full.height() - volume_height - gap
        if price_height < 24:
            volume_height, gap = 0.0, 0.0
            price_height = full.height()

        price_rect = QRectF(full.left(), full.top(), full.width(), price_height)
        volume_rect = QRectF(
            full.left(), price_rect.bottom() + gap, full.width(), volume_height
        )

        source = self._candles
        start, end = self._visible_bounds()
        bands = bollinger_bands(source) if self._show_bollinger else ()
        visible_bands = bands[start:end] if bands else ()

        candle_high = max(c.h for c in candles)
        candle_low = min(c.l for c in candles)
        high, low = candle_high, candle_low
        if visible_bands:
            band_high = max(
                (band[1] for band in visible_bands if band is not None),
                default=candle_high,
            )
            band_low = min(
                (band[2] for band in visible_bands if band is not None),
                default=candle_low,
            )
            # Bands may stretch the scale, but only half a candle-range each
            # way. A wide envelope after a gap would otherwise flatten the
            # candles into a single line; past the cap the bands clip instead.
            room = (candle_high - candle_low) or abs(candle_high) * 0.001 or 1.0
            high = max(candle_high, min(band_high, candle_high + room * 0.5))
            low = min(candle_low, max(band_low, candle_low - room * 0.5))
        pad = (high - low) * 0.05 or max(high, 1.0) * 0.001
        high += pad
        low -= pad

        # Vertical zoom: shrinking the span stretches prices apart. The centre
        # of the natural range stays put, so the wheel does not make the chart
        # jump up or down while zooming.
        span = (high - low) / self._price_zoom
        centre = (high + low) / 2
        high = centre + span / 2
        low = centre - span / 2

        slot = full.width() / len(candles)
        body_width = max(1.0, slot * 0.62)

        def price_y(price: float) -> float:
            return price_rect.bottom() - (price - low) / span * price_rect.height()

        def x_at(index: int) -> float:
            return full.left() + (index + 0.5) * slot

        # -- grid + price axis --
        last_y = price_y(candles[-1].c)
        painter.setFont(mono_font(8))
        for fraction in (0.0, 0.5, 1.0):
            level = low + span * fraction
            gy = price_y(level)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(QPointF(price_rect.left(), gy), QPointF(price_rect.right(), gy))
            if abs(gy - last_y) < 11:
                continue  # leave the slot to the accent last-price label
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(price_rect.right() + 4, gy - 7, self.GUTTER - 6, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                format_price(level, self._precision),
            )

        # -- Bollinger bands, under the candles --
        if visible_bands:
            painter.setClipRect(price_rect)
            runs: list[list[tuple[int, tuple[float, float, float]]]] = []
            current: list[tuple[int, tuple[float, float, float]]] = []
            for index, band in enumerate(visible_bands):
                if band is None:
                    if len(current) > 1:
                        runs.append(current)
                    current = []
                else:
                    current.append((index, band))
            if len(current) > 1:
                runs.append(current)

            band_color = QColor(BAND)
            fill_color = QColor(BAND)
            fill_color.setAlpha(26)
            for run in runs:
                upper = [
                    QPointF(x_at(index), price_y(band[1])) for index, band in run
                ]
                lower = [
                    QPointF(x_at(index), price_y(band[2])) for index, band in run
                ]
                polygon = QPolygonF(upper + list(reversed(lower)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill_color)
                painter.drawPolygon(polygon)

                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(band_color, 1))
                painter.drawPolyline(QPolygonF(upper))
                painter.drawPolyline(QPolygonF(lower))

                middle_color = QColor(BAND)
                middle_color.setAlpha(120)
                painter.setPen(QPen(middle_color, 1, Qt.PenStyle.DotLine))
                painter.drawPolyline(
                    QPolygonF(
                        [
                            QPointF(x_at(index), price_y(band[0]))
                            for index, band in run
                        ]
                    )
                )
            painter.setClipping(False)

        # -- candles --
        painter.setClipRect(price_rect)
        for index, candle in enumerate(candles):
            color = QColor(UP if candle.is_up else DOWN)
            x = x_at(index)
            painter.setPen(QPen(color, 1))
            painter.drawLine(
                QPointF(x, price_y(candle.h)), QPointF(x, price_y(candle.l))
            )
            top = price_y(max(candle.o, candle.c))
            bottom = price_y(min(candle.o, candle.c))
            painter.fillRect(
                QRectF(x - body_width / 2, top, body_width, max(1.0, bottom - top)),
                color,
            )
        painter.setClipping(False)

        # -- volume --
        if volume_height:
            peak = max(c.v for c in candles)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(
                QPointF(volume_rect.left(), volume_rect.top()),
                QPointF(volume_rect.right(), volume_rect.top()),
            )
            if peak > 0:
                painter.setClipRect(volume_rect)
                for index, candle in enumerate(candles):
                    if candle.v <= 0:
                        continue
                    bar = (candle.v / peak) * (volume_rect.height() - 1)
                    color = QColor(UP if candle.is_up else DOWN)
                    color.setAlpha(115)
                    x = x_at(index)
                    painter.fillRect(
                        QRectF(
                            x - body_width / 2,
                            volume_rect.bottom() - bar,
                            body_width,
                            max(1.0, bar),
                        ),
                        color,
                    )
                painter.setClipping(False)

        # -- last price --
        painter.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(price_rect.left(), last_y), QPointF(price_rect.right(), last_y)
        )
        painter.setPen(QColor(ACCENT))
        painter.drawText(
            QRectF(price_rect.right() + 4, last_y - 7, self.GUTTER - 6, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            format_price(candles[-1].c, self._precision),
        )

        # -- time axis --
        painter.setFont(mono_font(8))
        metrics = painter.fontMetrics()
        step = max(1, len(candles) // 4)
        right_edge = full.left() - 4.0
        for index in range(0, len(candles), step):
            x = x_at(index)
            text = format_axis_time(candles[index].t, self._interval)
            width = float(metrics.horizontalAdvance(text))
            left = x - width / 2
            if left < right_edge + 8 or left + width > full.right():
                continue
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(
                QPointF(x, full.bottom() + 1), QPointF(x, full.bottom() + 4)
            )
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, full.bottom() + 1, width, self.TIME_AXIS - 2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            right_edge = left + width

        # -- scrolled-back hint --
        if not self.is_live:
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(full.left() + 4, full.top(), full.width() - 8, 12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                f"{self._offset} back · double-click for live",
            )
        painter.end()


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

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:  # noqa: N802
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
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
            "color: #8a8a90; background: #1a1a1f; border: 1px solid #25262a;"
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

        self.body.addLayout(header)
        self.body.addWidget(self.search)
        self.body.addWidget(self.timeframes)
        self.body.addWidget(self.chart, 1)

        self.name.clicked.connect(self.open_search)
        self.set_placeholder("search a market above")
        # A card born with a coin is already loaded; only fresh tiles search.
        self.search.setVisible(coin is None)
        self.timeframes.setVisible(coin is not None)

    # -- state -------------------------------------------------------------

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
        if market is None:
            self.chart.set_series(())
            self.set_placeholder("search a market above")
            self.price.setText("—")

    def apply_mid(self, price: float) -> None:
        self._has_mids = True
        self.price.setText(format_price(price, self._sz_decimals))

    def apply_candles(self, series: CandleSeries) -> None:
        if series.coin != self.coin or series.interval != self.interval:
            return
        self.chart.set_series(series.candles)
        self.set_placeholder("waiting for candles…")
        last = series.last_price
        if last is not None and not self._has_mids:
            self.price.setText(format_price(last, self._sz_decimals))

    # -- slots -------------------------------------------------------------

    def _on_search_chosen(self, coin: str) -> None:
        # The search bar collapses on selection; the name label re-opens it.
        self.search.setVisible(False)
        self.market_changed.emit(coin)

    def _on_interval_changed(self, interval: str) -> None:
        self.interval = interval
        self.chart.set_interval(interval)
        self.chart.set_series(())
        self.set_placeholder("loading…")
        self.interval_changed.emit(interval)
