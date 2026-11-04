"""The results tile: three curves, drawn as the run goes.

The strategy, a random-buy strategy, and buy and hold, all revealed a bar at a
time as the playback walks. Random-buy is the benchmark that matters: any
entry rule that cannot beat buying at random has no edge, so both are drawn
against the same exits, sizing and fees.

The curve data comes from `lalala.strat_playback` — this module only knows how
to draw it. Its scale is fixed when the run starts, so the picture never
rescales as it fills.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
        if session is None or not session.candles:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        total = len(session.candles)
        low, high = session.low, session.high

        def x_of(index: int) -> float:
            return left + (right - left) * index / max(1, total - 1)

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        # Grid, so the levels are readable without a table.
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

        # Buy and hold, then random-buy, then the strategy on top.
        for curve, colour, style, width_pt in (
            (session.benchmark, HOLD_COLOUR, Qt.PenStyle.DashLine, 1.0),
            (session.random_curve, RANDOM_COLOUR, Qt.PenStyle.SolidLine, 1.2),
            (session.strategy_curve, STRATEGY_COLOUR, Qt.PenStyle.SolidLine, 1.6),
        ):
            shown = session.revealed(curve)
            if len(shown) < 2:
                continue
            painter.setPen(QPen(QColor(colour), width_pt, style))
            painter.drawPolyline(
                [QPointF(x_of(i), y_of(v)) for i, v in enumerate(shown)]
            )

        # Bar times at both ends of the span.
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        for index, x, align in (
            (0, left, Qt.AlignmentFlag.AlignLeft),
            (total - 1, right - 68.0, Qt.AlignmentFlag.AlignRight),
        ):
            stamp = datetime.fromtimestamp(
                session.candles[index].stamp / 1000, tz=timezone.utc
            )
            painter.drawText(
                QRectF(x, bottom + 1, 68, 13),
                align | Qt.AlignmentFlag.AlignVCenter,
                stamp.strftime("%d %b %H:%M"),
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

        self.legend: dict[str, QLabel] = {}
        for key, caption in (
            ("strategy", "strategy"),
            ("random", "random buy"),
            ("hold", "buy & hold"),
        ):
            label = QLabel(caption)
            label.setObjectName(f"legend_{key}")
            label.setFont(mono_font(8, bold=True))
            header.addWidget(label)
            self.legend[key] = label
        self.body.addLayout(header)

        self.note = QLabel("no run yet")
        self.note.setObjectName("hintLabel")
        self.body.addWidget(self.note)

        self.curve = LiveCurve()
        self.body.addWidget(self.curve, 1)

    # -- the run -----------------------------------------------------------

    def set_session(self, session) -> None:
        self.curve.set_session(session)
        self.note.setText("live — read as the loop walks")
        self.refresh()

    def clear_session(self) -> None:
        self.curve.set_session(None)
        self.note.setText("no run yet")
        for label in self.legend.values():
            label.setText(label.text().split(" ")[0])

    def refresh(self) -> None:
        """The legend carries the running totals, so they move with the lines."""
        session = self.curve.session
        if session is None:
            return
        for key, curve in (
            ("strategy", session.strategy_curve),
            ("random", session.random_curve),
            ("hold", session.benchmark),
        ):
            percent = session.return_of(curve) * 100
            name = {
                "strategy": "strategy",
                "random": "random buy",
                "hold": "buy & hold",
            }[key]
            self.legend[key].setText(f"{name} {percent:+,.2f}%")
        self.curve.update()


__all__ = ["LiveCurve", "ResultsTile"]
