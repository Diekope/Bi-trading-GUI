"""The backtest/strategy window.

Two rows, as in the mock. The top row is the run: the playback panel on the
left — candles, figures, Restart — and, on its right, a narrow column stacking
the history controls, the run's inputs and the strategy. The bottom row is the
results, full width. It shares the terminal's theme and gap, so the two windows
read as one product.

**Create a strategy** launches the builder window (`strat_builder.py`).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFrame,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bi_trading.ui.strat.strat_params import ParamsTile
from bi_trading.ui.strat.strat_playback import PlaybackTile
from bi_trading.ui.strat.strat_results import ResultsTile
from bi_trading.ui.strat.strat_runs import LoadRunTile, SaveRunTile
from bi_trading.ui.strat.strat_strategy import StrategyTile
from bi_trading.ui.strat.strat_tiles import DownloadTile
from bi_trading.ui.theme import CANVAS, CARD_GAP


class StratWindow(QMainWindow):
    """The run and its inputs on top, the results across the bottom."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("bi-trading · backtest + strategy")
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
        # The tiles need about 600px between them. Given less (the hub's 820px
        # window leaves the row ~400) they used to be squeezed under their own
        # contents; now the column keeps its height and scrolls instead.
        self.right.setMinimumHeight(self.right.minimumSizeHint().height())
        self.column_scroll = QScrollArea(self.splitter)
        self.column_scroll.setObjectName("stratColumnScroll")
        self.column_scroll.setWidget(self.right)
        self.column_scroll.setWidgetResizable(True)
        self.column_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.column_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.column_scroll.setStyleSheet(
            "#stratColumnScroll, #stratColumnScroll > QWidget > QWidget"
            " { background: transparent; }"
        )
        self.column_scroll.setMinimumWidth(360)
        self.column_scroll.setMaximumWidth(500)

        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.column_scroll)
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

        from bi_trading.ui.layout_memory import remember_splitter

        remember_splitter(self.splitter, "backtest.columns")
        remember_splitter(self.outer, "backtest.rows")

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
        self.load_run.overlay_requested.connect(self._overlay_run)
        self.load_run.renamed.connect(self._run_renamed)
        self.strategy.create_requested.connect(self._create_strategy)
        self.results.part_changed.connect(self._part_picked)
        self.left.finished.connect(self._refresh_compare)
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
        from bi_trading.engine.formula import ENTRY_FIELDS

        self.left.set_saved_strategy(
            item.name, item.entry, ENTRY_FIELDS, item.exit, item.side,
            item.short_entry, item.model,
        )
        if item.model and self._scoring is None:
            self._warm_model(item.model)

    def pick_strategy(self, name: str, run: bool = False) -> bool:
        """Point the window at a saved strategy; with `run`, start the backtest.

        A strategy that reads an ML model is run over the model's own test
        period (the only bars it has an honest call on), at the model's
        timeframe.
        """
        self.strategy.refresh_saved()
        item = next((s for s in self.strategy.saved if s.name == name), None)
        if item is None:
            return False
        if item.model:
            self._span_for_model(item.model)
        self.strategy.picker.setCurrentText(item.name)
        self._apply_saved(item)
        self._sync_playback()
        self._sync_params()
        if run and item.model:
            self._warm_model(item.model, then=self.left.restart)
        elif run:
            self.left.restart()
        return True

    def _warm_model(self, model: str, then=None) -> None:
        """Score the span with the model on a worker, then call `then`.

        Scoring a decade of minutes takes seconds; done here it keeps the window
        alive, and the run that follows reads the scores from the cache.
        """
        from bi_trading.ui.ml.workers import ScoreWorker

        start, end, resolution = self.download.span()
        worker = ScoreWorker(model, list(range(start, end + 1)), resolution)
        self._scoring = worker
        self.left.note.setText(f"scoring the span with {model}…")

        def finished() -> None:
            self._scoring = None
            worker.deleteLater()
            if then is not None:
                then()

        worker.done.connect(finished)
        worker.start()

    _scoring: Any = None

    @staticmethod
    def _model_stamp(model: str) -> float:
        if not model:
            return 0.0
        from bi_trading.ml.store import model_summary

        summary = model_summary(model)
        return summary["trained_at"] if summary else 0.0

    def _span_for_model(self, model: str) -> None:
        from datetime import UTC, datetime

        from bi_trading.ml import store
        from bi_trading.ml.train import MLError

        try:
            trained = store.load_model(model)
        except MLError:
            return  # the run's own note says why the model cannot be used
        if not trained.test_start:
            return
        first = datetime.fromtimestamp(trained.test_start / 1000, tz=UTC).year
        last = datetime.fromtimestamp(trained.test_end / 1000, tz=UTC).year
        self.download.set_span(first, max(first, last), trained.config.timeframe)

    # -- saved runs --------------------------------------------------------

    def _save_run(self, name: str) -> None:
        from bi_trading.state import runs

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
                model=self.left.saved_model(),
                model_stamp=self._model_stamp(self.left.saved_model()),
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

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Space runs and pauses, R restarts, 1-6 pick the resolution.

        Only keys the focused widget declined reach the window, so typing a
        digit into a field never changes the resolution, and Space on a focused
        button still presses that button.
        """
        if not event.modifiers():
            key = event.key()
            if key == Qt.Key.Key_Space:
                self.left._on_run()
                event.accept()
                return
            if key == Qt.Key.Key_R:
                self.left.restart()
                event.accept()
                return
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_6:
                if self.download.pick_resolution(key - Qt.Key.Key_1):
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _run_renamed(self, old: str, new: str) -> None:
        if self.save_run.name.text() == old:
            self.save_run.set_saved(new)

    def open_builder(self) -> None:
        """Open the strategy builder. The hub swaps this for its own Builder view."""
        from bi_trading.ui.strat.strat_builder import StrategyBuilderWindow

        self._builder = StrategyBuilderWindow()
        self._builder.show()

    def _create_strategy(self) -> None:
        self.open_builder()

    def _overlay_run(self, name: str) -> None:
        """Lay a saved run's strategy curve over the current run, or take it off."""
        from bi_trading.state import runs

        if not name:
            self.results.set_overlay("", None)
            return
        strategy, _random = runs.read_curves(name)
        if not strategy:
            self.load_run.note.setText(f"{name} has no stored curve to overlay")
            self.results.set_overlay("", None)
            return
        self.load_run.note.setText("")
        self.results.set_overlay(name, strategy)

    def _load_run(self, name: str) -> None:
        from bi_trading.state import runs
        from bi_trading.engine.formula import ENTRY_FIELDS

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
                item.exit, item.side, item.short_entry, item.model,
            )
        else:
            self.left.set_strategy(item.rule)
        self._sync_playback()
        self._sync_params()
        self.left.restart(autoplay=False)
        if item.model and item.model_stamp and self._model_stamp(item.model) != item.model_stamp:
            self.load_run.note.setText(
                f"{item.model} was retrained since this run: its trades are the old model's"
            )
        # A loaded run is shown whole. Its own trades and curves were stored
        # with it, so they go straight back on screen; only when they do not
        # fit this span is it walked again, off the main thread, and the
        # results are filled when that lands.
        if self.left.show_saved(item):
            self._run_loaded()
            return
        self.left.finished.connect(
            self._run_loaded, Qt.ConnectionType.SingleShotConnection
        )
        self.left.finish()

    # How many of the last bars Compare sweeps and walks forward over. The sweep runs
    # the rule once per (TP, SL) cell, so it reads a tail, as the builder's does.
    COMPARE_BARS = 2_000

    def _part_picked(self, index: int) -> None:
        if index == 2:
            self._refresh_compare()

    def _refresh_compare(self) -> None:
        """Hand Compare the run's rule and its last bars (only while it is showing)."""
        from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, FormulaError, parse

        if self.results.part() != "compare":
            return
        session = self.left.session
        entry = exit_ = short_entry = None
        bars: list = []
        side = self.left.side()
        try:
            if self.left.rule_key() == "bollinger":
                entry = parse(
                    "close < bollinger_lower(close, 20, 2)", ENTRY_FIELDS, FUNCTIONS
                )
            elif self.left._entry_formula is not None:
                entry = self.left._entry_formula
                exit_ = self.left._exit_formula
                short_entry = self.left._short_formula
        except FormulaError:
            entry = None
        if session is not None and session.span is not None and entry is not None:
            total = session.total
            bars = session.span.candles(max(0, total - self.COMPARE_BARS), total)
        params = self.params.params()
        self.results.set_compare_inputs(
            bars, entry, exit_, float(str(params["tp"])), float(str(params["sl"])),
            side == "short", short_entry if side == "both" else None,
        )

    def _run_loaded(self) -> None:
        self.results.set_part(0)
        self.results.refresh()
        self._refresh_compare()

    def showEvent(self, event) -> None:  # noqa: N802
        """Re-read the saved strategies and runs, so the pickers are current."""
        super().showEvent(event)
        self.strategy.refresh_saved()
        self.load_run.refresh()

    def _input_tiles(self) -> tuple:
        return (self.download, self.params, self.strategy)

