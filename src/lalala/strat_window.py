"""A blank second window, the starting point for the backtest/strategy work.

Nothing is drawn yet: it exists so the backtest and strategy screens have a
place to grow, beside the live terminal rather than inside it. It splits in
half — two empty floating cards on the same canvas — so the two screens have
their own side, and it shares the shell's theme and gap, so the windows read
as one product.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter, QVBoxLayout, QWidget

from lalala.panels import Card
from lalala.strat_tiles import DownloadTile
from lalala.theme import CANVAS, CARD_GAP


class StratWindow(QMainWindow):
    """Empty dark window, split in two. Fill the halves with the screens."""

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

        self.left = Card(self.splitter)

        # The right side stacks two tiles: the data controls on top, a second
        # tile underneath for whatever it feeds.
        self.right = QSplitter(Qt.Orientation.Vertical, self.splitter)
        self.right.setObjectName("stratColumn")
        self.right.setChildrenCollapsible(False)
        self.right.setHandleWidth(CARD_GAP)
        self.download = DownloadTile(self.right)
        self.blank = Card(self.right)
        self.right.addWidget(self.download)
        self.right.addWidget(self.blank)
        self.right.setStretchFactor(0, 0)
        self.right.setStretchFactor(1, 1)
        self.right.setSizes([220, 400])

        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([560, 560])

        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(canvas)
