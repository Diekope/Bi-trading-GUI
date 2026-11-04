"""A blank second window, the starting point for the backtest/strategy work.

Nothing is drawn yet: it exists so the backtest and strategy screens have a
place to grow, beside the live terminal rather than inside it. It shares the
shell's theme and sizing, so the two windows read as one product.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QWidget

from lalala.theme import CANVAS


class StratWindow(QMainWindow):
    """Empty dark window. Fill it with the backtest and strategy panels."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("lalala · backtest + strategy")
        self.setMinimumSize(620, 520)
        self.resize(1180, 760)

        canvas = QWidget(self)
        canvas.setObjectName("stratCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#stratCanvas {{ background-color: {CANVAS}; }}")
        self.setCentralWidget(canvas)
