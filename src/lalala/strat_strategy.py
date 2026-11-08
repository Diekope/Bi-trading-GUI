"""The strategy tile: which entry rule the run is pointed at.

Two built-ins — **Random buy** (the no-edge baseline, kept on purpose) and
**Bollinger reversion** — followed by every **saved strategy** from
`strategies.json`. Picking a saved one points the run at its entry rule: the
rule is checked over the whole span and the walk opens on the bars it fires on.

Only BTC is in scope, so nothing here names a market. The choice is remembered
and picked up when the run is started, like the span and the parameters.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from lalala import strategies
from lalala.panels import Card
from lalala.strat_playback import DEFAULT_STRATEGY, STRATEGIES, strategy_label


class StrategyTile(Card):
    """Pick the entry rule — built-in or saved — and offer to build a new one."""

    changed = Signal(str)
    saved_picked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("STRATEGY")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        self.picker = QComboBox()
        self.picker.setObjectName("strategySelect")
        self.picker.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.saved: list = []
        self._fill_picker()

        self.create_button = QPushButton("Create a strategy")
        self.create_button.setObjectName("createStrategy")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.setMinimumHeight(36)
        self.create_button.setToolTip("Not wired up yet")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.picker, 1)
        row.addWidget(self.create_button)
        self.body.addLayout(row)

        self.note = QLabel("")
        self.note.setObjectName("hintLabel")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)

        # The first item is not the default; say which one is.
        self.picker.setCurrentText(strategy_label(DEFAULT_STRATEGY))
        self._apply(DEFAULT_STRATEGY)
        self.picker.currentTextChanged.connect(self._on_picked)

    # -- the list ----------------------------------------------------------

    def _fill_picker(self) -> None:
        """The built-ins, then every saved strategy."""
        self.picker.blockSignals(True)
        self.picker.clear()
        for _, label, note in STRATEGIES:
            self.picker.addItem(label)
            self.picker.setItemData(
                self.picker.count() - 1, note, Qt.ItemDataRole.ToolTipRole
            )
        self.saved = strategies.load()
        if self.saved:
            self.picker.insertSeparator(self.picker.count())
            for item in self.saved:
                self.picker.addItem(item.name)
                self.picker.setItemData(
                    self.picker.count() - 1,
                    f"saved strategy · {item.entry}",
                    Qt.ItemDataRole.ToolTipRole,
                )
        self.picker.blockSignals(False)

    def refresh_saved(self) -> None:
        """Re-read the saved list, keeping the current pick if it is there."""
        current = self.picker.currentText()
        self._fill_picker()
        index = self.picker.findText(current)
        if index >= 0:
            self.picker.setCurrentIndex(index)

    # -- values ------------------------------------------------------------

    def rule(self) -> str:
        for key, label, _ in STRATEGIES:
            if label == self.picker.currentText():
                return key
        return DEFAULT_STRATEGY

    def set_rule(self, rule: str) -> None:
        for key, label, note in STRATEGIES:
            if key == rule:
                self.picker.setCurrentText(label)
                self._apply(key, note)
                return

    def _on_picked(self, label: str) -> None:
        for key, text, note in STRATEGIES:
            if text == label:
                self._apply(key, note)
                self.changed.emit(key)
                return
        for item in self.saved:
            if item.name == label:
                self.note.setText(f"saved · {item.entry}")
                self.saved_picked.emit(item)
                return

    def _apply(self, rule: str, note: str | None = None) -> None:
        if note is None:
            note = next(
                (text for key, _, text in STRATEGIES if key == rule), ""
            )
        self.note.setText(note)


__all__ = ["StrategyTile"]
