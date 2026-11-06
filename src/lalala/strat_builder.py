"""The strategy builder window, launched on its own.

Three vertical tiles side by side, splitting the width 21 / 47 / 32: a narrow
rail on the left, the working area in the middle, and a wider rail on the
right. All three are empty for now — the shape of a strategy description has
not been decided yet.

Standalone on purpose: nothing in the backtest window opens it, and nothing in
it is wired to the run, the parameters or the candle data.

    uv run lalala-builder

It carries the same canvas, cards and gap as the other windows, so it reads as
another sheet of the same desk rather than a separate application.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lalala.logs import install_qt_handler, setup
from lalala.panels import Card
from lalala.theme import CANVAS, CARD_GAP, apply_dark_theme

# The three columns, as a share of the width the tiles share between them.
COLUMN_SHARES = (0.21, 0.47, 0.32)


class StrategyBuilderWindow(QMainWindow):
    """Three empty tiles, 21 / 47 / 32, to build a strategy on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("lalala · create a strategy")
        self.setMinimumSize(560, 420)
        self.resize(1280, 720)

        canvas = QWidget(self)
        canvas.setObjectName("builderCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#builderCanvas {{ background-color: {CANVAS}; }}")

        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(CARD_GAP)

        # Vertical split: three tiles side by side, the gap doing the dividing
        # rather than a drawn line.
        self.splitter = QSplitter(Qt.Orientation.Horizontal, canvas)
        self.splitter.setObjectName("builderSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(CARD_GAP)

        self.left = Card(self.splitter)
        self.center = Card(self.splitter)
        self.right = Card(self.splitter)
        for tile in (self.left, self.center, self.right):
            self.splitter.addWidget(tile)
            # The card's default floor is too high for a 21% rail: it would
            # win the argument with the proportions at ordinary widths.
            tile.setMinimumWidth(120)
        for column in range(3):
            self.splitter.setStretchFactor(column, 1)
        self._proportions_set = False

        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(canvas)

    def column_sizes(self) -> list[int]:
        """Pixel widths that satisfy `COLUMN_SHARES`, in the current width."""
        usable = max(3, self.splitter.width() - 2 * CARD_GAP)
        left = round(usable * COLUMN_SHARES[0])
        middle = round(usable * COLUMN_SHARES[1])
        return [left, middle, usable - left - middle]

    def showEvent(self, event) -> None:  # noqa: N802
        """Lay the three tiles out once the real width is known."""
        super().showEvent(event)
        if not self._proportions_set:
            self._proportions_set = True
            self.splitter.setSizes(self.column_sizes())

    def is_open(self) -> bool:
        return self.isVisible()


def run(argv: list[str] | None = None) -> int:
    """Open the builder on its own. Returns the Qt exit code."""
    # A file, never the console, like the other windows.
    setup()
    install_qt_handler()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setApplicationName("lalala")
    QApplication.setOrganizationName("lalala")

    app = QApplication(list(sys.argv if argv is None else argv))
    apply_dark_theme(app)

    window = StrategyBuilderWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()


__all__ = ["StrategyBuilderWindow", "run"]
