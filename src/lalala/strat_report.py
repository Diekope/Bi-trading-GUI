"""The right rail: what the rule did, and what to compare it to.

Five numbers in two rows — PnL, Sharpe, max drawdown, trades, win rate — and
under them three curves drawn as return since the start: the **strategy**, a
**random buy** version of it and **buy and hold**, with the legend below.

Everything is **return**, not a balance. Over a long span buy and hold
compounds many times over while a rule that is in and out of the market barely
moves; in dollars the first would flatten the other two into the axis.

The numbers come from `lalala.formula_eval.backtest` over the tail of the
newest year on disk. `tp` and `sl` are this tile's own defaults, since the
run's parameters live in the other window, and nothing is written or fetched.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.candles import candle_file, tail_rows
from lalala.cards import mono_font
from lalala.formula_eval import backtest
from lalala.panels import Card
from lalala.theme import ACCENT, BAND, BORDER, TEXT, TEXT_FAINT, TEXT_MUTED, UP, DOWN

# Bars per displayed slot, and how much history to keep out of sight.
FACTOR = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
VISIBLE = 1200
WARMUP = 200

# This tile's own defaults, since the run's parameters live elsewhere.
PREVIEW_TP = 2.0
PREVIEW_SL = 1.0

# Amber is the strategy, indigo the random-buy stand-in, grey buy and hold.
STRATEGY_COLOUR = ACCENT
RANDOM_COLOUR = BAND
HOLD_COLOUR = TEXT_MUTED

MIN_SPAN = 0.4  # percent; never let the scale collapse to a flat line
PAD = 0.08


@dataclass(frozen=True)
class Bar:
    stamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def compact(bars: list[Bar], factor: int) -> list[Bar]:
    """Group bars `factor`-to-one: first open, last close, extremes kept."""
    if factor <= 1:
        return list(bars)
    out: list[Bar] = []
    for start in range(0, len(bars), factor):
        group = bars[start : start + factor]
        out.append(
            Bar(
                group[0].stamp,
                group[0].open,
                max(bar.high for bar in group),
                min(bar.low for bar in group),
                group[-1].close,
                sum(bar.volume for bar in group),
            )
        )
    return out


def latest_year(now: int = 2026) -> int | None:
    """The newest year with a candle file, or None when the store is empty."""
    for year in range(now, 2016, -1):
        if candle_file(year).exists():
            return year
    return None


def load_bars(
    resolution: str = "1h",
    visible: int = VISIBLE,
    warmup: int = WARMUP,
) -> tuple[list[Bar], int | None]:
    """The tail of the newest year, compacted to `resolution`."""
    year = latest_year()
    if year is None:
        return [], None
    factor = FACTOR.get(resolution, 1)
    rows = tail_rows(candle_file(year), (visible + warmup) * factor)
    bars = [Bar(*row) for row in rows]
    return compact(bars, factor), year


def _returns(curve: list[float]) -> list[float]:
    if not curve or curve[0] <= 0:
        return []
    first = curve[0]
    return [(value / first - 1.0) * 100.0 for value in curve]


class CurveChart(QWidget):
    """The three return curves, drawn against a scale that fits the two rules."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.report = None
        self.message = "nothing to show yet"
        self.setMinimumHeight(140)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_report(self, report) -> None:
        self.report = report
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())
        left, right = 52.0, width - 8.0
        top, bottom = 12.0, height - 10.0
        if right - left < 40 or bottom - top < 30:
            return

        report = self.report
        if report is None or not report.strategy:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        strategy = _returns(report.strategy)
        random_buy = _returns(report.random)
        hold = _returns(report.hold)
        # The scale follows the two rules; buy and hold may run past it.
        low = min(strategy + random_buy + [0.0])
        high = max(strategy + random_buy + [0.0])
        span = max(high - low, MIN_SPAN)
        low -= span * PAD
        high += span * PAD

        points = max(1, len(strategy) - 1)

        def x_of(index: int) -> float:
            return left + (right - left) * index / points

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        painter.setFont(mono_font(7))
        for step in range(3):
            value = low + (high - low) * step / 2.0
            y = y_of(value)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(QPointF(left, y), QPointF(right, y))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, y - 7, left - 6, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:+,.1f}%",
            )

        # Buy and hold first, then random-buy, then the strategy on top.
        for curve, colour, style, weight in (
            (hold, HOLD_COLOUR, Qt.PenStyle.DashLine, 1.0),
            (random_buy, RANDOM_COLOUR, Qt.PenStyle.SolidLine, 1.2),
            (strategy, STRATEGY_COLOUR, Qt.PenStyle.SolidLine, 1.6),
        ):
            if len(curve) < 2:
                continue
            painter.setPen(QPen(QColor(colour), weight, style))
            painter.drawPolyline(
                [QPointF(x_of(i), y_of(v)) for i, v in enumerate(curve)]
            )

        if hold and hold[-1] > high:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(right - 170, top - 2, 170, 13),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "buy & hold is off the top",
            )


def _percent(value: float) -> str:
    return f"{value * 100:+,.2f}%"


class ReportTile(Card):
    """The rule's numbers in two rows, then its curve against two others."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("RESULTS", self)
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        self.note = QLabel("no rule yet", self)
        self.note.setObjectName("hintLabel")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)

        # Five numbers, two rows: PnL, Sharpe, max drawdown, then the two
        # counting ones.
        self._metrics: list[tuple[QLabel, QLabel]] = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        for index, caption in enumerate(
            ("PnL", "Sharpe", "Max DD", "Trades", "Win rate")
        ):
            row, column = divmod(index, 3)
            label = QLabel(caption, self)
            label.setObjectName("fieldLabel")
            value = QLabel("—", self)
            value.setObjectName("metricValue_text")
            value.setFont(mono_font(9, bold=True))
            grid.addWidget(label, row * 2, column)
            grid.addWidget(value, row * 2 + 1, column)
            self._metrics.append((label, value))
        for column in range(3):
            grid.setColumnStretch(column, 1)
        self.body.addLayout(grid)

        self.chart = CurveChart(self)
        self.body.addWidget(self.chart, 1)

        # The legend reads along the bottom, under the lines it names.
        legend = QHBoxLayout()
        legend.setContentsMargins(0, 0, 0, 0)
        legend.setSpacing(10)
        self.legend: dict[str, QLabel] = {}
        for key, caption in (
            ("strategy", "strategy"),
            ("random", "random buy"),
            ("hold", "buy & hold"),
        ):
            label = QLabel(caption, self)
            label.setObjectName(f"legend_{key}")
            label.setFont(mono_font(8, bold=True))
            legend.addWidget(label)
            self.legend[key] = label
        legend.addStretch(1)
        self.body.addLayout(legend)

        self.entry_rule = None
        self.exit_rule = None
        self.resolution = "1h"
        self.tp = PREVIEW_TP
        self.sl = PREVIEW_SL

    # -- what to show ------------------------------------------------------

    def configure(self, entry, exit_, resolution: str | None = None) -> None:
        """Take the rules and the bar, then show them once."""
        self.entry_rule = entry
        self.exit_rule = exit_
        if resolution is not None:
            self.resolution = resolution
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        bars, year = load_bars(self.resolution)
        if not bars:
            self._clear("no candles on disk — download history in the backtest window")
            return
        if self.entry_rule is None or self.entry_rule.condition is None:
            self._clear(f"{year} · {self.resolution} — no entry rule yet")
            return

        report = backtest(
            bars,
            self.entry_rule,
            self.exit_rule,
            tp=self.tp,
            sl=self.sl,
        )
        self.note.setText(
            f"{year} · {self.resolution} · {len(bars):,} bars"
            f" · tp {self.tp:g} / sl {self.sl:g}"
        )
        self.chart.set_report(report)
        self._show_metrics(report)
        self._show_legend(report)

    def _clear(self, message: str) -> None:
        self.note.setText(message)
        self.chart.set_report(None)
        self.chart.message = "write an entry rule to see it here"
        for _, value in self._metrics:
            value.setText("—")
        for key, caption in (
            ("strategy", "strategy"),
            ("random", "random buy"),
            ("hold", "buy & hold"),
        ):
            self.legend[key].setText(caption)

    def _show_metrics(self, report) -> None:
        rows = [
            (
                _percent(report.pnl),
                "accent" if report.pnl >= 0 else "down",
            ),
            (
                f"{report.sharpe:,.2f}" if report.trades else "—",
                "accent" if report.sharpe > 1 else "muted",
            ),
            (
                _percent(report.max_drawdown),
                "down" if report.max_drawdown < 0 else "muted",
            ),
            (f"{report.trades:,}", "text"),
            (
                f"{report.win_rate * 100:,.0f}%" if report.trades else "—",
                "text",
            ),
        ]
        for (_, value), (text, role) in zip(self._metrics, rows):
            if value.text() != text:
                value.setText(text)
            if value.property("role") != role:
                value.setProperty("role", role)
                value.setObjectName(f"metricValue_{role}")
                style = value.style()
                style.unpolish(value)
                style.polish(value)

    def _show_legend(self, report) -> None:
        for key, name, curve in (
            ("strategy", "strategy", report.strategy),
            ("random", "random buy", report.random),
            ("hold", "buy & hold", report.hold),
        ):
            percent = report.return_of(curve) * 100
            self.legend[key].setText(f"{name} {percent:+,.2f}%")
        self.legend["strategy"].setStyleSheet(f"color: {STRATEGY_COLOUR};")
        self.legend["random"].setStyleSheet(f"color: {RANDOM_COLOUR};")
        self.legend["hold"].setStyleSheet(f"color: {HOLD_COLOUR};")


__all__ = [
    "Bar",
    "CurveChart",
    "FACTOR",
    "PREVIEW_SL",
    "PREVIEW_TP",
    "ReportTile",
    "VISIBLE",
    "compact",
    "latest_year",
    "load_bars",
]
