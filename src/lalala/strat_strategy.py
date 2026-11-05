"""The strategy tile: which entry rule the run is pointed at.

Two so far. Random buy stays in the list on purpose — it is the baseline an
entry rule has to beat, not a fallback. Bollinger reversion buys when a close
falls below the lower band of a 20-bar, 2σ channel.

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

from lalala.panels import Card
from lalala.strat_playback import DEFAULT_STRATEGY, STRATEGIES, strategy_label


class StrategyTile(Card):
    """Pick the entry rule, and offer to build a new one."""

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("STRATEGY")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        self.picker = QComboBox()
        self.picker.setObjectName("strategySelect")
        for _, label, note in STRATEGIES:
            self.picker.addItem(label)
            self.picker.setItemData(
                self.picker.count() - 1, note, Qt.ItemDataRole.ToolTipRole
            )
        self.picker.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        # A placeholder: building a strategy is a bigger job than this tile,
        # and the window it will open stands on its own for now.
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

    def _apply(self, rule: str, note: str | None = None) -> None:
        if note is None:
            note = next(
                (text for key, _, text in STRATEGIES if key == rule), ""
            )
        self.note.setText(note)


__all__ = ["StrategyTile"]
