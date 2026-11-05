"""The playback tile: candles rolling through a backtest, figures live.

This is the run itself. It walks the **whole selected span**, one bar at a
time, and keeps a long-only simulation on top: one position at a time, take
profit and stop loss from the parameter tile, a fee each way. Every figure
above the chart is recomputed from that walk.

The span can be years of one-minute bars, so nothing is held in memory that
does not have to be. Bars are streamed off disk, and only what the picture and
the figures need is kept:

* a rolling window of the most recent bars, for the chart;
* the most recent entries and exits, to mark on it;
* running totals, and a running mean/variance for the Sharpe.

The walk is also sped up to stay watchable: `stride` bars are consumed per
tick, chosen so a run over any amount of data takes about `WATCH_MS`. With a
few hundred bars that is one bar a tick; with years of minutes the trail
advances in bigger jumps.

The entry rule comes from the strategy tile. Fills are the optimistic kind —
the stop and the target are both read off one candle's range, so a candle that
touches both pays the target.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from lalala.candles import candle_file
from lalala.cards import mono_font
from lalala.panels import Card
from lalala.theme import ACCENT, DOWN, TEXT_FAINT, TEXT_MUTED, UP

# A run is watched over about this long, whatever the span holds.
WATCH_MS = 120_000
STEP_MS = 50
FRAME_MS = 30
MAX_TICKS = max(1, WATCH_MS // STEP_MS)

# What the picture needs, no matter how long the run is.
CHART_BARS = 600
MAX_MARKERS = 4000

MAX_READ = 48_000
FACTOR = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

# How fast the price window chases the data. Lower is calmer; the tile is
# unreadable when the scale snaps on every new extreme.
EASE_RANGE = 0.14
# The metric row wraps like the other galleries.
WIDE_METRICS = 6
NARROW_METRICS = 4
WIDE_AT = 520

SAMPLE_SEED = 11
# A span with nothing on disk still has something to show.
SAMPLE_BARS = 400

# The strategies the run can be pointed at. Random buy is the baseline: an
# entry rule that cannot beat a coin flip has no edge, so it stays in the list
# as something to measure against.
STRATEGIES = (
    (
        "random",
        "Random buy",
        "Opens on a coin flip. The no-edge baseline to measure against.",
    ),
    (
        "bollinger",
        "Bollinger reversion",
        "Buys when the close falls below the lower band (20 bars, 2σ).",
    ),
)
DEFAULT_STRATEGY = "bollinger"

BOLLINGER_PERIOD = 20
BOLLINGER_DEVIATIONS = 2.0


def strategy_label(rule: str) -> str:
    for key, label, _ in STRATEGIES:
        if key == rule:
            return label
    return STRATEGIES[0][1]


@dataclass(frozen=True)
class Candle:
    stamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def aggregate(bars: Iterable[Candle], factor: int) -> Iterator[Candle]:
    """Compact bars `factor`-to-one: first open, last close, extremes kept."""
    if factor <= 1:
        yield from bars
        return
    group: list[Candle] = []
    for bar in bars:
        group.append(bar)
        if len(group) < factor:
            continue
        yield _merge(group)
        group = []
    if group:
        yield _merge(group)


def _merge(group: list[Candle]) -> Candle:
    return Candle(
        stamp=group[0].stamp,
        open=group[0].open,
        high=max(bar.high for bar in group),
        low=min(bar.low for bar in group),
        close=group[-1].close,
        volume=sum(bar.volume for bar in group),
    )


def _parse(line: str) -> Candle | None:
    parts = line.rstrip("\n").split(",")
    if len(parts) < 6:
        return None
    try:
        return Candle(
            stamp=int(parts[0]),
            open=float(parts[1]),
            high=float(parts[2]),
            low=float(parts[3]),
            close=float(parts[4]),
            volume=float(parts[5]),
        )
    except ValueError:
        return None


def _iter_file(path, factor: int) -> Iterator[Candle]:
    def bars() -> Iterator[Candle]:
        try:
            with path.open() as handle:
                next(handle, None)  # the header
                for line in handle:
                    bar = _parse(line)
                    if bar is not None:
                        yield bar
        except OSError:
            return
    yield from aggregate(bars(), factor)


def iter_candles(years: list[int], resolution: str) -> Iterator[Candle]:
    """The whole span, one bar at a time, compacted to `resolution`."""
    factor = FACTOR.get(resolution, 1)
    for year in sorted(years):
        path = candle_file(year)
        if path.exists():
            yield from _iter_file(path, factor)


def count_bars(years: list[int], resolution: str) -> int:
    """How many bars the span holds at `resolution`.

    Counted per file and rounded up, because bars are compacted within a year:
    a file whose row count is not a multiple of the factor still yields one
    more, shorter bar. The total therefore matches what `iter_candles` yields,
    which matters: progress is measured against it.
    """
    factor = FACTOR.get(resolution, 1)
    bars = 0
    for year in sorted(years):
        path = candle_file(year)
        lines = 0
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    lines += block.count(b"\n")
        except OSError:
            continue
        rows = max(0, lines - 1)  # one header per file
        bars += -(-rows // factor)
    return bars


def load_candles(
    years: list[int], resolution: str, limit: int = SAMPLE_BARS
) -> list[Candle]:
    """The first `limit` bars of the span, for tests and small views."""
    bars: list[Candle] = []
    for bar in iter_candles(years, resolution):
        bars.append(bar)
        if len(bars) >= limit:
            break
    return bars


def sample_candles(count: int = SAMPLE_BARS, seed: int = SAMPLE_SEED) -> list[Candle]:
    """A fixed-seed walk, for when the store has nothing to show."""
    rng = random.Random(seed)
    price = 78_000.0
    stamp = 1_700_000_000_000
    bars: list[Candle] = []
    for _ in range(count):
        open_ = price
        close = open_ * (1.0 + rng.gauss(0.0, 0.0018))
        wick = abs(rng.gauss(0.0, 0.0009)) * open_
        bars.append(
            Candle(
                stamp=stamp,
                open=open_,
                high=max(open_, close) + wick,
                low=min(open_, close) - wick,
                close=close,
                volume=abs(rng.gauss(4.0, 2.0)) + 0.1,
            )
        )
        price = close
        stamp += 60_000
    return bars


def plan_stride(total: int) -> int:
    """Bars per tick so a run over `total` bars lasts about `WATCH_MS`."""
    if total <= MAX_TICKS:
        return 1
    return max(1, -(-total // MAX_TICKS))


def _feed_factory(candles) -> Callable[[], Iterator[Candle]]:
    if isinstance(candles, (list, tuple)):
        return lambda: iter(candles)
    return candles


def _bollinger(
    closes: deque[float],
    total: float,
    total_squares: float,
    period: int,
    deviations: float,
) -> tuple[float, float, float] | None:
    if len(closes) < period:
        return None
    middle = total / period
    variance = max(0.0, total_squares / period - middle * middle)
    spread = variance ** 0.5 * deviations
    return middle, middle + spread, middle - spread


def bollinger_bands(
    candles: Iterable[Candle],
    period: int = BOLLINGER_PERIOD,
    deviations: float = BOLLINGER_DEVIATIONS,
) -> tuple[tuple[float, float, float] | None, ...]:
    """(middle, upper, lower) per bar, or None until there is enough history.

    The walk keeps the same numbers with a rolling window; this version exists
    for whole series — tests, and anywhere the bars are already in hand.
    """
    bands: list[tuple[float, float, float] | None] = []
    closes: deque[float] = deque(maxlen=period)
    total = 0.0
    total_squares = 0.0
    for bar in candles:
        if len(closes) == period:
            gone = closes[0]
            total -= gone
            total_squares -= gone * gone
        closes.append(bar.close)
        total += bar.close
        total_squares += bar.close * bar.close
        bands.append(_bollinger(closes, total, total_squares, period, deviations))
    return tuple(bands)


class Playback:
    """One position at a time, walked bar by bar off a stream."""

    def __init__(
        self,
        candles,
        capital: float = 10_000.0,
        tp: float = 2.0,
        sl: float = 1.0,
        position: float = 10.0,
        sizing: str = "balance",
        max_cash: float = 2_000.0,
        fee: float = 0.0006,
        max_hold: int = 90,
        rule: str = DEFAULT_STRATEGY,
        seed: int = 1234,
        entry_chance: float = 0.03,
        total: int | None = None,
        stride: int = 1,
    ) -> None:
        self._feed_factory = _feed_factory(candles)
        if total is None:
            total = len(candles) if isinstance(candles, (list, tuple)) else 0
        self.total = total
        self.stride = max(1, stride)
        self.capital = capital
        self.tp = tp
        self.sl = sl
        self.position = position
        self.sizing = sizing
        self.max_cash = max_cash
        self.fee = fee
        self.max_hold = max_hold
        self.rule = rule
        self.seed = seed
        self.entry_chance = entry_chance
        self.reset()

    # -- state -------------------------------------------------------------

    def reset(self) -> None:
        self._rng = random.Random(self.seed)
        self._feed = self._feed_factory()
        self._exhausted = False
        self.index = 0
        self.first_close = 0.0
        self.cash = self.capital
        self.qty = 0.0
        self.entry_price = 0.0
        self.entry_index = 0
        self.entry_cost = 0.0
        self.peak = self.capital
        self.max_drawdown = 0.0
        self.max_gain = 0.0
        self.fees = 0.0
        self.trade_returns: list[float] = []
        self.streak = 0          # > 0 wins in a row, < 0 losses in a row
        self.best_win = 0
        self.worst_loss = 0
        self.bars_in_market = 0
        self.markers: deque[tuple[int, str, float]] = deque(maxlen=MAX_MARKERS)
        self._window: deque[Candle] = deque(maxlen=CHART_BARS)
        self._previous: Candle | None = None
        self._closes: deque[float] = deque(maxlen=BOLLINGER_PERIOD)
        self._close_total = 0.0
        self._close_squares = 0.0
        self._band: tuple[float, float, float] | None = None
        self._last_equity = self.capital
        self._returns = 0
        self._return_mean = 0.0
        self._return_m2 = 0.0

    @property
    def done(self) -> bool:
        """True once the feed is spent, or the known total has been walked."""
        if self._exhausted:
            return True
        return self.total > 0 and self.index >= self.total

    @property
    def in_position(self) -> bool:
        return self.qty > 0.0

    def close_price(self) -> float:
        if self._window:
            return self._window[-1].close
        return self.first_close

    @property
    def equity(self) -> float:
        """The realised book: capital plus what closed trades made.

        An open position is carried at what it cost, so entering a trade does
        not move the figures — only the fee, and then the result when it
        closes. Unrealised profit is deliberately not shown.
        """
        return self.cash + self.qty * self.entry_price

    def drawdown(self) -> float:
        if self.peak <= 0:
            return 0.0
        return self.equity / self.peak - 1.0

    @property
    def trades(self) -> int:
        return len(self.trade_returns)

    @property
    def win_rate(self) -> float:
        if not self.trade_returns:
            return 0.0
        return sum(1 for value in self.trade_returns if value > 0) / len(
            self.trade_returns
        )

    @property
    def sharpe(self) -> float:
        """Mean over deviation of the per-bar book returns — not annualised.

        The walk is minutes long, so annualising would multiply a handful of
        trades by the square root of a year and produce a number that says
        nothing. The plain ratio is the honest shape of it.
        """
        if self._returns < 2 or self._return_m2 <= 0:
            return 0.0
        deviation = (self._return_m2 / (self._returns - 1)) ** 0.5
        if deviation == 0:
            return 0.0
        return self._return_mean / deviation

    @property
    def exposure(self) -> float:
        walked = max(1, self.index)
        return min(1.0, self.bars_in_market / walked)

    @property
    def progress(self) -> float:
        if not self.total:
            return 1.0 if self.done else 0.0
        return min(1.0, self.index / self.total)

    def recent(self) -> list[Candle]:
        """The bars the chart can draw, newest last."""
        return list(self._window)

    # -- stepping ----------------------------------------------------------

    def step(self) -> None:
        """Consume `stride` bars: the picture and the figures move together."""
        for _ in range(self.stride):
            if not self._advance_one():
                break

    def advance(self) -> None:
        self.step()

    def _advance_one(self) -> bool:
        try:
            candle = next(self._feed)
        except StopIteration:
            self._exhausted = True
            return False

        if not self.first_close:
            self.first_close = candle.close
        self._update_band(candle.close)

        if self.in_position:
            self.bars_in_market += 1
            self._manage(candle)
        elif self._wants_long(candle, self._previous or candle):
            self._enter(candle)

        self._previous = candle
        self._window.append(candle)
        self.index += 1

        equity = self.equity
        self.peak = max(self.peak, equity)
        self.max_drawdown = min(self.max_drawdown, self.drawdown())
        self.max_gain = max(self.max_gain, equity / self.capital - 1.0)
        self._observe(equity)
        return True

    def _observe(self, equity: float) -> None:
        """Welford, so the Sharpe costs no memory however long the run is."""
        if self._last_equity > 0:
            change = equity / self._last_equity - 1.0
            self._returns += 1
            delta = change - self._return_mean
            self._return_mean += delta / self._returns
            self._return_m2 += delta * (change - self._return_mean)
        self._last_equity = equity

    def _update_band(self, close: float) -> None:
        if len(self._closes) == self._closes.maxlen:
            gone = self._closes[0]
            self._close_total -= gone
            self._close_squares -= gone * gone
        self._closes.append(close)
        self._close_total += close
        self._close_squares += close * close
        self._band = _bollinger(
            self._closes,
            self._close_total,
            self._close_squares,
            BOLLINGER_PERIOD,
            BOLLINGER_DEVIATIONS,
        )

    def _wants_long(self, candle: Candle, previous: Candle) -> bool:
        """When to open, per the chosen strategy.

        `random` buys on a coin flip: the honest benchmark for any entry rule.
        `bollinger` buys mean reversion — the close has fallen below the lower
        band, so the bar is stretched away from its own average.
        """
        if self.index == 0:
            return False
        if self.rule == "random":
            return self._rng.random() < self.entry_chance
        if self.rule == "bollinger":
            return self._band is not None and candle.close < self._band[2]
        return False

    def _budget(self) -> float:
        """How much to put on: a share of what the cap allows us to trade with."""
        deployable = min(self.cash, self.max_cash)
        if self.sizing == "fixed":
            return max(0.0, min(self.position, deployable))
        return deployable * max(0.0, self.position) / 100.0

    def _enter(self, candle: Candle) -> None:
        notional = self._budget()
        if notional <= 0.0 or candle.close <= 0.0:
            return
        cost = notional * self.fee
        self.qty = notional / candle.close
        self.cash -= notional + cost
        self.fees += cost
        self.entry_price = candle.close
        self.entry_index = self.index
        self.entry_cost = notional + cost
        self.markers.append((self.index, "in", candle.close))

    def _manage(self, candle: Candle) -> None:
        target = self.entry_price * (1.0 + self.tp / 100.0)
        stop = self.entry_price * (1.0 - self.sl / 100.0)
        price: float | None = None
        if self.tp > 0 and candle.high >= target:
            price = target
        elif self.sl > 0 and candle.low <= stop:
            price = stop
        elif self.index - self.entry_index >= self.max_hold:
            price = candle.close
        if price is None:
            return
        proceeds = self.qty * price
        cost = proceeds * self.fee
        self.cash += proceeds - cost
        self.fees += cost
        invested = self.entry_cost
        self.qty = 0.0
        self.entry_cost = 0.0
        self.markers.append((self.index, "out", price))
        self._book(proceeds - cost, invested)

    def _book(self, proceeds: float, invested: float) -> None:
        """Record the trade's return and move the streak counters."""
        result = proceeds / invested - 1.0 if invested else 0.0
        self.trade_returns.append(result)
        if result > 0:
            self.streak = self.streak + 1 if self.streak > 0 else 1
            self.best_win = max(self.best_win, self.streak)
        else:
            self.streak = self.streak - 1 if self.streak < 0 else -1
            self.worst_loss = min(self.worst_loss, self.streak)

    # -- readouts ----------------------------------------------------------

    def metrics(self) -> list[tuple[str, str, str]]:
        """(caption, value, colour role) — the row above the chart."""
        pnl = self.equity / self.capital - 1.0
        streak = "—"
        if self.streak > 0:
            streak = f"W{self.streak}"
        elif self.streak < 0:
            streak = f"L{abs(self.streak)}"
        return [
            ("PnL", f"{pnl * 100:+,.2f}%", "accent" if pnl >= 0 else "down"),
            ("Equity", _money(self.equity), "text"),
            (
                "Progress",
                f"{self.progress * 100:,.0f}% · {self.index:,}/{self.total:,}",
                "muted",
            ),
            (
                "Sharpe",
                f"{self.sharpe:,.2f}" if self.trades else "—",
                "accent" if self.sharpe > 1 else "muted",
            ),
            (
                "Drawdown",
                f"{self.drawdown() * 100:,.2f}%",
                "down" if self.drawdown() < 0 else "muted",
            ),
            ("Max DD", f"{self.max_drawdown * 100:,.2f}%", "down"),
            ("Max gain", f"{self.max_gain * 100:+,.2f}%", "accent"),
            ("Streak", streak, "accent" if self.streak > 0 else "text"),
            ("Best W", f"{self.best_win}", "accent"),
            ("Worst L", f"{abs(self.worst_loss)}", "down"),
            ("Trades", f"{self.trades:,}", "text"),
            ("Win rate", f"{self.win_rate * 100:,.0f}%", "text"),
            ("Fees", _money(self.fees), "muted"),
        ]


def _money(value: float) -> str:
    return f"${value:,.0f}"


# -- the three curves ------------------------------------------------------


@dataclass
class BacktestSession:
    """One run: the live walk, the random baseline, and buy and hold.

    The curves are sampled once per tick rather than once per bar — a run can
    be millions of bars, and the chart cannot use more points than it has
    pixels.
    """

    strategy: Playback
    random: Playback
    benchmark: list[float] = field(default_factory=list)
    strategy_curve: list[float] = field(default_factory=list)
    random_curve: list[float] = field(default_factory=list)
    low: float = 0.0
    high: float = 0.0

    @property
    def index(self) -> int:
        return self.strategy.index

    @property
    def total(self) -> int:
        return self.strategy.total

    @property
    def capital(self) -> float:
        return self.strategy.capital

    def advance(self) -> None:
        self.strategy.step()
        self.random.step()
        self._sample()

    def _sample(self) -> None:
        play = self.strategy
        self.strategy_curve.append(play.equity)
        self.random_curve.append(self.random.equity)
        self.benchmark.append(self.buy_and_hold())
        for curve in (self.strategy_curve, self.random_curve):
            self._grow(curve[-1])

    def buy_and_hold(self) -> float:
        play = self.strategy
        if not play.first_close:
            return play.capital
        return play.capital * play.close_price() / play.first_close

    def _grow(self, value: float) -> None:
        if not self.low:
            self.low = self.high = self.capital
        self.low = min(self.low, value)
        self.high = max(self.high, value)

    def return_of(self, curve: list[float]) -> float:
        if not curve or curve[0] <= 0:
            return 0.0
        return curve[-1] / curve[0] - 1.0


def _walk_settings(params: dict) -> dict:
    return {
        "capital": float(params["initial_capital"] or 0.0),
        "tp": float(params["tp"] or 0.0),
        "sl": float(params["sl"] or 0.0),
        "position": float(params["position"] or 0.0),
        "sizing": str(params["sizing"]),
        "max_cash": float(params["cash"] or 0.0),
    }


def build_session(
    years: list[int],
    params: dict,
    rule: str = DEFAULT_STRATEGY,
    resolution: str = "1m",
    fallback: list[Candle] | None = None,
) -> BacktestSession:
    """A run over the whole span, streamed rather than loaded."""
    settings = _walk_settings(params)
    total = count_bars(years, resolution)
    if total:
        feeds = [lambda: iter_candles(years, resolution) for _ in range(2)]
    else:
        bars = fallback if fallback is not None else sample_candles()
        total = len(bars)
        feeds = [lambda: iter(bars) for _ in range(2)]
    stride = plan_stride(total)
    strategy = Playback(
        feeds[0], rule=rule, total=total, stride=stride, **settings
    )
    random_buy = Playback(
        feeds[1], rule="random", total=total, stride=stride, **settings
    )
    session = BacktestSession(strategy=strategy, random=random_buy)
    session.low = session.high = settings["capital"]
    session._sample()
    return session


class CandlePlayer(QWidget):
    """Candles scrolling under a playhead, with the entries marked."""

    def __init__(self, playback: Playback, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.playback = playback
        # How far the loop has travelled toward the next candle, 0..1. The
        # chart slides by this much every frame, so it scrolls like a live one
        # instead of hopping a whole slot at a time.
        self.offset = 0.0
        # The price window eases, so filling the tile does not make it jump.
        self._low: float | None = None
        self._high: float | None = None
        self.message = "press Run to start the backtest"
        self.setMinimumHeight(140)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_offset(self, offset: float) -> None:
        self.offset = max(0.0, min(0.999, offset))

    def reset_range(self, candles: list[Candle] | None = None) -> None:
        """Start the price window at the whole series, not at the first bar.

        Easing toward the visible slice from a single bar would leave the
        opening candles wildly zoomed until the scale caught up.
        """
        series = self.playback.recent() if candles is None else candles
        if not series:
            self._low = None
            self._high = None
            return
        low = min(bar.low for bar in series)
        high = max(bar.high for bar in series)
        pad = max((high - low) * 0.08, high * 0.0002)
        self._low, self._high = low - pad, high + pad

    def visible_count(self, width: float) -> int:
        return max(30, int((width - 62.0) / 7.0))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        # No price grid: just the candles, as wide as the tile allows.
        left = 8.0
        right = width - 8.0
        top = 18.0
        bottom = height - 16.0
        if right - left < 40 or bottom - top < 30:
            return

        bars = self.playback.recent()
        if not bars:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        # Absolute indices: the window is the tail of a stream, so position in
        # the list is not position in the run.
        base = self.playback.index - len(bars)
        last = base + len(bars) - 1
        playhead = last + self.offset
        room = self.visible_count(width)
        slot = (right - left) / room
        first = max(base, int(-(-(playhead + 0.5 - room) // 1)))
        window = bars[first - base :]
        if not window:
            return

        low = min(bar.low for bar in window)
        high = max(bar.high for bar in window)
        pad = max((high - low) * 0.08, high * 0.0002)
        if self._low is None:
            self._low, self._high = low - pad, high + pad
        else:
            self._low += (low - pad - self._low) * EASE_RANGE
            self._high += (high + pad - self._high) * EASE_RANGE
        low, high = self._low, self._high

        def x_of(position: int) -> float:
            return right - (playhead - position + 0.5) * slot

        def y_of(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        body = max(1.0, slot * 0.6)
        for position, bar in enumerate(window, start=first):
            x = x_of(position)
            if x < left - slot or x > right + slot:
                continue
            rising = bar.close >= bar.open
            painter.setPen(QPen(QColor(UP if rising else DOWN), 1))
            painter.drawLine(QPointF(x, y_of(bar.high)), QPointF(x, y_of(bar.low)))
            top_y = y_of(max(bar.open, bar.close))
            height_y = max(1.0, abs(y_of(bar.open) - y_of(bar.close)))
            painter.setBrush(QColor(UP if rising else DOWN))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(x - body / 2, top_y, body, height_y))

        # Entries and exits, so the trades are visible on the candles.
        for position, kind, price in self.playback.markers:
            x = x_of(position)
            if x < left - slot or x > right + slot:
                continue
            y = y_of(price)
            colour = QColor(ACCENT if kind == "in" else TEXT_MUTED)
            painter.setPen(QPen(colour, 1))
            painter.setBrush(colour)
            if kind == "in":
                painter.drawPolygon(
                    QPolygonF(
                        [QPointF(x, y - 6), QPointF(x - 4, y - 12), QPointF(x + 4, y - 12)]
                    )
                )
            else:
                painter.drawPolygon(
                    QPolygonF(
                        [QPointF(x, y + 6), QPointF(x - 4, y + 12), QPointF(x + 4, y + 12)]
                    )
                )

        # Times: the newest at the right edge, and the oldest only once the
        # trail has actually reached the left of the plot.
        painter.setFont(mono_font(7))
        painter.setPen(QColor(TEXT_FAINT))
        stamps: list[tuple[int, float, Qt.AlignmentFlag]] = [
            (last, right - 68.0, Qt.AlignmentFlag.AlignRight)
        ]
        if x_of(first) >= left - slot * 0.6:
            stamps.append((first, left, Qt.AlignmentFlag.AlignLeft))
        for position, x, align in stamps:
            if not base <= position <= last:
                continue
            bar = bars[position - base]
            stamp = datetime.fromtimestamp(bar.stamp / 1000, tz=timezone.utc)
            painter.drawText(
                QRectF(x, bottom + 1, 68, 13),
                align | Qt.AlignmentFlag.AlignVCenter,
                stamp.strftime("%d %b %H:%M"),
            )


class PlaybackTile(Card):
    """The candles rolling, with the live figures above them."""

    advanced = Signal()
    restarted = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Nothing runs until Run is pressed: opening the window is not a run.
        self.playback = Playback([], total=0)
        self.session: BacktestSession | None = None
        self.source = "—"
        self._launched = False
        # What the controls are set to. A change here is not a restart: it is
        # picked up the next time the run is started.
        self._wanted_years: list[int] = []
        self._wanted_resolution = "1m"
        self._wanted_params: dict | None = None
        self._wanted_rule = DEFAULT_STRATEGY

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("BACKTEST")
        title.setObjectName("tileTitle")
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.setToolTip("Start the walk over with the current span")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.run_button)
        self.body.addLayout(header)

        self.note = QLabel("idle — press Run")
        self.note.setObjectName("hintLabel")
        self.body.addWidget(self.note)

        self._metrics = QGridLayout()
        self._metrics.setContentsMargins(0, 0, 0, 0)
        self._metrics.setHorizontalSpacing(10)
        self._metrics.setVerticalSpacing(3)
        self._metric_labels: list[tuple[QLabel, QLabel]] = [
            (self._caption(""), self._value())
            for _ in self.playback.metrics()
        ]
        self._metric_columns = 0
        self._reflow_metrics(WIDE_METRICS)
        self.body.addLayout(self._metrics)
        for caption, value in self._metric_labels:
            if caption.text() == "Sharpe":
                value.setToolTip(
                    "Mean over deviation of the per-bar book returns, "
                    "not annualised"
                )

        self.player = CandlePlayer(self.playback)
        self.body.addWidget(self.player, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._elapsed = 0
        self.run_button.clicked.connect(self.restart)
        self._refresh_metrics()

    # -- the loop ----------------------------------------------------------

    def _tick(self) -> None:
        if self.playback.done:
            # It stops here. Starting over is a decision, not a loop.
            self.pause()
            self.run_button.setText("Run")
            self.note.setText(
                f"finished — {self.playback.trades:,} trades, "
                f"{self.playback.win_rate * 100:,.0f}% won, press Run to replay"
            )
            return
        self._elapsed += FRAME_MS
        if self._elapsed >= STEP_MS:
            self._elapsed -= STEP_MS
            if self.session is not None:
                self.session.advance()
            else:
                self.playback.advance()
            self._refresh_metrics()
            self.advanced.emit()
        # Every frame, not every candle: this is what makes it scroll.
        self.player.set_offset(self._elapsed / STEP_MS)
        self.player.update()

    def play(self) -> None:
        self._timer.start()

    def pause(self) -> None:
        self._timer.stop()

    def playing(self) -> bool:
        return self._timer.isActive()

    def restart(self) -> None:
        """Adopt the controls and start the walk over. The only way it resets."""
        params = self._wanted_params or {
            "initial_capital": 10_000.0,
            "tp": 2.0,
            "sl": 1.0,
            "position": 10.0,
            "sizing": "balance",
            "cash": 2_000.0,
        }
        self.session = build_session(
            self._wanted_years,
            params,
            self._wanted_rule,
            self._wanted_resolution,
        )
        self.playback = self.session.strategy
        self.player.playback = self.playback

        if self._wanted_years and self.session.total:
            played = self._wanted_years[-1] if self._wanted_years else 0
            self.source = f"{played} · {self._wanted_resolution}"
        else:
            self.source = "example"

        self._launched = True
        self._elapsed = 0
        self.player.set_offset(0.0)
        self.player.reset_range()
        self.run_button.setText("Restart")
        self._describe()
        self._refresh_metrics()
        self.player.update()
        self.restarted.emit(self.session)
        self.play()

    # -- source ------------------------------------------------------------

    def set_source(self, years: list[int], resolution: str) -> None:
        """Remember the span. Nothing changes until the next restart."""
        self._wanted_years = list(years)
        self._wanted_resolution = resolution
        self._describe()

    def set_params(self, params: dict) -> None:
        """Remember the parameters. Nothing changes until the next restart."""
        self._wanted_params = dict(params)
        self._describe()

    def set_strategy(self, rule: str) -> None:
        """Remember the strategy. Nothing changes until the next restart."""
        self._wanted_rule = rule
        self._describe()

    def _describe(self) -> None:
        if not self._launched:
            self.note.setText("idle — press Run")
            return
        name = strategy_label(self._wanted_rule)
        stride = self.playback.stride
        pace = "" if stride <= 1 else f" · fast-forward ×{stride:,}"
        if self._wanted_years:
            span = f"{self._wanted_years[0]}–{self._wanted_years[-1]}"
            self.note.setText(
                f"{name} on {span} · {self._wanted_resolution}{pace}"
            )
        else:
            self.note.setText(f"{name} on the sample{pace}")

    # -- layout ------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        columns = WIDE_METRICS if self.width() >= WIDE_AT else NARROW_METRICS
        if columns != self._metric_columns:
            self._reflow_metrics(columns)

    def _reflow_metrics(self, columns: int) -> None:
        for caption, value in self._metric_labels:
            self._metrics.removeWidget(caption)
            self._metrics.removeWidget(value)
        self._metric_columns = columns
        for index, (caption, value) in enumerate(self._metric_labels):
            row = index // columns * 2
            column = index % columns
            self._metrics.addWidget(caption, row, column)
            self._metrics.addWidget(value, row + 1, column)
        for column in range(WIDE_METRICS):
            self._metrics.setColumnStretch(
                column, 1 if column < columns else 0
            )

    def _refresh_metrics(self) -> None:
        if self._launched:
            rows = self.playback.metrics()
        else:
            # Nothing to report yet: the labels are there, the values are not.
            rows = [
                (title, "—", "muted")
                for title, _, _ in self.playback.metrics()
            ]
        for (caption, value), (title, text, role) in zip(
            self._metric_labels, rows
        ):
            if caption.text() != title:
                caption.setText(title)
            if value.text() != text:
                value.setText(text)
            if value.property("role") != role:
                value.setProperty("role", role)
                value.setObjectName(f"metricValue_{role}")
                style = value.style()
                style.unpolish(value)
                style.polish(value)

    # -- widgets -----------------------------------------------------------

    def _caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _value(self) -> QLabel:
        label = QLabel("")
        label.setObjectName("metricValue_text")
        label.setFont(mono_font(8, bold=True))
        return label


__all__ = [
    "DEFAULT_STRATEGY",
    "STRATEGIES",
    "BacktestSession",
    "Candle",
    "CandlePlayer",
    "Playback",
    "PlaybackTile",
    "aggregate",
    "bollinger_bands",
    "build_session",
    "count_bars",
    "iter_candles",
    "load_candles",
    "plan_stride",
    "sample_candles",
    "strategy_label",
]
