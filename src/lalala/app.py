from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from lalala.main_window import MainWindow
from lalala.theme import apply_dark_theme


def run(argv: list[str] | None = None) -> int:
    """Start the terminal. Returns the Qt exit code."""
    # Qt 6 handles HiDPI scaling natively; this only opts out of rounding
    # artefacts on fractional-scaled external displays.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setApplicationName("lalala")
    QApplication.setOrganizationName("lalala")

    app = QApplication(list(sys.argv if argv is None else argv))
    apply_dark_theme(app)

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()
