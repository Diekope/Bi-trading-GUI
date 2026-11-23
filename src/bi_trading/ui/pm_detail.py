"""The right half of the Polymarket-only Live screen.

A larger copy of the BTC chart against the window's target, three figures (the
model's P(up), the market's UP ask, the edge between them) and the bets you hold.
It reads the Polymarket panel on the left; it holds no data of its own.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bi_trading.ui.cards import mono_font
from bi_trading.ui.panels import Card
from bi_trading.ui.polymarket_panel import PriceChart
from bi_trading.ui.theme import DOWN, TEXT, TEXT_MUTED, UP

REFRESH_MS = 500


def _tile(caption: str) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("figureTile")
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    column = QVBoxLayout(frame)
    column.setContentsMargins(12, 8, 12, 8)
    column.setSpacing(2)
    head = QLabel(caption)
    head.setObjectName("gl")
    value = QLabel("—")
    value.setObjectName("figureValue")
    value.setFont(mono_font(15, bold=True))
    column.addWidget(head)
    column.addWidget(value)
    return frame, value


class PmDetail(Card):
    """Big chart, the model against the market, and your paper bets."""

    def __init__(
        self,
        panel,
        ask: Callable[[], float | None],
        bets: Callable[[], list[tuple[str, str, str, str, str]]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._panel = panel
        self._ask = ask
        self._bets = bets
        self._slug = ""

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel("BTC / USD VS TARGET")
        title.setObjectName("sectionTitle")
        self.target_label = QLabel("")
        self.target_label.setObjectName("gl")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.target_label)
        self.body.addLayout(head)

        self.chart = PriceChart()
        self.body.addWidget(self.chart, 1)

        tiles = QHBoxLayout()
        tiles.setContentsMargins(0, 4, 0, 4)
        tiles.setSpacing(10)
        model, self.model_value = _tile("Model P(up)")
        market, self.ask_value = _tile("Market UP ask")
        edge, self.edge_value = _tile("Edge")
        for tile in (model, market, edge):
            tiles.addWidget(tile, 1)
        self.body.addLayout(tiles)

        bets_title = QLabel("YOUR PAPER BETS")
        bets_title.setObjectName("sectionTitle")
        self.body.addWidget(bets_title)
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("betsTable")
        self.table.setHorizontalHeaderLabels(["Side", "Stake", "Entry", "Now / result"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumHeight(140)
        self.body.addWidget(self.table)

        self._refresh_bets()
        self._clock = QTimer(self)
        self._clock.setInterval(REFRESH_MS)
        self._clock.timeout.connect(self.refresh)
        self._clock.start()

    def refresh(self) -> None:
        """Follow the Polymarket panel: its chart data, its target, the figures."""
        panel = self._panel
        market = panel.market
        self._refresh_bets()
        if market is None:
            return
        if market.slug != self._slug:
            self._slug = market.slug
            self.chart.set_market(market, panel.points, panel.target)
        else:
            self.chart.set_data(panel.points, panel.target)
        target = panel.target
        self.target_label.setText("" if target is None else f"target {target:,.1f}")

        ask = self._ask()
        self.ask_value.setText("—" if ask is None else f"{ask * 100:.1f}¢")
        # No model on this branch: the figures wait for one.
        self.model_value.setText("—")
        self.edge_value.setText("—")
        self.edge_value.setStyleSheet(f"color: {TEXT};")

    def _refresh_bets(self) -> None:
        rows = self._bets()
        self.table.setRowCount(max(1, len(rows)))
        if not rows:
            self._cell(0, 0, "none open", TEXT_MUTED)
            for column in (1, 2, 3):
                self.table.setItem(0, column, QTableWidgetItem(""))
        for index, (side, stake, entry, now, tone) in enumerate(rows):
            self._cell(index, 0, side, UP if side == "UP" else DOWN)
            self._cell(index, 1, stake, TEXT)
            self._cell(index, 2, entry, TEXT)
            self._cell(index, 3, now, {"up": UP, "down": DOWN}.get(tone, TEXT))

    def _cell(self, row: int, column: int, text: str, colour: str) -> None:
        item = QTableWidgetItem(text)
        item.setFont(mono_font(9))
        item.setForeground(QColor(colour))
        self.table.setItem(row, column, item)


__all__ = ["PmDetail"]
