"""The bar under the terminal: which strategy is armed, its reading, and a bet.

It ties the two panels together — the strategy's close / band / signal from the
candle chart, and the two sides' prices from the Polymarket panel — with the
size and the two bet buttons the mock draws.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from lalala.cards import mono_font
from lalala.panels import Card
from lalala.theme import DOWN_SOFT, TEXT_MUTED, UP

STRATEGIES = ("Bollinger reversion", "Random buy")


class StrategyBar(Card):
    """ARMED chip, the strategy's current reading, size and the two bets."""

    bet = Signal(str)  # "up" | "down"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("strategyBar", )
        self.setProperty("bar", True)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)

        label = QLabel("Strategy")
        label.setObjectName("gl")
        self.picker = QComboBox()
        self.picker.setObjectName("strategySelect")
        self.picker.addItems(STRATEGIES)
        self.picker.setFixedWidth(190)
        self.armed = QLabel("armed")
        self.armed.setObjectName("armedChip")
        row.addWidget(label)
        row.addWidget(self.picker)
        row.addWidget(self.armed)

        # The strategy's reading on the newest bar.
        reading = QHBoxLayout()
        reading.setContentsMargins(0, 0, 0, 0)
        reading.setSpacing(16)
        self.close_label = self._reading("close", "—", reading)
        self.band_label = self._reading("band", "—", reading)
        self.signal_label = self._reading("signal", "—", reading)
        self.signal_label.setProperty("state", "off")
        row.addLayout(reading)

        self.note = QLabel("Position : none")
        self.note.setObjectName("gl")
        row.addWidget(self.note, 1)

        self.auto = QCheckBox("Auto-bet")
        self.auto.setObjectName("overlayToggle")
        self.auto.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.auto)

        self.size = QLineEdit("$20")
        self.size.setObjectName("numberEdit")
        self.size.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.size.setFixedWidth(80)
        row.addWidget(self.size)

        self.bet_up = QPushButton("Bet UP —")
        self.bet_up.setObjectName("betUp")
        self.bet_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bet_up.clicked.connect(lambda: self.bet.emit("up"))
        self.bet_down = QPushButton("Bet DOWN —")
        self.bet_down.setObjectName("betDown")
        self.bet_down.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bet_down.clicked.connect(lambda: self.bet.emit("down"))
        row.addWidget(self.bet_up)
        row.addWidget(self.bet_down)

        self.body.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("gl")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

    def set_status(self, text: str, tone: str = "info") -> None:
        self.status.setText(text)
        colour = {"ok": UP, "error": DOWN_SOFT}.get(tone, TEXT_MUTED)
        self.status.setStyleSheet(f"color: {colour};")

    def _reading(self, caption: str, value: str, layout: QHBoxLayout) -> QLabel:
        box = QHBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        key = QLabel(caption)
        key.setObjectName("gl")
        shown = QLabel(value)
        shown.setObjectName("readingValue")
        shown.setFont(mono_font(10, bold=True))
        box.addWidget(key)
        box.addWidget(shown)
        layout.addLayout(box)
        return shown

    def set_reading(self, close: float | None, band: float | None) -> None:
        self.close_label.setText("—" if close is None else f"{close:,.1f}")
        self.band_label.setText("—" if band is None else f"{band:,.1f}")
        holds = close is not None and band is not None and close < band
        self.signal_label.setText("TRUE" if holds else "FALSE")
        state = "on" if holds else "off"
        if self.signal_label.property("state") != state:
            self.signal_label.setProperty("state", state)
            style = self.signal_label.style()
            style.unpolish(self.signal_label)
            style.polish(self.signal_label)

    def set_bets(self, up: float | None, down: float | None) -> None:
        self.bet_up.setText("Bet UP —" if up is None else f"Bet UP {up * 100:.0f}¢")
        self.bet_down.setText(
            "Bet DOWN —" if down is None else f"Bet DOWN {down * 100:.0f}¢"
        )

    def strategy(self) -> str:
        return self.picker.currentText()

    def bet_size(self) -> str:
        return self.size.text().strip()

    def auto_bet(self) -> bool:
        return self.auto.isChecked()


__all__ = ["STRATEGIES", "StrategyBar"]
