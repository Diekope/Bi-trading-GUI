"""Entry point for the blank backtest/strategy window."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from lalala.settings import ensure_file
from lalala.strat_window import StratWindow
from lalala.theme import apply_dark_theme


def run(argv: list[str] | None = None) -> int:
    """Open the blank window. Returns the Qt exit code."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setApplicationName("lalala")
    QApplication.setOrganizationName("lalala")

    ensure_file()

    app = QApplication(list(sys.argv if argv is None else argv))
    apply_dark_theme(app)

    window = StratWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()
