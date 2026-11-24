"""The Polymarket backtest window: bets on five-minute up/down markets.

The Hyperliquid backtest walks candles with a long or short position. A
Polymarket strategy does something else: it buys an Up or a Down share at the
market price, and either cashes out early or holds to settlement. This window
runs that (`engine.binary`) over the downloaded Polymarket prices and the Binance
candles, and says plainly how much of it rests on real prices.

    left   HISTORY (Polymarket + Binance coverage, download) and the BET inputs
    right  the result: figures, baselines, equity curve, every bet
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np
from PySide6.QtCore import QLocale, QPointF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bi_trading.data import candles, polymarket_history
from bi_trading.engine import binary
from bi_trading.engine.formula import (
    PM_ENTRY_FIELDS,
    PM_EXIT_FIELDS,
    Formula,
    FormulaError,
    parse,
)
from bi_trading.state import strategies
from bi_trading.ui.panels import Card
from bi_trading.ui.theme import CANVAS, CARD_GAP
from bi_trading.ui.theme_colors import DOWN, UP

SPANS = (("All history", 0), ("Last 90 days", 90), ("Last 30 days", 30), ("Last 7 days", 7))
DAY_MS = 86_400_000


def load_candles(first_ms: int, last_ms: int) -> dict[str, np.ndarray]:
    """The 1m Binance candles between two times, from every year file touched."""
    parts: list[tuple[np.ndarray, ...]] = []
    for year in range(
        datetime.fromtimestamp(first_ms / 1000, UTC).year,
        datetime.fromtimestamp(last_ms / 1000, UTC).year + 1,
    ):
        data = candles.arrays(candles.candle_file(year))
        if data is not None:
            parts.append(data)
    names = ("timestamp", "open", "high", "low", "close", "volume")
    if not parts:
        return {name: np.array([]) for name in names}
    joined = [np.concatenate([p[i] for p in parts]) for i in range(6)]
    mask = (joined[0] >= first_ms) & (joined[0] <= last_ms)
    return {name: joined[i][mask] for i, name in enumerate(names)}


class RunWorker(QThread):
    """The run, off the GUI thread: loading and walking a year is not instant."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, entry: Formula, exit_: Formula | None, params, first_ms, last_ms,
                 entry_down: Formula | None = None) -> None:
        super().__init__()
        self._args = (entry, exit_, params, first_ms, last_ms, entry_down)

    def run(self) -> None:
        entry, exit_, params, first_ms, last_ms, entry_down = self._args
        try:
            bars = load_candles(first_ms, last_ms)
            history = polymarket_history.load_rows(first_ms, last_ms)
            result = binary.run_binary(bars, history, entry, exit_, params, entry_down)
            baselines = {
                side: binary.always_side(bars, history, side, params)
                for side in ("up", "down")
            }
            self.done.emit((result, baselines, len(bars["timestamp"])))
        except Exception as exc:  # shown to the user, never raised through Qt
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class EquityCurve(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self._values: list[float] = []

    def set_values(self, values: list[float]) -> None:
        self._values = values
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        values = self._values
        if len(values) < 2:
            return
        low, high = min(values), max(values)
        span = (high - low) or 1.0
        width, height = self.width() - 8, self.height() - 12
        step = width / (len(values) - 1)
        points = [QPointF(4 + i * step, 6 + height * (1 - (v - low) / span)) for i, v in enumerate(values)]
        painter.setPen(QPen(QColor(UP if values[-1] >= values[0] else DOWN), 1.6))
        # a long run is drawn from a sample, a point per pixel is plenty
        stride = max(1, len(points) // max(1, width))
        painter.drawPolyline(points[::stride] + [points[-1]])


class PolymarketBacktestWindow(QMainWindow):
    """Run a strategy against past five-minute markets."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("bi-trading · Polymarket backtest")
        self.setMinimumSize(620, 520)
        self.resize(1180, 940)
        self._worker: RunWorker | None = None
        self._downloader: polymarket_history.PolymarketHistoryDownloader | None = None
        self.open_builder = lambda: None  # the hub points this at its Builder

        canvas = QWidget(self)
        canvas.setObjectName("stratCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#stratCanvas {{ background-color: {CANVAS}; }}")
        root = QHBoxLayout(canvas)
        root.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        root.setSpacing(CARD_GAP)

        left = QWidget(canvas)
        left.setMaximumWidth(430)
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CARD_GAP)
        column.addWidget(self._history_card())
        column.addWidget(self._bet_card(), 1)
        root.addWidget(left)
        root.addWidget(self._result_card(), 1)
        self.setCentralWidget(canvas)
        self.refresh_coverage()
        self.refresh_strategies()

    # -- cards ------------------------------------------------------------

    def _title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("tileTitle")
        return label

    def _history_card(self) -> Card:
        card = Card()
        card.body.addWidget(self._title("HISTORY"))
        self.coverage_label = QLabel("")
        self.coverage_label.setWordWrap(True)
        card.body.addWidget(self.coverage_label)
        self.span = QComboBox()
        for label, _days in SPANS:
            self.span.addItem(label)
        card.body.addWidget(self.span)
        row = QHBoxLayout()
        self.download_button = QPushButton("Download Polymarket prices")
        self.download_button.clicked.connect(self._download)
        row.addWidget(self.download_button, 1)
        card.body.addLayout(row)
        self.download_note = QLabel("")
        self.download_note.setWordWrap(True)
        card.body.addWidget(self.download_note)
        return card

    def _field(self, value: float, low: float, high: float) -> QLineEdit:
        edit = QLineEdit(f"{value:g}")
        edit.setObjectName("paramField")
        validator = QDoubleValidator(low, high, 3, edit)
        validator.setLocale(QLocale.c())
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        edit.setValidator(validator)
        edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return edit

    def _bet_card(self) -> Card:
        card = Card()
        card.body.addWidget(self._title("BET"))
        self.strategy = QComboBox()
        self.strategy.setToolTip("A saved strategy: its entry rule bets, its exit rule cashes out")
        card.body.addWidget(self.strategy)
        self.strategy_note = QLabel("")
        self.strategy_note.setWordWrap(True)
        card.body.addWidget(self.strategy_note)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.capital = self._field(1000, 1, 1e9)
        self.stake = self._field(5, 0.01, 100)
        self.minute = self._field(1, 1, 4)
        self.spread = self._field(1, 0, 20)
        self.fee = self._field(0, 0, 10)
        self.tp = self._field(0, 0, 10_000)
        self.sl = self._field(0, 0, 10_000)
        rows = (
            ("Start capital $", self.capital),
            ("Stake % of equity", self.stake), ("First decision minute", self.minute),
            ("Half spread (cents)", self.spread), ("Fee %", self.fee),
            ("TP % (share price)", self.tp), ("SL % (share price)", self.sl),
        )
        for index, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), index, 0)
            grid.addWidget(widget, index, 1)
        card.body.addLayout(grid)
        self.run_button = QPushButton("Run backtest")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._run)
        card.body.addWidget(self.run_button)
        self.run_note = QLabel("")
        self.run_note.setWordWrap(True)
        card.body.addWidget(self.run_note)
        card.body.addStretch(1)
        return card

    def _result_card(self) -> Card:
        card = Card()
        card.body.addWidget(self._title("RESULT"))
        self.figures = QLabel("Run a strategy to see its bets.")
        self.figures.setTextFormat(Qt.TextFormat.RichText)
        self.figures.setWordWrap(True)
        card.body.addWidget(self.figures)
        self.curve = EquityCurve()
        card.body.addWidget(self.curve)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["Market (UTC)", "Side", "In", "Buy", "Out", "Sold", "Stake $", "PnL $", "Ended", "Prices"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        card.body.addWidget(self.table, 1)
        return card

    # -- data -------------------------------------------------------------

    def refresh_coverage(self) -> None:
        have, missing, newest = polymarket_history.coverage()
        if have + missing == 0:
            pm = "Polymarket prices: none downloaded yet."
        else:
            when = datetime.fromtimestamp(newest / 1000, UTC).strftime("%Y-%m-%d %H:%M")
            pm = (f"Polymarket prices: {have:,} markets on disk "
                  f"({missing:,} not on Polymarket), newest {when} UTC.")
        year = datetime.now(tz=UTC).year
        rows = candles.row_count(candles.candle_file(year))
        self.coverage_label.setText(f"{pm}\nBinance 1m candles {year}: {rows:,} rows.")

    def refresh_strategies(self) -> None:
        self.strategy.clear()
        for item in strategies.load():
            self.strategy.addItem(item.name)
        if self.strategy.count() == 0:
            self.strategy.addItem("(no saved strategy: build one in the Builder)")
        self.strategy.setEnabled(self.strategy.count() > 0 and bool(strategies.load()))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh_strategies()
        self.refresh_coverage()

    def _download(self) -> None:
        if self._downloader is not None and self._downloader.busy():
            self._downloader.cancel()
            self.download_note.setText("stopping after this batch…")
            return
        self._downloader = polymarket_history.PolymarketHistoryDownloader(self)
        self._downloader.progressed.connect(self._download_progress)
        self._downloader.finished.connect(self._download_done)
        self._downloader.failed.connect(self._download_failed)
        if self._downloader.start():
            self.download_button.setText("Stop download")
            self.download_note.setText("starting…")

    def _download_progress(self, done: int, total: int) -> None:
        self.download_note.setText(f"{done:,} / {total:,} markets")

    def _download_failed(self, message: str) -> None:
        self._download_done()
        self.download_note.setText(f"stopped: {message}")

    def _download_done(self) -> None:
        self.download_button.setText("Download Polymarket prices")
        if not self.download_note.text().startswith("stopped"):
            self.download_note.setText("download finished")
        self.refresh_coverage()

    # -- running ----------------------------------------------------------

    def _number(self, edit: QLineEdit, default: float) -> float:
        try:
            return float(edit.text())
        except ValueError:
            return default

    def _rules(self) -> tuple[Formula, Formula | None, Formula | None] | None:
        name = self.strategy.currentText()
        item = next((s for s in strategies.load() if s.name == name), None)
        if item is None:
            self.strategy_note.setText("Save a strategy in the Builder first.")
            return None
        try:
            entry = parse(item.entry, PM_ENTRY_FIELDS)
            down = parse(item.short_entry, PM_ENTRY_FIELDS) if item.short_entry.strip() else None
            exit_ = parse(item.exit, PM_EXIT_FIELDS) if item.exit.strip() else None
        except FormulaError as exc:
            self.strategy_note.setText(f"This strategy does not read here: {exc}")
            return None
        lines = [f"bet UP when: {item.entry or '(never)'}"]
        if down is not None:
            lines.append(f"bet DOWN when: {item.short_entry}")
        if item.exit.strip():
            lines.append(f"cash out when: {item.exit}")
        self.strategy_note.setText("\n".join(lines))
        return entry, exit_, down

    def _params(self) -> binary.BinaryParams:
        return binary.BinaryParams(
            capital=self._number(self.capital, 1000.0),
            stake_pct=self._number(self.stake, 5.0),
            first_minute=int(min(4, max(1, self._number(self.minute, 1)))),
            half_spread=self._number(self.spread, 1.0) / 100.0,
            fee_pct=self._number(self.fee, 0.0),
            tp=self._number(self.tp, 0.0),
            sl=self._number(self.sl, 0.0),
        )

    def _span_ms(self) -> tuple[int, int]:
        last = int(time.time() * 1000)
        days = SPANS[self.span.currentIndex()][1]
        first = polymarket_history.HISTORY_START_MS if days == 0 else last - days * DAY_MS
        return max(first, polymarket_history.HISTORY_START_MS), last

    def _run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        rules = self._rules()
        if rules is None:
            return
        first, last = self._span_ms()
        self.run_button.setEnabled(False)
        self.run_note.setText("running…")
        self._worker = RunWorker(rules[0], rules[1], self._params(), first, last, rules[2])
        self._worker.done.connect(self._show)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.run_note.setText(f"failed: {message}")

    def _show(self, payload) -> None:
        result, baselines, bars = payload
        self.run_button.setEnabled(True)
        self.run_note.setText("")
        n = len(result.trades)
        if result.windows == 0:
            self.figures.setText("No complete five-minute windows of Binance candles in this span. "
                                 "Download candles in the Hyperliquid backtest first.")
            self.table.setRowCount(0)
            self.curve.set_values([])
            return
        real = sum(1 for t in result.trades if t.real_price)
        estimated = sum(1 for t in result.trades if t.estimated_outcome)

        def line(name: str, r) -> str:
            return (f"{name}: {len(r.trades):,} bets, win {r.win_rate:.1%}, "
                    f"ROI {r.roi:+.2%}, final ${r.final_equity:,.0f}")

        self.figures.setText(
            f"<b>{n:,} bets</b> over {result.windows:,} markets · win rate "
            f"<b>{result.win_rate:.1%}</b> · ROI on stake <b>{result.roi:+.2%}</b> · "
            f"PnL <b>${result.pnl:+,.2f}</b> · final ${result.final_equity:,.2f} · "
            f"max drawdown {result.max_drawdown:.1%}<br>"
            f"Cashed out early: {result.early:,} · held to settlement: {n - result.early:,} · "
            f"entry at a real price: {real:,} of {n:,} (the rest simulated) · "
            f"outcome estimated from Binance: {estimated:,}<br>"
            f"<span style='color:#8b94a3'>Baselines at minute {result.params.first_minute}, "
            f"held to settlement. {line('Always UP', baselines['up'])}. "
            f"{line('Always DOWN', baselines['down'])}. "
            f"Prices carry an assumed {result.params.half_spread * 100:g} cent half spread: "
            f"no order book history exists.</span>"
        )
        self.curve.set_values(result.equity)
        self.table.setRowCount(0)
        for trade in result.trades[-500:]:
            self.table.insertRow(self.table.rowCount())
            cells = (
                datetime.fromtimestamp(trade.start_ms / 1000, UTC).strftime("%m-%d %H:%M"),
                trade.side.upper(), f"m{trade.entry_minute}", f"{trade.entry_price:.2f}",
                "settle" if trade.exit_minute == binary.STEPS else f"m{trade.exit_minute}",
                f"{trade.exit_price:.2f}", f"{trade.stake:,.2f}", f"{trade.pnl:+,.2f}",
                trade.reason, "real" if trade.real_price else "sim",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 7:
                    item.setForeground(QColor(UP if trade.pnl > 0 else DOWN))
                self.table.setItem(self.table.rowCount() - 1, column, item)
        self.table.scrollToBottom()


__all__ = ["PolymarketBacktestWindow", "load_candles"]
