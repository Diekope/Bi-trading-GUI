"""The Polymarket column: one five-minute BTC up/down market, at a glance.

The useful information is where BTC is relative to the window's open, how long
is left, how the book and tape look, and what the market implies. So the panel
paints four things:

    outcome tiles   UP / DOWN in cents, with a probability bar
    clock           the window and a live countdown to the close
    price chart     BTC across the window, against the opening target
    tape            the last trades, newest first

Books, price samples and trades are kept per window and cleared when the feed
rolls to the next five-minute slug.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from lalala.cards import mono_font
from lalala.panels import Card
from lalala.polymarket_data import (
    PolymarketMarket,
    PricePoint,
    TokenBook,
    Trade,
    format_cents,
    format_compact,
    format_countdown,
    format_shares,
)
from lalala.theme import (
    ACCENT,
    BORDER,
    DOWN,
    PANEL_ALT,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    UP,
)

AMBER = "#e0b341"
TRACK = "#1b1b20"
SAMPLE_EVERY_MS = 1_000    # price-chart resolution; the wire is much faster
MAX_POINTS = 1_200         # a 5m window at 1 Hz is 300; leave room for backfill


def _alpha(color: str, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


class OutcomeTile(QWidget):
    """One side of the market: name, cents, probability bar, best quotes."""

    clicked = Signal()

    def __init__(self, name: str, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.accent = accent
        self.price: float | None = None
        self.bid: float | None = None
        self.ask: float | None = None
        self.selected = False
        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to highlight this outcome on the chart")

    def set_quote(
        self, price: float | None, bid: float | None, ask: float | None
    ) -> None:
        if (price, bid, ask) == (self.price, self.bid, self.ask):
            return
        self.price, self.bid, self.ask = price, bid, ask
        self.update()

    def set_name(self, name: str) -> None:
        if name != self.name:
            self.name = name
            self.update()

    def set_selected(self, selected: bool) -> None:
        if selected != self.selected:
            self.selected = selected
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.setPen(QPen(QColor(self.accent if self.selected else BORDER), 1))
        painter.setBrush(QColor(PANEL_ALT))
        painter.drawRoundedRect(rect, 4, 4)

        if self.selected:
            painter.setPen(QPen(QColor(self.accent), 1))
            painter.drawLine(rect.left() + 4, rect.top(), rect.right() - 4, rect.top())

        pad = 8.0
        painter.setFont(mono_font(9, bold=True))
        painter.setPen(QColor(self.accent))
        painter.drawText(
            QRectF(pad, 5, 60, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.name.upper(),
        )

        painter.setFont(mono_font(17, bold=True))
        painter.setPen(QColor(self.accent))
        painter.drawText(
            QRectF(rect.width() - 92, 2, 84, 22),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            format_cents(self.price),
        )

        track = QRectF(pad, 30, max(1.0, rect.width() - pad * 2), 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TRACK))
        painter.drawRoundedRect(track, 2, 2)
        if self.price is not None and self.price > 0:
            width = track.width() * max(0.0, min(1.0, self.price))
            painter.setBrush(QColor(self.accent))
            painter.drawRoundedRect(
                QRectF(track.left(), track.top(), max(2.0, width), track.height()),
                2,
                2,
            )

        painter.setFont(mono_font(8))
        painter.setPen(QColor(TEXT_FAINT))
        quote = (
            f"bid {format_cents(self.bid)}  ·  ask {format_cents(self.ask)}"
            if self.bid is not None or self.ask is not None
            else "waiting for quotes"
        )
        painter.drawText(
            QRectF(pad, 39, rect.width() - pad * 2, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            quote,
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PriceChart(QWidget):
    """BTC through the five-minute window, against the target (open) price.

    The binary market's question is whether BTC ends above where it started, so
    the useful line is the underlying price, not the implied probability. The
    chart keeps the full window as its x-axis even when only part of it has
    data, so the line visibly fills in as the window runs.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.market: PolymarketMarket | None = None
        self.points: list[PricePoint] = []
        self.target: float | None = None
        self._lo: float | None = None
        self._hi: float | None = None
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_market(
        self,
        market: PolymarketMarket,
        points: list[PricePoint],
        target: float | None,
    ) -> None:
        if self.market is None or self.market.slug != market.slug:
            # New window, new scale. Within a window the range only widens,
            # so the line does not jump as BTC moves.
            self._lo = None
            self._hi = None
        self.market = market
        self.points = points
        self.target = target
        self.update()

    def set_data(self, points: list[PricePoint], target: float | None) -> None:
        self.points = points
        self.target = target
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        painter.setFont(mono_font(8, bold=True))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(0, 0, width, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "BTC / USD",
        )

        market = self.market
        if market is None:
            self._message(painter, "waiting for the market…")
            return

        start = market.start_ms
        end = market.end_ms
        if end <= start:
            end = start + 1
        span = end - start

        points = [
            point
            for point in self.points
            if start <= point.timestamp_ms <= end
        ]
        target = self.target
        if not points or target is None:
            self._message(painter, "collecting…")
            return

        values = [point.price for point in points] + [target]
        lo, hi = self._range(values, target)

        left = 46.0
        right = width - 8.0
        top = 18.0
        bottom = height - 16.0
        if right - left < 20 or bottom - top < 20:
            return

        # Horizontal grid, labelled as whole dollars.
        painter.setFont(mono_font(7))
        for step in range(3):
            value = lo + (hi - lo) * step / 2.0
            y = bottom - (value - lo) / (hi - lo) * (bottom - top)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(left, y, right, y)
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, y - 7, left - 4, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:,.0f}",
            )

        # Window bounds on the time axis.
        start_at = datetime.fromtimestamp(start / 1000, tz=timezone.utc)
        end_at = datetime.fromtimestamp(end / 1000, tz=timezone.utc)
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(left, bottom + 1, 60, 13),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{start_at:%H:%M}",
        )
        painter.drawText(
            QRectF(right - 60, bottom + 1, 60, 13),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{end_at:%H:%M}",
        )

        def x_of(point: PricePoint) -> float:
            return left + min(
                1.0, max(0.0, (point.timestamp_ms - start) / span)
            ) * (right - left)

        def y_of(price: float) -> float:
            return bottom - (price - lo) / (hi - lo) * (bottom - top)

        target_y = y_of(target)
        last = points[-1]
        above = last.price >= target
        color = UP if above else DOWN

        path = QPainterPath()
        for point in points:
            if path.elementCount() == 0:
                path.moveTo(x_of(point), y_of(point.price))
            else:
                path.lineTo(x_of(point), y_of(point.price))

        # Shade the gap to the target, green above and red below, so the side
        # of the line reads even when the move is only a few dollars.
        fill = QPainterPath(path)
        fill.lineTo(x_of(last), target_y)
        fill.lineTo(x_of(points[0]), target_y)
        fill.closeSubpath()
        painter.save()
        painter.setClipRect(
            QRectF(left, top, right - left, max(0.0, target_y - top))
        )
        painter.fillPath(fill, _alpha(UP, 30))
        painter.restore()
        painter.save()
        painter.setClipRect(
            QRectF(left, target_y, right - left, max(0.0, bottom - target_y))
        )
        painter.fillPath(fill, _alpha(DOWN, 30))
        painter.restore()

        # The target: the window-open price the outcome is measured against.
        painter.setPen(QPen(QColor(AMBER), 1, Qt.PenStyle.DashLine))
        painter.drawLine(left, target_y, right, target_y)
        painter.setFont(mono_font(7))
        painter.setPen(QColor(AMBER))
        painter.drawText(
            QRectF(left + 2, target_y - 13, right - left - 4, 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"open {target:,.1f}",
        )

        pen = QPen(QColor(color), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(
            QPointF(x_of(last), y_of(last.price)), 2.6, 2.6
        )

        # The side and the gap in the header: the answer to the market's
        # question, not just the price.
        delta = (last.price - target) / target * 100.0 if target else 0.0
        painter.setFont(mono_font(8, bold=True))
        painter.setPen(QColor(color))
        painter.drawText(
            QRectF(left, 0, right - left, 14),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{'ABOVE' if above else 'BELOW'} {delta:+.2f}%",
        )

    def _range(self, values: list[float], target: float) -> tuple[float, float]:
        """The y-range, sticky within a window: widen, never shrink."""
        low = min(values)
        high = max(values)
        # Keep the target's line away from the edges, and give a quiet window
        # enough resolution to see a $10 move on a $78,000 price.
        pad = max((high - low) * 0.18, abs(target) * 0.00025, 1.0)
        lo = low - pad
        hi = high + pad
        if self._lo is None:
            self._lo, self._hi = lo, hi
        else:
            self._lo = min(self._lo, lo)
            self._hi = max(self._hi, hi)
        return self._lo, self._hi

    def _message(self, painter: QPainter, text: str) -> None:
        painter.setFont(mono_font(9))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(0, 16, self.width(), self.height() - 16),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )


class TradeTape(QWidget):
    """The most recent prints, newest first."""

    MAX_ROWS = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.trades: list[tuple[Trade, str]] = []
        self.setMinimumHeight(74)
        self.setMaximumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def add(self, trade: Trade, name: str) -> None:
        self.trades.insert(0, (trade, name))
        del self.trades[self.MAX_ROWS:]
        self.update()

    def clear(self) -> None:
        self.trades.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        painter.setFont(mono_font(8, bold=True))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(0, 0, width, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "TAPE",
        )
        if not self.trades:
            painter.setFont(mono_font(9))
            painter.drawText(
                QRectF(0, 16, width, max(1.0, height - 16)),
                Qt.AlignmentFlag.AlignCenter,
                "waiting for trades…",
            )
            return

        row_h = 14.0
        rows = min(self.MAX_ROWS, int(max(1.0, height - 16) / row_h))
        painter.setFont(mono_font(8))
        for index, (trade, name) in enumerate(self.trades[:rows]):
            y = 16 + index * row_h
            moment = datetime.fromtimestamp(
                trade.timestamp_ms / 1000 if trade.timestamp_ms else time.time(),
                tz=timezone.utc,
            ).strftime("%H:%M:%S")
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, y, 58, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                moment,
            )
            painter.setPen(QColor(UP if name.lower().startswith("up") else DOWN))
            painter.drawText(
                QRectF(62, y, 44, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name.upper()[:6],
            )
            painter.setPen(QColor(TEXT))
            painter.drawText(
                QRectF(108, y, 52, row_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_cents(trade.price),
            )
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(width - 84, y, 84, row_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"× {format_shares(trade.size)}",
            )


@dataclass
class _Status:
    text: str
    color: str


STATUS: dict[str, _Status] = {
    "waiting": _Status("waiting for market…", AMBER),
    "snapshot": _Status("loading book…", ACCENT),
    "live": _Status("live", UP),
    "reconnecting": _Status("reconnecting…", AMBER),
    "closed": _Status("closed", TEXT_FAINT),
}


class PolymarketPanel(Card):
    """One market, with the information a binary bet actually needs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.market: PolymarketMarket | None = None
        self.books: dict[str, TokenBook] = {}
        self.points: list[PricePoint] = []
        self.target: float | None = None
        self._btc: float | None = None
        self._selected = 0
        self._last_sample = 0
        self._status = STATUS["waiting"]
        # Below this the chart labels and the tape overlap; the Hyperliquid
        # column still gets the rest of a 620px-minimum window.
        self.setMinimumWidth(300)

        # -- header --
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.title_label = QLabel("POLYMARKET")
        title_font = QFont(mono_font(8, bold=True))
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self.badge = QLabel("5m")
        self.badge.setFont(mono_font(8))
        self.badge.setStyleSheet(
            f"color: {TEXT_MUTED}; background: #1a1a1f; border: 1px solid {BORDER};"
            " border-radius: 3px; padding: 1px 4px;"
        )

        self.status_dot = QLabel("●")
        self.status_dot.setFont(mono_font(8))
        self.status_dot.setStyleSheet(f"color: {AMBER}; background: transparent;")
        self.status_text = QLabel(self._status.text)
        self.status_text.setFont(mono_font(8))
        self.status_text.setStyleSheet(
            f"color: {TEXT_FAINT}; background: transparent;"
        )

        header.addWidget(self.title_label)
        header.addWidget(self.badge)
        header.addStretch(1)
        header.addWidget(self.status_dot)
        header.addWidget(self.status_text)

        # -- question + clock --
        self.question = QLabel("Waiting for the next five-minute market…")
        question_font = self.question.font()
        question_font.setPointSize(12)
        question_font.setWeight(QFont.Weight.DemiBold)
        self.question.setFont(question_font)
        self.question.setWordWrap(True)
        self.question.setStyleSheet(f"color: {TEXT}; background: transparent;")

        clock = QHBoxLayout()
        clock.setContentsMargins(0, 0, 0, 0)
        clock.setSpacing(6)

        self.window_label = QLabel("—")
        self.window_label.setFont(mono_font(8))
        self.window_label.setStyleSheet(
            f"color: {TEXT_FAINT}; background: transparent;"
        )

        close_caption = QLabel("closes in")
        close_caption.setFont(mono_font(8))
        close_caption.setStyleSheet(
            f"color: {TEXT_FAINT}; background: transparent;"
        )

        self.countdown = QLabel("—")
        self.countdown.setFont(mono_font(15, bold=True))
        self.countdown.setStyleSheet(f"color: {TEXT}; background: transparent;")

        clock.addWidget(self.window_label)
        clock.addStretch(1)
        clock.addWidget(close_caption)
        clock.addWidget(self.countdown)

        # -- outcome tiles --
        tiles = QHBoxLayout()
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(6)

        self.up_tile = OutcomeTile("Up", UP)
        self.down_tile = OutcomeTile("Down", DOWN)
        self.up_tile.clicked.connect(lambda: self._select_token(0))
        self.down_tile.clicked.connect(lambda: self._select_token(1))
        tiles.addWidget(self.up_tile, 1)
        tiles.addWidget(self.down_tile, 1)

        # -- stats --
        stats = QGridLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setHorizontalSpacing(3)
        stats.setVerticalSpacing(1)

        self.spread_value = self._stat(stats, 0, 0, "SPREAD")
        self.liquidity_value = self._stat(stats, 0, 1, "LIQUIDITY")
        self.depth_value = self._stat(stats, 1, 0, "DEPTH")
        self.target_value = self._stat(stats, 1, 1, "TARGET")
        self.btc_value = self._stat(stats, 2, 0, "BTC")
        self.move_value = self._stat(stats, 2, 1, "Δ OPEN")
        self.target_value.setToolTip(
            "Window-open BTC price the outcome is measured against. "
            "Polymarket resolves on Chainlink's BTC/USD TWAP; this reference "
            "is Hyperliquid's BTC open at the same moment."
        )
        self.move_value.setToolTip("BTC now versus the window-open target.")
        stats.setColumnStretch(1, 1)
        stats.setColumnStretch(3, 1)

        # -- price chart + tape --
        self.price_chart = PriceChart()
        self.tape = TradeTape()

        self.body.addLayout(header)
        self.body.addWidget(self.question)
        self.body.addLayout(clock)
        self.body.addLayout(tiles)
        self.body.addLayout(stats)
        self.body.addSpacing(2)
        self.body.addWidget(self.price_chart, 1)
        self.body.addWidget(self.tape, 0)

        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    @staticmethod
    def _stat(
        grid: QGridLayout, row: int, column: int, caption: str
    ) -> QLabel:
        label = QLabel(caption)
        label.setFont(mono_font(7))
        label.setStyleSheet(f"color: {TEXT_FAINT}; background: transparent;")
        value = QLabel("—")
        value.setFont(mono_font(9, bold=True))
        value.setStyleSheet(f"color: {TEXT}; background: transparent;")
        grid.addWidget(label, row, column * 2)
        grid.addWidget(value, row, column * 2 + 1)
        return value

    # -- data --------------------------------------------------------------

    def set_market(self, market: PolymarketMarket) -> None:
        if not isinstance(market, PolymarketMarket):
            return
        rolled = self.market is None or self.market.slug != market.slug
        self.market = market

        if rolled:
            self.books.clear()
            self.points = []
            self.target = None
            self._selected = 0
            self._last_sample = 0
            self.tape.clear()
            self.price_chart.set_market(market, self.points, self.target)
            self.depth_value.setText("—")
            self.target_value.setText("—")
            self.move_value.setText("—")
            self.move_value.setStyleSheet(
                f"color: {TEXT}; background: transparent;"
            )
            self.btc_value.setStyleSheet(
                f"color: {TEXT}; background: transparent;"
            )
            self.spread_value.setText(
                format_cents(market.spread) if market.spread > 0 else "—"
            )
        else:
            self.price_chart.set_market(market, self.points, self.target)

        self.question.setText(market.question)
        self.window_label.setText(self._window_text(market))
        self.liquidity_value.setText(format_compact(market.liquidity))
        self.status_text.setToolTip(market.slug)

        for tile, outcome in zip((self.up_tile, self.down_tile), market.outcomes):
            tile.set_name(outcome.name)
            bid = outcome.best_bid
            ask = outcome.best_ask
            price = outcome.mid if outcome.mid is not None else outcome.price
            tile.set_quote(price, bid, ask)

        self._refresh_selection()
        self._tick()

    def apply_book(self, book: TokenBook) -> None:
        if self.market is None:
            return
        outcome = self.market.outcome_for_token(book.token_id)
        if outcome is None:
            return
        self.books[book.token_id] = book

        tile = self._tile_for(outcome.token_id)
        if tile is not None:
            tile.set_quote(book.mid, book.best_bid, book.best_ask)

        selected = self._selected_book()
        if selected is not None:
            self._set_text(self.spread_value, format_cents(selected.spread))
        # Depth near the touch: the whole book is dominated by 1¢ lottery
        # tickets far from the price, which says little about executable size.
        self._set_text(
            self.depth_value,
            format_compact(
                sum(
                    level.price * level.size
                    for held in self.books.values()
                    for level in held.bids[:8] + held.asks[:8]
                )
            ),
        )

    def set_window_prices(
        self, target: float | None, points: object
    ) -> None:
        """Seed the target and the pre-launch part of the price chart."""
        if self.market is None or target is None or target <= 0:
            return
        self.target = float(target)
        self._set_text(self.target_value, f"{self.target:,.1f}")

        merged: dict[int, PricePoint] = {}
        for point in points if isinstance(points, (list, tuple)) else ():
            if isinstance(point, PricePoint):
                merged[point.timestamp_ms] = point
        for point in self.points:
            merged[point.timestamp_ms] = point
        ordered = sorted(merged.values(), key=lambda point: point.timestamp_ms)
        del ordered[:-MAX_POINTS]
        self.points = ordered
        self.price_chart.set_data(self.points, self.target)
        if self._btc is not None:
            self._update_delta(self._btc)

    def _sample_price(self, price: float) -> None:
        """Record BTC once a second for the reference chart."""
        if self.market is None:
            return
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_sample < SAMPLE_EVERY_MS:
            return
        self._last_sample = now_ms
        self.points.append(PricePoint(now_ms, float(price)))
        del self.points[:-MAX_POINTS]
        self.price_chart.set_data(self.points, self.target)

    def _update_delta(self, price: float) -> None:
        """Above/below the target, in percent, for the header readouts."""
        target = self.target
        if target is None or target <= 0:
            return
        delta = (price - target) / target * 100.0
        color = UP if delta >= 0 else DOWN
        self._set_text(self.move_value, f"{delta:+.2f}%")
        self.move_value.setStyleSheet(
            f"color: {color}; background: transparent;"
        )
        self.btc_value.setStyleSheet(
            f"color: {color}; background: transparent;"
        )
        self.move_value.setToolTip(
            f"{'Above' if delta >= 0 else 'Below'} target by "
            f"{abs(price - target):,.1f} ({abs(delta):.2f}%)"
        )

    @staticmethod
    def _set_text(label: QLabel, text: str) -> None:
        """QLabel relayouts on every setText, even when the string is equal."""
        if label.text() != text:
            label.setText(text)

    def apply_trade(self, trade: Trade) -> None:
        if self.market is None:
            return
        outcome = self.market.outcome_for_token(trade.token_id)
        name = outcome.name if outcome is not None else "?"
        self.tape.add(trade, name)

    def set_btc(self, price: float) -> None:
        """Reference BTC mid, forwarded from the Hyperliquid feed."""
        self._btc = float(price)
        self._set_text(self.btc_value, f"{price:,.1f}")
        self._update_delta(price)
        self._sample_price(price)

    def set_status(self, status: str) -> None:
        looked_up = STATUS.get(status)
        if looked_up is None:
            return
        self._status = looked_up
        self.status_text.setText(looked_up.text)
        self.status_dot.setStyleSheet(
            f"color: {looked_up.color}; background: transparent;"
        )

    def text(self) -> str:
        """Kept for the shell contract: the column is still the Polymarket one."""
        return "Polymarket"

    # -- internals ---------------------------------------------------------

    def _selected_token(self) -> str | None:
        if self.market is None or self._selected >= len(self.market.outcomes):
            return None
        return self.market.outcomes[self._selected].token_id

    def _selected_book(self) -> TokenBook | None:
        token = self._selected_token()
        return self.books.get(token) if token else None

    def _tile_for(self, token_id: str) -> OutcomeTile | None:
        if self.market is None:
            return None
        for index, outcome in enumerate(self.market.outcomes[:2]):
            if outcome.token_id == token_id:
                return (self.up_tile, self.down_tile)[index]
        return None

    def _select_token(self, index: int) -> None:
        if self.market is None or index >= len(self.market.outcomes):
            return
        self._selected = index
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        self.up_tile.set_selected(self._selected == 0)
        self.down_tile.set_selected(self._selected == 1)

    @staticmethod
    def _window_text(market: PolymarketMarket) -> str:
        if market.start_ms <= 0 or market.end_ms <= 0:
            return "—"
        start = datetime.fromtimestamp(market.start_ms / 1000, tz=timezone.utc)
        end = datetime.fromtimestamp(market.end_ms / 1000, tz=timezone.utc)
        return f"{start:%H:%M}–{end:%H:%M} UTC"

    def _tick(self) -> None:
        if self.market is None:
            self.countdown.setText("—")
            return
        remaining = (self.market.end_ms - time.time() * 1000) / 1000.0
        self.countdown.setText(format_countdown(remaining))
        color = DOWN if remaining <= 30 else AMBER if remaining <= 60 else TEXT
        self.countdown.setStyleSheet(f"color: {color}; background: transparent;")
