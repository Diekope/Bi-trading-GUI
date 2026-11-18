"""The keyboard shortcuts in one place, and the overlay that lists them.

`SHORTCUTS` is the list the help overlay shows (press **?** or **F1** in the hub or
any window). A view binds its own keys with `bind`, which limits them to that
view, so Ctrl+S in the builder never reaches the Logs. Keys that only act when
no field has focus (the backtest's Space and R) are documented here but handled
where the key arrives, in the window.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bi_trading.ui.cards import mono_font

# context -> (keys, what it does). The order is the order the overlay shows.
SHORTCUTS: dict[str, tuple[tuple[str, str], ...]] = {
    "Everywhere": (
        ("Ctrl+1 … Ctrl+5", "Home, Live, Builder, Backtest, Logs"),
        ("Ctrl+,", "Settings"),
        ("? or F1", "this list"),
    ),
    "Live": (
        ("1 … 6", "timeframe: 1m, 3m, 5m, 15m, 30m, 1h"),
        ("← →  ·  Shift", "pan the chart one candle (ten with Shift)"),
        ("↑ ↓", "zoom the time range"),
        ("Home · End · 0", "oldest candle · back to the live edge"),
    ),
    "Backtest": (
        ("Space", "run, pause and resume the walk"),
        ("R", "restart the walk"),
        ("1 … 6", "resolution: 1m, 3m, 5m, 15m, 30m, 1h"),
    ),
    "Builder": (
        ("Ctrl+S", "save the strategy"),
        ("Ctrl+N", "a fresh draft (the same as Reset)"),
        ("Alt+1 · Alt+2 · Alt+3", "the rule as Rules · Formula · Code"),
    ),
    "Logs": (
        ("Ctrl+F  or  /", "search the log"),
        ("Esc", "clear the search"),
        ("Ctrl+P", "pause and resume the table"),
        ("Ctrl+E", "export to CSV"),
        ("Ctrl+Shift+Backspace", "clear the log (no confirm, so it is hard to hit)"),
    ),
}

# The view a hub rail key opens, as the context to put first in the overlay.
CONTEXT_OF_VIEW = {
    "home": "Everywhere",
    "live": "Live",
    "builder": "Builder",
    "backtest": "Backtest",
    "logs": "Logs",
    "settings": "Everywhere",
}


def bind(
    widget: QWidget, keys: str, action: Callable[[], object]
) -> QShortcut:
    """`keys` calls `action` while focus is anywhere inside `widget`."""
    shortcut = QShortcut(QKeySequence(keys), widget)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(action)
    return shortcut


class ShortcutsDialog(QDialog):
    """Every shortcut, with the current view's first."""

    def __init__(self, current: str = "Everywhere", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("confirmDialog")
        self.setWindowTitle("Keyboard shortcuts")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        title = QLabel("Keyboard shortcuts", self)
        title.setObjectName("confirmTitle")
        layout.addWidget(title)

        order = [current] + [name for name in SHORTCUTS if name != current]
        self.sections = [name for name in order if name in SHORTCUTS]
        for name in self.sections:
            heading = QLabel(name.upper() + ("  ·  this view" if name == current else ""), self)
            heading.setObjectName("confirmBody")
            layout.addWidget(heading)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(3)
            for row, (keys, what) in enumerate(SHORTCUTS[name]):
                key_label = QLabel(keys, self)
                key_label.setFont(mono_font(10, bold=True))
                key_label.setMinimumWidth(210)   # one column of descriptions for all
                grid.addWidget(key_label, row, 0)
                grid.addWidget(QLabel(what, self), row, 1)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close", self)
        close.setObjectName("ghostButton")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)


def show_help(parent: QWidget | None, current: str = "Everywhere") -> ShortcutsDialog:
    dialog = ShortcutsDialog(current, parent)
    dialog.open()
    return dialog


def bind_help(window: QWidget, current: Callable[[], str] | str = "Everywhere") -> None:
    """Open the overlay on **?** and **F1**. `current` names the view in front."""

    def open_it() -> None:
        show_help(window, current() if callable(current) else current)

    for keys in ("?", "F1"):
        shortcut = QShortcut(QKeySequence(keys), window)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(open_it)


__all__ = [
    "CONTEXT_OF_VIEW",
    "SHORTCUTS",
    "ShortcutsDialog",
    "bind",
    "bind_help",
    "show_help",
]
