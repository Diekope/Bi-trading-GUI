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
    binary_return,
    format_cents,
    format_compact,
    format_countdown,
    format_delta,
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
SAMPLE_EVERY_MS = 1_000    # one history point per second; the wire is faster
MAX_POINTS = 3_600         # one hour of samples; the line keeps rolling past windows
SMOOTH = 0.30              # per sample; a one-tick spike becomes a bend, not a needle

# The chart is a rolling window, not one market window. Fifteen minutes shows
# three Polymarket windows and still gives a five-minute move room to breathe.
VIEW_MS = 15 * 60_000
WINDOW_MARK_MS = 300_000
FRAME_MS = 33              # ~30 fps: the scroll and the live tip glide
LAG_MS = 1_500             # > one sample: the tip always has a future keyframe
EASE_TIP = 0.18            # per frame, toward the interpolated tip
EASE_RANGE = 0.08          # per frame, toward the natural y-range


def smooth_path(vertices: list[tuple[float, float]]) -> QPainterPath:
    """A path whose corners are rounded instead of meeting at hard angles.

    Each interior vertex becomes the control point of a quadratic that runs
    between the midpoints of its two segments, so the curve brushes past every
    sample and turns a one-sample spike into a bend. It cannot overshoot: every
    control point is a real data point.
    """
    path = QPainterPath()
    if not vertices:
        return path
    path.moveTo(*vertices[0])
    for index in range(1, len(vertices) - 1):
        x, y = vertices[index]
        next_x, next_y = vertices[index + 1]
        path.quadTo(x, y, (x + next_x) * 0.5, (y + next_y) * 0.5)
    path.lineTo(*vertices[-1])
    return path


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
        cost = self.ask if self.ask is not None else self.price
        earning = binary_return(cost)
        room = 46.0 if earning is not None and rect.width() >= 168 else 0.0
        quote = (
            f"bid {format_cents(self.bid)}  ·  ask {format_cents(self.ask)}"
            if self.bid is not None or self.ask is not None
            else "waiting for quotes"
        )
        painter.drawText(
            QRectF(pad, 39, rect.width() - pad * 2 - room, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            quote,
        )

        # What a winning share pays, from the price you would actually pay.
        # Only on a tile wide enough to carry it without clipping the quotes;
        # the selected outcome always has the numbers in the stats rows.
        if room:
            multiple, _ = earning
            painter.setFont(mono_font(8, bold=True))
            painter.setPen(QColor(self.accent))
            painter.drawText(
                QRectF(rect.width() - pad - room, 39, room, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"×{multiple:.2f}",
            )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PriceChart(QWidget):
    """BTC over a rolling fifteen minutes, against the window's target.

    The binary market's question is whether BTC ends above where the window
    started, so the useful line is the underlying price, not the implied
    probability. The x-axis is a rolling fifteen minutes that ends a fraction
    of a second behind live, so a rollover never clears the line and the newest
    sample never snaps: old windows scroll left, the new target segment grows
    from the right edge, and the tip is interpolated along the last segment.
    The curve is smoothed through the samples, and the y-range eases, so the
    chart glides instead of stepping once per sample.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.market: PolymarketMarket | None = None
        self.points: list[PricePoint] = []
        self.target: float | None = None
        self._lo: float | None = None
        self._hi: float | None = None
        self._tip: float | None = None
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def set_market(
        self,
        market: PolymarketMarket,
        points: list[PricePoint],
        target: float | None,
    ) -> None:
        """Point the chart at a new window without dropping the history."""
        self.market = market
        self.points = points
        if target is not None:
            self.target = target
        self.update()

    def set_data(self, points: list[PricePoint], target: float | None) -> None:
        self.points = points
        if target is not None:
            self.target = target
        self.update()

    def _advance(self) -> None:
        if self.market is None or not self.isVisible():
            return
        self._ease()
        self.update()

    def _ease(self) -> None:
        target = self._tip_at(int(time.time() * 1000) - LAG_MS)
        if target is None:
            return
        if self._tip is None:
            self._tip = target
        else:
            self._tip += (target - self._tip) * EASE_TIP

    def _tip_at(self, moment_ms: int) -> float | None:
        """Price at a moment between keyframes, so the line never snaps.

        The painted tip sits on the segment that contains `moment_ms`. The
        view is delayed by more than one sample, so a new sample always lands
        ahead of the cursor: it extends the curve without moving the part
        already on screen. The scan runs backwards from the newest sample,
        which is where the cursor always is.
        """
        if not self.points:
            return None
        before: PricePoint | None = None
        after: PricePoint | None = None
        for index in range(len(self.points) - 1, -1, -1):
            point = self.points[index]
            if point.timestamp_ms <= moment_ms:
                before = point
                following = index + 1
                if following < len(self.points):
                    after = self.points[following]
                break

        if before is None:
            return self.points[0].price
        if after is None or after.timestamp_ms <= before.timestamp_ms:
            return before.price
        gap = after.timestamp_ms - before.timestamp_ms
        fraction = (moment_ms - before.timestamp_ms) / gap
        return before.price + (after.price - before.price) * fraction

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

        now = int(time.time() * 1000)
        end = now - LAG_MS
        start = end - VIEW_MS
        span = float(VIEW_MS)

        points = [
            point
            for point in self.points
            if start <= point.timestamp_ms <= end
        ]
        target = self.target
        tip = self._tip if self._tip is not None else self._tip_at(end)
        reference = tip if tip is not None else (points[-1].price if points else None)
        if reference is None:
            self._message(painter, "collecting…")
            return

        values = [point.price for point in points]
        if target is not None:
            values.append(target)
        if tip is not None:
            values.append(tip)
        lo, hi = self._range(values, target if target is not None else reference)

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

        def x_of(stamp_ms: int) -> float:
            return left + min(
                1.0, max(0.0, (stamp_ms - start) / span)
            ) * (right - left)

        def y_of(price: float) -> float:
            return bottom - (price - lo) / (hi - lo) * (bottom - top)

        # Five-minute boundaries: enough context to see a window roll over.
        # Only a tick on the edge, not a full-height rule: the line stays one
        # unbroken curve across windows.
        painter.setFont(mono_font(7))
        boundary = ((start + WINDOW_MARK_MS - 1) // WINDOW_MARK_MS) * WINDOW_MARK_MS
        last_label = left - 44.0
        while boundary <= end:
            x = x_of(boundary)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(x, bottom - 3, x, bottom)
            if x - last_label >= 44.0 and x <= right - 44.0:
                painter.setPen(QColor(TEXT_FAINT))
                painter.drawText(
                    QRectF(x - 18, bottom + 1, 36, 13),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    datetime.fromtimestamp(
                        boundary / 1000, tz=timezone.utc
                    ).strftime("%H:%M"),
                )
                last_label = x
            boundary += WINDOW_MARK_MS

        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(right - 44, bottom + 1, 44, 13),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            datetime.fromtimestamp(end / 1000, tz=timezone.utc).strftime("%H:%M"),
        )

        # The line: the samples inside the view, plus the eased live tip.
        # Rounded between samples so a one-tick spike bends instead of forming
        # the hard vertical corner that made the edge look like it jumped.
        series: list[tuple[int, float]] = [
            (point.timestamp_ms, point.price) for point in points
        ]
        if tip is not None and (not series or series[-1][0] < end):
            series.append((end, tip))

        above = target is not None and reference >= target
        color = (UP if above else DOWN) if target is not None else ACCENT

        path = smooth_path(
            [(x_of(stamp), y_of(price)) for stamp, price in series]
        )

        # The target and the shaded gap belong to the current window only:
        # older windows had a different opening price, so shading them against
        # this one would be a lie.
        if target is not None:
            target_y = y_of(target)
            window = [
                (stamp, price)
                for stamp, price in series
                if stamp >= market.start_ms
            ]
            if window:
                fill = QPainterPath(
                    smooth_path(
                        [(x_of(stamp), y_of(price)) for stamp, price in window]
                    )
                )
                fill.lineTo(x_of(window[-1][0]), target_y)
                fill.lineTo(x_of(window[0][0]), target_y)
                fill.closeSubpath()
                painter.save()
                painter.setClipRect(
                    QRectF(left, top, right - left, max(0.0, target_y - top))
                )
                painter.fillPath(fill, _alpha(UP, 30))
                painter.restore()
                painter.save()
                painter.setClipRect(
                    QRectF(
                        left,
                        target_y,
                        right - left,
                        max(0.0, bottom - target_y),
                    )
                )
                painter.fillPath(fill, _alpha(DOWN, 30))
                painter.restore()

            seg_start = max(start, market.start_ms)
            seg_end = min(end, market.end_ms if market.end_ms > 0 else end)
            if seg_end > seg_start:
                painter.setPen(QPen(QColor(AMBER), 1, Qt.PenStyle.DashLine))
                painter.drawLine(
                    x_of(seg_start), target_y, x_of(seg_end), target_y
                )
                if x_of(seg_end) - x_of(seg_start) > 70:
                    painter.setFont(mono_font(7))
                    painter.setPen(QColor(AMBER))
                    painter.drawText(
                        QRectF(x_of(seg_end) - 90, target_y - 13, 88, 12),
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter,
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
        painter.drawEllipse(QPointF(x_of(end), y_of(reference)), 2.6, 2.6)

        # The side and the gap in the header: the answer to the market's
        # question, not just the price.
        painter.setFont(mono_font(8, bold=True))
        painter.setPen(QColor(color))
        if target is not None and target > 0:
            delta = (reference - target) / target * 100.0
            text = f"{'ABOVE' if above else 'BELOW'} {format_delta(delta)}"
        else:
            text = f"{reference:,.1f}"
        painter.drawText(
            QRectF(left, 0, right - left, 14),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _range(
        self, values: list[float], target: float
    ) -> tuple[float, float]:
        """Ease the y-range toward the visible data instead of snapping.

        The range still leaves the target clear of the edges, and it can shrink
        again once an old extreme scrolls out of view — otherwise an hour of
        history would flatten the line to nothing.
        """
        low = min(values)
        high = max(values)
        pad = max((high - low) * 0.18, abs(target) * 0.00025, 1.0)
        lo = low - pad
        hi = high + pad
        if self._lo is None:
            self._lo, self._hi = lo, hi
        else:
            self._lo += (lo - self._lo) * EASE_RANGE
            self._hi += (hi - self._hi) * EASE_RANGE
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

        # -- latency --
        # Above the tiles, on the left: the venue's own round trip, next to
        # the market it belongs to rather than in the Hyperliquid top bar.
        delay = QHBoxLayout()
        delay.setContentsMargins(0, 0, 0, 0)
        delay.setSpacing(6)

        self.latency_label = QLabel("PM DELAY ● —")
        self.latency_label.setFont(mono_font(8, bold=True))
        self.latency_label.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;"
        )
        self.latency_label.setToolTip(
            "WebSocket ping/pong round trip to Polymarket's CLOB"
        )
        delay.addWidget(self.latency_label)
        delay.addStretch(1)

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
        self.return_value = self._stat(stats, 3, 0, "RETURN")
        self.payout_value = self._stat(stats, 3, 1, "PER $100")
        self.return_value.setToolTip(
            "Profit if the selected outcome wins, bought at its ask."
        )
        self.payout_value.setToolTip(
            "Cash returned per $100 staked on the selected outcome."
        )
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
        self.body.addLayout(delay)
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
            self._selected = 0
            self._last_sample = 0
            self.tape.clear()
            self.depth_value.setText("—")
            self.spread_value.setText(
                format_cents(market.spread) if market.spread > 0 else "—"
            )
        # The price line keeps rolling across rollovers. Only the book, the
        # tape and the target segment belong to one window.
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
        self._refresh_earning()
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
        """Record BTC once a second for the reference chart.

        The value is eased from the previous sample, so a single tick that
        jumps and comes back reads as a bend in the line instead of a needle.
        Only consecutive samples are eased: after a gap the first sample is
        taken as-is, or the line would drag toward a stale backfill.
        """
        if self.market is None:
            return
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_sample < SAMPLE_EVERY_MS:
            return
        self._last_sample = now_ms
        value = float(price)
        if self.points and now_ms - self.points[-1].timestamp_ms <= (
            SAMPLE_EVERY_MS * 2
        ):
            value = self.points[-1].price + (value - self.points[-1].price) * SMOOTH
        self.points.append(PricePoint(now_ms, value))
        del self.points[:-MAX_POINTS]
        self.price_chart.set_data(self.points, self.target)

    def _update_delta(self, price: float) -> None:
        """Above/below the target, in percent, for the header readouts."""
        target = self.target
        if target is None or target <= 0:
            return
        delta = (price - target) / target * 100.0
        color = UP if delta >= 0 else DOWN
        self._set_text(self.move_value, format_delta(delta))
        self.move_value.setStyleSheet(
            f"color: {color}; background: transparent;"
        )
        self.btc_value.setStyleSheet(
            f"color: {color}; background: transparent;"
        )
        if abs(delta) < 0.005:
            self.move_value.setToolTip("At the target (less than 0.01%)")
        else:
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

    def set_latency(self, milliseconds: float, color: str = TEXT_MUTED) -> None:
        """Polymarket's own round trip, shown above its tiles."""
        self._set_text(self.latency_label, f"PM DELAY ● {milliseconds:.0f} ms")
        self.latency_label.setStyleSheet(
            f"color: {color}; background: transparent;"
        )

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
        self._refresh_earning()

    def _refresh_earning(self) -> None:
        """What the selected outcome pays, at the price you could actually pay.

        A winning binary share is worth $1.00, so the price alone fixes both
        the multiple and the profit: 64 cents returns $1.56, or +56%.

        The live book comes first. Gamma's best ask is a snapshot from when the
        market was listed and can be tens of cents away late in the window; a
        one-sided book falls back to the live mid, and only a market with no
        book at all uses Gamma's quote.
        """
        if self.market is None or self._selected >= len(self.market.outcomes):
            return
        outcome = self.market.outcomes[self._selected]
        tile = self.up_tile if self._selected == 0 else self.down_tile
        book = self.books.get(outcome.token_id)
        if book is not None and book.best_ask is not None:
            cost = book.best_ask
        elif tile.price is not None:
            cost = tile.price
        else:
            cost = outcome.best_ask
        earning = binary_return(cost)
        if earning is None:
            self._set_text(self.return_value, "—")
            self._set_text(self.payout_value, "—")
            return
        multiple, percent = earning
        self._set_text(self.return_value, f"+{percent:,.0f}%")
        self._set_text(self.payout_value, f"${multiple * 100:,.0f}")
        self.return_value.setStyleSheet(f"color: {UP}; background: transparent;")
        self.payout_value.setStyleSheet(f"color: {TEXT}; background: transparent;")
        self.return_value.setToolTip(
            f"{outcome.name} at {format_cents(cost)}: profit if it wins."
        )
        self.payout_value.setToolTip(
            f"Cash back per $100 staked on {outcome.name}."
        )
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
