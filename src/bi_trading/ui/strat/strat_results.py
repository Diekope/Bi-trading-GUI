"""The results tile: three return curves, drawn as the run goes.

The strategy, a random-buy strategy, and buy and hold, revealed point by point
as the playback walks. Random-buy is the benchmark that matters: any entry rule
that cannot beat buying at random has no edge, so both are drawn against the
same exits, sizing and fees.

Everything is drawn as **return from the start**, not as a dollar balance.
Over a long span buy and hold compounds many times over, while a strategy that
deploys a fraction of the book per trade barely moves; in dollars the first
would flatten the others into the axis. In percent the two strategies stay
readable, and buy and hold is left to run off the top with its number in the
legend.

The curve data comes from `bi_trading.ui.strat.strat_playback` — this module only knows how
to draw it.
"""

from __future__ import annotations

from datetime import datetime, UTC

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFileDialog,
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bi_trading.engine.stats import (
    annualised_return,
    bars_per_year,
    by_year,
    calmar,
    cost_stress,
    trade_stats,
    write_trades_csv,
)
from bi_trading.ui.cards import mono_font
from bi_trading.ui.panels import Card
from bi_trading.ui.theme import ACCENT, BAND, BORDER, DOWN, TEXT_FAINT, TEXT_MUTED, UP

# Amber is the strategy, indigo the random-buy stand-in, grey buy and hold.
STRATEGY_COLOUR = ACCENT
RANDOM_COLOUR = BAND
HOLD_COLOUR = TEXT_MUTED
# A saved run laid over the current one: its strategy curve, in teal.
OVERLAY_COLOUR = "#4dd0c8"

# Never let the scale collapse to a flat line around zero.
MIN_SPAN = 0.4  # percent
PAD = 0.08


def _returns(curve: list[float]) -> list[float]:
    if not curve or curve[0] <= 0:
        return []
    first = curve[0]
    return [(value / first - 1.0) * 100.0 for value in curve]


def _resample(curve: list[float], count: int) -> list[float]:
    """`curve` cut to at most `count` points, keeping its shape (and its ends)."""
    if len(curve) <= count or count < 2:
        return list(curve)
    last = len(curve) - 1
    return [curve[round(i * last / (count - 1))] for i in range(count)]


class LiveCurve(QWidget):
    """The run's three curves, revealed up to wherever the walk has reached."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = None
        # A saved run's strategy curve, as returns in percent, drawn over the
        # current one; empty when none is laid on.
        self.overlay: list[float] = []
        self.message = "run the backtest to see the curves"
        self.setMinimumHeight(80)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_session(self, session) -> None:
        self.session = session
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        left = 56.0
        right = width - 8.0
        top = 14.0
        bottom = height - 16.0
        if right - left < 40 or bottom - top < 30:
            return

        session = self.session
        if session is None or not session.strategy_curve:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        strategy = _returns(session.strategy_curve)
        random_buy = _returns(session.random_curve)
        hold = _returns(session.benchmark)
        # The scale follows the two strategies and an overlaid run; buy and hold
        # may run past it.
        low = min(strategy + random_buy + self.overlay + [0.0])
        high = max(strategy + random_buy + self.overlay + [0.0])
        span = max(high - low, MIN_SPAN)
        low -= span * PAD
        high += span * PAD

        points = max(1, len(strategy) - 1)

        def x_of(index: int) -> float:
            return left + (right - left) * index / points

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        # Grid, labelled in percent, with the break-even line picked out.
        painter.setFont(mono_font(7))
        for step in range(3):
            value = low + (high - low) * step / 2.0
            y = y_of(value)
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(left, y, right, y)
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(0, y - 7, left - 6, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:+,.2f}%",
            )

        # Buy and hold first, then random-buy, the overlaid run, and the
        # strategy on top. The overlay is stretched to the same width, so two
        # runs of different length are read by how far through each one is.
        for curve, colour, style, width_pt in (
            (hold, HOLD_COLOUR, Qt.PenStyle.DashLine, 1.0),
            (random_buy, RANDOM_COLOUR, Qt.PenStyle.SolidLine, 1.2),
            (_resample(self.overlay, 2 * int(right - left)), OVERLAY_COLOUR,
             Qt.PenStyle.DashDotLine, 1.4),
            (strategy, STRATEGY_COLOUR, Qt.PenStyle.SolidLine, 1.6),
        ):
            if len(curve) < 2:
                continue
            painter.setPen(QPen(QColor(colour), width_pt, style))
            painter.drawPolyline(
                [QPointF(x_of(i), y_of(v)) for i, v in enumerate(curve)]
            )

        # The walk's position along the bottom, and a word when buy and hold
        # has left the chart.
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        painter.drawText(
            QRectF(left, bottom + 1, 200, 13),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{session.index:,} / {session.total:,} bars",
        )
        if hold and hold[-1] > high:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRectF(right - 180, top - 2, 180, 13),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "buy & hold is off the top",
            )


class ResultsTile(Card):
    """The run's results, in two parts: an Overview and a Trades table."""

    trade_selected = Signal(object)
    part_changed = Signal(int)   # a part was picked: 0 overview, 1 trades, 2 compare

    # How many of the newest trades the table shows; a run can hold far more.
    TRADES_SHOWN = 400

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        title = QLabel("RESULTS")
        title.setObjectName("tileTitle")
        header.addWidget(title)
        header.addStretch(1)

        # The two parts, as small pills: Overview and Trades.
        self.tabs = QButtonGroup(self)
        self.tabs.setExclusive(True)
        self.tab_buttons: dict[str, QPushButton] = {}
        for index, (key, caption) in enumerate(
            (("overview", "Overview"), ("trades", "Trades"), ("compare", "Compare"))
        ):
            button = QPushButton(caption)
            button.setObjectName("resultTab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tabs.addButton(button, index)
            self.tab_buttons[key] = button
            header.addWidget(button)
        self.tabs.idClicked.connect(self.set_part)
        self.body.addLayout(header)

        self.note = QLabel("no run yet")
        self.note.setObjectName("hintLabel")
        self.body.addWidget(self.note)

        self.stack = QStackedWidget()
        self.stack.setObjectName("resultsStack")
        self.body.addWidget(self.stack, 1)

        # Overview: the figures, the three curves, and how the trades ended.
        overview = QWidget()
        overview.setObjectName("overviewPage")
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(8)

        # Every figure on one line, a size up from the playback tile's: the headline
        # figures first, then what one trade is worth (read off the trade log).
        figures = QHBoxLayout()
        figures.setContentsMargins(0, 0, 0, 0)
        figures.setSpacing(22)
        self.metrics: dict[str, QLabel] = {}
        for key, caption, tip in (
            ("pnl", "PnL", ""),
            ("sharpe", "Sharpe", ""),
            ("maxdd", "Max DD", ""),
            ("trades", "Trades", ""),
            ("win", "Win rate", ""),
            ("fees", "Fees", ""),
            ("expectancy", "Expectancy", "the average trade: its return, and its profit in dollars"),
            ("hold", "Avg hold", "bars a trade ran, on average"),
            ("exposure", "Exposure", "the share of bars with a position open"),
            ("pf", "Profit factor", "what the winners made over what the losers lost"),
            ("sortino", "Sortino", "the average trade over its downside deviation (losing trades "
             "only); per trade and not annualised, unlike the Sharpe, which is per bar"),
        ):
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            cap = QLabel(caption)
            cap.setObjectName("fieldLabel")
            value = QLabel("—")
            value.setObjectName("metricValue_text")
            value.setFont(mono_font(11, bold=True))
            if tip:
                cap.setToolTip(tip)
                value.setToolTip(tip)
            box.addWidget(cap)
            box.addWidget(value)
            figures.addLayout(box)
            self.metrics[key] = value
        figures.addStretch(1)
        # The line clips rather than forcing the window wider when it is narrow.
        figures_row = QWidget()
        figures_row.setObjectName("resultsPage")      # a plain container: no canvas fill
        figures_row.setLayout(figures)
        figures_row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        overview_layout.addWidget(figures_row)

        # How much the figures can be trusted: the risk on a yearly footing, the
        # doubt on the average trade, what higher costs do, and each year apart.
        # Hidden until a run has trades, so an idle tile keeps its shape.
        self.evidence = QLabel("")
        self.evidence.setObjectName("hintLabel")
        self.evidence.setWordWrap(True)
        self.evidence.setVisible(False)
        overview_layout.addWidget(self.evidence)
        self.years = QLabel("")
        self.years.setObjectName("hintLabel")
        self.years.setWordWrap(True)
        self.years.setVisible(False)
        overview_layout.addWidget(self.years)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        self.curve = LiveCurve()
        left.addWidget(self.curve, 1)

        # The drawdown, the same width as the curves above it.
        dd_title = QLabel("Drawdown")
        dd_title.setObjectName("hintLabel")
        dd_title.setContentsMargins(0, 10, 0, 0)
        left.addWidget(dd_title)
        self.drawdown = DrawdownCurve()
        left.addWidget(self.drawdown)

        legend = QHBoxLayout()
        legend.setContentsMargins(0, 0, 0, 0)
        legend.setSpacing(12)
        self.legend: dict[str, QLabel] = {}
        for key, caption in (
            ("strategy", "strategy"),
            ("random", "random buy"),
            ("hold", "buy & hold"),
            ("overlay", ""),
        ):
            label = QLabel(caption)
            label.setObjectName(f"legend_{key}")
            label.setFont(mono_font(8, bold=True))
            legend.addWidget(label)
            self.legend[key] = label
        self.legend["overlay"].setVisible(False)
        legend.addStretch(1)
        left.addLayout(legend)
        body.addLayout(left, 1)

        # How the trades ended, and by side.
        rail = QWidget()
        rail.setObjectName("resultsRail")
        rail.setFixedWidth(240)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(6)
        end_title = QLabel("How trades end")
        end_title.setObjectName("panelTitle")
        rail_layout.addWidget(end_title)
        self.end_bars: dict[str, tuple] = {}
        for key, caption, colour in (
            ("tp", "Take profit", UP),
            ("sl", "Stop loss", DOWN),
            ("time", "Time", BAND),
            ("rule", "Rule", TEXT_MUTED),
            ("gap", "Data gap", TEXT_MUTED),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            name = QLabel(caption)
            name.setObjectName("hintLabel")
            name.setFixedWidth(64)
            bar = QProgressBar()
            bar.setObjectName("endBar")
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                f"QProgressBar {{ background: #1d1e23; border: none;"
                f" border-radius: 4px; }}"
                f"QProgressBar::chunk {{ background: {colour};"
                f" border-radius: 4px; }}"
            )
            pct = QLabel("0%")
            pct.setObjectName("hintLabel")
            pct.setFixedWidth(32)
            row.addWidget(name)
            row.addWidget(bar, 1)
            row.addWidget(pct)
            rail_layout.addLayout(row)
            self.end_bars[key] = (bar, pct)

        # The spread of trade returns, under the ends, down the same column.
        rail_layout.addSpacing(6)
        pnl_title = QLabel("PnL distribution")
        pnl_title.setObjectName("panelTitle")
        rail_layout.addWidget(pnl_title)
        self.pnl_bars = PnlBars()
        rail_layout.addWidget(self.pnl_bars, 1)
        body.addWidget(rail, 0)

        overview_layout.addLayout(body, 1)
        self.stack.addWidget(overview)

        # Trades: a filterable table with a detail panel for the picked trade.
        self.trades_page = TradesPage()
        self.trades_page.trade_selected.connect(self.trade_selected)
        self.stack.addWidget(self.trades_page)

        # Compare: the run against its stand-ins, a TP/SL sweep and walk-forward.
        from bi_trading.ui.strat.strat_compare import ComparePage

        self.compare = ComparePage()
        self.compare_hint = QLabel(
            "Compare needs an entry rule: pick Bollinger reversion or a saved strategy."
        )
        self.compare_hint.setObjectName("hintLabel")
        compare_page = QWidget()
        compare_page.setObjectName("resultsPage")   # a plain container: no canvas fill
        compare_layout = QVBoxLayout(compare_page)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.setSpacing(6)
        compare_layout.addWidget(self.compare_hint)
        compare_layout.addWidget(self.compare, 1)
        self.stack.addWidget(compare_page)

    # -- the parts ---------------------------------------------------------

    def part(self) -> str:
        for key, button in self.tab_buttons.items():
            if button.isChecked():
                return key
        return "overview"

    def set_part(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        keys = list(self.tab_buttons)
        if 0 <= index < len(keys):
            self.tab_buttons[keys[index]].setChecked(True)
        if index == 1:
            self.trades_page.refresh()
        self.note.setText(
            "return since the start, read as the loop walks"
            if index == 0
            else "closed trades, newest first"
            if index == 1
            else "the rule on the last bars, against a random buy and buy & hold"
        )
        self.part_changed.emit(index)

    # -- the run -----------------------------------------------------------

    def set_session(self, session) -> None:
        self.curve.set_session(session)
        self.trades_page.set_session(session)
        self.note.setText("return since the start, read as the loop walks")
        self.refresh()

    def set_compare_inputs(
        self, bars, entry, exit_, tp: float, sl: float,
        short: bool = False, short_entry=None,
    ) -> None:
        """Feed Compare: the last bars, the rule, and the run's TP and SL.

        Without an entry rule (the random baseline) there is nothing to sweep, so
        it says so instead of drawing an empty page.
        """
        self.compare_hint.setVisible(entry is None or not bars)
        if entry is None or not bars:
            self.compare.configure([], None, None, None, tp, sl)
            return
        from bi_trading.engine.formula_eval import backtest

        report = backtest(
            bars, entry, exit_, tp=tp, sl=sl, short=short, short_entry=short_entry
        )
        self.compare.configure(bars, entry, exit_, report, tp, sl, short, short_entry)

    def set_overlay(self, name: str, curve: list[float] | None) -> None:
        """Lay a saved run's strategy curve over the current one; none clears it."""
        label = self.legend["overlay"]
        if not name or not curve:
            self.curve.overlay = []
            label.setVisible(False)
        else:
            self.curve.overlay = _returns(list(curve))
            gained = self.curve.overlay[-1]
            label.setText(f"overlay: {name} {gained:+,.2f}%")
            label.setStyleSheet(f"color: {OVERLAY_COLOUR};")
            label.setVisible(True)
        self.curve.update()

    def clear_session(self) -> None:
        self.curve.set_session(None)
        self.note.setText("no run yet")
        self.trades_page.clear()
        for value in self.metrics.values():
            value.setText("—")
        self.evidence.setVisible(False)
        self.years.setVisible(False)
        for bar, pct in self.end_bars.values():
            bar.setValue(0)
            pct.setText("0%")
        self.pnl_bars.set_values([])
        self.drawdown.set_curve([])
        for key, caption in (
            ("strategy", "strategy"),
            ("random", "random buy"),
            ("hold", "buy & hold"),
        ):
            self.legend[key].setText(caption)

    def refresh(self) -> None:
        """The legend carries the running totals, so they move with the lines."""
        session = self.curve.session
        if session is None:
            return
        for key, name, curve in (
            ("strategy", "strategy", session.strategy_curve),
            ("random", "random buy", session.random_curve),
            ("hold", "buy & hold", session.benchmark),
        ):
            percent = session.return_of(curve) * 100
            self.legend[key].setText(f"{name} {percent:+,.2f}%")
        self.curve.update()
        self._refresh_figures(session)
        if self.stack.currentIndex() == 1:
            self.trades_page.refresh()

    def _refresh_figures(self, session) -> None:
        play = session.strategy
        pnl = play.equity / play.capital - 1.0
        self.metrics["pnl"].setText(f"{pnl * 100:+,.2f}%")
        self.metrics["sharpe"].setText(f"{play.sharpe:,.2f}")
        self.metrics["maxdd"].setText(f"{play.max_drawdown * 100:,.2f}%")
        self.metrics["trades"].setText(f"{play.trades:,}")
        self.metrics["win"].setText(f"{play.win_rate * 100:,.0f}%")
        self.metrics["fees"].setText(f"${play.fees:,.0f}")
        self.metrics["fees"].setToolTip(
            f"{play.fee * 100:.3g}% fee + {play.slippage * 100:.3g}% slippage "
            "on each fill"
        )
        stats = trade_stats(play.trades_log, play.index or session.total)
        if stats.trades:
            self.metrics["expectancy"].setText(
                f"{stats.expectancy * 100:+,.2f}% · "
                f"{'-' if stats.expectancy_usd < 0 else '+'}${abs(stats.expectancy_usd):,.2f}"
            )
            self.metrics["hold"].setText(f"{stats.average_hold:,.1f} bars")
            self.metrics["exposure"].setText(f"{stats.exposure * 100:,.0f}%")
            self.metrics["pf"].setText(
                "—" if stats.profit_factor is None else f"{stats.profit_factor:,.2f}"
            )
            self.metrics["sortino"].setText(
                "—" if stats.sortino is None else f"{stats.sortino:,.2f}"
            )
        else:
            for key in ("expectancy", "hold", "exposure", "pf", "sortino"):
                self.metrics[key].setText("—")
        self._refresh_evidence(session, play, stats, pnl)
        self.pnl_bars.set_values([record[6] for record in play.trades_log])
        self.drawdown.set_curve(session.strategy_curve)

        reasons = {"tp": 0, "sl": 0, "time": 0, "rule": 0, "gap": 0}
        for record in play.trades_log:
            reasons[record[9]] = reasons.get(record[9], 0) + 1
        total = max(1, sum(reasons.values()))
        for key, (bar, pct) in self.end_bars.items():
            share = reasons.get(key, 0) / total * 100
            bar.setValue(int(round(share)))
            pct.setText(f"{share:,.0f}%")


    def _refresh_evidence(self, session, play, stats, pnl: float) -> None:
        """The two small lines under the figures (see `evidence`, `years`)."""
        bars = play.index or session.total
        if not stats.trades or bars <= 0:
            self.evidence.setVisible(False)
            self.years.setVisible(False)
            return
        per_year = bars_per_year(session.resolution)
        wet = play.longest_underwater
        days = wet / per_year * 365.0
        parts = []
        if stats.few:
            parts.append(f"only {stats.trades} trades: too few to tell skill from luck")
        # A yearly rate from a few days is a number about nothing: show it only
        # for a span of at least a month.
        if bars / per_year * 365.0 >= MIN_ANNUAL_DAYS:
            annual = annualised_return(pnl, bars, per_year)
            ratio = calmar(annual, play.max_drawdown)
            parts.append(f"Sharpe/yr {play.sharpe * per_year**0.5:,.2f}")
            parts.append("Calmar " + ("—" if ratio is None else f"{ratio:,.2f}"))
        else:
            parts.append(f"span under {MIN_ANNUAL_DAYS} days: no yearly Sharpe or Calmar")
        parts.append(f"longest under water {wet:,} bars ({days:,.1f} days)")
        if stats.t_stat is not None and stats.p_value is not None:
            parts.append(
                f"trade Sharpe {stats.sharpe_trade or 0.0:,.3f} · t {stats.t_stat:+.2f} "
                f"(p {stats.p_value:.2f}) · avg trade 95% "
                f"{stats.ci_low * 100:+.2f}% to {stats.ci_high * 100:+.2f}%"
            )
        now, stressed = cost_stress(play.trades_log, play.slippage)
        parts.append(f"PnL ${now:,.0f} at these costs, ${stressed:,.0f} at 2x")
        self.evidence.setText("  |  ".join(parts))
        self.evidence.setToolTip(
            "Yearly figures assume BTC trades every minute of the year. The t, p and "
            "interval assume independent trades; 2x costs is a first-order estimate "
            "from the trade log, not a second run."
        )
        self.evidence.setVisible(True)
        years = by_year(play.trades_log)
        self.years.setText(
            "By year:  "
            + "  |  ".join(
                f"{year or '?'}: {count} trades, {'-' if profit < 0 else '+'}${abs(profit):,.0f}, "
                f"{win * 100:.0f}% won"
                for year, count, profit, win in years
            )
        )
        self.years.setVisible(len(years) > 0)


MIN_ANNUAL_DAYS = 30


class PnlBars(QWidget):
    """A histogram of the trades' returns — where the money landed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pnlBars")
        self.setMinimumHeight(90)
        self._values: list[float] = []

    def set_values(self, values: list[float]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 6, -4, -10)
        if not self._values or rect.width() <= 0 or rect.height() <= 0:
            return
        low = min(self._values)
        high = max(self._values)
        if high - low < 1e-9:
            high = low + 1e-9
        bins = 32
        counts = [0] * bins
        for value in self._values:
            index = min(bins - 1, int((value - low) / (high - low) * bins))
            counts[index] += 1
        peak = max(counts) or 1
        width = rect.width() / bins
        zero_x = rect.left() + (0 - low) / (high - low) * rect.width()
        painter.setPen(QPen(QColor(BORDER), 1))
        if rect.left() <= zero_x <= rect.right():
            painter.drawLine(
                QPointF(zero_x, rect.top()), QPointF(zero_x, rect.bottom())
            )
        for index, count in enumerate(counts):
            if not count:
                continue
            centre = low + (index + 0.5) * (high - low) / bins
            height = count / peak * rect.height()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(UP if centre >= 0 else DOWN)
            )
            painter.drawRect(
                QRectF(
                    rect.left() + index * width + 0.5,
                    rect.bottom() - height,
                    max(1.0, width - 1.0),
                    height,
                )
            )
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            QRectF(rect.left(), rect.bottom() + 1, rect.width(), 10),
            Qt.AlignmentFlag.AlignLeft,
            f"{low * 100:+.1f}%",
        )
        painter.drawText(
            QRectF(rect.left(), rect.bottom() + 1, rect.width(), 10),
            Qt.AlignmentFlag.AlignRight,
            f"{high * 100:+.1f}%",
        )


class DrawdownCurve(QWidget):
    """The equity's drawdown under the run — how far below the peak it fell."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drawdownCurve")
        self.setMinimumHeight(44)
        self._curve: list[float] = []

    def set_curve(self, curve: list[float]) -> None:
        self._curve = list(curve)
        self.update()

    def _drawdowns(self) -> list[float]:
        out: list[float] = []
        peak = 0.0
        for value in self._curve:
            peak = max(peak, value)
            out.append(value / peak - 1.0 if peak > 0 else 0.0)
        return out

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 6, -4, -10)
        series = self._drawdowns()
        if len(series) < 2 or rect.width() <= 0 or rect.height() <= 0:
            return
        worst = min(series) or -1e-6
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawLine(
            QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top())
        )
        points = [
            QPointF(
                rect.left() + rect.width() * index / (len(series) - 1),
                rect.top() + (value / worst) * rect.height(),
            )
            for index, value in enumerate(series)
        ]
        area = QPolygonF([QPointF(rect.left(), rect.top()), *points,
                          QPointF(rect.right(), rect.top())])
        fill = QColor(DOWN)
        fill.setAlpha(40)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPolygon(area)
        painter.setPen(QPen(QColor(DOWN), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for start, end in zip(points, points[1:], strict=False):
            painter.drawLine(start, end)
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            QRectF(rect.left(), rect.bottom() + 1, rect.width(), 10),
            Qt.AlignmentFlag.AlignLeft,
            f"{worst * 100:,.1f}%",
        )


class TradeSpark(QWidget):
    """A trade drawn small: its candles when they can be read, else a line.

    The candles run from a few bars before the entry to a few after the exit, the
    entry and the exit marked on them. When the bars are not on disk (a sample
    run) it falls back to a line through the prices the trade saw.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tradeSpark")
        self.setMinimumHeight(72)
        self._trade: dict | None = None
        self._bars: list = []

    def set_trade(self, trade: dict | None, bars: list | None = None) -> None:
        self._trade = trade
        self._bars = list(bars or [])
        self.update()

    def _paint_candles(self, painter: QPainter, rect, trade: dict) -> bool:
        bars = self._bars
        if len(bars) < 2:
            return False
        low = min(bar.low for bar in bars)
        high = max(bar.high for bar in bars)
        spread = high - low or abs(high) * 1e-3 or 1.0
        low -= spread * 0.1
        high += spread * 0.1
        slot = rect.width() / len(bars)
        body = max(1.0, min(8.0, slot * 0.6))

        def y_of(price: float) -> float:
            return rect.bottom() - (price - low) / (high - low) * rect.height()

        entered = exited = None
        for index, bar in enumerate(bars):
            x = rect.left() + slot * (index + 0.5)
            colour = QColor(UP if bar.close >= bar.open else DOWN)
            painter.setPen(QPen(colour, 1))
            painter.drawLine(QPointF(x, y_of(bar.high)), QPointF(x, y_of(bar.low)))
            top, bottom = sorted((y_of(bar.open), y_of(bar.close)))
            painter.setBrush(colour)
            painter.drawRect(QRectF(x - body / 2, top, body, max(1.0, bottom - top)))
            if entered is None and bar.stamp >= int(trade["in_stamp"]):
                entered = (x, float(trade["in_price"]))
            if bar.stamp <= int(trade["out_stamp"]):
                exited = (x, float(trade["out_price"]))
        painter.setPen(Qt.PenStyle.NoPen)
        if entered is not None:
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(QPointF(entered[0], y_of(entered[1])), 3, 3)
        if exited is not None:
            painter.setBrush(QColor("#c9cad0"))
            painter.drawEllipse(QPointF(exited[0], y_of(exited[1])), 3, 3)
        return True

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101114"))
        trade = self._trade
        if trade is None:
            return
        rect = self.rect().adjusted(8, 8, -8, -8)
        if self._paint_candles(painter, rect, trade):
            return
        path = list(trade.get("path") or [])
        if not path:
            path = [float(trade["in_price"]), float(trade["out_price"])]
        low, high = min(path), max(path)
        spread = high - low or abs(high) * 1e-3 or 1.0
        low -= spread * 0.2
        high += spread * 0.2

        def point(index: int, price: float) -> QPointF:
            x = rect.left() + (
                rect.width() * index / max(1, len(path) - 1)
            )
            y = rect.bottom() - (price - low) / (high - low) * rect.height()
            return QPointF(x, y)

        rising = float(trade["out_price"]) >= float(trade["in_price"])
        colour = QColor(UP if rising else DOWN)
        painter.setPen(QPen(QColor("#c9cad0"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        points = [point(i, p) for i, p in enumerate(path)]
        for start, end in zip(points, points[1:], strict=False):
            painter.drawLine(start, end)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(points[0], 3, 3)
        painter.setBrush(colour)
        painter.drawEllipse(points[-1], 3, 3)


STRIP_ROLE = Qt.ItemDataRole.UserRole + 1   # a row's strip: [(open, high, low, close), …]
STRIP_WIDTH = 150


class _StripDelegate(QStyledItemDelegate):
    """The "In → Out" cell: the prices as text, and the trade's candles beside it."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        strip = index.data(STRIP_ROLE)
        if not strip or len(strip) < 2:
            return
        rect = QRectF(option.rect).adjusted(0, 5, -8, -5)
        rect.setLeft(max(rect.left(), rect.right() - STRIP_WIDTH))
        low = min(bar[2] for bar in strip)
        high = max(bar[1] for bar in strip)
        spread = (high - low) or abs(high) * 1e-3 or 1.0
        slot = rect.width() / len(strip)
        body = max(1.0, min(5.0, slot * 0.6))

        def y_of(price: float) -> float:
            return rect.bottom() - (price - low) / spread * rect.height()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for position, (open_, high_, low_, close) in enumerate(strip):
            x = rect.left() + slot * (position + 0.5)
            colour = QColor(UP if close >= open_ else DOWN)
            painter.setPen(QPen(colour, 1))
            painter.drawLine(QPointF(x, y_of(high_)), QPointF(x, y_of(low_)))
            top, bottom = sorted((y_of(open_), y_of(close)))
            painter.setBrush(colour)
            painter.drawRect(QRectF(x - body / 2, top, body, max(1.0, bottom - top)))
        painter.restore()


class TradesPage(QWidget):
    """The closed trades: a filter row, a table, and the picked trade beside it."""

    trade_selected = Signal(object)

    # How many of the newest trades the table reads; a run can hold far more.
    SHOWN = 400
    REASONS = {"tp": "TP", "sl": "SL", "time": "Time", "rule": "Rule", "gap": "Data gap"}
    COLUMNS = ("Entry", "Market", "Side", "In → Out", "Size", "PnL", "Exit")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tradesPage")
        self.session = None
        self.trades: list[dict] = []
        self._shown: list[dict] = []
        self._last_total = -1
        # Each trade's strip of candles, kept so a filter or a refresh does not read
        # the store again: {(entry stamp, exit stamp): strip or None}.
        self._strips: dict[tuple[int, int], list | None] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # The filter row, as in the mock.
        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("tradeSearch")
        self.search.setPlaceholderText("search a trade…")
        self.search.setFixedWidth(200)
        self.side = QComboBox()
        self.side.addItems(["side: all", "Long", "Short"])
        self.side.setFixedWidth(110)
        self.outcome = QComboBox()
        self.outcome.addItems(["result: all", "win", "loss"])
        self.outcome.setFixedWidth(130)
        self.exit = QComboBox()
        self.exit.addItems(["exit: all", "TP", "SL", "Time", "Rule"])
        self.exit.setFixedWidth(140)
        self.count = QLabel("0 trades")
        self.count.setObjectName("hintLabel")
        self.export_button = QPushButton("Export CSV")
        self.export_button.setObjectName("ghostButton")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.setToolTip("write every trade of the run to a CSV file (times in UTC)")
        self.export_button.clicked.connect(lambda: self.export_csv())
        filters.addWidget(self.search)
        filters.addWidget(self.side)
        filters.addWidget(self.outcome)
        filters.addWidget(self.exit)
        filters.addStretch(1)
        filters.addWidget(self.count)
        filters.addWidget(self.export_button)
        layout.addLayout(filters)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)

        self.table = QTableWidget()
        self.table.setObjectName("tradesTable")
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setShowGrid(False)
        head = self.table.horizontalHeader()
        for column in range(len(self.COLUMNS)):
            head.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(3, _StripDelegate(self.table))
        body.addWidget(self.table, 1)

        detail = QFrame()
        detail.setObjectName("tradeDetail")
        detail.setFixedWidth(270)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(10, 8, 10, 10)
        detail_layout.setSpacing(4)
        self.detail_title = QLabel("Trade —")
        self.detail_title.setObjectName("panelTitle")
        detail_layout.addWidget(self.detail_title)
        self.spark = TradeSpark()
        detail_layout.addWidget(self.spark)
        self.detail_rows: dict[str, QLabel] = {}
        for key, caption in (
            ("entry", "Entry"),
            ("exit", "Exit"),
            ("reason", "Reason"),
            ("duration", "Duration · fees"),
            ("return", "Return"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            name = QLabel(caption)
            name.setObjectName("hintLabel")
            value = QLabel("—")
            value.setObjectName("tradeValue")
            value.setFont(mono_font(8, bold=True))
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(value)
            detail_layout.addLayout(row)
            self.detail_rows[key] = value
        detail_layout.addStretch(1)
        body.addWidget(detail, 0)

        layout.addLayout(body, 1)

        self.search.textChanged.connect(self._reapply)
        self.side.currentIndexChanged.connect(self._reapply)
        self.outcome.currentIndexChanged.connect(self._reapply)
        self.exit.currentIndexChanged.connect(self._reapply)
        self.table.itemSelectionChanged.connect(
            lambda: self._show_detail(emit=True)
        )

    # -- the run -----------------------------------------------------------

    def set_session(self, session) -> None:
        self.session = session
        self._strips.clear()           # another run may be on another span or resolution
        self.refresh()

    def export_csv(self, path: str | None = None) -> int:
        """Write every trade of the run (not just the newest shown) to a CSV.

        With no `path` it asks where. Returns how many trades were written, 0 if
        there is nothing to write or the dialog was cancelled.
        """
        if self.session is None or not self.session.strategy.trades_log:
            self.count.setText("no trades to export")
            return 0
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export trades", "trades.csv", "CSV (*.csv)"
            )
            if not path:
                return 0
        try:
            written = write_trades_csv(self.session.strategy.trades_log, path)
        except OSError as exc:
            self.count.setText(f"could not write: {exc.strerror or exc}")
            return 0
        self.count.setText(f"{written:,} trades written")
        return written

    def clear(self) -> None:
        self.session = None
        self.trades = []
        self._shown = []
        self._last_total = -1
        self._strips.clear()
        self.table.setRowCount(0)
        self.count.setText("0 trades")
        self.spark.set_trade(None)

    def refresh(self) -> None:
        if self.session is None:
            self.clear()
            return
        total = self.session.strategy.trades
        if total == self._last_total and self.trades:
            return  # nothing new: leave the table where it is
        self._last_total = total
        log = self.session.strategy.trades_log[-self.SHOWN :]
        total = self.session.strategy.trades
        self.trades = []
        for offset, record in enumerate(reversed(log)):
            (
                in_stamp,
                in_index,
                in_price,
                out_stamp,
                out_index,
                out_price,
                result,
                size,
                pnl,
                reason,
                fees,
                path,
                direction,
            ) = record
            self.trades.append(
                {
                    "n": total - offset,
                    "in_stamp": in_stamp,
                    "in_index": in_index,
                    "in_price": in_price,
                    "out_stamp": out_stamp,
                    "out_index": out_index,
                    "out_price": out_price,
                    "result": result,
                    "size": size,
                    "pnl": pnl,
                    "reason": reason,
                    "fees": fees,
                    "path": path,
                    "side": "Short" if direction == "short" else "Long",
                    "market": "BTC",
                }
            )
        self._reapply()

    # -- the filters -------------------------------------------------------

    def _reapply(self) -> None:
        want = self.search.text().strip().lower()
        side = self.side.currentText().lower()
        outcome = self.outcome.currentText().lower()
        exit_ = self.exit.currentText().lower()
        rows = []
        for trade in self.trades:
            if side not in ("side: all", "all") and trade["side"].lower() != side:
                continue
            if outcome in ("win", "loss"):
                won = trade["result"] > 0
                if won != (outcome == "win"):
                    continue
            if exit_ not in ("exit: all", "all"):
                if self.REASONS.get(trade["reason"], "Time").lower() != exit_:
                    continue
            if want and want not in self._search_text(trade):
                continue
            rows.append(trade)
        self._shown = rows
        self._fill(rows)
        self.count.setText(f"{len(rows):,} trades")
        self._show_detail(emit=False)

    def _search_text(self, trade: dict) -> str:
        return " ".join(
            [
                str(trade["n"]),
                trade["market"].lower(),
                trade["side"].lower(),
                self.REASONS.get(trade["reason"], "Time").lower(),
            ]
        )

    def _strips_for(self, rows: list[dict]) -> None:
        """Read the candles of the rows that have none yet (one read per year)."""
        session = self.session
        if session is None or not session.years:
            return
        from bi_trading.ui.strat.playback_data import trade_strips

        missing = [
            (trade["in_stamp"], trade["out_stamp"])
            for trade in rows
            if (trade["in_stamp"], trade["out_stamp"]) not in self._strips
        ]
        if not missing:
            return
        try:
            found = trade_strips(session.years, session.resolution, missing)
        except (OSError, ValueError):
            found = [None] * len(missing)
        self._strips.update(zip(missing, found, strict=True))

    def _fill(self, rows: list[dict]) -> None:
        self._strips_for(rows)
        self.table.setRowCount(len(rows))
        for row, trade in enumerate(rows):
            pnl = trade["pnl"]
            sign = "+" if pnl >= 0 else "−"
            cells = (
                _moment(trade["in_stamp"]),
                trade["market"],
                trade["side"],
                f"{trade['in_price']:,.0f} → {trade['out_price']:,.0f}",
                f"${trade['size']:,.0f}",
                f"{sign}${abs(pnl):,.1f}",
                self.REASONS.get(trade["reason"], "Time"),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 1 or column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif column in (4, 5):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                if column == 5:
                    item.setForeground(
                        QColor(UP if trade["pnl"] >= 0 else DOWN)
                    )
                elif column == 6:
                    item.setForeground(QColor(TEXT_MUTED))
                elif column == 3:
                    item.setData(
                        STRIP_ROLE, self._strips.get((trade["in_stamp"], trade["out_stamp"]))
                    )
                self.table.setItem(row, column, item)

    def _selected(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._shown):
            return self._shown[index]
        return None

    def _candles_of(self, trade: dict | None) -> list:
        """The trade's candles from the store, or none (a sample run, another year)."""
        session = self.session
        if trade is None or session is None or not session.years:
            return []
        from bi_trading.ui.strat.playback_data import bars_between

        try:
            return bars_between(
                session.years, session.resolution,
                int(trade["in_stamp"]), int(trade["out_stamp"]),
            )
        except (OSError, ValueError):
            return []

    def _show_detail(self, emit: bool = False) -> None:
        trade = self._selected()
        if trade is None and self._shown:
            self.table.selectRow(0)
            trade = self._shown[0]
        self.spark.set_trade(trade, self._candles_of(trade))
        if trade is None:
            self.detail_title.setText("Trade —")
            for label in self.detail_rows.values():
                label.setText("—")
            return
        self.detail_title.setText(f"Trade #{trade['n']:,}")
        self.detail_rows["entry"].setText(
            f"{_moment(trade['in_stamp'])} · {trade['in_price']:,.0f}"
        )
        self.detail_rows["exit"].setText(
            f"{_moment(trade['out_stamp'])} · {trade['out_price']:,.0f}"
        )
        self.detail_rows["reason"].setText(
            self.REASONS.get(trade["reason"], "Time")
        )
        minutes = max(0, (trade["out_stamp"] - trade["in_stamp"]) // 60_000)
        self.detail_rows["duration"].setText(
            f"{minutes:,} min · ${trade['fees']:,.2f}"
        )
        self.detail_rows["return"].setText(f"{trade['result'] * 100:+.2f}%")
        if emit:
            self.trade_selected.emit(trade)


def _moment(milliseconds: int) -> str:
    if not milliseconds:
        return "—"
    return datetime.fromtimestamp(
        milliseconds / 1000, tz=UTC
    ).strftime("%d %b %H:%M")


__all__ = ["LiveCurve", "ResultsTile", "TradesPage"]
