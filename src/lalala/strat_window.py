"""The backtest/strategy window.

Two halves. The left is still open. The right stacks three tiles: the history
controls on top, the backtest parameters below them, and an empty tile under
that, the lower two sharing the space equally. It shares the terminal's theme
and gap, so the two windows read as one product.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lalala.panels import Card
from lalala.strat_params import ParamsTile
from lalala.strat_playback import PlaybackTile
from lalala.strat_results import ResultsTile
from lalala.strat_strategy import StrategyTile
from lalala.strat_tiles import DownloadTile
from lalala.theme import CANVAS, CARD_GAP


class StratWindow(QMainWindow):
    """Left half open, right half stacked into three tiles."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("lalala · backtest + strategy")
        self.setMinimumSize(620, 520)
        self.resize(1180, 760)

        canvas = QWidget(self)
        canvas.setObjectName("stratCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#stratCanvas {{ background-color: {CANVAS}; }}")

        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(CARD_GAP)

        # Same transparent gap as the terminal, so the halves float apart.
        self.splitter = QSplitter(Qt.Orientation.Horizontal, canvas)
        self.splitter.setObjectName("stratSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(CARD_GAP)

        self.left = PlaybackTile(self.splitter)

        # The right side stacks four tiles: the history controls on top, then
        # the run's inputs and its strategy, then the results, which take
        # whatever height is left.
        self.right = QSplitter(Qt.Orientation.Vertical, self.splitter)
        self.right.setObjectName("stratColumn")
        self.right.setChildrenCollapsible(False)
        self.right.setHandleWidth(CARD_GAP)
        self.download = DownloadTile(self.right)
        self.params = ParamsTile(self.right)
        self.strategy = StrategyTile(self.right)
        self.results = ResultsTile(self.right)
        self.right.addWidget(self.download)
        self.right.addWidget(self.params)
        self.right.addWidget(self.strategy)
        self.right.addWidget(self.results)
        # The input tiles keep only the height their content needs.
        self.right.setStretchFactor(0, 0)
        self.right.setStretchFactor(1, 0)
        self.right.setStretchFactor(2, 0)
        self.right.setStretchFactor(3, 1)
        for tile in (self.download, self.params, self.strategy):
            tile.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
            )

        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([560, 560])

        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(canvas)
        self._balanced = False

        # The left tile plays whatever the other two are set to. A change of
        # span or parameters only marks the run ready — pressing Start
        # backtest is what actually restarts it.
        self.download.span_changed.connect(self._sync_playback)
        self.params.changed.connect(self._sync_params)
        self.strategy.changed.connect(self.left.set_strategy)
        self.download.started.connect(self.left.restart)
        self.left.restarted.connect(self.results.set_session)
        self.left.advanced.connect(self.results.refresh)
        self._sync_playback()
        self._sync_params()
        self.left.set_strategy(self.strategy.rule())

    def _sync_playback(self) -> None:
        start, end, resolution = self.download.span()
        self.left.set_source(list(range(start, end + 1)), resolution)
    def _sync_params(self) -> None:
        self.left.set_params(self.params.params())

    def showEvent(self, event) -> None:  # noqa: N802
        """Fit the upper tiles to their content once the real size is known."""
        super().showEvent(event)
        if self._balanced:
            return
        self._balanced = True
        tops = [tile.sizeHint().height() for tile in self._input_tiles()]
        rest = max(2, self.right.height() - sum(tops) - 3 * CARD_GAP)
        self.right.setSizes([*tops, rest])

    def _input_tiles(self) -> tuple:
        return (self.download, self.params, self.strategy)
