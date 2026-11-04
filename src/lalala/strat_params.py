"""The backtest parameters tile.

Only the inputs so far: take profit, stop loss, an optional dynamic take
profit, the share of capital a position may use, and the share of capital that
may sit in cash (everything above it is meant to be parked in a cold wallet).
Nothing here feeds a run yet.
"""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.panels import Card

# Field defaults: a couple of percent either way, a tenth of the book per
# trade, and most of the balance allowed to sit in cash.
DEFAULTS = {
    "tp": "2.0",
    "sl": "1.0",
    "position": "10.0",
    "cash": "20.0",
}


class ParamsTile(Card):
    """Take profit / stop loss / sizing, laid out as labelled fields."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("BACKTEST")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        self.tp_field = self._field("tp", 0.0, 10_000.0)
        self.sl_field = self._field("sl", 0.0, 100.0)
        self.position_field = self._field("position", 0.0, 100.0)
        self.cash_field = self._field("cash", 0.0, 100.0)

        for row, (label, field) in enumerate(
            (
                ("TP %", self.tp_field),
                ("SL %", self.sl_field),
                ("Position %", self.position_field),
                ("Max cash %", self.cash_field),
            )
        ):
            grid.addWidget(self._label(label), row, 0)
            grid.addWidget(field, row, 1)

        self.body.addLayout(grid)

        self.dynamic_tp = QCheckBox("Dynamic TP")
        self.dynamic_tp.setObjectName("paramToggle")
        self.dynamic_tp.setToolTip("Let the take profit trail as price runs")
        self.dynamic_tp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body.addWidget(self.dynamic_tp)

        hint = QLabel("Cash above the cap is meant for the cold wallet.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        self.body.addWidget(hint)

        self.body.addStretch(1)

    # -- values ------------------------------------------------------------

    def params(self) -> dict[str, object]:
        """What the run would read: numbers, plus the on/off switch."""
        return {
            "tp": _number(self.tp_field.text()),
            "sl": _number(self.sl_field.text()),
            "position": _number(self.position_field.text()),
            "cash": _number(self.cash_field.text()),
            "dynamic_tp": self.dynamic_tp.isChecked(),
        }

    # -- widgets -----------------------------------------------------------

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _field(self, key: str, low: float, high: float) -> QLineEdit:
        field = QLineEdit(DEFAULTS[key])
        field.setObjectName("paramField")
        validator = QDoubleValidator(low, high, 2, field)
        # Always a dot for the decimal mark, whatever the system locale says,
        # so what is typed here parses the same way everywhere.
        validator.setLocale(QLocale.c())
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        field.setValidator(validator)
        field.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        field.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        return field


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None
