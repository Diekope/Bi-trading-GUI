"""The playback tile: candles rolling through a backtest, numbers live.

This is the *preview* of a run, not a run. It walks a series of candles one at
a time, so the chart scrolls the way a live chart does, and keeps a light
long-only simulation on top: one position at a time, take profit and stop loss
from the parameter tile, a fee each way. Every figure above the chart is
recomputed from that walk.

Two things are deliberately provisional:

* The **entry rule** is a placeholder — enter long when a candle closes above
  the previous close. The real rule belongs to its own tile.
* The candles come from the local store when the span has any, and from a
  fixed-seed walk otherwise. The subtitle says which.

Fills are the optimistic kind: the stop and the target are both checked
against a candle's range, so if one candle touches both, the target wins.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from lalala.candles import candle_file
from lalala.cards import mono_font
from lalala.panels import Card
from lalala.theme import (
    ACCENT,
    BORDER,
    DOWN,
    PANEL_ALT,
    TEXT_FAINT,
    TEXT_MUTED,
    UP,
)

# Bars the loop walks before it starts over, and how long each one is on screen.
BARS_TO_PLAY = 400
STEP_MS = 90
FRAME_MS = 30
# How fast the price window chases the data. Lower is calmer; the tile is
# unreadable when the scale snaps on every new extreme.
EASE_RANGE = 0.14
# Never read more than this from a file, whatever the resolution needs.
MAX_READ = 48_000
FACTOR = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

# The metric row wraps like the other galleries.
WIDE_METRICS = 6
NARROW_METRICS = 4
WIDE_AT = 520

SAMPLE_SEED = 11


@dataclass(frozen=True)
class Candle:
    stamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


# -- series ----------------------------------------------------------------


def aggregate(candles: list[Candle], factor: int) -> list[Candle]:
    """Compact bars `factor`-to-one: first open, last close, extremes kept."""
    if factor <= 1:
        return list(candles)
    bars: list[Candle] = []
    for start in range(0, len(candles), factor):
        group = candles[start : start + factor]
        if not group:
            continue
        bars.append(
            Candle(
                stamp=group[0].stamp,
                open=group[0].open,
                high=max(bar.high for bar in group),
                low=min(bar.low for bar in group),
                close=group[-1].close,
                volume=sum(bar.volume for bar in group),
            )
        )
    return bars


def _read_head(path, limit: int) -> list[Candle]:
    """The first `limit` data rows of a store file, header skipped.

    A pair's opening minutes carry no trades — BTCUSDT's first bar is flat at
    its listing price with zero volume, and a few more follow. They are
    skipped so the walk starts where the market does; zero-volume bars later
    on are real quiet minutes and are kept.
    """
    rows: list[Candle] = []
    started = False
    try:
        with path.open() as handle:
            next(handle, None)
            for line in handle:
                parts = line.rstrip("\n").split(",")
                if len(parts) < 6:
                    continue
                try:
                    bar = Candle(
                        stamp=int(parts[0]),
                        open=float(parts[1]),
                        high=float(parts[2]),
                        low=float(parts[3]),
                        close=float(parts[4]),
                        volume=float(parts[5]),
                    )
                except ValueError:
                    continue
                if not started and (bar.high <= bar.low or bar.volume <= 0):
                    continue
                started = True
                rows.append(bar)
                if len(rows) >= limit:
                    break
    except OSError:
        return []
    return rows


def load_candles(
    years: list[int], resolution: str, limit: int = BARS_TO_PLAY
) -> list[Candle]:
    """Play the span's most recent year on disk, compacted as asked.

    The latest year, not the earliest: early BTCUSDT minutes are so thin that
    most bars have no range at all, which makes for a dull thing to watch.
    """
    factor = FACTOR.get(resolution, 1)
    need = min(limit * factor, MAX_READ)
    for year in sorted(years, reverse=True):
        raw = _read_head(candle_file(year), need)
        if raw:
            return aggregate(raw, factor)[:limit]
    return []


def sample_candles(count: int = BARS_TO_PLAY, seed: int = SAMPLE_SEED) -> list[Candle]:
    """A fixed-seed walk, for when the store has nothing to show."""
    rng = random.Random(seed)
    price = 78_000.0
    stamp = 1_700_000_000_000
    bars: list[Candle] = []
    for _ in range(count):
        open_ = price
        close = open_ * (1.0 + rng.gauss(0.0, 0.0018))
        wick = abs(rng.gauss(0.0, 0.0009)) * open_
        bars.append(
            Candle(
                stamp=stamp,
                open=open_,
                high=max(open_, close) + wick,
                low=min(open_, close) - wick,
                close=close,
                volume=abs(rng.gauss(4.0, 2.0)) + 0.1,
            )
        )
        price = close
        stamp += 60_000
    return bars


# -- the walk --------------------------------------------------------------


class Playback:
    """One position at a time, walked candle by candle."""

    def __init__(
        self,
        candles: list[Candle],
        capital: float = 10_000.0,
        tp: float = 2.0,
        sl: float = 1.0,
        position: float = 10.0,
        sizing: str = "balance",
        max_cash: float = 2_000.0,
        fee: float = 0.0006,
        max_hold: int = 90,
    ) -> None:
        self.candles = list(candles)
        self.capital = capital
        self.tp = tp
        self.sl = sl
        self.position = position
        self.sizing = sizing
        self.max_cash = max_cash
        self.fee = fee
        self.max_hold = max_hold
        self.reset()

    # -- state -------------------------------------------------------------

    def reset(self) -> None:
        self.index = 0
        self.cash = self.capital
        self.qty = 0.0
        self.entry_price = 0.0
        self.entry_index = 0
        self.peak = self.capital
        self.max_drawdown = 0.0
        self.max_gain = 0.0
        self.fees = 0.0
        self.trade_returns: list[float] = []
        self.streak = 0          # > 0 wins in a row, < 0 losses in a row
        self.best_win = 0
        self.worst_loss = 0
        self.markers: list[tuple[int, str, float]] = []
        self.bars_in_market = 0
        self.entry_cost = 0.0

    @property
    def done(self) -> bool:
        return self.index >= len(self.candles)

    @property
    def in_position(self) -> bool:
        return self.qty > 0.0

    def close_price(self) -> float:
        if not self.candles:
            return 0.0
        return self.candles[min(self.index, len(self.candles) - 1)].close

    @property
    def equity(self) -> float:
        return self.cash + self.qty * self.close_price()

    def drawdown(self) -> float:
        if self.peak <= 0:
            return 0.0
        return self.equity / self.peak - 1.0

    @property
    def trades(self) -> int:
        return len(self.trade_returns)

    @property
    def win_rate(self) -> float:
        if not self.trade_returns:
            return 0.0
        return sum(1 for value in self.trade_returns if value > 0) / len(
            self.trade_returns
        )

    @property
    def exposure(self) -> float:
        walked = max(1, self.index)
        return min(1.0, self.bars_in_market / walked)

    # -- stepping ----------------------------------------------------------

    def step(self) -> None:
        """Advance one candle: manage the open trade, else look for one."""
        if self.done:
            return
        candle = self.candles[self.index]
        previous = self.candles[self.index - 1] if self.index else candle

        if self.in_position:
            self.bars_in_market += 1
            self._manage(candle)
        elif self._wants_long(candle, previous):
            self._enter(candle)

        self.peak = max(self.peak, self.equity)
        self.max_drawdown = min(self.max_drawdown, self.drawdown())
        self.max_gain = max(self.max_gain, self.equity / self.capital - 1.0)
        self.index += 1

    def advance(self) -> None:
        """One tick of the loop: step, and start over at the end."""
        if self.done:
            self.reset()
        self.step()

    def _wants_long(self, candle: Candle, previous: Candle) -> bool:
        """Placeholder entry: the candle closed above the one before it."""
        return self.index > 0 and candle.close > previous.close

    def _budget(self) -> float:
        deployable = min(self.cash, self.max_cash)
        if self.sizing == "fixed":
            return max(0.0, min(self.position, deployable))
        return deployable * max(0.0, self.position) / 100.0

    def _enter(self, candle: Candle) -> None:
        notional = self._budget()
        if notional <= 0.0 or candle.close <= 0.0:
            return
        cost = notional * self.fee
        self.qty = notional / candle.close
        self.cash -= notional + cost
        self.fees += cost
        self.entry_price = candle.close
        self.entry_index = self.index
        self.entry_cost = notional + cost
        self.markers.append((self.index, "in", candle.close))

    def _manage(self, candle: Candle) -> None:
        target = self.entry_price * (1.0 + self.tp / 100.0)
        stop = self.entry_price * (1.0 - self.sl / 100.0)
        price: float | None = None
        if self.tp > 0 and candle.high >= target:
            price = target
        elif self.sl > 0 and candle.low <= stop:
            price = stop
        elif self.index - self.entry_index >= self.max_hold:
            price = candle.close
        if price is None:
            return
        proceeds = self.qty * price
        cost = proceeds * self.fee
        self.cash += proceeds - cost
        self.fees += cost
        invested = self.entry_cost
        self.qty = 0.0
        self.entry_cost = 0.0
        self.markers.append((self.index, "out", price))
        self._book(proceeds - cost, invested)

    def _book(self, proceeds: float, invested: float) -> None:
        """Record the trade's return and move the streak counters."""
        result = proceeds / invested - 1.0 if invested else 0.0
        self.trade_returns.append(result)
        if result > 0:
            self.streak = self.streak + 1 if self.streak > 0 else 1
            self.best_win = max(self.best_win, self.streak)
        else:
            self.streak = self.streak - 1 if self.streak < 0 else -1
            self.worst_loss = min(self.worst_loss, self.streak)

    # -- readouts ----------------------------------------------------------

    def metrics(self) -> list[tuple[str, str, str]]:
        """(caption, value, colour role) — the row above the chart."""
        pnl = self.equity / self.capital - 1.0
        streak = "—"
        if self.streak > 0:
            streak = f"W{self.streak}"
        elif self.streak < 0:
            streak = f"L{abs(self.streak)}"
        return [
            ("PnL", f"{pnl * 100:+,.2f}%", "accent" if pnl >= 0 else "down"),
            ("Equity", _money(self.equity), "text"),
            ("Cash", _money(self.cash), "muted"),
            (
                "Drawdown",
                f"{self.drawdown() * 100:,.2f}%",
                "down" if self.drawdown() < 0 else "muted",
            ),
            ("Max DD", f"{self.max_drawdown * 100:,.2f}%", "down"),
            ("Max gain", f"{self.max_gain * 100:+,.2f}%", "accent"),
            ("Streak", streak, "accent" if self.streak > 0 else "text"),
            ("Best W", f"{self.best_win}", "accent"),
            ("Worst L", f"{abs(self.worst_loss)}", "down"),
            ("Trades", f"{self.trades}", "text"),
            ("Win rate", f"{self.win_rate * 100:,.0f}%", "text"),
            ("Fees", _money(self.fees), "muted"),
        ]


def _money(value: float) -> str:
    return f"${value:,.0f}"


class CandlePlayer(QWidget):
    """Candles scrolling under a playhead, with the entries marked."""

    def __init__(self, playback: Playback, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.playback = playback
        # How far the loop has travelled toward the next candle, 0..1. The
        # chart slides by this much every frame, so it scrolls like a live one
        # instead of hopping a whole slot at a time.
        self.offset = 0.0
        # The price window eases, so filling the tile does not make it jump.
        self._low: float | None = None
        self._high: float | None = None
        self.message = "press Run to start the backtest"
        self.setMinimumHeight(140)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_offset(self, offset: float) -> None:
        self.offset = max(0.0, min(0.999, offset))

    def reset_range(self) -> None:
        self._low = None
        self._high = None

    def visible_count(self, width: float) -> int:
        return max(30, int((width - 62.0) / 7.0))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        left = 54.0
        right = width - 8.0
        top = 18.0
        bottom = height - 16.0
        if right - left < 40 or bottom - top < 30:
            return

        if not self.playback.candles:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        room = self.visible_count(width)
        # The walk can sit one past the end for a frame before it wraps.
        last = min(self.playback.index, len(self.playback.candles) - 1)
        first = max(0, last - room + 1)
        window = self.playback.candles[first : last + 1]
        if not window:
            return

        low = min(bar.low for bar in window)
        high = max(bar.high for bar in window)
        pad = max((high - low) * 0.08, high * 0.0002)
        if self._low is None:
            self._low, self._high = low - pad, high + pad
        else:
            self._low += (low - pad - self._low) * EASE_RANGE
            self._high += (high + pad - self._high) * EASE_RANGE
        low, high = self._low, self._high

        slot = (right - left) / room

        def x_of(position: int) -> float:
            return left + (position - first + 0.5 - self.offset) * slot

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        # Grid, labelled in dollars.
        painter.setFont(mono_font(7))
        for step in range(3):
            value = low + (high - low) * step / 2.0
            y = y_of(value)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(left, y, right, y)
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, y - 7, left - 6, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:,.0f}",
            )

        body = max(1.0, slot * 0.6)
        for position, bar in enumerate(window, start=first):
            x = x_of(position)
            rising = bar.close >= bar.open
            painter.setPen(QPen(QColor(UP if rising else DOWN), 1))
            painter.drawLine(QPointF(x, y_of(bar.high)), QPointF(x, y_of(bar.low)))
            top_y = y_of(max(bar.open, bar.close))
            height_y = max(1.0, abs(y_of(bar.open) - y_of(bar.close)))
            painter.setBrush(QColor(UP if rising else DOWN))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(x - body / 2, top_y, body, height_y))

        # Entries and exits, so the trades are visible on the candles.
        for position, kind, price in self.playback.markers:
            if not (first <= position <= last):
                continue
            x = x_of(position)
            y = y_of(price)
            colour = QColor(ACCENT if kind == "in" else TEXT_MUTED)
            painter.setPen(QPen(colour, 1))
            painter.setBrush(colour)
            if kind == "in":
                painter.drawPolygon(
                    QPolygonF(
                        [QPointF(x, y - 6), QPointF(x - 4, y - 12), QPointF(x + 4, y - 12)]
                    )
                )
            else:
                painter.drawPolygon(
                    QPolygonF(
                        [QPointF(x, y + 6), QPointF(x - 4, y + 12), QPointF(x + 4, y + 12)]
                    )
                )

        # While a position is open, its entry price rides across the plot.
        if self.playback.in_position and self.playback.entry_price > 0:
            y = y_of(self.playback.entry_price)
            painter.setPen(QPen(QColor(PANEL_ALT), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(left, y), QPointF(right, y))

        # Times at both ends of the window, kept inside the plot.
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        for position, x, align in (
            (first, left, Qt.AlignmentFlag.AlignLeft),
            (last, right - 68.0, Qt.AlignmentFlag.AlignRight),
        ):
            bar = self.playback.candles[position]
            stamp = datetime.fromtimestamp(bar.stamp / 1000, tz=timezone.utc)
            painter.drawText(
                QRectF(x, bottom + 1, 68, 13),
                align | Qt.AlignmentFlag.AlignVCenter,
                stamp.strftime("%d %b %H:%M"),
            )


class PlaybackTile(Card):
    """The candles rolling, with the live figures above them."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Nothing runs until Run is pressed: opening the window is not a run.
        self.playback = Playback([])
        self.source = "—"
        self._launched = False
        # What the controls are set to. A change here is not a restart: it is
        # picked up the next time the run is started.
        self._wanted_years: list[int] = []
        self._wanted_resolution = "1m"
        self._wanted_params: dict | None = None

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("BACKTEST")
        title.setObjectName("tileTitle")
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.setToolTip("Start the walk over with the current span")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.run_button)
        self.body.addLayout(header)

        self.note = QLabel("idle — press Run")
        self.note.setObjectName("hintLabel")
        self.body.addWidget(self.note)

        self._metrics = QGridLayout()
        self._metrics.setContentsMargins(0, 0, 0, 0)
        self._metrics.setHorizontalSpacing(10)
        self._metrics.setVerticalSpacing(3)
        self._metric_labels: list[tuple[QLabel, QLabel]] = [
            (self._caption(""), self._value())
            for _ in self.playback.metrics()
        ]
        self._metric_columns = 0
        self._reflow_metrics(WIDE_METRICS)
        self.body.addLayout(self._metrics)

        self.player = CandlePlayer(self.playback)
        self.body.addWidget(self.player, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._elapsed = 0
        self.run_button.clicked.connect(self.restart)
        self._refresh_metrics()

    # -- the loop ----------------------------------------------------------

    def _tick(self) -> None:
        self._elapsed += FRAME_MS
        if self._elapsed >= STEP_MS:
            self._elapsed -= STEP_MS
            self.playback.advance()
            self._refresh_metrics()
        # Every frame, not every candle: this is what makes it scroll.
        self.player.set_offset(self._elapsed / STEP_MS)
        self.player.update()

    def play(self) -> None:
        self._timer.start()

    def pause(self) -> None:
        self._timer.stop()

    def playing(self) -> bool:
        return self._timer.isActive()

    def restart(self) -> None:
        """Adopt the controls and start the walk over. The only way it resets."""
        bars = load_candles(
            self._wanted_years, self._wanted_resolution, BARS_TO_PLAY
        )
        if bars:
            played = self._wanted_years[-1] if self._wanted_years else 0
            self.source = f"{played} · {self._wanted_resolution}"
        else:
            self.source = "example"
            bars = sample_candles()
        self.playback.candles = bars
        if self._wanted_params is not None:
            self._adopt_params(self._wanted_params)
        self.playback.reset()
        self._launched = True
        self._elapsed = 0
        self.player.set_offset(0.0)
        self.player.reset_range()
        self.run_button.setText("Restart")
        self._describe()
        self._refresh_metrics()
        self.player.update()
        self.play()

    # -- source ------------------------------------------------------------

    def set_source(self, years: list[int], resolution: str) -> None:
        """Remember the span. Nothing changes until the next restart."""
        self._wanted_years = list(years)
        self._wanted_resolution = resolution
        self._describe()

    def set_params(self, params: dict) -> None:
        """Remember the parameters. Nothing changes until the next restart."""
        self._wanted_params = dict(params)
        self._describe()

    def _adopt_params(self, params: dict) -> None:
        self.playback.capital = float(params["initial_capital"] or 0.0)
        self.playback.tp = float(params["tp"] or 0.0)
        self.playback.sl = float(params["sl"] or 0.0)
        self.playback.position = float(params["position"] or 0.0)
        self.playback.sizing = str(params["sizing"])
        self.playback.max_cash = float(params["cash"] or 0.0)

    def _describe(self) -> None:
        if not self._launched:
            self.note.setText("idle — press Run")
            return
        arrow = "placeholder entry rule"
        if self._wanted_years:
            ready = f"{self._wanted_years[-1]} · {self._wanted_resolution}"
            if ready == self.source:
                self.note.setText(f"looping {self.source} — {arrow}")
            else:
                self.note.setText(
                    f"looping {self.source} — ready {ready}, press Run"
                )
        else:
            self.note.setText(f"{self.source} loop — {arrow}")

    # -- layout ------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        columns = WIDE_METRICS if self.width() >= WIDE_AT else NARROW_METRICS
        if columns != self._metric_columns:
            self._reflow_metrics(columns)

    def _reflow_metrics(self, columns: int) -> None:
        for caption, value in self._metric_labels:
            self._metrics.removeWidget(caption)
            self._metrics.removeWidget(value)
        self._metric_columns = columns
        for index, (caption, value) in enumerate(self._metric_labels):
            row = index // columns * 2
            column = index % columns
            self._metrics.addWidget(caption, row, column)
            self._metrics.addWidget(value, row + 1, column)
        for column in range(WIDE_METRICS):
            self._metrics.setColumnStretch(
                column, 1 if column < columns else 0
            )

    def _refresh_metrics(self) -> None:
        if self._launched:
            rows = self.playback.metrics()
        else:
            # Nothing to report yet: the labels are there, the values are not.
            rows = [
                (title, "—", "muted")
                for title, _, _ in self.playback.metrics()
            ]
        for (caption, value), (title, text, role) in zip(
            self._metric_labels, rows
        ):
            if caption.text() != title:
                caption.setText(title)
            if value.text() != text:
                value.setText(text)
            if value.property("role") != role:
                value.setProperty("role", role)
                value.setObjectName(f"metricValue_{role}")
                style = value.style()
                style.unpolish(value)
                style.polish(value)

    # -- widgets -----------------------------------------------------------

    def _caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _value(self) -> QLabel:
        label = QLabel("")
        label.setObjectName("metricValue_text")
        label.setFont(mono_font(8, bold=True))
        return label


__all__ = [
    "BARS_TO_PLAY",
    "Candle",
    "CandlePlayer",
    "Playback",
    "PlaybackTile",
    "aggregate",
    "load_candles",
    "sample_candles",
]
