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

from bi_trading.state import strategies
from bi_trading.ui.panels import Card
from bi_trading.ui.strat.strat_playback import DEFAULT_STRATEGY, STRATEGIES, strategy_label


class StrategyTile(Card):
    """Pick the entry rule — built-in or saved — and offer to build a new one."""

    changed = Signal(str)
    saved_picked = Signal(object)
    # The Create button: open the builder (the window decides where).
    create_requested = Signal()

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
        self.create_button.setToolTip("Open the strategy builder")
        self.create_button.clicked.connect(self.create_requested)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.picker, 1)
        row.addWidget(self.create_button)
        self.body.addLayout(row)

        # A saved strategy's rules can be changed here, in a line or two. The button
        # shares the note's row, so the tile keeps its height.
        self.edit_button = QPushButton("Edit rules")
        self.edit_button.setObjectName("ghostButton")
        self.edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_button.setToolTip("Change the picked strategy's entry and exit rule")
        self.edit_button.setEnabled(False)
        self.edit_button.clicked.connect(self._ask_edit)

        self.note = QLabel("")
        self.note.setObjectName("hintLabel")
        self.note.setWordWrap(True)
        note_row = QHBoxLayout()
        note_row.setContentsMargins(0, 0, 0, 0)
        note_row.setSpacing(8)
        note_row.addWidget(self.note, 1)
        note_row.addWidget(self.edit_button, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(note_row)

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

    def picked_saved(self):
        """The saved strategy on show, or None for a built-in."""
        label = self.picker.currentText()
        return next((item for item in self.saved if item.name == label), None)

    def _ask_edit(self) -> None:
        item = self.picked_saved()
        if item is None:
            return
        from bi_trading.ui.strat.rule_edit import RuleEditDialog

        dialog = RuleEditDialog(item.name, item.entry, item.exit, self)
        if dialog.exec():
            self.save_rules(dialog.entry(), dialog.exit())

    def save_rules(self, entry: str, exit_: str):
        """Keep new rules for the picked saved strategy and point the run at them."""
        item = self.picked_saved()
        if item is None:
            return None
        from dataclasses import replace

        updated = replace(item, entry=entry, exit=exit_)
        strategies.save(updated)
        self.refresh_saved()
        self.note.setText(f"saved · {updated.entry}")
        self.saved_picked.emit(updated)
        return updated

    def _on_picked(self, label: str) -> None:
        self.edit_button.setEnabled(any(item.name == label for item in self.saved))
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
