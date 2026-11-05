"""The results tile: three return curves, drawn as the run goes.

The strategy, a random-buy strategy, and buy and hold, revealed point by point
as the playback walks. Random-buy is the benchmark that matters: any entry rule
that cannot beat buying at random has no edge, so both are drawn against the
same exits, sizing and fees.

Everything is drawn as **return from the start**, not as a dollar balance.
Over a long span buy and hold compounds many times over, while a strategy that
deploys a fraction of the book per trade barely moves; in dollars the first
would flatten the others into the axis. In percent the two strategies stay
readable, and buy and hold is left to run off the top with its number in the
legend.

The curve data comes from `lalala.strat_playback` — this module only knows how
to draw it.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from lalala.cards import mono_font
from lalala.panels import Card
from lalala.theme import ACCENT, BAND, BORDER, TEXT_FAINT, TEXT_MUTED

# Amber is the strategy, indigo the random-buy stand-in, grey buy and hold.
STRATEGY_COLOUR = ACCENT
RANDOM_COLOUR = BAND
HOLD_COLOUR = TEXT_MUTED

# Never let the scale collapse to a flat line around zero.
MIN_SPAN = 0.4  # percent
PAD = 0.08


def _returns(curve: list[float]) -> list[float]:
    if not curve or curve[0] <= 0:
        return []
    first = curve[0]
    return [(value / first - 1.0) * 100.0 for value in curve]


class LiveCurve(QWidget):
    """The run's three curves, revealed up to wherever the walk has reached."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = None
        self.message = "run the backtest to see the curves"
        self.setMinimumHeight(120)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_session(self, session) -> None:
        self.session = session
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        left = 56.0
        right = width - 8.0
        top = 14.0
        bottom = height - 16.0
        if right - left < 40 or bottom - top < 30:
            return

        session = self.session
        if session is None or not session.strategy_curve:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        strategy = _returns(session.strategy_curve)
        random_buy = _returns(session.random_curve)
        hold = _returns(session.benchmark)
        # The scale follows the two strategies; buy and hold may run past it.
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

        # Grid, labelled in percent, with the break-even line picked out.
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
                f"{value:+,.2f}%",
            )

        # Buy and hold first, then random-buy, then the strategy on top.
        for curve, colour, style, width_pt in (
            (hold, HOLD_COLOUR, Qt.PenStyle.DashLine, 1.0),
            (random_buy, RANDOM_COLOUR, Qt.PenStyle.SolidLine, 1.2),
            (strategy, STRATEGY_COLOUR, Qt.PenStyle.SolidLine, 1.6),
        ):
            if len(curve) < 2:
                continue
            painter.setPen(QPen(QColor(colour), width_pt, style))
            painter.drawPolyline(
                [QPointF(x_of(i), y_of(v)) for i, v in enumerate(curve)]
            )

        # The walk's position along the bottom, and a word when buy and hold
        # has left the chart.
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(left, bottom + 1, 200, 13),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{session.index:,} / {session.total:,} bars",
        )
        if hold and hold[-1] > high:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(right - 180, top - 2, 180, 13),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "buy & hold is off the top",
            )


class ResultsTile(Card):
    """The three curves of the running backtest."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        title = QLabel("RESULTS")
        title.setObjectName("tileTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.body.addLayout(header)

        self.note = QLabel("no run yet")
        self.note.setObjectName("hintLabel")
        self.body.addWidget(self.note)

        self.curve = LiveCurve()
        self.body.addWidget(self.curve, 1)

        # The legend reads along the bottom, under the lines it names.
        legend = QHBoxLayout()
        legend.setContentsMargins(0, 0, 0, 0)
        legend.setSpacing(12)
        self.legend: dict[str, QLabel] = {}
        for key, caption in (
            ("strategy", "strategy"),
            ("random", "random buy"),
            ("hold", "buy & hold"),
        ):
            label = QLabel(caption)
            label.setObjectName(f"legend_{key}")
            label.setFont(mono_font(8, bold=True))
            legend.addWidget(label)
            self.legend[key] = label
        legend.addStretch(1)
        self.body.addLayout(legend)

    # -- the run -----------------------------------------------------------

    def set_session(self, session) -> None:
        self.curve.set_session(session)
        self.note.setText("return since the start, read as the loop walks")
        self.refresh()

    def clear_session(self) -> None:
        self.curve.set_session(None)
        self.note.setText("no run yet")
        for key, caption in (
            ("strategy", "strategy"),
            ("random", "random buy"),
            ("hold", "buy & hold"),
        ):
            self.legend[key].setText(caption)

    def refresh(self) -> None:
        """The legend carries the running totals, so they move with the lines."""
        session = self.curve.session
        if session is None:
            return
        for key, name, curve in (
            ("strategy", "strategy", session.strategy_curve),
            ("random", "random buy", session.random_curve),
            ("hold", "buy & hold", session.benchmark),
        ):
            percent = session.return_of(curve) * 100
            self.legend[key].setText(f"{name} {percent:+,.2f}%")
        self.curve.update()


__all__ = ["LiveCurve", "ResultsTile"]
