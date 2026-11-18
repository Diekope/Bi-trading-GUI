"""Remember where the splitters and the windows were left.

    remember_splitter(splitter, "terminal.columns")   # restore now, save on drag
    remember_window(window, "backtest")               # restore now, save on quit

Splitters are saved as ratios a moment after the user stops dragging, so a
different window size still gets the same split. Nothing here can fail loudly:
an unreadable or missing setting just leaves the default layout.
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import QByteArray, QTimer
from PySide6.QtWidgets import QApplication, QSplitter, QWidget

from bi_trading.state.settings import (
    load_splitter,
    load_window,
    save_splitter,
    save_window,
)

SAVE_AFTER_MS = 400


def remember_splitter(splitter: QSplitter, name: str) -> None:
    """Restore `splitter`'s split from last time, and keep saving it as it moves."""
    ratios = load_splitter(name)
    if len(ratios) == splitter.count():
        splitter.setSizes([max(1, round(ratio * 10_000)) for ratio in ratios])

    timer = QTimer(splitter)
    timer.setSingleShot(True)
    timer.setInterval(SAVE_AFTER_MS)
    timer.timeout.connect(lambda: save_splitter(name, splitter.sizes()))
    splitter.splitterMoved.connect(lambda *_: timer.start())


def remember_window(window: QWidget, name: str, app: QApplication | None = None) -> None:
    """Restore a standalone window's size and place, and save them when the app quits."""
    saved = load_window(name)
    if saved:
        window.restoreGeometry(QByteArray.fromBase64(saved.encode()))
    app = app or QApplication.instance()  # type: ignore[assignment]
    if app is not None:
        app.aboutToQuit.connect(lambda: save_current_window(window, name))


def save_current_window(window: QWidget, name: str) -> None:
    with contextlib.suppress(RuntimeError):  # the window is already gone
        save_window(name, bytes(window.saveGeometry().toBase64().data()).decode("ascii"))


__all__ = ["remember_splitter", "remember_window", "save_current_window"]
