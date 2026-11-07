"""The compare subwindow: the run against its two stand-ins, and a sweep.

Inspired by the compare mock. Three things:

- the three curves — strategy, a random-buy version and buy and hold — with a
  table of the same figures side by side;
- a **train / test** split with a handle, so the first part of the span is read
  as the past and the rest as the unknown;
- a **walk-forward** count over four folds, and a **TP × SL sweep** drawn as a
  heat-map grid.

Everything is computed from the same tail of candles the report reads, by
slicing it and running `lalala.formula_eval.backtest` on each part. It is a
read, not a promise: nothing is wired back to the run.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import mono_font
from lalala.formula_eval import (
    backtest,
    curve_drawdown,
    curve_return,
    curve_sharpe,
)
from lalala.strat_report import CurveChart
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

# The TP / SL grid the sweep walks, and the columns of the compare table.
SWEEP_TPS = (1.0, 1.5, 2.0, 3.0, 4.0)
SWEEP_SLS = (0.5, 1.0, 1.5, 2.0, 3.0)

# The colours the sweep cells take, from worst to best.
SWEEP_COLOURS = ("#8f3a40", "#5a2328", "#2a2b31", "#1f4a33", "#2a7a52")

FOLDS = 4
DEFAULT_SPLIT = 70


def _segments(bars, parts: int) -> list[list]:
    """Cut `bars` into `parts` roughly equal runs."""
    if not bars or parts <= 0:
        return []
    size = max(1, len(bars) // parts)
    chunks = [bars[i : i + size] for i in range(0, len(bars), size)]
    return chunks[:parts]


def split_returns(bars, entry, exit_, split: int, tp: float, sl: float) -> tuple:
    """Return of the first `split` % of the span, and of the rest."""
    if not bars:
        return 0.0, 0.0
    cut = max(1, min(len(bars) - 1, int(len(bars) * split / 100)))
    train = backtest(bars[:cut], entry, exit_, tp=tp, sl=sl)
    test = backtest(bars[cut:], entry, exit_, tp=tp, sl=sl)
    return train.pnl, test.pnl


def walk_forward(bars, entry, exit_, tp: float, sl: float, folds: int = FOLDS):
    """The return of each fold, so the caller can count the positive ones."""
    return [
        backtest(chunk, entry, exit_, tp=tp, sl=sl).pnl
        for chunk in _segments(bars, folds)
    ]


def sweep_returns(bars, entry, exit_, tps=SWEEP_TPS, sls=SWEEP_SLS) -> list:
    """A return per (tp, sl) cell: rows are sl, columns tp."""
    grid: list[list[float]] = []
    for sl in sls:
        row = [
            backtest(bars, entry, exit_, tp=tp, sl=sl).pnl for tp in tps
        ]
        grid.append(row)
    return grid


def _sweep_colour(value: float) -> str:
    if value <= -0.03:
        return SWEEP_COLOURS[0]
    if value <= -0.008:
        return SWEEP_COLOURS[1]
    if value < 0.008:
        return SWEEP_COLOURS[2]
    if value < 0.03:
        return SWEEP_COLOURS[3]
    return SWEEP_COLOURS[4]


class TagChip(QFrame):
    """A run beside its dot, as in the mock's row of compared runs."""

    def __init__(self, label: str, colour: str | None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("compareTag")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 9, 4)
        row.setSpacing(6)
        if colour is not None:
            dot = QFrame(self)
            dot.setObjectName("compareDot")
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(
                f"#compareDot {{ background-color: {colour};"
                "border-radius: 4px; }"
            )
            row.addWidget(dot)
        text = QLabel(label, self)
        text.setObjectName("compareTagText" if colour else "compareTagAdd")
        self._label = label
        row.addWidget(text)

    def name(self) -> str:
        return self._label


class SweepHeatmap(QWidget):
    """The TP × SL sweep as a grid of coloured cells."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.values: list[list[float]] = []
        self.setMinimumHeight(70)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

    def set_values(self, values: list) -> None:
        self.values = values
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rows = len(self.values)
        columns = len(self.values[0]) if rows else 0
        if not rows or not columns:
            return
        gap = 3.0
        width = (self.width() - gap * (columns - 1)) / columns
        height = (self.height() - gap * (rows - 1)) / rows
        for r, row in enumerate(self.values):
            for c, value in enumerate(row):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(_sweep_colour(value)))
                painter.drawRoundedRect(
                    QRectF(
                        c * (width + gap),
                        r * (height + gap),
                        width,
                        height,
                    ),
                    4,
                    4,
                )


class ComparePage(QWidget):
    """The compare subwindow, fed from the same tail as the report."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("resultsPage")
        self.bars: list = []
        self.entry = None
        self.exit = None
        self.report = None
        self.tp = 2.0
        self.sl = 1.0
        self._dirty = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # The runs being compared, then where another could be added.
        tags = QHBoxLayout()
        tags.setContentsMargins(0, 0, 0, 0)
        tags.setSpacing(6)
        self.tags = [
            TagChip("Strategy", ACCENT, self),
            TagChip("Random buy", BAND, self),
            TagChip("Buy & hold", TEXT_MUTED, self),
            TagChip("+ Add", None, self),
        ]
        for chip in self.tags:
            tags.addWidget(chip)
        tags.addStretch(1)
        layout.addLayout(tags)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        layout.addLayout(body, 1)

        # Left: the curves over the table of the same figures.
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        self.chart = CurveChart(self)
        left.addWidget(self.chart, 1)
        self.table = QGridLayout()
        self.table.setContentsMargins(0, 0, 0, 0)
        self.table.setHorizontalSpacing(10)
        self.table.setVerticalSpacing(4)
        self._cells: dict[tuple[int, int], QLabel] = {}
        self._build_table()
        left.addLayout(self.table)
        body.addLayout(left, 1)

        # Right: the train / test split, the folds, and the sweep.
        rail = QWidget(self)
        rail.setObjectName("resultsRail")
        rail.setFixedWidth(250)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(6)

        self.split_caption = QLabel(f"Train / Test · {DEFAULT_SPLIT} % / "
                                    f"{100 - DEFAULT_SPLIT} %", rail)
        self.split_caption.setObjectName("panelTitle")
        rail_layout.addWidget(self.split_caption)

        self.split_slider = QSlider(Qt.Orientation.Horizontal, rail)
        self.split_slider.setObjectName("splitSlider")
        self.split_slider.setRange(20, 90)
        self.split_slider.setValue(DEFAULT_SPLIT)
        self.split_slider.valueChanged.connect(self._split_changed)
        rail_layout.addWidget(self.split_slider)

        self.train_row = self._stat_row(rail, "Train")
        self.test_row = self._stat_row(rail, "Test")
        self.folds_row = self._stat_row(rail, "Walk-forward (4)")

        sweep_caption = QLabel("TP x SL sweep", rail)
        sweep_caption.setObjectName("panelTitle")
        rail_layout.addWidget(sweep_caption)
        self.heatmap = SweepHeatmap(rail)
        rail_layout.addWidget(self.heatmap)
        rail_layout.addStretch(1)
        body.addWidget(rail, 0)

    # -- the table ---------------------------------------------------------

    def _build_table(self) -> None:
        headers = ("Metric", "Strategy", "Random", "Hold")
        for column, title in enumerate(headers):
            label = QLabel(title, self)
            label.setObjectName("tableHead")
            self.table.addWidget(label, 0, column)
        for row, name in enumerate(("PnL", "Sharpe", "Max DD", "Win rate"), 1):
            caption = QLabel(name, self)
            caption.setObjectName("tableMetric")
            self.table.addWidget(caption, row, 0)
            for column in range(1, 4):
                cell = QLabel("—", self)
                cell.setObjectName("tableCell")
                cell.setFont(mono_font(9))
                self.table.addWidget(cell, row, column)
                self._cells[(row, column)] = cell
        for column in range(4):
            self.table.setColumnStretch(column, 1)

    def _stat_row(self, parent: QWidget, caption: str) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        key = QLabel(caption, parent)
        key.setObjectName("valueKey")
        value = QLabel("—", parent)
        value.setObjectName("valueNumber")
        value.setFont(mono_font(9))
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(key, 1)
        row.addWidget(value, 0)
        parent.layout().addLayout(row)
        return value

    # -- the data ----------------------------------------------------------

    def configure(self, bars, entry, exit_, report, tp: float, sl: float) -> None:
        """Take new inputs; recompute on the next show (or now, if shown)."""
        self.bars = list(bars or [])
        self.entry = entry
        self.exit = exit_
        self.report = report
        self.tp = tp
        self.sl = sl
        self._dirty = True
        if self.isVisible():
            self.recompute()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self.recompute()

    def recompute(self) -> None:
        self._dirty = False
        self.chart.set_report(self.report)
        self._fill_table(self.report)
        self._update_split()
        self._update_folds()
        self._update_sweep()

    def _split_changed(self, value: int) -> None:
        self.split_caption.setText(
            f"Train / Test · {value} % / {100 - value} %"
        )
        self._update_split()

    def _ready(self) -> bool:
        return bool(self.bars) and self.entry is not None

    def _fill_table(self, report) -> None:
        if report is None or not report.strategy:
            for cell in self._cells.values():
                cell.setText("—")
                cell.setProperty("tone", "muted")
            return

        def percent(value: float) -> str:
            return f"{value * 100:+,.2f}%"

        def win_rate(count: int, wins: int) -> str:
            if not count:
                return "—"
            return f"{wins / count * 100:,.0f}%"

        random_curve, hold_curve = report.random, report.hold
        rows = [
            ("PnL",
             percent(report.pnl),
             percent(report.return_of(random_curve)),
             percent(report.return_of(hold_curve))),
            ("Sharpe",
             f"{curve_sharpe(report.strategy):,.2f}",
             f"{curve_sharpe(random_curve):,.2f}",
             f"{curve_sharpe(hold_curve):,.2f}"),
            ("Max DD",
             percent(curve_drawdown(report.strategy, report.capital)),
             percent(curve_drawdown(random_curve, report.capital)),
             percent(curve_drawdown(hold_curve, report.capital))),
            ("Win rate",
             win_rate(report.trades, report.wins),
             win_rate(report.random_trades, report.random_wins),
             "—"),
        ]
        for index, (_key, strategy, random_value, hold) in enumerate(rows, 1):
            for column, text in enumerate((strategy, random_value, hold), 1):
                cell = self._cells[(index, column)]
                cell.setText(text)
                cell.setProperty("tone", self._tone(index, text))
                style = cell.style()
                style.unpolish(cell)
                style.polish(cell)

    @staticmethod
    def _tone(row: int, text: str) -> str:
        """The colour a table cell takes: PnL by sign, Max DD red, else muted."""
        if row == 1:  # PnL
            if text.startswith("+"):
                return "up"
            if text.startswith("-"):
                return "down"
            return "muted"
        if row == 3 and text.startswith("-"):  # Max DD
            return "down"
        return "muted"

    def _update_split(self) -> None:
        if not self._ready():
            self.train_row.setText("—")
            self.test_row.setText("—")
            return
        train, test = split_returns(
            self.bars, self.entry, self.exit, self.split_slider.value(),
            self.tp, self.sl,
        )
        self.train_row.setText(f"{train * 100:+,.2f}%")
        self.test_row.setText(f"{test * 100:+,.2f}%")

    def _update_folds(self) -> None:
        if not self._ready():
            self.folds_row.setText("—")
            return
        returns = walk_forward(
            self.bars, self.entry, self.exit, self.tp, self.sl
        )
        positives = sum(1 for value in returns if value > 0)
        self.folds_row.setText(f"{positives} / {len(returns)} positive")

    def _update_sweep(self) -> None:
        if not self._ready():
            self.heatmap.set_values([])
            return
        self.heatmap.set_values(
            sweep_returns(self.bars, self.entry, self.exit)
        )


__all__ = [
    "ComparePage",
    "SweepHeatmap",
    "TagChip",
    "split_returns",
    "sweep_returns",
    "walk_forward",
]
