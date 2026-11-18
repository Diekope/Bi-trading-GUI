"""Entry point for the blank backtest/strategy window."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from bi_trading.logs import install_qt_handler, setup
from bi_trading.state.settings import ensure_file
from bi_trading.ui.strat.strat_window import StratWindow
from bi_trading.ui.theme import apply_theme


def run(argv: list[str] | None = None) -> int:
    """Open the blank window. Returns the Qt exit code."""
    # A file, never the console: this is a GUI, not a command.
    setup()
    install_qt_handler()

    # If a stray C++ object ever takes the process down, leave a Python
    # traceback on stderr instead of a bare segfault.
    import faulthandler

    faulthandler.enable()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setApplicationName("bi-trading")
    QApplication.setOrganizationName("bi-trading")

    ensure_file()

    app = QApplication(list(sys.argv if argv is None else argv))
    apply_theme(app)

    window = StratWindow()
    from bi_trading.ui.layout_memory import remember_window

    remember_window(window, "backtest")
    from bi_trading.ui.shortcuts import bind_help

    bind_help(window, "Backtest")
    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()
