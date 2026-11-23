"""The trade form under a market's chart: size, leverage, buy/sell, position.

Following LiveViewTrade.dc.html — a size field with 25/50/100% shortcuts, a
leverage slider with the margin and liquidation it implies, the two side
buttons, and a row for whatever position is open.

Buy / Sell place a **real** Hyperliquid order only when the venue is connected
*and* live orders are armed in Settings; otherwise they keep a paper position
and say so. Orders run off the GUI thread through `bi_trading.state.orders`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bi_trading.state.orders import HL_BTC, armed, config_for, service
from bi_trading.state.positions import store
from bi_trading.ui.badges import refresh_badge, testnet_badge
from bi_trading.ui.venue_icons import venue_mark
from bi_trading.ui.theme import UP

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
        from bi_trading.ui.cards import mono_font
        from bi_trading.state.settings import Settings

        defaults = Settings.load().trading
        self.price: float | None = None
        self.bar_enabled = True   # False once the form is laid out as a card
        # One paper position at a time, shared so it survives a view rebuild.
        self._position: dict | None = store().get()
        self._pending: str | None = None   # side of an order in flight
        self._wired = False                # the order service connected yet?
        self._fill: tuple[float, float] | None = None   # (size, dollars) of the order in flight

        # In the card, under the chart: the open positions (the design's "Paper
        # positions" strip). The order bar is a separate widget, `bar`, which the
        # terminal places in the footer under the card.
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(4)

        self.positions_head = QLabel("Paper positions")
        self.positions_head.setObjectName("gl")
        self.none_label = QLabel("none open")
        self.none_label.setObjectName("gl")
        column.addWidget(self.positions_head)
        column.addWidget(self.none_label)

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
        close.setToolTip("Close the position at once (the whole position, reduce-only, when live)")
        close.clicked.connect(self.close_clicked)
        self.close_button = close
        row.addWidget(self.position_label, 1)
        row.addWidget(self.pnl_label, 0)
        row.addWidget(close, 0)
        self.position_row.setVisible(False)
        column.addWidget(self.position_row)

        # -- the order bar: venue, coin, size, leverage, and the two sides --
        self.bar = QFrame(self)
        self.bar.setObjectName("orderBar")
        self.bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # A narrow column squeezes the bar instead of forcing the column wider.
        self.bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(10, 8, 12, 8)
        bar.setSpacing(8)

        tag = venue_mark("hl", 18)
        tag.setObjectName("venueLogo")
        coin = QLabel("BTC")
        coin.setObjectName("barCoin")
        bar.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(coin, 0, Qt.AlignmentFlag.AlignVCenter)
        size_label = QLabel("Size $")
        size_label.setObjectName("gl")
        self.size_field = QLineEdit(f"${defaults.size:,.0f}")
        self.size_field.setObjectName("numberEdit")
        self.size_field.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.size_field.setFixedWidth(64)
        self.size_field.textChanged.connect(self._refresh)
        # `size` is the name the rest of the app (and the tests) use for the
        # field; it shadows QWidget.size(), which nothing here calls.
        self.size = self.size_field  # type: ignore[method-assign,assignment]
        bar.addWidget(size_label)
        bar.addWidget(self.size_field)

        times = QLabel("x")
        times.setObjectName("gl")
        self.leverage = QSpinBox()
        self.leverage.setObjectName("leverageSpin")
        self.leverage.setRange(1, MAX_LEVERAGE)
        self.leverage.setValue(max(1, min(MAX_LEVERAGE, defaults.leverage)))
        self.leverage.setFixedWidth(56)
        self.leverage.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.leverage.valueChanged.connect(self._refresh)
        bar.addWidget(times)
        bar.addWidget(self.leverage)

        # What the old form showed beside the slider; now a tooltip on the field.
        self.leverage_value = QLabel(f"{self.leverage.value()}×", self.bar)
        self.margin_label = QLabel("Margin —", self.bar)
        self.liq_label = QLabel("Liq. —", self.bar)
        for hidden in (self.leverage_value, self.margin_label, self.liq_label):
            hidden.hide()
        # Shown only where the form is laid out as a card (see `place_panel`).
        self.info_label = QLabel("", self.bar)
        self.info_label.setObjectName("gl")
        self.info_label.setWordWrap(True)
        self.info_label.hide()

        bar.addStretch(1)
        self.status_label = QLabel("")
        self.status_label.setObjectName("gl")
        bar.addWidget(self.status_label)
        # Which network these buttons talk to, when it is not the real one.
        self.network_badge = testnet_badge(self)
        bar.addWidget(self.network_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mode_badge = QLabel("PAPER")
        self.mode_badge.setObjectName("modeBadge")
        bar.addWidget(self.mode_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self.buy = QPushButton("Buy / Long")
        self.buy.setObjectName("buyButton")
        self.buy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.buy.clicked.connect(lambda: self._trade("LONG"))
        self.sell = QPushButton("Sell / Short")
        self.sell.setObjectName("sellButton")
        self.sell.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sell.clicked.connect(lambda: self._trade("SHORT"))
        bar.addWidget(self.buy)
        bar.addWidget(self.sell)

    # -- other arrangements ------------------------------------------------

    def show_bar(self, on: bool) -> None:
        """Show or hide the order bar, unless the form lives in a card instead."""
        self.bar.setVisible(on and self.bar_enabled)

    def place_positions(self, layout) -> None:
        """Put the open-position strip in another card (the Hyperliquid screen)."""
        self.positions_head.hide()
        layout.addWidget(self.none_label)
        layout.addWidget(self.position_row)
        self.hide()   # what is left in the chart's card is empty

    def place_panel(self, layout, head) -> None:
        """Lay the form out as a card of its own instead of a bar: the same
        fields and buttons, stacked."""
        from PySide6.QtWidgets import QGridLayout

        head.addWidget(self.network_badge)
        head.addWidget(self.mode_badge)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        size_label = QLabel("Size (USD)")
        size_label.setObjectName("gl")
        leverage_label = QLabel("Leverage ×")
        leverage_label.setObjectName("gl")
        for widget in (self.size_field, self.leverage):
            widget.setFixedWidth(16_777_215)
            widget.setMinimumWidth(0)
        grid.addWidget(size_label, 0, 0)
        grid.addWidget(leverage_label, 0, 1)
        grid.addWidget(self.size_field, 1, 0)
        grid.addWidget(self.leverage, 1, 1)
        layout.addLayout(grid)
        self.info_label.show()
        self.bar_enabled = False   # the bar's job is done here
        layout.addWidget(self.info_label)
        layout.addWidget(self.status_label)
        sides = QHBoxLayout()
        sides.setContentsMargins(0, 0, 0, 0)
        sides.setSpacing(8)
        sides.addWidget(self.buy, 1)
        sides.addWidget(self.sell, 1)
        layout.addLayout(sides)
        self.bar.hide()

    # -- values ------------------------------------------------------------

    def set_size_share(self, percent: int) -> None:
        self.size_field.setText(f"${BASE_USD * percent / 100:,.0f}")

    def set_price(self, price: float | None) -> None:
        self.price = price
        self._refresh()

    def leverage_value_int(self) -> int:
        return int(self.leverage.value())

    def margin(self) -> float:
        return _size(self.size_field.text()) / max(1, self.leverage.value())

    def open_position(self, side: str) -> None:
        self._position = {
            "side": side,
            "leverage": self.leverage.value(),
            "size": _size(self.size_field.text()),
            "entry": self.price,
        }
        store().set(self._position)
        from bi_trading.state.events import event_log

        event_log().record(
            "info", "hyperliquid", "OPENED",
            f"{side} {HL_BTC.symbol} ${self._position['size']:,.0f} · "
            f"{self._position['leverage']}× · paper"
            + (f" @ {self.price:,.1f}" if self.price else ""),
            "manual",
        )
        self._refresh()

    def close_clicked(self) -> None:
        """The Close button: a real close when live orders are on, else the paper one.

        A real close reads the whole position from the venue and closes it at once,
        reduce-only and fill-or-cancel, so it never opens the other way and needs
        no size from here. No confirm dialog: it only ever shrinks what is open,
        and it should be as quick as pressing the button.
        """
        refresh_badge(self.network_badge)
        if config_for("hyperliquid") is None or not armed():
            self.close_position()
            return
        self._pending = "CLOSE"
        self._status("closing…")
        svc = service()
        if not self._wired:
            svc.placed.connect(self._on_placed)
            svc.failed.connect(self._on_failed)
            svc.filled.connect(self._on_filled)
            self._wired = True
        svc.close_position(
            "hyperliquid", HL_BTC, config_for("hyperliquid") or {}, self.price
        )

    def close_position(self) -> None:
        position, self._position = self._position, None
        store().set(None)
        if position is not None:
            from bi_trading.state.events import event_log
            from bi_trading.state.positions import change

            pnl = change(position, self.price)
            sign = "" if pnl is None else f" · {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f}"
            event_log().record(
                "info", "hyperliquid", "CLOSED",
                f"Close {position['side']} {HL_BTC.symbol} · paper"
                + (f" @ {self.price:,.1f}" if self.price else "") + sign,
                "manual", pnl=None if pnl is None else round(pnl, 2),
            )
        self._refresh()

    def position(self) -> dict | None:
        return self._position

    # -- orders ------------------------------------------------------------

    def _trade(self, side: str) -> None:
        """Buy/Sell: a real order when armed and connected, else paper."""
        from bi_trading.state.settings import Settings

        price = self.price
        usd = _size(self.size_field.text())
        if not price or price <= 0:
            self._status("waiting for a price…")
            return
        if usd <= 0:
            self._status("enter a size first")
            return

        if config_for("hyperliquid") is None:
            self.open_position(side)
            self._status("not connected — paper position only")
            return
        if not armed():
            self.open_position(side)
            self._status("dry run — paper position (arm live orders in Settings)")
            return

        if Settings.load().trading.confirm_orders and not self._confirm(side, usd, price):
            return

        buy = side == "LONG"
        limit = round(price * (1.002 if buy else 0.998), 1)
        from bi_trading.venues.base import OrderRequest

        order = OrderRequest(
            instrument=HL_BTC,
            side="buy" if buy else "sell",
            price=limit,
            size=round(usd / price, 5),
            market=True,       # fill-or-cancel at that price: it fills now or says why not
        )
        self._pending = side
        self._status("sending…")
        svc = service()
        if not self._wired:
            svc.placed.connect(self._on_placed)
            svc.failed.connect(self._on_failed)
            svc.filled.connect(self._on_filled)
            self._wired = True
        svc.submit("hyperliquid", order, config_for("hyperliquid") or {})

    def _confirm(self, side: str, usd: float, price: float) -> bool:
        verb = "Buy" if side == "LONG" else "Sell"
        answer = QMessageBox.question(
            self,
            "Place a real order",
            f"{verb} ${usd:,.0f} of {HL_BTC.symbol} at ~{price:,.1f}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_placed(self, venue: str, summary: str) -> None:
        if venue != "hyperliquid" or self._pending is None:
            return
        side, self._pending = self._pending, None
        if side == "CLOSE":
            self.close_position()
            self._status(f"closed · {summary}", tone="ok")
            return
        self.open_position(side)
        fill, self._fill = self._fill, None
        if fill is not None and fill[0] > 0 and self._position is not None:
            # The venue's own average price, not the one the click saw.
            self._position["entry"] = fill[1] / fill[0]
            store().set(self._position)
        self._status(f"filled · {summary}", tone="ok")

    def _on_filled(self, venue: str, token: str, side: str, shares: float, dollars: float) -> None:
        if venue == "hyperliquid" and self._pending not in (None, "CLOSE"):
            self._fill = (shares, dollars)

    def _on_failed(self, venue: str, reason: str) -> None:
        if venue != "hyperliquid" or self._pending is None:
            return
        self._pending = None
        self._status(reason, tone="error")

    def _status(self, text: str, tone: str = "info") -> None:
        self.status_label.setText(text)
        from bi_trading.ui.palette import DOWN_SOFT, MUTED

        colour = {"ok": UP, "error": DOWN_SOFT}.get(tone, MUTED)
        self.status_label.setStyleSheet(f"color: {colour};")

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
        self.leverage.setToolTip(f"{self.margin_label.text()} · {self.liq_label.text()}")
        self.info_label.setText(
            f"{self.margin_label.text()} · {self.liq_label.text()} · Fee ~0.06%"
        )
        live = armed()
        self.mode_badge.setText("LIVE" if live else "PAPER")
        self.mode_badge.setProperty("live", "true" if live else "false")
        self.mode_badge.style().unpolish(self.mode_badge)
        self.mode_badge.style().polish(self.mode_badge)

        position = self._position
        self.position_row.setVisible(position is not None)
        self.none_label.setVisible(position is None)
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
