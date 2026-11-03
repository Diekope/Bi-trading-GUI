"""The Polymarket column: one five-minute BTC up/down market, at a glance.

Not a candlestick chart — a binary market has no OHLC. The useful information
is the probability of each side, how long is left, how deep the book is, and
what has traded. So the panel paints four things:

    outcome tiles   UP / DOWN in cents, with a probability bar
    clock           the window and a live countdown to the close
    ladder          the selected token's book, with depth bars
    tape            the last trades, newest first

The tiles switch the ladder between the two tokens. Books and trades are kept
per window and cleared when the feed rolls to the next five-minute slug.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from lalala.cards import mono_font
from lalala.panels import Card
from lalala.polymarket_data import (
    PolymarketMarket,
    TokenBook,
    Trade,
    format_cents,
    format_compact,
    format_countdown,
    format_shares,
)
from lalala.theme import (
    ACCENT,
    BORDER,
    DOWN,
    PANEL_ALT,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    UP,
)

AMBER = "#e0b341"
TRACK = "#1b1b20"


def _alpha(color: str, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


class OutcomeTile(QWidget):
    """One side of the market: name, cents, probability bar, best quotes."""

    clicked = Signal()

    def __init__(self, name: str, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.accent = accent
        self.price: float | None = None
        self.bid: float | None = None
        self.ask: float | None = None
        self.selected = False
        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to show this token's order book")

    def set_quote(
        self, price: float | None, bid: float | None, ask: float | None
    ) -> None:
        if (price, bid, ask) == (self.price, self.bid, self.ask):
            return
        self.price, self.bid, self.ask = price, bid, ask
        self.update()

    def set_name(self, name: str) -> None:
        if name != self.name:
            self.name = name
            self.update()

    def set_selected(self, selected: bool) -> None:
        if selected != self.selected:
            self.selected = selected
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.setPen(QPen(QColor(self.accent if self.selected else BORDER), 1))
        painter.setBrush(QColor(PANEL_ALT))
        painter.drawRoundedRect(rect, 4, 4)

        if self.selected:
            painter.setPen(QPen(QColor(self.accent), 1))
            painter.drawLine(rect.left() + 4, rect.top(), rect.right() - 4, rect.top())

        pad = 8.0
        painter.setFont(mono_font(9, bold=True))
        painter.setPen(QColor(self.accent))
        painter.drawText(
            QRectF(pad, 5, 60, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.name.upper(),
        )

        painter.setFont(mono_font(17, bold=True))
        painter.setPen(QColor(self.accent))
        painter.drawText(
            QRectF(rect.width() - 92, 2, 84, 22),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            format_cents(self.price),
        )

        track = QRectF(pad, 30, max(1.0, rect.width() - pad * 2), 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TRACK))
        painter.drawRoundedRect(track, 2, 2)
        if self.price is not None and self.price > 0:
            width = track.width() * max(0.0, min(1.0, self.price))
            painter.setBrush(QColor(self.accent))
            painter.drawRoundedRect(
                QRectF(track.left(), track.top(), max(2.0, width), track.height()),
                2,
                2,
            )

        painter.setFont(mono_font(8))
        painter.setPen(QColor(TEXT_FAINT))
        quote = (
            f"bid {format_cents(self.bid)}  ·  ask {format_cents(self.ask)}"
            if self.bid is not None or self.ask is not None
            else "waiting for quotes"
        )
        painter.drawText(
            QRectF(pad, 39, rect.width() - pad * 2, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            quote,
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DepthLadder(QWidget):
    """The selected token's book, painted as a compact ladder with depth bars."""

    ROW = 15
    MAX_LEVELS = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book: TokenBook | None = None
        self.title = ""
        self._shown: tuple | None = None
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_book(self, book: TokenBook | None, title: str) -> None:
        # The wire moves levels well below the visible slice far more often
        # than it moves the top of the book. Repainting on those would burn
        # most of the CPU for pixels nobody can see.
        shown = (title, self._signature(book))
        if shown == self._shown:
            return
        self._shown = shown
        self.book = book
        self.title = title
        self.update()

    @staticmethod
    def _signature(book: TokenBook | None) -> tuple:
        if book is None:
            return ()
        depth = DepthLadder.MAX_LEVELS
        return (
            book.token_id,
            tuple((level.price, level.size) for level in book.asks[:depth]),
            tuple((level.price, level.size) for level in book.bids[:depth]),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        painter.setFont(mono_font(8, bold=True))
        painter.setPen(QColor(TEXT_FAINT))
        heading = f"{self.title.upper()} BOOK" if self.title else "ORDER BOOK"
        painter.drawText(
            QRectF(0, 0, width, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            heading,
        )
        book = self.book
        if book is not None and book.mid is not None:
            painter.setPen(QColor(ACCENT))
            painter.drawText(
                QRectF(0, 0, width, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"mid {format_cents(book.mid)}",
            )

        if book is None or (not book.bids and not book.asks):
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, 16, width, height - 16),
                Qt.AlignmentFlag.AlignCenter,
                "waiting for the book…",
            )
            return

        top = 18.0
        mid_height = 16.0
        usable = max(2 * self.ROW, height - top - mid_height)
        levels = max(1, min(self.MAX_LEVELS, int(usable / (2 * self.ROW))))
        row_h = usable / (2 * levels)

        asks = book.asks[:levels]
        bids = book.bids[:levels]
        peak = max([level.size for level in asks + bids] + [1.0])

        def row(y: float, price: float, size: float, color: str) -> None:
            bar = (width - 2) * (size / peak)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_alpha(color, 34))
            painter.fillRect(
                QRectF(width - bar, y + 1, bar, max(1.0, row_h - 2)), _alpha(color, 34)
            )
            painter.setPen(QColor(color))
            painter.setFont(mono_font(8, bold=True))
            painter.drawText(
                QRectF(0, y, 52, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                format_cents(price),
            )
            painter.setPen(QColor(TEXT_MUTED))
            painter.setFont(mono_font(8))
            size_width = min(96.0, max(52.0, width * 0.40))
            painter.drawText(
                QRectF(width - size_width, y, size_width, row_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{format_shares(size)}",
            )

        # Asks descend toward the mid: the best ask sits on the mid line.
        y = top
        for level in reversed(asks):
            row(y, level.price, level.size, DOWN)
            y += row_h

        mid_y = top + levels * row_h
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawLine(
            0, int(mid_y), int(width), int(mid_y)
        )
        painter.setFont(mono_font(8))
        painter.setPen(QColor(ACCENT))
        spread = book.spread
        caption = "spread —" if spread is None else f"spread {format_cents(spread)}"
        painter.drawText(
            QRectF(0, mid_y, width, mid_height),
            Qt.AlignmentFlag.AlignCenter,
            caption,
        )

        y = mid_y + mid_height
        for level in bids:
            row(y, level.price, level.size, UP)
            y += row_h


class TradeTape(QWidget):
    """The most recent prints, newest first."""

    MAX_ROWS = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.trades: list[tuple[Trade, str]] = []
        self.setMinimumHeight(74)
        self.setMaximumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    def add(self, trade: Trade, name: str) -> None:
        self.trades.insert(0, (trade, name))
        del self.trades[self.MAX_ROWS:]
        self.update()

    def clear(self) -> None:
        self.trades.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        painter.setFont(mono_font(8, bold=True))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(0, 0, width, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "TAPE",
        )
        if not self.trades:
            painter.setFont(mono_font(9))
            painter.drawText(
                QRectF(0, 16, width, max(1.0, height - 16)),
                Qt.AlignmentFlag.AlignCenter,
                "waiting for trades…",
            )
            return

        row_h = 14.0
        rows = min(self.MAX_ROWS, int(max(1.0, height - 16) / row_h))
        painter.setFont(mono_font(8))
        for index, (trade, name) in enumerate(self.trades[:rows]):
            y = 16 + index * row_h
            moment = datetime.fromtimestamp(
                trade.timestamp_ms / 1000 if trade.timestamp_ms else time.time(),
                tz=timezone.utc,
            ).strftime("%H:%M:%S")
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, y, 58, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                moment,
            )
            painter.setPen(QColor(UP if name.lower().startswith("up") else DOWN))
            painter.drawText(
                QRectF(62, y, 44, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name.upper()[:6],
            )
            painter.setPen(QColor(TEXT))
            painter.drawText(
                QRectF(108, y, 52, row_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_cents(trade.price),
            )
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(width - 84, y, 84, row_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"× {format_shares(trade.size)}",
            )


@dataclass
class _Status:
    text: str
    color: str


STATUS: dict[str, _Status] = {
    "waiting": _Status("waiting for market…", AMBER),
    "snapshot": _Status("loading book…", ACCENT),
    "live": _Status("live", UP),
    "reconnecting": _Status("reconnecting…", AMBER),
    "closed": _Status("closed", TEXT_FAINT),
}


class PolymarketPanel(Card):
    """One market, with the information a binary bet actually needs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.market: PolymarketMarket | None = None
        self.books: dict[str, TokenBook] = {}
        self._selected = 0
        self._btc_open: float | None = None
        self._status = STATUS["waiting"]
        # Below this the ladder columns and the tape overlap; the Hyperliquid
        # column still gets the rest of a 620px-minimum window.
        self.setMinimumWidth(300)

        # -- header --
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.title_label = QLabel("POLYMARKET")
        title_font = QFont(mono_font(8, bold=True))
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")

        self.badge = QLabel("5m")
        self.badge.setFont(mono_font(8))
        self.badge.setStyleSheet(
            f"color: {TEXT_MUTED}; background: #1a1a1f; border: 1px solid {BORDER};"
            " border-radius: 3px; padding: 1px 4px;"
        )

        self.status_dot = QLabel("●")
        self.status_dot.setFont(mono_font(8))
        self.status_dot.setStyleSheet(f"color: {AMBER}; background: transparent;")
        self.status_text = QLabel(self._status.text)
        self.status_text.setFont(mono_font(8))
        self.status_text.setStyleSheet(
            f"color: {TEXT_FAINT}; background: transparent;"
        )

        header.addWidget(self.title_label)
        header.addWidget(self.badge)
        header.addStretch(1)
        header.addWidget(self.status_dot)
        header.addWidget(self.status_text)

        # -- question + clock --
        self.question = QLabel("Waiting for the next five-minute market…")
        question_font = self.question.font()
        question_font.setPointSize(12)
        question_font.setWeight(QFont.Weight.DemiBold)
        self.question.setFont(question_font)
        self.question.setWordWrap(True)
        self.question.setStyleSheet(f"color: {TEXT}; background: transparent;")

        clock = QHBoxLayout()
        clock.setContentsMargins(0, 0, 0, 0)
        clock.setSpacing(6)

        self.window_label = QLabel("—")
        self.window_label.setFont(mono_font(8))
        self.window_label.setStyleSheet(
            f"color: {TEXT_FAINT}; background: transparent;"
        )

        close_caption = QLabel("closes in")
        close_caption.setFont(mono_font(8))
        close_caption.setStyleSheet(
            f"color: {TEXT_FAINT}; background: transparent;"
        )

        self.countdown = QLabel("—")
        self.countdown.setFont(mono_font(15, bold=True))
        self.countdown.setStyleSheet(f"color: {TEXT}; background: transparent;")

        clock.addWidget(self.window_label)
        clock.addStretch(1)
        clock.addWidget(close_caption)
        clock.addWidget(self.countdown)

        # -- outcome tiles --
        tiles = QHBoxLayout()
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(6)

        self.up_tile = OutcomeTile("Up", UP)
        self.down_tile = OutcomeTile("Down", DOWN)
        self.up_tile.clicked.connect(lambda: self._select_token(0))
        self.down_tile.clicked.connect(lambda: self._select_token(1))
        tiles.addWidget(self.up_tile, 1)
        tiles.addWidget(self.down_tile, 1)

        # -- stats --
        stats = QGridLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setHorizontalSpacing(3)
        stats.setVerticalSpacing(1)

        self.spread_value = self._stat(stats, 0, 0, "SPREAD")
        self.liquidity_value = self._stat(stats, 0, 1, "LIQUIDITY")
        self.depth_value = self._stat(stats, 1, 0, "DEPTH")
        self.tick_value = self._stat(stats, 1, 1, "TICK")
        self.btc_value = self._stat(stats, 2, 0, "BTC")
        self.move_value = self._stat(stats, 2, 1, "MOVE")
        stats.setColumnStretch(1, 1)
        stats.setColumnStretch(3, 1)

        # -- book + tape --
        self.ladder = DepthLadder()
        self.tape = TradeTape()

        self.body.addLayout(header)
        self.body.addWidget(self.question)
        self.body.addLayout(clock)
        self.body.addLayout(tiles)
        self.body.addLayout(stats)
        self.body.addSpacing(2)
        self.body.addWidget(self.ladder, 1)
        self.body.addWidget(self.tape, 0)

        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    @staticmethod
    def _stat(
        grid: QGridLayout, row: int, column: int, caption: str
    ) -> QLabel:
        label = QLabel(caption)
        label.setFont(mono_font(7))
        label.setStyleSheet(f"color: {TEXT_FAINT}; background: transparent;")
        value = QLabel("—")
        value.setFont(mono_font(9, bold=True))
        value.setStyleSheet(f"color: {TEXT}; background: transparent;")
        grid.addWidget(label, row, column * 2)
        grid.addWidget(value, row, column * 2 + 1)
        return value

    # -- data --------------------------------------------------------------

    def set_market(self, market: PolymarketMarket) -> None:
        if not isinstance(market, PolymarketMarket):
            return
        rolled = self.market is None or self.market.slug != market.slug
        self.market = market

        if rolled:
            self.books.clear()
            self._selected = 0
            self._btc_open = None
            self.tape.clear()
            self.ladder.set_book(None, self._outcome_name(0))
            self.depth_value.setText("—")
            self.spread_value.setText(
                format_cents(market.spread) if market.spread > 0 else "—"
            )

        self.question.setText(market.question)
        self.window_label.setText(self._window_text(market))
        self.tick_value.setText(format_cents(market.tick_size))
        self.liquidity_value.setText(format_compact(market.liquidity))
        self.status_text.setToolTip(market.slug)

        for tile, outcome in zip((self.up_tile, self.down_tile), market.outcomes):
            tile.set_name(outcome.name)
            bid = outcome.best_bid
            ask = outcome.best_ask
            price = outcome.mid if outcome.mid is not None else outcome.price
            tile.set_quote(price, bid, ask)

        self._refresh_selection()
        self._tick()

    def apply_book(self, book: TokenBook) -> None:
        if self.market is None:
            return
        outcome = self.market.outcome_for_token(book.token_id)
        if outcome is None:
            return
        self.books[book.token_id] = book

        tile = self._tile_for(outcome.token_id)
        if tile is not None:
            tile.set_quote(book.mid, book.best_bid, book.best_ask)

        selected = self._selected_book()
        if selected is not None:
            self._set_text(self.spread_value, format_cents(selected.spread))
        # Depth near the touch: the whole ladder is dominated by 1¢ lottery
        # tickets far from the price, which says little about executable size.
        self._set_text(
            self.depth_value,
            format_compact(
                sum(
                    level.price * level.size
                    for held in self.books.values()
                    for level in held.bids[:8] + held.asks[:8]
                )
            ),
        )
        if book.token_id == self._selected_token():
            self.ladder.set_book(book, outcome.name)

    @staticmethod
    def _set_text(label: QLabel, text: str) -> None:
        """QLabel relayouts on every setText, even when the string is equal."""
        if label.text() != text:
            label.setText(text)

    def apply_trade(self, trade: Trade) -> None:
        if self.market is None:
            return
        outcome = self.market.outcome_for_token(trade.token_id)
        name = outcome.name if outcome is not None else "?"
        self.tape.add(trade, name)

    def set_btc(self, price: float) -> None:
        """Reference BTC mid, forwarded from the Hyperliquid feed."""
        if self._btc_open is None:
            self._btc_open = price
        self.btc_value.setText(f"{price:,.1f}")
        if self._btc_open and self._btc_open > 0:
            move = (price - self._btc_open) / self._btc_open * 100.0
            self.move_value.setText(f"{move:+.2f}%")
            self.move_value.setStyleSheet(
                f"color: {UP if move >= 0 else DOWN}; background: transparent;"
            )

    def set_status(self, status: str) -> None:
        looked_up = STATUS.get(status)
        if looked_up is None:
            return
        self._status = looked_up
        self.status_text.setText(looked_up.text)
        self.status_dot.setStyleSheet(
            f"color: {looked_up.color}; background: transparent;"
        )

    def text(self) -> str:
        """Kept for the shell contract: the column is still the Polymarket one."""
        return "Polymarket"

    # -- internals ---------------------------------------------------------

    def _outcome_name(self, index: int) -> str:
        if self.market is None or index >= len(self.market.outcomes):
            return ""
        return self.market.outcomes[index].name

    def _selected_token(self) -> str | None:
        if self.market is None or self._selected >= len(self.market.outcomes):
            return None
        return self.market.outcomes[self._selected].token_id

    def _selected_book(self) -> TokenBook | None:
        token = self._selected_token()
        return self.books.get(token) if token else None

    def _tile_for(self, token_id: str) -> OutcomeTile | None:
        if self.market is None:
            return None
        for index, outcome in enumerate(self.market.outcomes[:2]):
            if outcome.token_id == token_id:
                return (self.up_tile, self.down_tile)[index]
        return None

    def _select_token(self, index: int) -> None:
        if self.market is None or index >= len(self.market.outcomes):
            return
        self._selected = index
        self._refresh_selection()
        book = self._selected_book()
        if book is not None:
            self.ladder.set_book(book, self._outcome_name(index))
        else:
            self.ladder.set_book(None, self._outcome_name(index))

    def _refresh_selection(self) -> None:
        self.up_tile.set_selected(self._selected == 0)
        self.down_tile.set_selected(self._selected == 1)
        token = self._selected_token()
        book = self.books.get(token) if token else None
        self.ladder.set_book(book, self._outcome_name(self._selected))

    @staticmethod
    def _window_text(market: PolymarketMarket) -> str:
        if market.start_ms <= 0 or market.end_ms <= 0:
            return "—"
        start = datetime.fromtimestamp(market.start_ms / 1000, tz=timezone.utc)
        end = datetime.fromtimestamp(market.end_ms / 1000, tz=timezone.utc)
        return f"{start:%H:%M}–{end:%H:%M} UTC"

    def _tick(self) -> None:
        if self.market is None:
            self.countdown.setText("—")
            return
        remaining = (self.market.end_ms - time.time() * 1000) / 1000.0
        self.countdown.setText(format_countdown(remaining))
        color = DOWN if remaining <= 30 else AMBER if remaining <= 60 else TEXT
        self.countdown.setStyleSheet(f"color: {color}; background: transparent;")
