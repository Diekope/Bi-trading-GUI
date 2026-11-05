"""The strategy builder: a blank window, opened from the STRATEGY tile.

Deliberately empty for now. It exists so the rest of the window can point at
something real instead of a dead button, and so the parts of a strategy — entry
rule, exits, filters — have a place to land one at a time. It carries the same
canvas and gap as the backtest window, so it reads as another sheet of the same
desk rather than a separate application.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from lalala.theme import CANVAS, CARD_GAP, TEXT_FAINT


class StrategyBuilderWindow(QMainWindow):
    """An empty sheet to build a strategy on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("lalala · create a strategy")
        self.setMinimumSize(520, 420)
        self.resize(880, 640)

        canvas = QWidget(self)
        canvas.setObjectName("builderCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#builderCanvas {{ background-color: {CANVAS}; }}")

        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(CARD_GAP)

        # One line, faint and centred: the window is the point, not its text.
        self.placeholder = QLabel("nothing here yet")
        self.placeholder.setObjectName("builderPlaceholder")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(f"color: {TEXT_FAINT};")
        layout.addWidget(self.placeholder, 1)

        self.setCentralWidget(canvas)

    def is_open(self) -> bool:
        return self.isVisible()


__all__ = ["StrategyBuilderWindow"]
