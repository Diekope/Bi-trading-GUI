"""The backtest parameters tile.

A gallery of small labelled fields — three or four to a line depending on
width — holding what a run would need: the book size, how a position is sized,
take profit and stop loss, the cash cap, and the dynamic take-profit switch
with the pull-back that closes it.

Only BTC is in scope, so nothing here names a market. Nothing feeds a run yet;
the starting values come from `settings.backtest` (see `lalala.settings`).
"""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.panels import Card
from lalala.settings import SIZING_MODES, Settings

# What the position value means in each mode: caption, bounds, unit.
SIZING = {
    "balance": ("Position %", 0.0, 100.0),
    "fixed": ("Position $", 0.0, 1e9),
    "risk": ("Risk %", 0.0, 100.0),
}
SIZING_LABELS = {
    "balance": "Balance %",
    "fixed": "Fixed $",
    "risk": "Risk %",
}

WIDE_COLUMNS = 4
NARROW_COLUMNS = 3
WIDE_AT = 520


class _Element(QWidget):
    """One gallery cell: a caption over its control."""

    def __init__(
        self, caption: str, control: QWidget, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)

        self.caption = QLabel(caption)
        self.caption.setObjectName("fieldLabel")
        box.addWidget(self.caption)
        box.addWidget(control)

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        # Gray the caption with the control it names.
        super().setEnabled(enabled)
        self.caption.setEnabled(enabled)


class ParamsTile(Card):
    """The run's inputs, laid out as a wrapping gallery."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        defaults = Settings.load().backtest

        title = QLabel("BACKTEST VALUE")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        self.initial_capital = self._field(
            defaults.initial_capital, 0.0, 1e12
        )
        self.sizing = QComboBox()
        self.sizing.setObjectName("sizingSelect")
        self.sizing.addItems([SIZING_LABELS[mode] for mode in SIZING_MODES])
        self.sizing.setCurrentText(SIZING_LABELS[defaults.sizing])
        self.sizing.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.position = self._field(defaults.position, 0.0, 100.0)
        self.tp_field = self._field(defaults.tp, 0.0, 10_000.0)
        self.sl_field = self._field(defaults.sl, 0.0, 100.0)
        self.cash_field = self._field(defaults.cash, 0.0, 1e12)

        self.dynamic_tp = QCheckBox("Enabled")
        self.dynamic_tp.setObjectName("paramToggle")
        self.dynamic_tp.setToolTip("Let the take profit trail as price runs")
        self.dynamic_tp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dynamic_tp.setChecked(defaults.dynamic_tp)
        self.dynamic_tp.setMinimumHeight(24)
        # The whole cell is the hit area, not just the little box.
        self.dynamic_tp.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.reverse_field = self._field(defaults.dyn_tp_reverse, 0.0, 100.0)

        self._elements = [
            _Element("Initial capital $", self.initial_capital),
            _Element("Sizing", self.sizing),
            _Element(SIZING[defaults.sizing][0], self.position),
            _Element("TP %", self.tp_field),
            _Element("SL %", self.sl_field),
            _Element("Max cash $", self.cash_field),
            _Element("Dynamic TP", self.dynamic_tp),
            _Element("Reverse % to close", self.reverse_field),
        ]
        self.position_element = self._elements[2]
        self.reverse_element = self._elements[7]

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(8)
        self._columns = 0
        self._reflow(WIDE_COLUMNS)

        gallery = QWidget()
        gallery.setObjectName("paramsGrid")
        gallery.setLayout(self._grid)
        self.body.addWidget(gallery)

        hint = QLabel(
            "Most cash the run may trade with; anything above it is set "
            "aside. BTC only."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        self.body.addWidget(hint)

        self._apply_sizing(defaults.sizing)
        self._apply_dynamic(defaults.dynamic_tp)

        self.sizing.currentTextChanged.connect(self._on_sizing_changed)
        self.dynamic_tp.toggled.connect(self._apply_dynamic)

    # -- values ------------------------------------------------------------

    def sizing_mode(self) -> str:
        """The mode whose label the combo is showing."""
        label = self.sizing.currentText()
        for mode, text in SIZING_LABELS.items():
            if text == label:
                return mode
        return SIZING_MODES[0]

    def params(self) -> dict[str, object]:
        """What the run would read."""
        return {
            "initial_capital": _number(self.initial_capital.text()),
            "sizing": self.sizing_mode(),
            "position": _number(self.position.text()),
            "tp": _number(self.tp_field.text()),
            "sl": _number(self.sl_field.text()),
            "cash": _number(self.cash_field.text()),
            "dynamic_tp": self.dynamic_tp.isChecked(),
            "dyn_tp_reverse": _number(self.reverse_field.text()),
        }

    # -- behavior ----------------------------------------------------------

    def _apply_sizing(self, mode: str) -> None:
        """Swap what the position field means: a share, or dollars."""
        caption, low, high = SIZING[mode]
        self.position_element.set_caption(caption)
        validator = self.position.validator()
        validator.setRange(low, high)
        value = _number(self.position.text())
        if value is not None:
            self.position.setText(_format(max(low, min(high, value))))

    def _apply_dynamic(self, enabled: bool) -> None:
        """The reverse field only means anything when the trail is on."""
        self.reverse_element.setEnabled(enabled)

    def _on_sizing_changed(self, _: str) -> None:
        self._apply_sizing(self.sizing_mode())
        self.changed.emit()

    # -- layout ------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        columns = WIDE_COLUMNS if self.width() >= WIDE_AT else NARROW_COLUMNS
        if columns != self._columns:
            self._reflow(columns)

    def _reflow(self, columns: int) -> None:
        for element in self._elements:
            self._grid.removeWidget(element)
        self._columns = columns
        for index, element in enumerate(self._elements):
            self._grid.addWidget(element, index // columns, index % columns)
        for column in range(WIDE_COLUMNS):
            self._grid.setColumnStretch(
                column, 1 if column < columns else 0
            )

    # -- widgets -----------------------------------------------------------

    def _field(self, value: float, low: float, high: float) -> QLineEdit:
        field = QLineEdit(_format(value))
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


def _format(value: float) -> str:
    """Trim a float to what a person would type."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


__all__ = ["ParamsTile", "SIZING", "SIZING_LABELS"]
