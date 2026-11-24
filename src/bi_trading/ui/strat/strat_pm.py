"""The Polymarket backtest window: bets on five-minute up/down markets.

It is laid out like the Hyperliquid backtest (`strat_window.py`) so the two read
as one tool, but what it runs is different: a strategy buys an UP or a DOWN share
at the market price and either cashes out early or holds to settlement
(`engine.binary`), over the downloaded Polymarket prices and the Binance candles.

    top left    BACKTEST: the figures, and the chosen bet's share price over its
                five minutes with the buy and the sale marked
    top right   HISTORY (download), BET VALUE (the inputs), STRATEGY
    bottom      RESULTS: Overview (curves, how bets ended) and Bets (the table)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np
from PySide6.QtCore import QLocale, QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
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
from bi_trading.ui.cards import mono_font
from bi_trading.ui.panels import Card
from bi_trading.ui.strat.strat_results import DrawdownCurve, LiveCurve, PnlBars
from bi_trading.ui.theme import (
    ACCENT,
    BAND,
    BORDER,
    CANVAS,
    CARD_GAP,
    DOWN,
    TEXT_FAINT,
    TEXT_MUTED,
    UP,
)

SPANS = (("All history", 0), ("Last 90 days", 90), ("Last 30 days", 30), ("Last 7 days", 7))
DAY_MS = 86_400_000
BETS_SHOWN = 500


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
            rows = {row.start_ms: row for row in history}
            self.done.emit((result, baselines, rows))
        except Exception as exc:  # shown to the user, never raised through Qt
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _Curves:
    """What `LiveCurve` reads of a run, here the three equity curves by market."""

    unit = "markets"

    def __init__(self, strategy: list[float], up: list[float], down: list[float]) -> None:
        self.strategy_curve = strategy
        self.random_curve = up          # drawn indigo
        self.benchmark = down           # drawn grey, dashed
        self.index = self.total = max(0, len(strategy) - 1)


class BetChart(QWidget):
    """The picked bet: the Up share's price across its five minutes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._trade: binary.BinaryTrade | None = None
        self._row = None
        self.message = "run a strategy, then pick a bet in the Bets tab"

    def set_bet(self, trade: binary.BinaryTrade | None, row) -> None:
        self._trade, self._row = trade, row
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right = 44.0, self.width() - 12.0
        top, bottom = 22.0, self.height() - 22.0
        if right - left < 60 or bottom - top < 40:
            return
        painter.setFont(mono_font(9))
        trade, row = self._trade, self._row
        if trade is None:
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(QRectF(left, top, right - left, bottom - top),
                             Qt.AlignmentFlag.AlignCenter, self.message)
            return

        def x_of(second: float) -> float:
            return left + (right - left) * second / 300.0

        def y_of(price: float) -> float:
            return bottom - (bottom - top) * price

        painter.setFont(mono_font(7))
        for level in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = y_of(level)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(QPointF(left, y), QPointF(right, y))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(QRectF(0, y - 7, left - 6, 14),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{level * 100:.0f}¢")
        for minute in range(6):
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(QRectF(x_of(minute * 60) - 20, bottom + 3, 40, 14),
                             Qt.AlignmentFlag.AlignCenter, f"m{minute}")

        start = datetime.fromtimestamp(trade.start_ms / 1000, UTC).strftime("%d %b %H:%M")
        painter.setFont(mono_font(8, bold=True))
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(QRectF(left, 2, right - left, 16), Qt.AlignmentFlag.AlignLeft,
                         f"{start} UTC · bet {trade.side.upper()} · Up share price")

        samples: list[tuple[int, float]] = (
            list(zip(row.offsets, row.prices, strict=False)) if row is not None else []
        )
        if len(samples) >= 2:
            painter.setPen(QPen(QColor(ACCENT), 1.6))
            for (s0, p0), (s1, p1) in zip(samples, samples[1:], strict=False):
                painter.drawLine(QPointF(x_of(s0), y_of(p0)), QPointF(x_of(s1), y_of(p1)))
            painter.setBrush(QColor(ACCENT))
            for s, p in samples:
                painter.drawEllipse(QPointF(x_of(s), y_of(p)), 2.2, 2.2)
        else:
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(QRectF(left, top, right - left, bottom - top),
                             Qt.AlignmentFlag.AlignCenter,
                             "simulated prices: none downloaded for this market")

        # The buy and the sale, on the Up price: a Down share is 1 minus it.
        def marks(minute: int, price: float, colour: str, label: str) -> None:
            shown = price if trade.side == "up" else 1.0 - price
            point = QPointF(x_of(minute * 60.0), y_of(shown))
            painter.setPen(QPen(QColor(colour), 1.2))
            painter.setBrush(QColor(colour))
            painter.drawEllipse(point, 5, 5)
            painter.setPen(QColor(colour))
            painter.setFont(mono_font(8, bold=True))
            painter.drawText(QRectF(point.x() + 8, point.y() - 8, 100, 16),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        marks(trade.entry_minute, trade.entry_price, UP,
              f"buy {trade.side} {trade.entry_price * 100:.0f}¢")
        if trade.exit_minute < binary.STEPS:
            marks(trade.exit_minute, trade.exit_price, DOWN,
                  f"sell {trade.exit_price * 100:.0f}¢")
        else:
            up_won = trade.won == (trade.side == "up")
            painter.setPen(QColor(UP if trade.won else DOWN))
            painter.setFont(mono_font(8, bold=True))
            painter.drawText(QRectF(right - 190, y_of(1.0 if up_won else 0.0) - 16, 186, 14),
                             Qt.AlignmentFlag.AlignRight,
                             f"settled {'UP' if up_won else 'DOWN'} · {trade.pnl:+,.2f}")


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    return label


def _figure() -> QLabel:
    label = QLabel("—")
    label.setObjectName("metricValue_text")
    label.setFont(mono_font(9, bold=True))
    return label


class PolymarketBacktestWindow(QMainWindow):
    """Run a strategy against past five-minute markets."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("bi-trading · Polymarket backtest")
        self.setMinimumSize(620, 520)
        self.resize(1180, 940)
        self._worker: RunWorker | None = None
        self._downloader: polymarket_history.PolymarketHistoryDownloader | None = None
        self._rows: dict = {}
        self._shown: list[binary.BinaryTrade] = []
        self._result: binary.BinaryResult | None = None
        self.open_builder = lambda: None  # the hub points this at its Builder

        canvas = QWidget(self)
        canvas.setObjectName("stratCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#stratCanvas {{ background-color: {CANVAS}; }}")
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(CARD_GAP)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, canvas)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(CARD_GAP)
        self.left = self._backtest_tile()

        self.right = QWidget(self.splitter)
        self.right.setObjectName("stratColumn")
        column = QVBoxLayout(self.right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CARD_GAP)
        column.addWidget(self._history_tile())
        column.addWidget(self._bet_tile())
        column.addWidget(self._strategy_tile())
        column.addStretch(1)
        self.right.setMinimumWidth(360)
        self.right.setMaximumWidth(480)
        self.right.setMinimumHeight(self.right.minimumSizeHint().height())
        scroll = QScrollArea(self.splitter)
        scroll.setObjectName("stratColumnScroll")
        scroll.setWidget(self.right)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "#stratColumnScroll, #stratColumnScroll > QWidget > QWidget"
            " { background: transparent; }"
        )
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(500)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(scroll)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([700, 460])

        self.results = self._results_tile()
        self.outer = QSplitter(Qt.Orientation.Vertical, canvas)
        self.outer.setChildrenCollapsible(False)
        self.outer.setHandleWidth(CARD_GAP)
        self.outer.addWidget(self.splitter)
        self.outer.addWidget(self.results)
        self.outer.setStretchFactor(0, 1)
        self.outer.setStretchFactor(1, 1)
        self.outer.setSizes([560, 420])

        from bi_trading.ui.layout_memory import remember_splitter

        remember_splitter(self.splitter, "pm_backtest.columns")
        remember_splitter(self.outer, "pm_backtest.rows")
        layout.addWidget(self.outer, 1)
        self.setCentralWidget(canvas)
        self.refresh_coverage()
        self.refresh_strategies()

    # -- tiles ------------------------------------------------------------

    def _backtest_tile(self) -> Card:
        card = Card(self.splitter)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        title = QLabel("BACKTEST")
        title.setObjectName("tileTitle")
        self.note = QLabel("idle — pick a strategy and press Run")
        self.note.setObjectName("hintLabel")
        titles.addWidget(title)
        titles.addWidget(self.note)
        header.addLayout(titles)
        header.addStretch(1)
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.setToolTip("Run the strategy over the span (Space)")
        self.run_button.clicked.connect(self._run)
        header.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignVCenter)
        card.body.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setObjectName("playbackProgress")
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress_label = QLabel("—")
        self.progress_label.setObjectName("progressCount")
        self.progress_label.setFont(mono_font(7))
        progress = QHBoxLayout()
        progress.setSpacing(10)
        progress.addWidget(self.progress, 1)
        progress.addWidget(self.progress_label)
        card.body.addLayout(progress)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        self.stat: dict[str, QLabel] = {}
        keys = ("PnL", "Equity", "Max DD", "ROI on stake", "Bets", "Win rate",
                "Cashed out", "Avg buy", "Real prices", "Final")
        for index, key in enumerate(keys):
            row, col = divmod(index, 5)
            grid.addWidget(_caption(key), row * 2, col)
            value = _figure()
            grid.addWidget(value, row * 2 + 1, col)
            self.stat[key] = value
        card.body.addLayout(grid)

        self.chart = BetChart()
        card.body.addWidget(self.chart, 1)
        return card

    def _history_tile(self) -> Card:
        card = Card()
        title = QLabel("HISTORY")
        title.setObjectName("tileTitle")
        card.body.addWidget(title)
        self.coverage_label = QLabel("")
        self.coverage_label.setObjectName("hintLabel")
        self.coverage_label.setWordWrap(True)
        card.body.addWidget(self.coverage_label)
        self.span = QComboBox()
        self.span.setObjectName("yearSelect")
        self.span.addItems([label for label, _ in SPANS])
        card.body.addWidget(self.span)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.download_button = QPushButton("Download Polymarket prices")
        self.download_button.setObjectName("actionButton")
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.clicked.connect(self._download)
        self.download_note = QLabel("")
        self.download_note.setObjectName("coverageLabel")
        row.addWidget(self.download_button, 3)
        row.addWidget(self.download_note, 2)
        card.body.addLayout(row)
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

    def _bet_tile(self) -> Card:
        card = Card()
        title = QLabel("BET VALUE")
        title.setObjectName("tileTitle")
        card.body.addWidget(title)
        self.capital = self._field(1000, 1, 1e9)
        self.stake = self._field(5, 0.01, 100)
        self.minute = self._field(1, 1, 4)
        self.spread = self._field(1, 0, 20)
        self.fee = self._field(0, 0, 10)
        self.tp = self._field(0, 0, 10_000)
        self.sl = self._field(0, 0, 10_000)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        fields = (
            ("Start capital $", self.capital), ("Stake % of equity", self.stake),
            ("First minute", self.minute), ("Half spread ¢", self.spread),
            ("Fee %", self.fee), ("TP % (price)", self.tp), ("SL % (price)", self.sl),
        )
        for index, (caption, edit) in enumerate(fields):
            row, col = divmod(index, 3)
            grid.addWidget(_caption(caption), row * 2, col)
            grid.addWidget(edit, row * 2 + 1, col)
        card.body.addLayout(grid)
        note = QLabel(
            "A share pays $1 if its side won, $0 if not. The spread is assumed: "
            "no order-book history exists."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        card.body.addWidget(note)
        return card

    def _strategy_tile(self) -> Card:
        card = Card()
        title = QLabel("STRATEGY")
        title.setObjectName("tileTitle")
        card.body.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.strategy = QComboBox()
        self.strategy.setObjectName("strategySelect")
        self.strategy.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.create_button = QPushButton("Create a strategy")
        self.create_button.setObjectName("createStrategy")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.clicked.connect(lambda: self.open_builder())
        row.addWidget(self.strategy, 1)
        row.addWidget(self.create_button)
        card.body.addLayout(row)
        self.strategy_note = QLabel("")
        self.strategy_note.setObjectName("hintLabel")
        self.strategy_note.setWordWrap(True)
        card.body.addWidget(self.strategy_note)
        self.strategy.currentTextChanged.connect(lambda _t: self._rules())
        return card

    def _results_tile(self) -> Card:
        card = Card()
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        title = QLabel("RESULTS")
        title.setObjectName("tileTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.tabs = QButtonGroup(self)
        self.tabs.setExclusive(True)
        for index, caption in enumerate(("Overview", "Bets")):
            button = QPushButton(caption)
            button.setObjectName("resultTab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tabs.addButton(button, index)
            header.addWidget(button)
        card.body.addLayout(header)
        self.results_note = QLabel("no run yet")
        self.results_note.setObjectName("hintLabel")
        card.body.addWidget(self.results_note)

        self.stack = QStackedWidget()
        self.stack.setObjectName("resultsStack")
        card.body.addWidget(self.stack, 1)
        self.tabs.idClicked.connect(self.stack.setCurrentIndex)

        overview = QWidget()
        overview.setObjectName("overviewPage")
        over = QVBoxLayout(overview)
        over.setContentsMargins(0, 0, 0, 0)
        over.setSpacing(8)
        figures = QHBoxLayout()
        figures.setContentsMargins(0, 0, 0, 0)
        figures.setSpacing(22)
        self.metrics: dict[str, QLabel] = {}
        for key in ("PnL", "ROI on stake", "Win rate", "Max DD", "Bets", "Cashed out",
                    "Avg buy", "Real prices"):
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(_caption(key))
            value = _figure()
            value.setFont(mono_font(11, bold=True))
            box.addWidget(value)
            figures.addLayout(box)
            self.metrics[key] = value
        figures.addStretch(1)
        figures_row = QWidget()
        figures_row.setObjectName("resultsPage")
        figures_row.setLayout(figures)
        figures_row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        over.addWidget(figures_row)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.curve = LiveCurve()
        self.curve.message = "run a strategy to see the curves"
        left.addWidget(self.curve, 1)
        dd_title = QLabel("Drawdown")
        dd_title.setObjectName("hintLabel")
        dd_title.setContentsMargins(0, 10, 0, 0)
        left.addWidget(dd_title)
        self.drawdown = DrawdownCurve()
        left.addWidget(self.drawdown)
        legend = QHBoxLayout()
        legend.setSpacing(12)
        for key, caption in (("strategy", "strategy"), ("random", "always UP"),
                             ("hold", "always DOWN")):
            label = QLabel(caption)
            label.setObjectName(f"legend_{key}")
            label.setFont(mono_font(8, bold=True))
            legend.addWidget(label)
        legend.addStretch(1)
        left.addLayout(legend)
        body.addLayout(left, 1)

        rail = QWidget()
        rail.setObjectName("resultsRail")
        rail.setFixedWidth(240)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(6)
        ends = QLabel("How bets end")
        ends.setObjectName("panelTitle")
        rail_layout.addWidget(ends)
        self.end_bars: dict[str, tuple[QProgressBar, QLabel]] = {}
        for key, caption, colour in (
            ("settled", "Settled", BAND),
            ("tp", "Take profit", UP),
            ("sl", "Stop loss", DOWN),
            ("rule", "Rule", TEXT_MUTED),
        ):
            row = QHBoxLayout()
            row.setSpacing(6)
            name = QLabel(caption)
            name.setObjectName("hintLabel")
            name.setFixedWidth(64)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                f"QProgressBar {{ background: #1d1e23; border: none; border-radius: 4px; }}"
                f"QProgressBar::chunk {{ background: {colour}; border-radius: 4px; }}"
            )
            pct = QLabel("0%")
            pct.setObjectName("hintLabel")
            pct.setFixedWidth(32)
            row.addWidget(name)
            row.addWidget(bar, 1)
            row.addWidget(pct)
            rail_layout.addLayout(row)
            self.end_bars[key] = (bar, pct)
        rail_layout.addSpacing(6)
        dist = QLabel("PnL distribution")
        dist.setObjectName("panelTitle")
        rail_layout.addWidget(dist)
        self.pnl_bars = PnlBars()
        rail_layout.addWidget(self.pnl_bars, 1)
        body.addWidget(rail, 0)
        over.addLayout(body, 1)
        self.stack.addWidget(overview)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["Market (UTC)", "Side", "In", "Buy", "Out", "Sold", "Stake $", "PnL $",
             "Ended", "Prices"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._bet_picked)
        self.stack.addWidget(self.table)
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
        self.strategy.blockSignals(True)
        self.strategy.clear()
        saved = strategies.load()
        for item in saved:
            self.strategy.addItem(item.name)
        if not saved:
            self.strategy.addItem("(no saved strategy: build one in the Builder)")
        self.strategy.setEnabled(bool(saved))
        self.strategy.blockSignals(False)
        self._rules()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh_strategies()
        self.refresh_coverage()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not event.modifiers() and event.key() == Qt.Key.Key_Space:
            self._run()
            event.accept()
            return
        super().keyPressEvent(event)

    def _download(self) -> None:
        if self._downloader is not None and self._downloader.busy():
            self._downloader.cancel()
            self.download_note.setText("stopping…")
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
        self.note.setText("running…")
        self.progress.setRange(0, 0)           # busy
        self._worker = RunWorker(rules[0], rules[1], self._params(), first, last, rules[2])
        self._worker.done.connect(self._show)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 1000)
        self.note.setText(f"failed: {message}")

    # -- showing the result -----------------------------------------------

    def _set(self, label: QLabel, text: str, tone: str = "text") -> None:
        label.setText(text)
        label.setObjectName(f"metricValue_{tone}")
        label.style().unpolish(label)
        label.style().polish(label)

    def _show(self, payload) -> None:
        result, baselines, rows = payload
        self._result, self._rows = result, rows
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 1000)
        self.progress.setValue(1000)
        trades = result.trades
        n = len(trades)
        if result.windows == 0:
            self.note.setText("no complete five-minute windows of Binance candles in this span")
            self.progress_label.setText("—")
            self.results_note.setText("download candles in the Hyperliquid backtest first")
            self.table.setRowCount(0)
            self.curve.set_session(None)
            self.drawdown.set_curve([])
            self.pnl_bars.set_values([])
            self.chart.set_bet(None, None)
            return
        capital = result.params.capital
        pnl_pct = (result.final_equity / capital - 1.0) * 100.0 if capital else 0.0
        real = sum(1 for t in trades if t.real_price)
        estimated = sum(1 for t in trades if t.estimated_outcome)
        self.note.setText(
            f"finished — {n:,} bets, {result.win_rate:.0%} won"
            + (f", {estimated:,} outcomes estimated" if estimated else "")
        )
        self.progress_label.setText(f"100% · {result.windows:,} / {result.windows:,} markets")
        tone = "down" if pnl_pct < 0 else "accent"
        avg_buy = (sum(t.entry_price for t in trades) / n * 100.0) if n else 0.0
        figures = {
            "PnL": (f"{pnl_pct:+.2f}%", tone),
            "Equity": (f"${result.final_equity:,.0f}", "text"),
            "Final": (f"${result.final_equity:,.2f}", "text"),
            "Max DD": (f"-{result.max_drawdown * 100:.2f}%",
                       "down" if result.max_drawdown else "text"),
            "ROI on stake": (f"{result.roi * 100:+.2f}%", "down" if result.roi < 0 else "accent"),
            "Bets": (f"{n:,}", "text"),
            "Win rate": (f"{result.win_rate:.0%}", "text"),
            "Cashed out": (f"{result.early:,}", "text"),
            "Avg buy": (f"{avg_buy:.0f}¢", "text"),
            "Real prices": (f"{real / n:.0%}" if n else "—", "text"),
        }
        for key, (text, how) in figures.items():
            if key in self.stat:
                self._set(self.stat[key], text, how)
            if key in self.metrics:
                self._set(self.metrics[key], text, how)

        self.results_note.setText(
            f"bets on {result.windows:,} markets, equity read market by market · "
            f"{real:,} of {n:,} bets entered at a real price, the rest simulated · "
            f"{result.params.half_spread * 100:g}¢ half spread assumed"
        )
        self.curve.set_session(_Curves(
            result.window_equity, baselines["up"].window_equity,
            baselines["down"].window_equity,
        ))
        self.drawdown.set_curve(result.window_equity)
        self.pnl_bars.set_values([t.pnl / t.stake * 100.0 for t in trades if t.stake])

        kinds = {"settled": 0, "tp": 0, "sl": 0, "rule": 0}
        for t in trades:
            if t.exit_minute == binary.STEPS:
                kinds["settled"] += 1
            elif t.reason == "Take profit":
                kinds["tp"] += 1
            elif t.reason == "Stop loss":
                kinds["sl"] += 1
            else:
                kinds["rule"] += 1
        for key, (bar, pct) in self.end_bars.items():
            share = round(kinds[key] / n * 100) if n else 0
            bar.setValue(share)
            pct.setText(f"{share}%")

        self._fill_table(trades)

    def _fill_table(self, trades: list[binary.BinaryTrade]) -> None:
        shown = trades[-BETS_SHOWN:][::-1]
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for trade in shown:
            at = self.table.rowCount()
            self.table.insertRow(at)
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
                self.table.setItem(at, column, item)
        self.table.blockSignals(False)
        self._shown = shown
        if shown:
            self.table.selectRow(0)
        else:
            self.chart.set_bet(None, None)

    def _bet_picked(self) -> None:
        model = self.table.selectionModel()
        rows = model.selectedRows() if model else []
        if not rows or not self._shown:
            return
        trade = self._shown[rows[0].row()]
        self.chart.set_bet(trade, self._rows.get(trade.start_ms))


__all__ = ["PolymarketBacktestWindow", "load_candles"]
