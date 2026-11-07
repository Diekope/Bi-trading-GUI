"""The preview tile: the rule run over the candles already on disk.

The right rail. It reads the newest year in the store, takes the tail of it,
and runs the entry rule over those bars with `lalala.formula_eval`, marking the
bars where it fires and pairing each with the bar the exit rule would close it
on. It is a look at the rule, not the run: `tp` and `sl` are the defaults here
because the run's parameters live in the other window.

Nothing is downloaded, and nothing is written — no candles on disk means a
note saying so, not an empty chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from lalala.candles import candle_file, tail_rows
from lalala.cards import mono_font
from lalala.formula_eval import simulate
from lalala.panels import Card
from lalala.theme import ACCENT, BORDER, DOWN, TEXT_FAINT, TEXT_MUTED, UP

# Bars per displayed slot, and how much history to keep out of sight.
FACTOR = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
VISIBLE = 220
WARMUP = 400

# The preview's own defaults, since the run's parameters live elsewhere.
PREVIEW_TP = 2.0
PREVIEW_SL = 1.0


@dataclass(frozen=True)
class PreviewBar:
    stamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def compact(bars: list[PreviewBar], factor: int) -> list[PreviewBar]:
    """Group bars `factor`-to-one: first open, last close, extremes kept."""
    if factor <= 1:
        return list(bars)
    out: list[PreviewBar] = []
    for start in range(0, len(bars), factor):
        group = bars[start : start + factor]
        out.append(
            PreviewBar(
                group[0].stamp,
                group[0].open,
                max(bar.high for bar in group),
                min(bar.low for bar in group),
                group[-1].close,
                sum(bar.volume for bar in group),
            )
        )
    return out


def latest_year() -> int | None:
    """The newest year with a candle file, or None when the store is empty."""
    for year in range(2026, 2016, -1):
        if candle_file(year).exists():
            return year
    return None


def load_bars(
    resolution: str = "1h",
    visible: int = VISIBLE,
    warmup: int = WARMUP,
) -> tuple[list[PreviewBar], int | None]:
    """The tail of the newest year, compacted to `resolution`."""
    year = latest_year()
    if year is None:
        return [], None
    factor = FACTOR.get(resolution, 1)
    rows = tail_rows(candle_file(year), (visible + warmup) * factor)
    bars = [PreviewBar(*row) for row in rows]
    return compact(bars, factor), year


class SignalChart(QWidget):
    """Candles with the entries and exits marked on them."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.bars: list[PreviewBar] = []
        self.entries: list[int] = []
        self.exits: list[int] = []
        self.message = "press nothing — the preview follows the rule"
        self.setMinimumHeight(160)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def show_run(self, bars, entries, exits, message: str = "") -> None:
        self.bars = list(bars)
        self.entries = list(entries)
        self.exits = list(exits)
        if message:
            self.message = message
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())
        left, right = 8.0, width - 8.0
        top, bottom = 22.0, height - 22.0
        if right - left < 40 or bottom - top < 30:
            return

        first = max(0, len(self.bars) - VISIBLE)
        window = self.bars[first:]
        if not window:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        low = min(bar.low for bar in window)
        high = max(bar.high for bar in window)
        pad = max((high - low) * 0.08, high * 0.0002)
        low, high = low - pad, high + pad
        slot = (right - left) / len(window)

        def x_of(index: int) -> float:
            return left + (index - first + 0.5) * slot

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        body = max(1.0, slot * 0.6)
        for index, bar in enumerate(window, start=first):
            x = x_of(index)
            rising = bar.close >= bar.open
            colour = QColor(UP if rising else DOWN)
            painter.setPen(QPen(colour, 1))
            painter.drawLine(QPointF(x, y_of(bar.high)), QPointF(x, y_of(bar.low)))
            painter.setBrush(colour)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(
                QRectF(
                    x - body / 2,
                    y_of(max(bar.open, bar.close)),
                    body,
                    max(1.0, abs(y_of(bar.open) - y_of(bar.close))),
                )
            )

        # Entries below the bar, exits above it.
        shown_entries = [index for index in self.entries if index >= first]
        shown_exits = [index for index in self.exits if index >= first]
        for index in shown_entries:
            bar = self.bars[index]
            x, y = x_of(index), y_of(bar.low) + 6
            painter.setPen(QPen(QColor(ACCENT), 1))
            painter.setBrush(QColor(ACCENT))
            painter.drawPolygon(
                QPolygonF([QPointF(x, y - 7), QPointF(x - 4, y), QPointF(x + 4, y)])
            )
        for index in shown_exits:
            bar = self.bars[index]
            x, y = x_of(index), y_of(bar.high) - 6
            painter.setPen(QPen(QColor(TEXT_MUTED), 1))
            painter.setBrush(QColor(TEXT_MUTED))
            painter.drawPolygon(
                QPolygonF([QPointF(x, y + 7), QPointF(x - 4, y), QPointF(x + 4, y)])
            )

        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        last = self.bars[-1]
        stamp = datetime.fromtimestamp(last.stamp / 1000, tz=timezone.utc)
        painter.drawText(
            QRectF(left, bottom + 2, 160, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            stamp.strftime("%d %b %Y %H:%M"),
        )
        if shown_entries:
            painter.drawText(
                QRectF(right - 160, top - 16, 160, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{len(shown_entries)} entries here",
            )


class PreviewTile(Card):
    """The rule, run over the tail of the newest year on disk."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("PREVIEW", self)
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        self.note = QLabel("no rule yet", self)
        self.note.setObjectName("hintLabel")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)

        self.chart = SignalChart(self)
        self.body.addWidget(self.chart, 1)

        # What to preview. The window pushes these in as the tiles change.
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
        """Say what is known as soon as the tile appears."""
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        bars, year = load_bars(self.resolution)
        if not bars:
            self.note.setText(
                "no candles on disk — download history in the backtest window"
            )
            self.chart.show_run([], [], [], "nothing to show yet")
            return
        if self.entry_rule is None or self.entry_rule.condition is None:
            self.note.setText(
                f"{year} · {self.resolution} — no entry rule yet"
            )
            self.chart.show_run(bars, [], [], "write an entry rule to see it here")
            return

        entries, exits = simulate(
            bars, self.entry_rule, self.exit_rule, tp=self.tp, sl=self.sl
        )
        shown = sum(1 for index in entries if index >= len(bars) - VISIBLE)
        self.note.setText(
            f"{year} · {self.resolution} · {shown} entries in view"
            f" · tp {self.tp:g} / sl {self.sl:g}"
        )
        self.chart.show_run(bars, entries, exits)


__all__ = [
    "FACTOR",
    "PREVIEW_SL",
    "PREVIEW_TP",
    "VISIBLE",
    "PreviewBar",
    "PreviewTile",
    "SignalChart",
    "compact",
    "latest_year",
    "load_bars",
]
