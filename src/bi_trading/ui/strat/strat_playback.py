"""The playback tile: candles rolling through a backtest, figures live.

This is the run itself. It walks the **whole selected span**, one bar at a
time, and keeps a long-only simulation on top: one position at a time, take
profit and stop loss from the parameter tile, a fee each way. Every figure
above the chart is recomputed from that walk.

The span can be years of one-minute bars, so nothing is held in memory that
does not have to be. Bars are streamed off disk, and only what the picture and
the figures need is kept:

* a rolling window of the most recent bars, for the chart;
* the most recent entries and exits, to mark on it;
* running totals, and a running mean/variance for the Sharpe.

The walk is also sped up to stay watchable: `stride` bars are consumed per
tick, chosen so a run over any amount of data takes about `WATCH_MS`. With a
few hundred bars that is one bar a tick; with years of minutes the trail
advances in bigger jumps.

The entry rule comes from the strategy tile. Fills are the optimistic kind —
the stop and the target are both read off one candle's range, so a candle that
touches both pays the target.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bi_trading.engine.formula import Formula
from bi_trading.ui.cards import mono_font
from bi_trading.ui.panels import Card
from bi_trading.ui.theme import ACCENT, DOWN, TEXT_FAINT, TEXT_MUTED, UP

from bi_trading.ui.strat.playback_data import (  # noqa: F401
    BOLLINGER_DEVIATIONS,
    BOLLINGER_PERIOD,
    CHART_BARS,
    Candle,
    ColumnSpan,
    DEFAULT_STRATEGY,
    FACTOR,
    FRAME_MS,
    MAX_MARKERS,
    MAX_READ,
    MAX_TICKS,
    SAMPLE_BARS,
    SAMPLE_SEED,
    STEP_MS,
    STRATEGIES,
    WATCH_MS,
    _SPAN_ARRAY_CACHE,
    _SPAN_CACHE,
    _compact_arrays,
    _feed_factory,
    _iter_file,
    _merge,
    _span_signature,
    _stream_chunks,
    aggregate,
    count_bars,
    iter_candles,
    load_all_candles,
    load_candles,
    load_span,
    plan_stride,
    sample_candles,
    span_columns,
    strategy_label,
    window_around,
)
from bi_trading.ui.strat.playback_session import (  # noqa: F401
    BacktestSession,
    CORE_MAX,
    ChunkRun,
    ChunkTail,
    _after_warmup,
    _random_draws,
    _walk_settings,
    bollinger_entries,
    bollinger_entries_columns,
    build_session,
    random_entries,
    walk_clamps,
)
from bi_trading.ui.strat.playback_walk import (  # noqa: F401
    Playback,
    _bollinger,
    _money,
    _slim,
    bollinger_bands,
)
from bi_trading.ui.strat import playback_control as _panels

log = logging.getLogger(__name__)

# The colour a picked trade is drawn in on the chart.
TRADE_HILITE = "#c08bff"


# How fast the price window chases the data. Lower is calmer; the tile is
# unreadable when the scale snaps on every new extreme.
EASE_RANGE = 0.14
# The metric row wraps like the other galleries.
WIDE_METRICS = 6
NARROW_METRICS = 4
WIDE_AT = 520


# How many bars each step walks. `WATCH_MS` already fits the run to the span;
# this is the watcher's own multiplier on top.
SPEEDS = ("×1", "×2", "×4", "×8")


# -- the three curves ------------------------------------------------------


class CandlePlayer(QWidget):
    """Candles scrolling under a playhead, with the entries marked."""

    def __init__(self, playback: Playback, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.playback = playback
        # How far the loop has travelled toward the next candle, 0..1. The
        # chart slides by this much every frame, so it scrolls like a live one
        # instead of hopping a whole slot at a time.
        self.offset = 0.0
        # The trade to bring out, when a row is picked in the results.
        self.trade: dict | None = None
        # A static window of candles to show instead of the live tail, so a
        # picked trade can be looked at without moving the run.
        self.view: list[Candle] | None = None
        self._view_head: int | None = None
        # The price window eases, so filling the tile does not make it jump.
        self._low: float | None = None
        self._high: float | None = None
        self.message = "press Run to start the backtest"
        self.setMinimumHeight(140)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_trade(self, trade: dict | None) -> None:
        self.trade = trade
        self.update()

    def clear_view(self) -> None:
        """Go back to the live tail."""
        self.view = None
        self._view_head = None
        self.update()

    def set_view(
        self, bars: list[Candle] | None, trade: dict | None = None
    ) -> None:
        """Show a fixed window of candles, with `trade` marked, or the live tail."""
        self.view = list(bars) if bars else None
        self.trade = trade
        self._view_head = None
        if self.view and trade is not None:
            # Where the trade's exit sits inside the window (by timestamp).
            head = None
            for index, bar in enumerate(self.view):
                if bar.stamp >= int(trade.get("out_stamp", 0)):
                    head = index
                    break
            self._view_head = head
        self.update()

    def set_offset(self, offset: float) -> None:
        self.offset = max(0.0, min(0.999, offset))

    @staticmethod
    def _position_for(bars: list[Candle], stamp: int, base: int) -> int:
        """The index (in the run's numbering) of the bar at `stamp`."""
        for index, bar in enumerate(bars):
            if bar.stamp >= int(stamp):
                return base + index
        return base + len(bars) - 1

    def reset_range(self, candles: list[Candle] | None = None) -> None:
        """Start the price window at the whole series, not at the first bar.

        Easing toward the visible slice from a single bar would leave the
        opening candles wildly zoomed until the scale caught up.
        """
        series = self.playback.recent() if candles is None else candles
        if not series:
            self._low = None
            self._high = None
            return
        low = min(bar.low for bar in series)
        high = max(bar.high for bar in series)
        pad = max((high - low) * 0.08, high * 0.0002)
        self._low, self._high = low - pad, high + pad

    def visible_count(self, width: float) -> int:
        return max(30, int((width - 62.0) / 7.0))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        # No price grid: just the candles, as wide as the tile allows.
        left = 8.0
        right = width - 8.0
        top = 18.0
        bottom = height - 16.0
        if right - left < 40 or bottom - top < 30:
            return

        viewing = self.view is not None
        bars = self.view if viewing else self.playback.recent()
        if not bars:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        room = self.visible_count(width)
        if viewing:
            # A fixed window: indices are positions in the list, and the trade
            # is centred rather than the newest candle.
            base = 0
            last = len(bars) - 1
            head = self._view_head if self._view_head is not None else last
            playhead = min(float(last), head + room / 2)
        else:
            # Absolute indices: the window is the tail of a stream, so position
            # in the list is not position in the run.
            base = self.playback.index - len(bars)
            last = base + len(bars) - 1
            playhead = last + self.offset
        slot = (right - left) / room
        first = max(base, int(-(-(playhead + 0.5 - room) // 1)))
        window = bars[first - base :]
        if not window:
            return

        low = min(bar.low for bar in window)
        high = max(bar.high for bar in window)
        pad = max((high - low) * 0.08, high * 0.0002)
        if self._low is None or self._high is None:
            self._low, self._high = low - pad, high + pad
        else:
            self._low += (low - pad - self._low) * EASE_RANGE
            self._high += (high + pad - self._high) * EASE_RANGE
            # Never let the eased range leave a candle off the plot: expand at
            # once when the window pokes out, and ease the shrink back after.
            self._low = min(self._low, low - pad)
            self._high = max(self._high, high + pad)
        low, high = self._low, self._high
        if high - low <= 0:
            # A flat stretch would divide by zero; give it a sliver of room.
            spread = max(abs(high) * 1e-4, 1e-6)
            low, high = low - spread, high + spread

        def x_of(position: int) -> float:
            return right - (playhead - position + 0.5) * slot

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        body = max(1.0, slot * 0.6)
        for position, bar in enumerate(window, start=first):
            x = x_of(position)
            if x < left - slot or x > right + slot:
                continue
            rising = bar.close >= bar.open
            painter.setPen(QPen(QColor(UP if rising else DOWN), 1))
            painter.drawLine(QPointF(x, y_of(bar.high)), QPointF(x, y_of(bar.low)))
            top_y = y_of(max(bar.open, bar.close))
            height_y = max(1.0, abs(y_of(bar.open) - y_of(bar.close)))
            painter.setBrush(QColor(UP if rising else DOWN))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(x - body / 2, top_y, body, height_y))

        # Entries and exits, so the trades are visible on the candles.
        if not viewing:
            for position, kind, price in self.playback.markers:
                x = x_of(position)
                if x < left - slot or x > right + slot:
                    continue
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

        # The picked trade, brought out in its own colour: the stretch it held,
        # a line across it, and its entry and exit prices.
        trade = self.trade
        if trade is not None:
            if viewing:
                in_at = self._position_for(bars, trade.get("in_stamp", 0), base)
                out_at = self._position_for(bars, trade.get("out_stamp", 0), base)
            else:
                in_at = trade["in_index"]
                out_at = trade["out_index"]
            x_in = x_of(in_at)
            x_out = x_of(out_at)
            y_in = y_of(trade["in_price"])
            y_out = y_of(trade["out_price"])
            band = QColor(TRADE_HILITE)
            band.setAlpha(46)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(band)
            painter.drawRect(
                QRectF(
                    min(x_in, x_out), top, abs(x_out - x_in), bottom - top
                )
            )
            painter.setPen(QPen(QColor(TRADE_HILITE), 1.5))
            painter.drawLine(QPointF(x_in, y_in), QPointF(x_out, y_out))
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(QPointF(x_in, y_in), 4, 4)
            painter.setBrush(
                QColor(UP if trade["result"] >= 0 else DOWN)
            )
            painter.drawEllipse(QPointF(x_out, y_out), 4, 4)
            painter.setFont(mono_font(7))
            painter.setPen(QColor(TRADE_HILITE))
            painter.drawText(
                QRectF(x_in - 30, y_in - 18, 60, 14),
                Qt.AlignmentFlag.AlignCenter,
                f"{trade['in_price']:,.0f}",
            )
            painter.drawText(
                QRectF(x_out - 30, y_out + 4, 60, 14),
                Qt.AlignmentFlag.AlignCenter,
                f"{trade['out_price']:,.0f}",
            )
            # A tag at the top of the band, so the pick is easy to spot.
            label = f"#{trade.get('n', 0):,}"
            centre = (x_in + x_out) / 2
            painter.setBrush(QColor(TRADE_HILITE))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(centre - 24, top - 2, 48, 13))
            painter.setPen(QColor("#0f1013"))
            painter.drawText(
                QRectF(centre - 24, top - 2, 48, 13),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

        # Times: the newest at the right edge, and the oldest only once the
        # trail has actually reached the left of the plot.
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        stamps: list[tuple[int, float, Qt.AlignmentFlag]] = [
            (last, right - 68.0, Qt.AlignmentFlag.AlignRight)
        ]
        if x_of(first) >= left - slot * 0.6:
            stamps.append((first, left, Qt.AlignmentFlag.AlignLeft))
        for position, x, align in stamps:
            if not base <= position <= last:
                continue
            bar = bars[position - base]
            stamp = datetime.fromtimestamp(bar.stamp / 1000, tz=UTC)
            painter.drawText(
                QRectF(x, bottom + 1, 68, 13),
                align | Qt.AlignmentFlag.AlignVCenter,
                stamp.strftime("%d %b %H:%M"),
            )


class PlaybackTile(Card):
    """The candles rolling, with the live figures above them."""

    advanced = Signal()
    restarted = Signal(object)
    # The walk to the end has landed (or was not needed).
    finished = Signal()
    # From the worker thread: (token, session, target, result or the error).
    _walk_ready = Signal(int, object, int, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._finish_token = 0
        self._walk_ready.connect(self._on_walk_ready)

        # Nothing runs until Run is pressed: opening the window is not a run.
        self.playback = Playback([], total=0)
        self.session: BacktestSession | None = None
        self.source = "—"
        self._launched = False
        # What the controls are set to. A change here is not a restart: it is
        # picked up the next time the run is started.
        self._wanted_years: list[int] = []
        self._wanted_resolution = "1m"
        self._wanted_params: dict | None = None
        self._wanted_rule = DEFAULT_STRATEGY
        self._speed = 1
        self._entry_formula: Formula | None = None
        self._entry_fields: tuple | None = None
        self._saved_name = ""
        self._saved_entry = ""
        self._saved_exit = ""
        self._exit_formula: Formula | None = None
        self._wanted_side = "long"
        self._short_formula: Formula | None = None
        self._saved_short = ""
        self._model = ""

        # Header: the title over its status line, then Restart, a speed picker
        # and the Run / Pause button, as in the mock.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        title = QLabel("BACKTEST")
        title.setObjectName("tileTitle")
        titles.addWidget(title)
        self.note = QLabel("idle — press Run")
        self.note.setObjectName("hintLabel")
        titles.addWidget(self.note)
        header.addLayout(titles)
        header.addStretch(1)

        self.restart_button = QPushButton("Restart")
        self.restart_button.setObjectName("restartButton")
        self.restart_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restart_button.setToolTip(
            "Start the walk over with the current span (R)"
        )
        self.restart_button.clicked.connect(self.restart)
        header.addWidget(
            self.restart_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        self.speed = QComboBox()
        self.speed.setObjectName("speedSelect")
        self.speed.addItems(SPEEDS)
        self.speed.setFixedWidth(64)
        self.speed.setToolTip("How many candles each step walks")
        self.speed.currentTextChanged.connect(self._speed_changed)
        header.addWidget(self.speed, 0, Qt.AlignmentFlag.AlignVCenter)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.setToolTip("Start, pause and resume the walk (Space)")
        self.run_button.clicked.connect(self._on_run)
        header.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(header)

        # Progress: the bar and the bar count, as in the mock.
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setObjectName("playbackProgress")
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress_label = QLabel("—")
        self.progress_label.setObjectName("progressCount")
        self.progress_label.setFont(mono_font(7))
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.progress_label)
        self.body.addLayout(progress_row)

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
        for caption, value in self._metric_labels:
            if caption.text() == "Sharpe":
                value.setToolTip(
                    "Mean over deviation of the per-bar book returns, "
                    "not annualised"
                )

        self.player = CandlePlayer(self.playback)
        self.body.addWidget(self.player, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._elapsed = 0
        # A one-shot to reveal a picked trade after the click has settled.
        self._pending_trade: dict | None = None
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.setInterval(0)
        self._reveal_timer.timeout.connect(self._reveal_pending)
        self._refresh_metrics()
        self._refresh_progress()

    def set_trade(self, trade: dict | None) -> None:
        """Bring a picked trade out on the chart, once the click has settled.

        Deferred to a timer the tile owns: revealing a trade may rewind the
        walk and refresh the results, and doing that inside the table's
        selection handler re-enters the table and can crash Qt.
        """
        self._pending_trade = trade
        self._reveal_timer.start()

    def _reveal_pending(self) -> None:
        self._reveal_trade(self._pending_trade)

    def _reveal_trade(self, trade: dict | None) -> None:
        """Show a picked trade on a fixed window of candles.

        It does **not** move the walk: a window of candles around the trade is
        read on demand and shown in place of the live tail, so a trade before
        the last candles can be looked at without cutting the run short.
        """
        if trade is None:
            self.player.set_view(None, None)
            return
        bars = window_around(
            self._wanted_years,
            self._wanted_resolution,
            int(trade.get("in_stamp", 0)),
        )
        if bars:
            self.player.set_view(bars, trade)
        else:
            self.player.set_trade(trade)
        self.player.update()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Stop the walk before the tile goes, so no tick lands on a dead widget."""
        self._timer.stop()
        self._reveal_timer.stop()
        super().closeEvent(event)

    # -- the loop ----------------------------------------------------------

    # Moved to playback_control.py; each is still a method of this class.
    _speed_changed = _panels.speed_changed
    _tick = _panels.tick
    play = _panels.play
    pause = _panels.pause
    playing = _panels.playing
    _on_run = _panels.on_run
    finish = _panels.finish
    show_saved = _panels.show_saved
    _on_walk_ready = _panels.on_walk_ready
    _landed = _panels.landed
    restart = _panels.restart
    set_source = _panels.set_source
    set_params = _panels.set_params
    set_strategy = _panels.set_strategy
    rule_key = _panels.rule_key
    saved_entry = _panels.saved_entry
    saved_name = _panels.saved_name
    saved_exit = _panels.saved_exit
    side = _panels.side
    saved_short = _panels.saved_short
    saved_model = _panels.saved_model
    set_saved_strategy = _panels.set_saved_strategy
    _describe = _panels.describe











    # -- source ------------------------------------------------------------












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

    def _refresh_progress(self) -> None:
        """The bar and the candle count."""
        play = self.playback
        if self._launched and play.total:
            self.progress.setValue(int(play.progress * 1000))
            self.progress_label.setText(
                f"{play.progress * 100:,.0f}% · "
                f"{play.index:,} / {play.total:,} candles"
            )
        else:
            self.progress.setValue(0)
            self.progress_label.setText("—")

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
            self._metric_labels, rows, strict=False
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
    "DEFAULT_STRATEGY",
    "STRATEGIES",
    "BacktestSession",
    "Candle",
    "CandlePlayer",
    "Playback",
    "PlaybackTile",
    "aggregate",
    "bollinger_bands",
    "build_session",
    "count_bars",
    "iter_candles",
    "load_candles",
    "plan_stride",
    "sample_candles",
    "strategy_label",
]
