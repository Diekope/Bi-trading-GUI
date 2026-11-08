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

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lalala.candles import candle_file, tail_rows
from lalala.cards import mono_font
from lalala.formula_eval import (
    REASON_END,
    REASON_RULE,
    REASON_STOP_LOSS,
    REASON_TAKE_PROFIT,
    REASON_TIME,
    backtest,
    watch_values,
)
from lalala.panels import Card
from lalala.theme import (
    ACCENT,
    BAND,
    BORDER,
    DOWN,
    PANEL_ALT,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    UP,
)

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

# How a trade ended, in the colour its bar takes: green when it took profit,
# red when it stopped, indigo on time, amber on the rule's own condition, grey
# when the data simply ran out.
REASON_COLOURS = {
    REASON_TAKE_PROFIT: UP,
    REASON_STOP_LOSS: DOWN,
    REASON_TIME: BAND,
    REASON_RULE: ACCENT,
    REASON_END: TEXT_MUTED,
}

# The results rail on the right, and the height of one reason row.
RAIL_WIDTH = 250
ROW_H = 26

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
        self.extra: list = []
        self.message = "nothing to show yet"
        self.setMinimumHeight(140)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_report(self, report) -> None:
        self.report = report
        self.update()

    def set_extra(self, curves) -> None:
        """Runs added from the sweep: (colour, curve) pairs."""
        self.extra = list(curves or [])
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
        extras = [
            (colour, _returns(curve)) for colour, curve in self.extra
        ]
        # The scale fits every curve, so no line runs out of view.
        every = strategy + random_buy + hold + [0.0]
        for _colour, curve in extras:
            every.extend(curve)
        low = min(every)
        high = max(every)
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
        ):
            if len(curve) < 2:
                continue
            painter.setPen(QPen(QColor(colour), weight, style))
            painter.drawPolyline(
                [QPointF(x_of(i), y_of(v)) for i, v in enumerate(curve)]
            )
        # Any runs added from the sweep, behind the main strategy line.
        for colour, curve in extras:
            if len(curve) < 2:
                continue
            painter.setPen(QPen(QColor(colour), 1.2))
            painter.drawPolyline(
                [QPointF(x_of(i), y_of(v)) for i, v in enumerate(curve)]
            )
        if len(strategy) >= 2:
            painter.setPen(QPen(QColor(STRATEGY_COLOUR), 1.6))
            painter.drawPolyline(
                [QPointF(x_of(i), y_of(v)) for i, v in enumerate(strategy)]
            )


def _percent(value: float) -> str:
    return f"{value * 100:+,.2f}%"


def _money(value: float) -> str:
    return f"${value:,.0f}"


class ReasonBars(QWidget):
    """How the trades ended: a labelled bar per reason, most first."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[tuple[str, float, str]] = []
        self.message = "no trades yet"
        self.setMinimumHeight(40)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

    def set_report(self, report) -> None:
        shares = report.reason_shares if report is not None else []
        self.rows = [
            (label, share, REASON_COLOURS.get(label, TEXT_MUTED))
            for label, _count, share in shares
        ]
        self.setMinimumHeight(max(1, len(self.rows)) * ROW_H + 4)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        if not self.rows:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, 0, width, float(self.height())),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        label_w, gap, pct_w = 84.0, 8.0, 38.0
        track_left = label_w + gap
        track_right = width - pct_w - gap
        track_w = max(4.0, track_right - track_left)
        painter.setFont(mono_font(9))
        for index, (label, share, colour) in enumerate(self.rows):
            top = index * ROW_H
            middle = top + ROW_H / 2.0
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(0, top, label_w, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PANEL_ALT))
            painter.drawRoundedRect(
                QRectF(track_left, middle - 4, track_w, 8), 4, 4
            )
            painter.setBrush(QColor(colour))
            painter.drawRoundedRect(
                QRectF(track_left, middle - 4, max(2.0, track_w * share), 8), 4, 4
            )
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(width - pct_w, top, pct_w, ROW_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{share * 100:,.0f}%",
            )


class ReportTile(Card):
    """The run's numbers and its curves, over two subwindows.

    `Overview` is the split — the figures and the three curves on the left, how
    the trades ended on the right; `Compare` is set aside for putting two runs
    side by side. Their names are the switch, the way `Rules` / `Formula` /
    `Code` switch in the rules tile.
    """

    view_changed = Signal(str)

    VIEWS = (
        ("overview", "Overview"),
        ("compare", "Compare"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_view = "overview"

        # RESULTS on the left with the span under it, the view pills on the
        # right, as in the mock.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        heading = QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(2)
        title = QLabel("RESULTS", self)
        title.setObjectName("tileTitle")
        heading.addWidget(title)
        self.note = QLabel("no rule yet", self)
        self.note.setObjectName("hintLabel")
        self.note.setWordWrap(True)
        heading.addWidget(self.note)
        header.addLayout(heading, 1)

        self.views = QButtonGroup(self)
        self.views.setExclusive(True)
        self.view_buttons: dict[str, QPushButton] = {}
        for index, (key, label) in enumerate(self.VIEWS):
            button = QPushButton(label, self)
            button.setObjectName("modeButton")
            button.setProperty("view", key)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.views.addButton(button, index)
            self.view_buttons[key] = button
            header.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        self.views.idClicked.connect(self._pick_view)
        self.body.addLayout(header)

        # One page per subwindow, only one on show.
        self.pages = QStackedWidget(self)
        self.pages.setObjectName("resultsStack")
        self.pages.addWidget(self._overview_page())
        self.pages.addWidget(self._compare_page())
        self.pages.setCurrentIndex(0)
        self.body.addWidget(self.pages, 1)

        self.entry_rule = None
        self.exit_rule = None
        self.resolution = "1h"
        self.tp = PREVIEW_TP
        self.sl = PREVIEW_SL
        # What the rule's names read on the newest bar, for the panel beside
        # the editor: (values, result).
        self.watch: tuple = ({}, None)

    # -- the subwindows ----------------------------------------------------

    def _overview_page(self) -> QWidget:
        """The split: figures and curves left, how trades ended right."""
        page = QWidget(self)
        page.setObjectName("resultsPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Left: the six figures in one row, the curve under them, the legend.
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)

        self._metrics: list[tuple[QLabel, QLabel]] = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        for index, caption in enumerate(
            ("PnL", "Sharpe", "Max DD", "Trades", "Win rate", "Fees")
        ):
            label = QLabel(caption, page)
            label.setObjectName("fieldLabel")
            value = QLabel("—", page)
            value.setObjectName("metricValue_text")
            value.setFont(mono_font(9, bold=True))
            grid.addWidget(label, 0, index)
            grid.addWidget(value, 1, index)
            self._metrics.append((label, value))
        for column in range(6):
            grid.setColumnStretch(column, 1)
        left.addLayout(grid)

        self.chart = CurveChart(page)
        left.addWidget(self.chart, 1)

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
            label = QLabel(caption, page)
            label.setObjectName(f"legend_{key}")
            label.setFont(mono_font(8, bold=True))
            legend.addWidget(label)
            self.legend[key] = label
        legend.addStretch(1)
        left.addLayout(legend)
        layout.addLayout(left, 1)

        # Right: how the trades ended, most-appearing reason first.
        rail = QWidget(page)
        rail.setObjectName("resultsRail")
        rail.setFixedWidth(RAIL_WIDTH)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(6)
        caption = QLabel("How trades end", rail)
        caption.setObjectName("panelTitle")
        rail_layout.addWidget(caption)
        self.reasons = ReasonBars(rail)
        rail_layout.addWidget(self.reasons)
        self.reasons_note = QLabel("no trades yet", rail)
        self.reasons_note.setObjectName("hintLabel")
        self.reasons_note.setWordWrap(True)
        rail_layout.addWidget(self.reasons_note)
        rail_layout.addStretch(1)
        layout.addWidget(rail, 0)
        return page

    def _compare_page(self) -> QWidget:
        """The compare subwindow: the run against its two stand-ins."""
        from lalala.strat_compare import ComparePage

        self.compare = ComparePage(self)
        self.compare_message = self.compare.tags[-1]  # the "+ Add" chip
        return self.compare

    def view(self) -> str:
        return self.current_view

    def set_view(self, key: str) -> None:
        for index, (name, _) in enumerate(self.VIEWS):
            if name == key:
                self.views.button(index).setChecked(True)
                self._pick_view(index)
                return

    def _pick_view(self, index: int) -> None:
        if not 0 <= index < len(self.VIEWS):
            return
        self.current_view = self.VIEWS[index][0]
        self.pages.setCurrentIndex(index)
        self.view_changed.emit(self.current_view)

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
            self.watch = ({}, None)
            self._clear("no candles on disk — download history in the backtest window")
            return
        if self.entry_rule is None or self.entry_rule.condition is None:
            self.watch = ({}, None)
            self._clear(f"{year} · {self.resolution} — no entry rule yet")
            return
        self.watch = watch_values(self.entry_rule, bars)

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
        self.reasons.set_report(report)
        self.compare.configure(
            bars, self.entry_rule, self.exit_rule, report, self.tp, self.sl
        )
        self.reasons_note.setText(
            f"{report.trades:,} trades · {len(report.reasons)} ways they ended"
            if report.trades
            else "no trades yet"
        )
        self._show_metrics(report)
        self._show_legend(report)

    def _clear(self, message: str) -> None:
        self.note.setText(message)
        self.chart.set_report(None)
        self.chart.message = "write an entry rule to see it here"
        for _, value in self._metrics:
            value.setText("—")
        self.reasons.set_report(None)
        self.reasons_note.setText("no trades yet")
        self.compare.configure([], None, None, None, self.tp, self.sl)
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
            (_money(report.fees), "muted"),
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
    "ReasonBars",
    "ReportTile",
    "VISIBLE",
    "compact",
    "latest_year",
    "load_bars",
]
