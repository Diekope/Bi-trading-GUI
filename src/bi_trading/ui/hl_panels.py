"""The right column of the Hyperliquid-only Live screen.

The order book, the open paper positions, and the trade form. Each is a card;
the data and the logic live elsewhere (the feed's book, `TradeForm`).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QWidget,
)

from bi_trading.data.market_data import Book, format_price
from bi_trading.ui.cards import mono_font
from bi_trading.ui.panels import Card
from bi_trading.ui.theme import DOWN, TEXT, TEXT_FAINT, TEXT_MUTED, UP

LEVELS = 5
ROW_H = 24


def _compact(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}k"
    return f"${value:,.0f}"


class BookView(QWidget):
    """Five asks, the mid and the spread, five bids; a bar behind each size."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book: Book | None = None
        self.decimals = 1
        self.setMinimumHeight(ROW_H * (2 * LEVELS + 1) + 8)

    def set_book(self, book: Book | None, decimals: int = 1) -> None:
        self.book = book
        self.decimals = decimals
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        book = self.book
        width = float(self.width())
        painter.setFont(mono_font(9))
        if book is None or not book.bids or not book.asks:
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, 0, width, float(self.height())),
                Qt.AlignmentFlag.AlignCenter, "waiting for the book…",
            )
            return
        asks = list(book.asks[:LEVELS])[::-1]          # best ask nearest the middle
        bids = list(book.bids[:LEVELS])
        biggest = max([level.sz for level in asks + bids] or [1.0])

        def row(index: int, level, colour: str) -> None:
            top = index * ROW_H
            share = 0.0 if biggest <= 0 else level.sz / biggest
            bar = QColor(colour)
            bar.setAlpha(46)
            painter.fillRect(QRectF(width * (1 - share), top + 1, width * share, ROW_H - 2), bar)
            painter.setPen(QColor(colour))
            painter.drawText(
                QRectF(8, top, width * 0.34, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                format_price(level.px, self.decimals),
            )
            painter.setPen(QColor(TEXT))
            painter.drawText(
                QRectF(width * 0.34, top, width * 0.30, ROW_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{level.sz:,.2f}",
            )
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(width * 0.64, top, width * 0.34, ROW_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _compact(level.px * level.sz),
            )

        for index, level in enumerate(asks):
            row(index, level, DOWN)
        middle = LEVELS * ROW_H
        spread = book.asks[0].px - book.bids[0].px
        painter.setPen(QColor(TEXT))
        painter.setFont(mono_font(10, bold=True))
        mid = book.mid or 0.0
        painter.drawText(
            QRectF(8, middle, width * 0.5, ROW_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            format_price(mid, self.decimals),
        )
        painter.setFont(mono_font(9))
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            QRectF(width * 0.4, middle, width * 0.58, ROW_H),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"spread {format_price(spread, self.decimals + 1)}",
        )
        for index, level in enumerate(bids):
            row(LEVELS + 1 + index, level, UP)


class OrderBookCard(Card):
    """ORDER BOOK, with the venue's round trip beside the title."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel("ORDER BOOK")
        title.setObjectName("sectionTitle")
        self.latency = QLabel("— ms")
        self.latency.setObjectName("gl")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.latency)
        self.body.addLayout(head)
        self.view = BookView()
        self.body.addWidget(self.view, 1)

    def set_book(self, book: Book | None, decimals: int = 1) -> None:
        self.view.set_book(book, decimals)

    def set_latency(self, milliseconds: float) -> None:
        self.latency.setText(f"{milliseconds:.0f} ms")


class PositionsCard(Card):
    """PAPER POSITIONS: the trade form's position strip lives here."""

    def __init__(self, form, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel("PAPER POSITIONS")
        title.setObjectName("sectionTitle")
        self.body.addWidget(title)
        form.place_positions(self.body)


class TradeCard(Card):
    """TRADE BTC: size, leverage, the two sides, and what they imply."""

    def __init__(self, form, coin: str = "BTC", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"TRADE {coin}")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.body.addLayout(head)
        form.place_panel(self.body, head)


__all__ = ["BookView", "OrderBookCard", "PositionsCard", "TradeCard"]
