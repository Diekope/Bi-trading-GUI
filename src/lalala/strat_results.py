"""The results tile: the equity curve and the headline numbers.

Nothing here comes from a real run yet — there is no engine to run. The tile
shows a **sample**, generated from a fixed seed, so the shape of the output can
be judged before it is built: an equity curve for a one-position-at-a-time
strategy, buy & hold drawn faintly behind it, where the worst drawdown
happened, and a row of metrics computed from that same sample (so the numbers
and the line always agree).

The sample obeys the rules that are already fixed: one position at a time,
fees charged on both sides, no trading while flat.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from lalala.cards import mono_font
from lalala.panels import Card
from lalala.theme import ACCENT, BORDER, TEXT, TEXT_FAINT, TEXT_MUTED

CAPITAL = 10_000.0
SAMPLE_DAYS = 180
SAMPLE_SEED = 5
# Matches the hard-coded cost assumption: a fee each way, and a little slippage.
FEE_PER_SIDE = 0.0006

# The metric row wraps to keep every caption readable on a narrow tile.
WIDE_METRICS = 5
NARROW_METRICS = 3
WIDE_AT = 520


@dataclass(frozen=True)
class SampleRun:
    """A made-up run. Every number the tile shows is derived from here."""

    days: int
    equity: tuple[float, ...]
    benchmark: tuple[float, ...]
    trade_returns: tuple[float, ...]
    trade_holds: tuple[int, ...]
    exposure: float

    @property
    def total_return(self) -> float:
        return self.equity[-1] / self.equity[0] - 1.0

    @property
    def benchmark_return(self) -> float:
        return self.benchmark[-1] / self.benchmark[0] - 1.0

    def drawdown(self) -> tuple[float, int]:
        """(worst peak-to-trough, the day it hit bottom)."""
        peak = self.equity[0]
        worst = 0.0
        worst_day = 0
        for day, value in enumerate(self.equity):
            peak = max(peak, value)
            drop = value / peak - 1.0
            if drop < worst:
                worst, worst_day = drop, day
        return worst, worst_day

    @property
    def win_rate(self) -> float:
        if not self.trade_returns:
            return 0.0
        wins = sum(1 for value in self.trade_returns if value > 0)
        return wins / len(self.trade_returns)

    @property
    def average_hold(self) -> float:
        if not self.trade_holds:
            return 0.0
        return sum(self.trade_holds) / len(self.trade_holds)

    @property
    def sharpe(self) -> float:
        """Annualised, from the day-by-day equity changes (flat days count)."""
        returns = [
            self.equity[i] / self.equity[i - 1] - 1.0
            for i in range(1, len(self.equity))
        ]
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        deviation = math.sqrt(variance)
        if deviation == 0:
            return 0.0
        return mean / deviation * math.sqrt(365)

    def metrics(self) -> list[tuple[str, str, str]]:
        """(caption, value, colour role) rows, ready to lay out."""
        drawdown, _ = self.drawdown()
        edge = self.total_return - self.benchmark_return
        return [
            ("Return", _percent(self.total_return), "accent"),
            ("Buy & hold", _percent(self.benchmark_return), "muted"),
            ("Edge", _percent(edge), "accent" if edge >= 0 else "down"),
            ("Max drawdown", _percent(drawdown), "down"),
            ("Sharpe", f"{self.sharpe:,.2f}", "text"),
            ("Trades", f"{len(self.trade_returns)}", "text"),
            ("Win rate", f"{self.win_rate * 100:,.0f}%", "text"),
            ("Avg hold", f"{self.average_hold:,.1f} d", "text"),
            ("Exposure", f"{self.exposure * 100:,.0f}%", "text"),
        ]


def sample_run(
    days: int = SAMPLE_DAYS,
    seed: int = SAMPLE_SEED,
    capital: float = CAPITAL,
) -> SampleRun:
    """A deterministic walk with an on/off holding pattern, for the preview."""
    rng = random.Random(seed)
    day_returns = [rng.gauss(0.0008, 0.035) for _ in range(days)]

    # Hold for a few days, sit out a few: one position at a time, flat between.
    held: list[bool] = []
    while len(held) < days:
        held.extend([True] * rng.randint(2, 6))
        held.extend([False] * rng.randint(1, 4))
    held = held[:days]

    equity = [capital]
    benchmark = [capital]
    value = capital
    in_trade = False
    entry_value = capital
    entry_day = 0
    trade_returns: list[float] = []
    trade_holds: list[int] = []

    for day in range(days):
        benchmark.append(benchmark[-1] * (1.0 + day_returns[day]))
        if held[day]:
            if not in_trade:
                in_trade = True
                entry_value = value * (1.0 - FEE_PER_SIDE)
                entry_day = day
            value = entry_value * math.prod(
                1.0 + rate for rate in day_returns[entry_day : day + 1]
            )
        elif in_trade:
            in_trade = False
            closed = value * (1.0 - FEE_PER_SIDE)
            trade_returns.append(closed / (equity[entry_day]) - 1.0)
            trade_holds.append(day - entry_day)
            value = closed
        equity.append(value)

    if in_trade:
        closed = value * (1.0 - FEE_PER_SIDE)
        trade_returns.append(closed / equity[entry_day] - 1.0)
        trade_holds.append(days - entry_day)
        equity[-1] = closed

    return SampleRun(
        days=days,
        equity=tuple(equity),
        benchmark=tuple(benchmark),
        trade_returns=tuple(trade_returns),
        trade_holds=tuple(trade_holds),
        exposure=sum(held) / days,
    )


def _percent(value: float) -> str:
    return f"{value * 100:+,.1f}%"


class EquityCurve(QWidget):
    """Strategy equity over buy & hold, with the worst drawdown marked."""

    def __init__(self, run: SampleRun, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.run = run
        self.setMinimumHeight(120)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        left = 54.0
        right = width - 8.0
        top = 20.0
        bottom = height - 16.0
        if right - left < 40 or bottom - top < 30:
            return

        values = list(self.run.equity) + list(self.run.benchmark)
        low = min(values)
        high = max(values)
        pad = max((high - low) * 0.08, 1.0)
        low -= pad
        high += pad

        def x_of(day: int) -> float:
            return left + (right - left) * day / max(1, self.run.days)

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        # Horizontal grid, labelled in dollars.
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

        # Buy & hold first, faint, so the strategy line reads on top of it.
        painter.setPen(QPen(QColor(TEXT_FAINT), 1, Qt.PenStyle.DashLine))
        for series in (self.run.benchmark,):
            path = [
                QPointF(x_of(day), y_of(value))
                for day, value in enumerate(series)
            ]
            painter.drawPolyline(path)

        painter.setPen(QPen(QColor(ACCENT), 1.6))
        path = [
            QPointF(x_of(day), y_of(value))
            for day, value in enumerate(self.run.equity)
        ]
        painter.drawPolyline(path)

        # Where the worst drawdown bottomed.
        drawdown, worst_day = self.run.drawdown()
        marker_x = x_of(worst_day)
        marker_y = y_of(self.run.equity[worst_day])
        painter.setPen(QPen(QColor(TEXT_FAINT), 1, Qt.PenStyle.DotLine))
        painter.drawLine(marker_x, marker_y, marker_x, bottom)
        painter.setFont(mono_font(7, bold=True))
        painter.setPen(QColor(TEXT_MUTED))
        text = f"max dd {_percent(drawdown)}"
        room = 96.0
        # Keep the tag inside the plot: flip it left when the trough is near
        # the right edge, which is where equity lows like to sit.
        if marker_x + 6 + room <= right:
            tag = QRectF(marker_x + 6, bottom - 13, room, 12)
            side = Qt.AlignmentFlag.AlignLeft
        else:
            tag = QRectF(marker_x - 6 - room, bottom - 13, room, 12)
            side = Qt.AlignmentFlag.AlignRight
        painter.drawText(
            tag, side | Qt.AlignmentFlag.AlignVCenter, text
        )

        # Legend, top right.
        painter.setFont(mono_font(7, bold=True))
        painter.setPen(QColor(ACCENT))
        painter.drawText(
            QRectF(right - 190, 0, 92, 14),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "strategy",
        )
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(right - 96, 0, 92, 14),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "buy & hold",
        )

        # Dates at both ends, so the span is readable.
        last = datetime.now(tz=timezone.utc)
        first = last - timedelta(days=self.run.days)
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(x_of(0), bottom + 1, 60, 13),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            first.strftime("%d %b"),
        )
        painter.drawText(
            QRectF(x_of(self.run.days) - 60, bottom + 1, 60, 13),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            last.strftime("%d %b"),
        )


class ResultsTile(Card):
    """Equity curve plus headline metrics — a sample until a run exists."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.run = sample_run()

        title = QLabel("RESULTS")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        note = QLabel("example data — no run yet")
        note.setObjectName("hintLabel")
        self.body.addWidget(note)

        self.curve = EquityCurve(self.run)
        self.body.addWidget(self.curve, 1)

        # The metrics wrap like the parameter gallery, so nine of them still
        # read on a narrow tile instead of clipping to three letters.
        self._metrics = QGridLayout()
        self._metrics.setContentsMargins(0, 0, 0, 0)
        self._metrics.setHorizontalSpacing(10)
        self._metrics.setVerticalSpacing(3)
        self._metric_widgets = [
            (self._caption(caption), self._value(value, role))
            for caption, value, role in self.run.metrics()
        ]
        self._metric_columns = 0
        self._reflow_metrics(WIDE_METRICS)
        self.body.addLayout(self._metrics)

    # -- layout ------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        columns = WIDE_METRICS if self.width() >= WIDE_AT else NARROW_METRICS
        if columns != self._metric_columns:
            self._reflow_metrics(columns)

    def _reflow_metrics(self, columns: int) -> None:
        for caption, value in self._metric_widgets:
            self._metrics.removeWidget(caption)
            self._metrics.removeWidget(value)
        self._metric_columns = columns
        for index, (caption, value) in enumerate(self._metric_widgets):
            row = index // columns * 2
            column = index % columns
            self._metrics.addWidget(caption, row, column)
            self._metrics.addWidget(value, row + 1, column)
        for column in range(WIDE_METRICS):
            self._metrics.setColumnStretch(
                column, 1 if column < columns else 0
            )

    # -- widgets -----------------------------------------------------------

    def _caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _value(self, text: str, role: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(f"metricValue_{role}")
        label.setFont(mono_font(9, bold=True))
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return label


__all__ = ["EquityCurve", "ResultsTile", "SampleRun", "sample_run"]
