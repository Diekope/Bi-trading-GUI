"""The compare subwindow: the run against its two stand-ins, and a sweep.

Inspired by the compare mock. Two things:

- the three curves — strategy, a random-buy version and buy and hold — with a
  table of the same figures side by side;
- a **walk-forward** count over four folds, and a **TP × SL sweep** drawn as a
  heat-map grid with a legend, so a setting can be read at a glance.

A saved strategy can be added to the comparison from the `+ Add` chip: it is
re-parsed from its stored text and run over the same bars, then it gets its own
chip, curve and table column.

Everything is computed from the same tail of candles the report reads. It is a
read, not a promise: nothing is wired back to the run.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import mono_font
from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS, FormulaError, parse
from lalala.formula_eval import (
    backtest,
    curve_drawdown,
    curve_return,
    curve_sharpe,
)
from lalala.strat_report import CurveChart
from lalala.strategies import load as load_strategies
from lalala.theme import ACCENT, BAND, TEXT_FAINT, TEXT_MUTED

# The TP / SL grid the sweep walks, and the columns of the compare table.
SWEEP_TPS = (1.0, 1.5, 2.0, 3.0, 4.0)
SWEEP_SLS = (0.5, 1.0, 1.5, 2.0, 3.0)

# The colours the sweep cells take, from worst to best.
SWEEP_COLOURS = ("#8f3a40", "#5a2328", "#2a2b31", "#1f4a33", "#2a7a52")

# What each colour band means, worst to best, for the legend.
SWEEP_CAPTIONS = ("≤ -3%", "-1%", "0%", "+1%", "≥ +3%")

# The colours extra runs take, in turn, so each one is told apart.
RUN_COLOURS = ("#6fd3c7", "#c58cf0", "#f08a5d", "#8fd14f", "#e05c8a")

FOLDS = 4

# How much room the axis figures take around the sweep grid.
GRID_LEFT = 30.0
GRID_BOTTOM = 14.0
GRID_GAP = 3.0


def _segments(bars, parts: int) -> list[list]:
    """Cut `bars` into `parts` roughly equal runs."""
    if not bars or parts <= 0:
        return []
    size = max(1, len(bars) // parts)
    chunks = [bars[i : i + size] for i in range(0, len(bars), size)]
    return chunks[:parts]


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

    clicked = Signal()

    def __init__(self, label: str, colour: str | None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("compareTag")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._text = text
        row.addWidget(text)

    def name(self) -> str:
        return self._label

    def set_label(self, label: str) -> None:
        self._label = label
        self._text.setText(label)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SweepHeatmap(QWidget):
    """The TP × SL sweep as a grid of coloured cells, labelled and hoverable."""

    cell_hovered = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.values: list[list[float]] = []
        self.hovered: tuple[int, int] | None = None
        self.setMinimumHeight(94)
        self.setMouseTracking(True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

    def set_values(self, values: list) -> None:
        self.values = values
        self.update()

    def _cell_rect(self, row: int, column: int) -> QRectF:
        rows = len(self.values)
        columns = len(self.values[0]) if rows else 0
        width = (self.width() - GRID_LEFT - GRID_GAP * (columns - 1)) / columns
        height = (
            self.height() - GRID_BOTTOM - GRID_GAP * (rows - 1)
        ) / rows
        return QRectF(
            GRID_LEFT + column * (width + GRID_GAP),
            row * (height + GRID_GAP),
            width,
            height,
        )

    def _cell_at(self, x: float, y: float) -> tuple[int, int] | None:
        for row in range(len(self.values)):
            for column in range(len(self.values[0])):
                if self._cell_rect(row, column).contains(x, y):
                    return row, column
        return None

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rows = len(self.values)
        columns = len(self.values[0]) if rows else 0
        if not rows or not columns:
            return

        painter.setFont(mono_font(7))
        for r, row in enumerate(self.values):
            for c, value in enumerate(row):
                rect = self._cell_rect(r, c)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(_sweep_colour(value)))
                painter.drawRoundedRect(rect, 4, 4)
                if self.hovered == (r, c):
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QColor(TEXT_MUTED))
                    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                                            4, 4)

        # SL down the left, TP under the columns.
        painter.setPen(QColor(TEXT_FAINT))
        for r, sl in enumerate(SWEEP_SLS):
            rect = self._cell_rect(r, 0)
            painter.drawText(
                QRectF(0, rect.top(), GRID_LEFT - 5, rect.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{sl:g}",
            )
        last = rows - 1
        for c, tp in enumerate(SWEEP_TPS):
            rect = self._cell_rect(last, c)
            painter.drawText(
                QRectF(rect.left() - 8, rect.bottom() + 2,
                       rect.width() + 16, GRID_BOTTOM - 2),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                f"{tp:g}",
            )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        cell = self._cell_at(event.position().x(), event.position().y())
        if cell != self.hovered:
            self.hovered = cell
            self.update()
            if cell:
                row, column = cell
                self.cell_hovered.emit(
                    (SWEEP_TPS[column], SWEEP_SLS[row],
                     self.values[row][column])
                )
            else:
                self.cell_hovered.emit(None)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.hovered is not None:
            self.hovered = None
            self.update()
            self.cell_hovered.emit(None)
        super().leaveEvent(event)


class SweepLegend(QWidget):
    """A row of swatches naming each colour band of the sweep."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(mono_font(8))
        step = self.width() / len(SWEEP_CAPTIONS)
        for index, (colour, caption) in enumerate(
            zip(SWEEP_COLOURS, SWEEP_CAPTIONS)
        ):
            left = index * step
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colour))
            painter.drawRoundedRect(QRectF(left, 2, 8, 8), 2, 2)
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left + 11, 0, step - 11, 12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                caption,
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
        self.runs: list[dict] = []
        self.selected_name: str | None = None
        self._dirty = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # The runs being compared, then where another could be added.
        self.tag_row = QHBoxLayout()
        self.tag_row.setContentsMargins(0, 0, 0, 0)
        self.tag_row.setSpacing(6)
        self.tags = [
            TagChip("Strategy", ACCENT, self),
            TagChip("Random buy", BAND, self),
            TagChip("Buy & hold", TEXT_MUTED, self),
        ]
        for chip in self.tags:
            self.tag_row.addWidget(chip)
        self.add_chip = TagChip("+ Add", None, self)
        self.add_chip.setToolTip("Add a saved strategy to the compare")
        self.add_chip.clicked.connect(self.open_add_menu)
        self.tag_row.addWidget(self.add_chip)
        self.tag_row.addStretch(1)
        layout.addLayout(self.tag_row)
        self.extra_chips: list[TagChip] = []

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

        # Right: the folds, then the sweep with its key and a hint.
        rail = QWidget(self)
        rail.setObjectName("resultsRail")
        rail.setFixedWidth(250)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(6)

        self.folds_row = self._stat_row(rail, "Walk-forward (4)")

        self.sweep_caption = QLabel("TP × SL sweep", rail)
        self.sweep_caption.setObjectName("panelTitle")
        rail_layout.addWidget(self.sweep_caption)

        self.sweep_hint = QLabel("SL down · TP across", rail)
        self.sweep_hint.setObjectName("sweepHint")
        rail_layout.addWidget(self.sweep_hint)

        self.heatmap = SweepHeatmap(rail)
        self.heatmap.cell_hovered.connect(self._cell_hovered)
        rail_layout.addWidget(self.heatmap)

        self.legend = SweepLegend(rail)
        rail_layout.addWidget(self.legend)
        rail_layout.addStretch(1)
        body.addWidget(rail, 0)

    # -- the chips and the saved strategies --------------------------------

    def open_add_menu(self) -> None:
        """Show the saved strategies under `+ Add`; pick one to compare it."""
        menu = self._build_add_menu()
        menu.exec(
            self.add_chip.mapToGlobal(
                QPoint(0, self.add_chip.height() + 2)
            )
        )

    def set_selected(self, name: str | None) -> None:
        """Name the strategy already on show, so `+ Add` leaves it out."""
        self.selected_name = name or None

    def _build_add_menu(self) -> QMenu:
        menu = QMenu(self)
        saved = [
            item for item in load_strategies()
            if item.name != self.selected_name
        ]
        if not saved:
            empty = menu.addAction("No other saved strategies")
            empty.setEnabled(False)
        else:
            for strategy in saved:
                taken = any(run["label"] == strategy.name for run in self.runs)
                label = (
                    f"{strategy.name} · added"
                    if taken
                    else f"{strategy.name} · {strategy.timeframe}"
                )
                action = menu.addAction(label)
                if taken:
                    action.setEnabled(False)
                    continue
                try:
                    self._rules_of(strategy)
                except (FormulaError, ValueError):
                    action.setText(f"{strategy.name} · invalid rule")
                    action.setEnabled(False)
                    continue
                action.triggered.connect(
                    lambda _checked=False, strategy=strategy:
                    self.add_strategy(strategy)
                )
        return menu

    @staticmethod
    def _rules_of(strategy):
        """A saved strategy's two rules, parsed the way the builder parses."""
        entry = parse(strategy.entry)
        exit_ = parse(strategy.exit, EXIT_FIELDS, EXIT_FUNCTIONS)
        return entry, exit_

    def _cell_hovered(self, cell) -> None:
        if cell is None:
            self.sweep_hint.setText("SL down · TP across")
            return
        tp, sl, value = cell
        self.sweep_hint.setText(
            f"TP {tp:g} / SL {sl:g} · {value * 100:+,.2f}%"
        )

    def add_strategy(self, strategy) -> None:
        """Compare a saved strategy over the same bars, with the same TP / SL."""
        if not self._ready():
            return
        if strategy.name == self.selected_name:
            return  # the run on show already is that strategy
        if any(run["label"] == strategy.name for run in self.runs):
            return
        try:
            entry, exit_ = self._rules_of(strategy)
        except (FormulaError, ValueError):
            return
        report = backtest(
            self.bars, entry, exit_, tp=self.tp, sl=self.sl
        )
        colour = RUN_COLOURS[len(self.runs) % len(RUN_COLOURS)]
        label = strategy.name
        self.runs.append(
            {"label": label, "colour": colour, "report": report,
             "strategy": strategy}
        )

        chip = TagChip(label, colour, self)
        chip.setToolTip("Click to remove this run")
        chip.clicked.connect(lambda chip=chip: self.remove_run(chip))
        self.tag_row.insertWidget(self.tag_row.indexOf(self.add_chip), chip)
        self.extra_chips.append(chip)

        self._rebuild_table()
        self._fill_table(self.report)
        self.chart.set_extra(
            [(run["colour"], run["report"].strategy) for run in self.runs]
        )

    def remove_run(self, chip: TagChip) -> None:
        index = self.extra_chips.index(chip)
        self.extra_chips.pop(index)
        self.runs.pop(index)
        self.tag_row.removeWidget(chip)
        chip.setParent(None)
        chip.deleteLater()
        self._rebuild_table()
        self._fill_table(self.report)
        self.chart.set_extra(
            [(run["colour"], run["report"].strategy) for run in self.runs]
        )

    # -- the table ---------------------------------------------------------

    def _build_table(self) -> None:
        while self.table.count():
            item = self.table.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cells = {}
        headers = ("Metric", "Strategy", "Random", "Hold")
        headers += tuple(run["label"] for run in self.runs)
        for column, title in enumerate(headers):
            label = QLabel(title, self)
            label.setObjectName("tableHead")
            self.table.addWidget(label, 0, column)
        for row, name in enumerate(("PnL", "Sharpe", "Max DD", "Win rate"), 1):
            caption = QLabel(name, self)
            caption.setObjectName("tableMetric")
            self.table.addWidget(caption, row, 0)
            for column in range(1, len(headers)):
                cell = QLabel("—", self)
                cell.setObjectName("tableCell")
                cell.setFont(mono_font(9))
                self.table.addWidget(cell, row, column)
                self._cells[(row, column)] = cell
        for column in range(len(headers)):
            self.table.setColumnStretch(column, 1)

    def _rebuild_table(self) -> None:
        self._build_table()
        self._fill_table(self.report)

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
        self._clear_runs()
        self._dirty = True
        if self.isVisible():
            self.recompute()

    def _clear_runs(self) -> None:
        while self.extra_chips:
            chip = self.extra_chips.pop()
            self.tag_row.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self.runs.clear()
        self.sweep_hint.setText("SL down · TP across")
        self._rebuild_table()
        self.chart.set_extra([])

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self.recompute()

    def recompute(self) -> None:
        self._dirty = False
        self.chart.set_report(self.report)
        self.chart.set_extra(
            [(run["colour"], run["report"].strategy) for run in self.runs]
        )
        self._fill_table(self.report)
        self._update_folds()
        self._update_sweep()

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
        base = [
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
        rows = [
            (index, values[1:] + tuple(self._run_text(index, run["report"])
                                       for run in self.runs))
            for index, values in enumerate(base, 1)
        ]
        for index, values in rows:
            for column, text in enumerate(values, 1):
                cell = self._cells[(index, column)]
                cell.setText(text)
                cell.setProperty("tone", self._tone(index, text))
                style = cell.style()
                style.unpolish(cell)
                style.polish(cell)

    @staticmethod
    def _run_text(row: int, run) -> str:
        if row == 1:
            return f"{run.pnl * 100:+,.2f}%"
        if row == 2:
            return f"{curve_sharpe(run.strategy):,.2f}"
        if row == 3:
            return f"{curve_drawdown(run.strategy, run.capital) * 100:+,.2f}%"
        return (
            f"{run.wins / run.trades * 100:,.0f}%" if run.trades else "—"
        )

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
    "SweepLegend",
    "TagChip",
    "sweep_returns",
    "walk_forward",
]
