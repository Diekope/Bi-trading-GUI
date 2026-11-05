"""The strategy builder window, launched on its own.

Blank on purpose, and standalone: nothing in the backtest window opens it yet,
and nothing in it is wired to the run, the parameters or the candle data. The
**Create a strategy** button stays a placeholder until the shape of a strategy
is settled here.

    uv run lalala-builder

It carries the same canvas and gap as the backtest window, so it reads as
another sheet of the same desk rather than a separate application.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from lalala.logs import install_qt_handler, setup
from lalala.theme import CANVAS, CARD_GAP, TEXT_FAINT, apply_dark_theme


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
