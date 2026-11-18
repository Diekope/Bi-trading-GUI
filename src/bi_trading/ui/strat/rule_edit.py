"""Edit a saved strategy's rules without leaving the backtest window.

A small dialog with the entry rule and the exit rule as text. Each is checked as
it is typed by the same parser the builder uses, so a typo is named with its line
and column, and Save is only offered for rules that parse. The builder remains the
place to build one from blocks; this is for the change you can make in a line.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bi_trading.engine.formula import (
    ENTRY_FIELDS,
    EXIT_FIELDS,
    EXIT_FUNCTIONS,
    FUNCTIONS,
    FormulaError,
    parse,
)


class RuleEditDialog(QDialog):
    """The entry and the exit rule of one saved strategy, as editable text."""

    def __init__(
        self, name: str, entry: str, exit_: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("confirmDialog")
        self.setWindowTitle(f"Edit {name}")
        self.setModal(True)
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel(f"Edit “{name}”", self)
        title.setObjectName("confirmTitle")
        layout.addWidget(title)

        self.entry_edit, self.entry_status = self._section(layout, "Entry rule", entry)
        self.exit_edit, self.exit_status = self._section(layout, "Exit rule", exit_)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("Save", self)
        self.save_button.setObjectName("saveButton")
        self.save_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.entry_edit.textChanged.connect(self._check)
        self.exit_edit.textChanged.connect(self._check)
        self._check()

    def _section(self, layout: QVBoxLayout, caption: str, text: str):
        label = QLabel(caption, self)
        label.setObjectName("confirmBody")
        layout.addWidget(label)
        edit = QPlainTextEdit(self)
        edit.setPlainText(text)
        edit.setMinimumHeight(70)
        layout.addWidget(edit, 1)
        status = QLabel("", self)
        status.setObjectName("hintLabel")
        layout.addWidget(status)
        return edit, status

    def entry(self) -> str:
        return self.entry_edit.toPlainText().strip()

    def exit(self) -> str:
        return self.exit_edit.toPlainText().strip()

    @staticmethod
    def problem(text: str, exit_rule: bool) -> str:
        """Why `text` does not parse, or "" when it does (an empty exit is fine)."""
        if not text.strip():
            return "" if exit_rule else "an entry rule is needed"
        try:
            if exit_rule:
                parse(text, EXIT_FIELDS, EXIT_FUNCTIONS)
            else:
                parse(text, ENTRY_FIELDS, FUNCTIONS)
        except FormulaError as exc:
            return str(exc)
        return ""

    def _check(self) -> None:
        entry = self.problem(self.entry(), exit_rule=False)
        exit_ = self.problem(self.exit(), exit_rule=True)
        self.entry_status.setText(entry or "✓ valid")
        self.exit_status.setText(exit_ or "✓ valid")
        self.save_button.setEnabled(not entry and not exit_)


__all__ = ["RuleEditDialog"]
