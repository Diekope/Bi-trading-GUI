from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from bi_trading.ui.main_window import MainWindow
from bi_trading.logs import install_qt_handler, setup
from bi_trading.state.settings import ensure_file
from bi_trading.ui.theme import apply_dark_theme


def run(argv: list[str] | None = None) -> int:
    """Start the terminal. Returns the Qt exit code."""
    # A file, never the console: this is a GUI, not a command.
    setup()
    install_qt_handler()

    # Qt 6 handles HiDPI scaling natively; this only opts out of rounding
    # artefacts on fractional-scaled external displays.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setApplicationName("bi-trading")
    QApplication.setOrganizationName("bi-trading")

    # First launch leaves an editable settings file behind.
    ensure_file()

    app = QApplication(list(sys.argv if argv is None else argv))
    apply_dark_theme(app)

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()
