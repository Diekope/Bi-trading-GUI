"""The trade form under a market's chart: size, leverage, buy/sell, position.

Following LiveViewTrade.dc.html — a size field with 25/50/100% shortcuts, a
leverage slider with the margin and liquidation it implies, the two side
buttons, and a row for whatever position is open. Nothing here sends an order
yet; it is the shape the mock draws, with the numbers kept in step with the
latest price.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from lalala.theme import UP

# What the shortcut buttons scale, in dollars.
BASE_USD = 10_000.0
MAX_LEVERAGE = 20


def _size(text: str) -> float:
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return max(0.0, float(cleaned))
    except ValueError:
        return 0.0


class TradeForm(QWidget):
    """Size, leverage and the two sides, with the open position below."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tradeForm")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        from lalala.cards import mono_font
        from lalala.settings import Settings

        defaults = Settings.load().trading
        self.price: float | None = None
        self._position: dict | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(12)

        top = QGridLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setHorizontalSpacing(16)
        top.setVerticalSpacing(6)

        size_label = QLabel("Size (USD)")
        size_label.setObjectName("gl")
        self.size = QLineEdit(f"${defaults.size:,.0f}")
        self.size.setObjectName("numberEdit")
        self.size.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.size.textChanged.connect(self._refresh)
        top.addWidget(size_label, 0, 0)
        top.addWidget(self.size, 0, 1)

        shortcuts = QHBoxLayout()
        shortcuts.setContentsMargins(0, 0, 0, 0)
        shortcuts.setSpacing(4)
        for percent in (25, 50, 100):
            button = QPushButton(f"{percent}%")
            button.setObjectName("ghostButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, p=percent: self.set_size_share(p)
            )
            shortcuts.addWidget(button, 1)
        top.addLayout(shortcuts, 1, 0, 1, 2)

        leverage_row = QHBoxLayout()
        leverage_row.setContentsMargins(0, 0, 0, 0)
        lev_label = QLabel("Leverage")
        lev_label.setObjectName("gl")
        self.leverage_value = QLabel(
            f"{max(1, min(MAX_LEVERAGE, defaults.leverage))}×"
        )
        self.leverage_value.setObjectName("readingValue")
        self.leverage_value.setFont(mono_font(10, bold=True))
        leverage_row.addWidget(lev_label)
        leverage_row.addStretch(1)
        leverage_row.addWidget(self.leverage_value)
        top.addLayout(leverage_row, 0, 2)

        self.leverage = QSlider(Qt.Orientation.Horizontal)
        self.leverage.setObjectName("leverageSlider")
        self.leverage.setRange(1, MAX_LEVERAGE)
        self.leverage.setValue(max(1, min(MAX_LEVERAGE, defaults.leverage)))
        self.leverage.valueChanged.connect(self._refresh)
        top.addWidget(self.leverage, 1, 2)

        self.margin_label = QLabel("Margin —")
        self.margin_label.setObjectName("gl")
        self.liq_label = QLabel("Liq. —")
        self.liq_label.setObjectName("gl")
        top.addWidget(self.margin_label, 2, 2)
        top.addWidget(self.liq_label, 2, 3)
        column.addLayout(top)

        sides = QHBoxLayout()
        sides.setContentsMargins(0, 0, 0, 0)
        sides.setSpacing(8)
        self.buy = QPushButton("Buy / Long")
        self.buy.setObjectName("buyButton")
        self.buy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.buy.clicked.connect(lambda: self.open_position("LONG"))
        self.sell = QPushButton("Sell / Short")
        self.sell.setObjectName("sellButton")
        self.sell.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sell.clicked.connect(lambda: self.open_position("SHORT"))
        sides.addWidget(self.buy, 1)
        sides.addWidget(self.sell, 1)
        column.addLayout(sides)

        self.position_row = QWidget(self)
        self.position_row.setObjectName("positionRow")
        self.position_row.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        row = QHBoxLayout(self.position_row)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)
        self.position_label = QLabel("")
        self.position_label.setObjectName("positionText")
        self.position_label.setFont(mono_font(10, bold=True))
        self.pnl_label = QLabel("")
        self.pnl_label.setObjectName("positionPnl")
        self.pnl_label.setFont(mono_font(10, bold=True))
        close = QPushButton("Close")
        close.setObjectName("ghostButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.close_position)
        row.addWidget(self.position_label, 1)
        row.addWidget(self.pnl_label, 0)
        row.addWidget(close, 0)
        self.position_row.setVisible(False)
        column.addWidget(self.position_row)

    # -- values ------------------------------------------------------------

    def set_size_share(self, percent: int) -> None:
        self.size.setText(f"${BASE_USD * percent / 100:,.0f}")

    def set_price(self, price: float | None) -> None:
        self.price = price
        self._refresh()

    def leverage_value_int(self) -> int:
        return int(self.leverage.value())

    def margin(self) -> float:
        return _size(self.size.text()) / max(1, self.leverage.value())

    def open_position(self, side: str) -> None:
        self._position = {
            "side": side,
            "leverage": self.leverage.value(),
            "size": _size(self.size.text()),
            "entry": self.price,
        }
        self._refresh()

    def close_position(self) -> None:
        self._position = None
        self._refresh()

    def position(self) -> dict | None:
        return self._position

    # -- drawing -----------------------------------------------------------

    def _refresh(self) -> None:
        leverage = max(1, self.leverage.value())
        self.leverage_value.setText(f"{leverage}×")
        self.margin_label.setText(f"Margin ${self.margin():,.0f}")
        if self.price and self.price > 0:
            liq = self.price * (1.0 - 1.0 / leverage)
            self.liq_label.setText(f"Liq. {liq:,.0f}")
        else:
            self.liq_label.setText("Liq. —")

        position = self._position
        self.position_row.setVisible(position is not None)
        if position is None:
            return
        self.position_label.setText(
            f"{position['side']} {position['leverage']}× · "
            f"${position['size']:,.0f}"
        )
        change = self._change(position)
        if change is None:
            self.pnl_label.setText("—")
            self.pnl_label.setStyleSheet("")
            return
        sign = "+" if change >= 0 else "−"
        arrow = "▲" if change >= 0 else "▼"
        self.pnl_label.setText(f"{arrow}{sign}${abs(change):,.2f}")
        colour = UP if change >= 0 else "#ff5c5c"
        self.pnl_label.setStyleSheet(f"color: {colour};")

    def _change(self, position: dict) -> float | None:
        entry = position["entry"]
        if not entry or not self.price:
            return None
        direction = 1.0 if position["side"] == "LONG" else -1.0
        return (
            (self.price / entry - 1.0)
            * position["size"]
            * position["leverage"]
            * direction
        )


__all__ = ["BASE_USD", "MAX_LEVERAGE", "TradeForm"]
