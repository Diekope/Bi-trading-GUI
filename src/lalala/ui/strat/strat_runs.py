"""Two small tiles for saved runs: one to save the current run, one to open it.

A run remembers the span, resolution, parameters, strategy and every trade
(`runs.py`), so a saved one can be opened and looked at again.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from lalala.state import runs
from lalala.ui.panels import Card


class SaveRunTile(Card):
    """Name the run and keep it."""

    save_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("SAVE RUN")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        self.name = QLineEdit()
        self.name.setObjectName("runName")
        self.name.setPlaceholderText("run name")
        self.button = QPushButton("Save run")
        self.button.setObjectName("saveRun")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._on_save)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.name, 1)
        row.addWidget(self.button)
        self.body.addLayout(row)

        self.note = QLabel("")
        self.note.setObjectName("hintLabel")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)

    def _on_save(self) -> None:
        name = self.name.text().strip()
        if name:
            self.save_requested.emit(name)

    def set_saved(self, name: str) -> None:
        self.name.setText(name)
        self.note.setText(f"saved · {name}")


class LoadRunTile(Card):
    """Pick a saved run and open it."""

    load_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("LOAD RUN")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        self.picker = QComboBox()
        self.picker.setObjectName("runsSelect")
        self.button = QPushButton("Load")
        self.button.setObjectName("loadRun")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(
            lambda: self.load_requested.emit(self.picker.currentText())
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.picker, 1)
        row.addWidget(self.button)
        self.body.addLayout(row)

        self.note = QLabel("")
        self.note.setObjectName("hintLabel")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)

        self.refresh()

    def refresh(self) -> None:
        current = self.picker.currentText()
        self.picker.clear()
        for item in runs.load():
            self.picker.addItem(item.name)
        index = self.picker.findText(current)
        if index >= 0:
            self.picker.setCurrentIndex(index)
        self.button.setEnabled(self.picker.count() > 0)
        self.note.setText("" if self.picker.count() else "no saved runs yet")


__all__ = ["LoadRunTile", "SaveRunTile"]
