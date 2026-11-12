"""The backtest/strategy window.

Two rows, as in the mock. The top row is the run: the playback panel on the
left — candles, figures, Restart — and, on its right, a narrow column stacking
the history controls, the run's inputs and the strategy. The bottom row is the
results, full width. It shares the terminal's theme and gap, so the two windows
read as one product.

**Create a strategy** launches the builder window (`strat_builder.py`).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lalala.ui.strat.strat_params import ParamsTile
from lalala.ui.strat.strat_playback import PlaybackTile
from lalala.ui.strat.strat_results import ResultsTile
from lalala.ui.strat.strat_runs import LoadRunTile, SaveRunTile
from lalala.ui.strat.strat_strategy import StrategyTile
from lalala.ui.strat.strat_tiles import DownloadTile
from lalala.ui.theme import CANVAS, CARD_GAP


class StratWindow(QMainWindow):
    """The run and its inputs on top, the results across the bottom."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("lalala · backtest + strategy")
        self.setMinimumSize(620, 520)
        self.resize(1180, 940)

        canvas = QWidget(self)
        canvas.setObjectName("stratCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#stratCanvas {{ background-color: {CANVAS}; }}")

        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(CARD_GAP)

        # Top row: the run on the left, the narrow input column on the right.
        self.splitter = QSplitter(Qt.Orientation.Horizontal, canvas)
        self.splitter.setObjectName("stratSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(CARD_GAP)

        self.left = PlaybackTile(self.splitter)

        # The right side is a narrow column of tiles; they share the height so
        # they always fill it, with no scrolling.
        self.right = QWidget(self.splitter)
        self.right.setObjectName("stratColumn")
        column = QVBoxLayout(self.right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CARD_GAP)
        self.download = DownloadTile(self.right)
        self.params = ParamsTile(self.right)
        self.strategy = StrategyTile(self.right)
        self.save_run = SaveRunTile(self.right)
        self.load_run = LoadRunTile(self.right)
        column.addWidget(self.download)
        column.addWidget(self.params)
        column.addWidget(self.strategy)
        # Save and Load side by side, so both stay in view.
        runs_row = QWidget(self.right)
        runs_row.setObjectName("runsRow")
        runs_layout = QHBoxLayout(runs_row)
        runs_layout.setContentsMargins(0, 0, 0, 0)
        runs_layout.setSpacing(CARD_GAP)
        runs_layout.addWidget(self.save_run, 1)
        runs_layout.addWidget(self.load_run, 1)
        column.addWidget(runs_row)
        for tile in (
            self.download,
            self.params,
            self.strategy,
            self.save_run,
            self.load_run,
        ):
            tile.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
            )
        # Share the slack: the inputs get the most, the small tiles the least.
        for index, weight in enumerate((3, 4, 3, 2)):
            column.setStretch(index, weight)
        self.right.setMinimumWidth(360)
        self.right.setMaximumWidth(480)

        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([700, 460])

        # Bottom row: the results, full width under both halves.
        self.results = ResultsTile(canvas)

        self.outer = QSplitter(Qt.Orientation.Vertical, canvas)
        self.outer.setObjectName("stratOuter")
        self.outer.setChildrenCollapsible(False)
        self.outer.setHandleWidth(CARD_GAP)
        self.outer.addWidget(self.splitter)
        self.outer.addWidget(self.results)
        self.outer.setStretchFactor(0, 1)
        self.outer.setStretchFactor(1, 1)
        self.outer.setSizes([560, 400])

        layout.addWidget(self.outer, 1)
        self.setCentralWidget(canvas)

        # The left tile plays whatever the other tiles are set to. A change of
        # span or parameters only marks the run ready — pressing Start
        # backtest is what actually restarts it.
        self.download.span_changed.connect(self._sync_playback)
        self.params.changed.connect(self._sync_params)
        self.strategy.changed.connect(self.left.set_strategy)
        self.download.started.connect(self.left.restart)
        self.left.restarted.connect(self.results.set_session)
        self.left.advanced.connect(self.results.refresh)
        self.results.trade_selected.connect(self.left.set_trade)
        self.strategy.saved_picked.connect(self._apply_saved)
        self.save_run.save_requested.connect(self._save_run)
        self.load_run.load_requested.connect(self._load_run)
        self._sync_playback()
        self._sync_params()
        self.left.set_strategy(self.strategy.rule())

    def _sync_playback(self) -> None:
        start, end, resolution = self.download.span()
        self.left.set_source(list(range(start, end + 1)), resolution)

    def _sync_params(self) -> None:
        self.left.set_params(self.params.params())

    def _apply_saved(self, item) -> None:
        """Point the run at a saved strategy's entry rule."""
        from lalala.engine.formula import ENTRY_FIELDS

        self.left.set_saved_strategy(
            item.name, item.entry, ENTRY_FIELDS, item.exit, item.side,
            item.short_entry,
        )

    # -- saved runs --------------------------------------------------------

    def _save_run(self, name: str) -> None:
        from lalala.state import runs

        if not name or self.left.session is None:
            return
        start, end, resolution = self.download.span()
        runs.save(
            runs.SavedRun(
                name=name,
                years=list(range(start, end + 1)),
                resolution=resolution,
                rule=self.left.rule_key(),
                strategy=self.left.saved_name(),
                entry=self.left.saved_entry(),
                exit=self.left.saved_exit(),
                side=self.left.side(),
                short_entry=self.left.saved_short(),
                params=self.params.params(),
                trades=[
                    list(record)
                    for record in self.left.session.strategy.trades_log
                ],
                strategy_curve=self.left.session.strategy_curve,
                random_curve=self.left.session.random_curve,
            )
        )
        self.save_run.set_saved(name)
        self.load_run.refresh()

    def _load_run(self, name: str) -> None:
        from lalala.state import runs
        from lalala.engine.formula import ENTRY_FIELDS

        item = runs.get(name)
        if item is None:
            return
        if item.years:
            self.download.set_span(item.years[0], item.years[-1], item.resolution)
        if item.params:
            self.params.set_params(item.params)
        if item.rule == "saved" and item.entry:
            self.left.set_saved_strategy(
                item.strategy or item.name, item.entry, ENTRY_FIELDS,
                item.exit, item.side, item.short_entry,
            )
        else:
            self.left.set_strategy(item.rule)
        self._sync_playback()
        self._sync_params()
        self.left.restart()
        # A loaded run is shown whole: walk it to the end so every result and
        # trade is there at once.
        self.left.finish()
        self.results.set_part(0)
        self.results.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        """Re-read the saved strategies and runs, so the pickers are current."""
        super().showEvent(event)
        self.strategy.refresh_saved()
        self.load_run.refresh()

    def _input_tiles(self) -> tuple:
        return (self.download, self.params, self.strategy)

