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
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.candles import candle_file
from lalala.cards import mono_font
from lalala.panels import Card
from lalala.theme import ACCENT, DOWN, TEXT_FAINT, TEXT_MUTED, UP

# The colour a picked trade is drawn in on the chart.
TRADE_HILITE = "#c08bff"

# A run is watched over about this long, whatever the span holds.
WATCH_MS = 120_000
STEP_MS = 50
FRAME_MS = 30
MAX_TICKS = max(1, WATCH_MS // STEP_MS)

# What the picture needs, no matter how long the run is. A good stretch, so the
# chart can be scrolled back through the candles it has already drawn.
CHART_BARS = 1500
MAX_MARKERS = 4000

MAX_READ = 48_000
FACTOR = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}

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

# How many bars each step walks. `WATCH_MS` already fits the run to the span;
# this is the watcher's own multiplier on top.
SPEEDS = ("×1", "×2", "×4", "×8")

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


def load_all_candles(years: list[int], resolution: str) -> list[Candle]:
    """The whole span in memory, for a rule-driven run.

    A saved strategy is a formula, and a formula is checked over a whole
    series rather than streamed, so this one run reads the span into a list.
    """
    return list(iter_candles(years, resolution))


def window_around(
    years: list[int], resolution: str, stamp: int, count: int = 400
) -> list[Candle]:
    """A window of `count` bars around `stamp`, read from the year it is in.

    Read on demand, so a picked trade can be shown without keeping the whole
    span in memory.
    """
    if not years or not stamp:
        return []
    year = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).year
    if year not in years:
        year = min(years, key=lambda value: abs(value - year))
    path = candle_file(year)
    if not path.exists():
        return []
    bars = list(_iter_file(path, FACTOR.get(resolution, 1)))
    if not bars:
        return []
    target = len(bars) - 1
    for index, bar in enumerate(bars):
        if bar.stamp >= stamp:
            target = index
            break
    start = max(0, target - count // 2)
    return bars[start : start + count]


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
        entries=None,
        dynamic_tp: bool = False,
        reverse: float = 0.0,
    ) -> None:
        self._feed_factory = _feed_factory(candles)
        if total is None:
            total = len(candles) if isinstance(candles, (list, tuple)) else 0
        self.total = total
        self.stride = max(1, stride)
        # A rule-driven run hands over the exact bars to open on; otherwise the
        # rule name decides, bar by bar.
        self._entries = None if entries is None else set(entries)
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
        self.dynamic_tp = dynamic_tp
        self.reverse = reverse
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
        self.entry_stamp = 0
        self.entry_notional = 0.0
        self.entry_fee = 0.0
        self.entry_cost = 0.0
        self._peak = 0.0
        self._path: list[float] = []
        self.peak = self.capital
        self.max_drawdown = 0.0
        self.max_gain = 0.0
        self.fees = 0.0
        self.trade_returns: list[float] = []
        self.trades_log: list[tuple] = []  # (in stamp, in px, out stamp, out px, result)
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

    def adopt(self, trades, equity, bars, index) -> None:
        """Take a state computed elsewhere (the core), flat at `index`.

        Rebuilds everything the figures and the picture read — the closed
        trades, the markers, the equity statistics, the candle window — from
        `trades`/`equity` over `bars`, so a seek is a slice, not a walk.
        """
        self.index = max(0, min(index, len(bars)))
        self.cash = (
            equity[self.index - 1] if 0 < self.index <= len(equity)
            else self.capital
        )
        self.qty = 0.0
        self.entry_price = 0.0
        self.entry_index = 0
        self.entry_cost = 0.0
        self.entry_stamp = 0
        self.entry_notional = 0.0
        self.entry_fee = 0.0
        self._path = []
        self._exhausted = self.total > 0 and self.index >= len(bars)
        self._feed = self._feed_factory() if bars is None else iter(
            bars[self.index :]
        )

        closed = [t for t in trades if t[2] < self.index]
        self.trade_returns = [t[4] for t in closed]
        self.trades_log = []
        self.markers = deque(maxlen=MAX_MARKERS)
        self.streak = 0
        self.best_win = 0
        self.worst_loss = 0
        for in_index, in_px, out_index, out_px, result, fees, notional, reason in closed:
            in_stamp = bars[in_index].stamp
            out_stamp = bars[out_index].stamp
            self.trades_log.append(
                (in_stamp, in_index, in_px, out_stamp, out_index, out_px,
                 result, notional, notional * result, reason, fees, [])
            )
            self.markers.append((in_index, "in", in_px))
            self.markers.append((out_index, "out", out_px))
            if result > 0:
                self.streak = self.streak + 1 if self.streak > 0 else 1
                self.best_win = max(self.best_win, self.streak)
            else:
                self.streak = self.streak - 1 if self.streak < 0 else -1
                self.worst_loss = min(self.worst_loss, self.streak)
        self.fees = sum(t[5] for t in closed)

        if bars:
            self.first_close = bars[0].close
            start = max(0, self.index - CHART_BARS)
            self._window = deque(bars[start : self.index], maxlen=CHART_BARS)
            self._previous = bars[self.index - 1] if self.index > 0 else None
        self._closes = deque(maxlen=BOLLINGER_PERIOD)
        self._close_total = 0.0
        self._close_squares = 0.0
        for bar in bars[max(0, self.index - BOLLINGER_PERIOD) : self.index]:
            self._closes.append(bar.close)
            self._close_total += bar.close
            self._close_squares += bar.close * bar.close
        self._band = self._compute_band()

        self.peak = self.capital
        self.max_drawdown = 0.0
        self.max_gain = 0.0
        self._last_equity = self.capital
        self._returns = 0
        self._return_mean = 0.0
        self._return_m2 = 0.0
        for value in equity[: self.index]:
            self.peak = max(self.peak, value)
            self.max_drawdown = min(self.max_drawdown, self._dd(value))
            self.max_gain = max(self.max_gain, value / self.capital - 1.0)
            self._observe(value)

    def _dd(self, equity: float) -> float:
        return equity / self.peak - 1.0 if self.peak > 0 else 0.0

    def _compute_band(self):
        return _bollinger(
            self._closes, self._close_total, self._close_squares,
            BOLLINGER_PERIOD, BOLLINGER_DEVIATIONS,
        )

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
        if self._entries is not None:
            return self.index in self._entries
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
        if self.sizing == "risk":
            # A stop-out should cost `position` percent of the cash in play.
            if self.sl > 0:
                risk = deployable * max(0.0, self.position) / self.sl
                return max(0.0, min(risk, deployable))
            return deployable
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
        self.entry_stamp = candle.stamp
        self.entry_notional = notional
        self.entry_fee = cost
        self.entry_cost = notional + cost
        self._peak = candle.high
        self._path = [candle.close]
        self.markers.append((self.index, "in", candle.close))

    def _manage(self, candle: Candle) -> None:
        self._path.append(candle.close)
        target = self.entry_price * (1.0 + self.tp / 100.0)
        stop = self.entry_price * (1.0 - self.sl / 100.0)
        if self.dynamic_tp and self.reverse > 0.0:
            self._peak = max(self._peak, candle.high)
        trail = self._peak * (1.0 - self.reverse / 100.0) if self._peak else 0.0
        price: float | None = None
        reason = "time"
        if self.tp > 0 and candle.high >= target:
            price = target
            reason = "tp"
        elif self.sl > 0 and candle.low <= stop:
            price = stop
            reason = "sl"
        elif (
            self.dynamic_tp
            and self.reverse > 0
            and self._peak > self.entry_price
            and candle.low <= trail
        ):
            price = trail
            reason = "tp"
        elif self.index - self.entry_index >= self.max_hold:
            price = candle.close
            reason = "time"
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
        self._book(
            proceeds - cost, invested, candle.stamp, price, reason,
            self.entry_fee + cost, self._path, self.index,
        )

    def _book(
        self,
        proceeds: float,
        invested: float,
        exit_stamp: int = 0,
        exit_price: float = 0.0,
        reason: str = "time",
        fees: float = 0.0,
        path: list | None = None,
        exit_index: int = 0,
    ) -> None:
        """Record the trade's return and move the streak counters."""
        result = proceeds / invested - 1.0 if invested else 0.0
        self.trade_returns.append(result)
        self.trades_log.append(
            (
                self.entry_stamp,
                self.entry_index,
                self.entry_price,
                exit_stamp,
                exit_index,
                exit_price,
                result,
                self.entry_notional,
                proceeds - invested,
                reason,
                fees,
                _slim(path or []),
            )
        )
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


def _slim(points, cap: int = 60) -> tuple:
    """A price path cut down to at most `cap` points, keeping its shape."""
    points = list(points)
    if len(points) <= cap:
        return tuple(points)
    step = len(points) / cap
    return tuple(points[int(index * step)] for index in range(cap))


def bollinger_entries(bars: list[Candle]) -> list[bool]:
    """Which bars the built-in rule opens on (close below the lower band)."""
    entries = [False] * len(bars)
    closes: deque[float] = deque(maxlen=BOLLINGER_PERIOD)
    total = 0.0
    squares = 0.0
    for index, bar in enumerate(bars):
        if len(closes) == closes.maxlen:
            gone = closes[0]
            total -= gone
            squares -= gone * gone
        closes.append(bar.close)
        total += bar.close
        squares += bar.close * bar.close
        if index == 0:
            continue
        band = _bollinger(
            closes, total, squares, BOLLINGER_PERIOD, BOLLINGER_DEVIATIONS
        )
        if band is not None and bar.close < band[2]:
            entries[index] = True
    return entries


def random_entries(
    bars: list[Candle], settings: dict, seed: int = 1234, chance: float = 0.03
) -> list[bool]:
    """The coin-flip baseline's entries, consumed a bar at a time while flat."""
    rng = random.Random(seed)
    entries = [False] * len(bars)
    in_position = False
    entry_price = 0.0
    entry_index = 0
    tp = settings["tp"]
    sl = settings["sl"]
    hold = 90
    for index in range(1, len(bars)):
        bar = bars[index]
        if in_position:
            target = entry_price * (1.0 + tp / 100.0)
            stop = entry_price * (1.0 - sl / 100.0)
            if (tp > 0 and bar.high >= target) or (
                sl > 0 and bar.low <= stop
            ) or (index - entry_index >= hold):
                in_position = False
        elif rng.random() < chance:
            entries[index] = True
            in_position = True
            entry_price = bar.close
            entry_index = index
    return entries



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
    # When the span is held in memory, the core can jump the walk to a bar.
    bars: list | None = None
    closes: tuple | None = None
    highs: tuple | None = None
    lows: tuple | None = None
    settings: dict | None = None
    strategy_entries: list | None = None
    random_entries: list | None = None

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

    def seek(self, target: int) -> None:
        """Rewind the walk and fast-forward to bar `target`, curves and all.

        With the span in memory the core does the jump — the bars are sliced
        and one native walk rebuilds the state; otherwise the Python walk steps
        through it.
        """
        target = max(0, min(int(target), self.strategy.total))
        if self._core_ready():
            self._core_seek(target)
            return
        self.strategy.reset()
        self.random.reset()
        self.strategy_curve = []
        self.random_curve = []
        self.benchmark = []
        self.low = self.high = self.capital
        stride = max(1, self.strategy.stride)
        steps = target // stride
        if target and steps == 0:
            steps = 1  # never land on bar zero by accident
        for _ in range(steps):
            if self.strategy.done:
                break
            self.strategy.step()
            self.random.step()
        self._sample()

    def _core_ready(self) -> bool:
        from lalala import core

        return (
            core.available()
            and self.bars is not None
            and self.settings is not None
            and self.strategy_entries is not None
            and self.random_entries is not None
        )

    def _core_seek(self, target: int) -> None:
        from lalala import core

        s = self.settings
        closes = list(self.closes[:target])
        highs = list(self.highs[:target])
        lows = list(self.lows[:target])
        args = (closes, highs, lows)

        def run(entries):
            return core.walk(
                *args,
                list(entries[:target]),
                s["capital"], s["tp"], s["sl"], s["position"], s["sizing"],
                s["max_cash"], s["fee"], 90,
                s.get("dynamic_tp", False), s.get("reverse", 0.0),
            )

        strategy_trades, strategy_equity = run(self.strategy_entries)
        random_trades, random_equity = run(self.random_entries)
        self.strategy.adopt(strategy_trades, strategy_equity, self.bars, target)
        self.random.adopt(random_trades, random_equity, self.bars, target)
        self.strategy_curve = strategy_equity
        self.random_curve = random_equity
        first = closes[0] if closes else 0.0
        self.benchmark = [
            s["capital"] * close / first if first else s["capital"]
            for close in closes
        ]
        self.low = self.high = s["capital"]
        for curve in (self.strategy_curve, self.random_curve):
            for value in curve:
                self._grow(value)


def _walk_settings(params: dict) -> dict:
    return {
        "capital": float(params["initial_capital"] or 0.0),
        "tp": float(params["tp"] or 0.0),
        "sl": float(params["sl"] or 0.0),
        "position": float(params["position"] or 0.0),
        "sizing": str(params["sizing"]),
        "max_cash": float(params["cash"] or 0.0),
        # The tile takes a percent; the walk a fraction per side.
        "fee": float(params.get("fee") or 0.0) / 100.0,
        "dynamic_tp": bool(params.get("dynamic_tp")),
        "reverse": float(params.get("dyn_tp_reverse") or 0.0),
    }


# Above this many bars a span is streamed rather than held in memory, so the
# core (which needs the bars) only drives the shorter runs.
CORE_MAX = 1_500_000


def build_session(
    years: list[int],
    params: dict,
    rule: str = DEFAULT_STRATEGY,
    resolution: str = "1m",
    fallback: list[Candle] | None = None,
    entry_formula=None,
    fields=None,
) -> BacktestSession:
    """A run over the whole span.

    A span small enough to hold is loaded and its entries worked out up front,
    so the walk (and every seek) can be done by the core. A longer span is
    streamed off disk and stepped in Python.
    """
    settings = _walk_settings(params)
    loaded: list[Candle] | None = None
    total = count_bars(years, resolution)
    if entry_formula is not None or (total and total <= CORE_MAX):
        loaded = load_all_candles(years, resolution)
        if not loaded:
            loaded = fallback if fallback is not None else sample_candles()
        total = len(loaded)
    if not total:
        loaded = fallback if fallback is not None else sample_candles()
        total = len(loaded)

    stride = plan_stride(total)
    session = BacktestSession(strategy=None, random=None)
    if loaded is not None:
        feeds = [lambda: iter(loaded) for _ in range(2)]
        session.settings = settings
        session.bars = loaded
        session.closes = tuple(bar.close for bar in loaded)
        session.highs = tuple(bar.high for bar in loaded)
        session.lows = tuple(bar.low for bar in loaded)
        if entry_formula is not None:
            from lalala.formula import ENTRY_FIELDS
            from lalala.formula_eval import entry_signals

            indices = set(
                entry_signals(entry_formula, loaded, fields or ENTRY_FIELDS)
            )
            strategy_entries = [i in indices for i in range(len(loaded))]
        elif rule == "bollinger":
            strategy_entries = bollinger_entries(loaded)
        else:
            strategy_entries = [False] * len(loaded)
        session.strategy_entries = strategy_entries
        session.random_entries = random_entries(loaded, settings)
        strategy = Playback(
            feeds[0], rule=rule, total=total, stride=stride,
            entries=set(i for i, on in enumerate(strategy_entries) if on),
            **settings,
        )
        random_buy = Playback(
            feeds[1], rule="random", total=total, stride=stride,
            entries=set(i for i, on in enumerate(session.random_entries) if on),
            **settings,
        )
    else:
        feeds = [lambda: iter_candles(years, resolution) for _ in range(2)]
        strategy = Playback(
            feeds[0], rule=rule, total=total, stride=stride, **settings
        )
        random_buy = Playback(
            feeds[1], rule="random", total=total, stride=stride, **settings
        )
    session.strategy = strategy
    session.random = random_buy
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
        # The trade to bring out, when a row is picked in the results.
        self.trade: dict | None = None
        # A static window of candles to show instead of the live tail, so a
        # picked trade can be looked at without moving the run.
        self.view: list[Candle] | None = None
        self._view_head: int | None = None
        # The price window eases, so filling the tile does not make it jump.
        self._low: float | None = None
        self._high: float | None = None
        self.message = "press Run to start the backtest"
        self.setMinimumHeight(140)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_trade(self, trade: dict | None) -> None:
        self.trade = trade
        self.update()

    def clear_view(self) -> None:
        """Go back to the live tail."""
        self.view = None
        self._view_head = None
        self.update()

    def set_view(
        self, bars: list[Candle] | None, trade: dict | None = None
    ) -> None:
        """Show a fixed window of candles, with `trade` marked, or the live tail."""
        self.view = list(bars) if bars else None
        self.trade = trade
        self._view_head = None
        if self.view and trade is not None:
            # Where the trade's exit sits inside the window (by timestamp).
            head = None
            for index, bar in enumerate(self.view):
                if bar.stamp >= int(trade.get("out_stamp", 0)):
                    head = index
                    break
            self._view_head = head
        self.update()

    def set_offset(self, offset: float) -> None:
        self.offset = max(0.0, min(0.999, offset))

    @staticmethod
    def _position_for(bars: list[Candle], stamp: int, base: int) -> int:
        """The index (in the run's numbering) of the bar at `stamp`."""
        for index, bar in enumerate(bars):
            if bar.stamp >= int(stamp):
                return base + index
        return base + len(bars) - 1

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

        viewing = self.view is not None
        bars = self.view if viewing else self.playback.recent()
        if not bars:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(TEXT_FAINT))
            painter.drawText(
                QRectF(left, top, right - left, bottom - top),
                Qt.AlignmentFlag.AlignCenter,
                self.message,
            )
            return

        room = self.visible_count(width)
        if viewing:
            # A fixed window: indices are positions in the list, and the trade
            # is centred rather than the newest candle.
            base = 0
            last = len(bars) - 1
            head = self._view_head if self._view_head is not None else last
            playhead = min(float(last), head + room / 2)
        else:
            # Absolute indices: the window is the tail of a stream, so position
            # in the list is not position in the run.
            base = self.playback.index - len(bars)
            last = base + len(bars) - 1
            playhead = last + self.offset
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
            # Never let the eased range leave a candle off the plot: expand at
            # once when the window pokes out, and ease the shrink back after.
            self._low = min(self._low, low - pad)
            self._high = max(self._high, high + pad)
        low, high = self._low, self._high
        if high - low <= 0:
            # A flat stretch would divide by zero; give it a sliver of room.
            spread = max(abs(high) * 1e-4, 1e-6)
            low, high = low - spread, high + spread

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
        if not viewing:
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

        # The picked trade, brought out in its own colour: the stretch it held,
        # a line across it, and its entry and exit prices.
        trade = self.trade
        if trade is not None:
            if viewing:
                in_at = self._position_for(bars, trade.get("in_stamp", 0), base)
                out_at = self._position_for(bars, trade.get("out_stamp", 0), base)
            else:
                in_at = trade["in_index"]
                out_at = trade["out_index"]
            x_in = x_of(in_at)
            x_out = x_of(out_at)
            y_in = y_of(trade["in_price"])
            y_out = y_of(trade["out_price"])
            band = QColor(TRADE_HILITE)
            band.setAlpha(46)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(band)
            painter.drawRect(
                QRectF(
                    min(x_in, x_out), top, abs(x_out - x_in), bottom - top
                )
            )
            painter.setPen(QPen(QColor(TRADE_HILITE), 1.5))
            painter.drawLine(QPointF(x_in, y_in), QPointF(x_out, y_out))
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(QPointF(x_in, y_in), 4, 4)
            painter.setBrush(
                QColor(UP if trade["result"] >= 0 else DOWN)
            )
            painter.drawEllipse(QPointF(x_out, y_out), 4, 4)
            painter.setFont(mono_font(7))
            painter.setPen(QColor(TRADE_HILITE))
            painter.drawText(
                QRectF(x_in - 30, y_in - 18, 60, 14),
                Qt.AlignmentFlag.AlignCenter,
                f"{trade['in_price']:,.0f}",
            )
            painter.drawText(
                QRectF(x_out - 30, y_out + 4, 60, 14),
                Qt.AlignmentFlag.AlignCenter,
                f"{trade['out_price']:,.0f}",
            )
            # A tag at the top of the band, so the pick is easy to spot.
            label = f"#{trade.get('n', 0):,}"
            centre = (x_in + x_out) / 2
            painter.setBrush(QColor(TRADE_HILITE))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(centre - 24, top - 2, 48, 13))
            painter.setPen(QColor("#0f1013"))
            painter.drawText(
                QRectF(centre - 24, top - 2, 48, 13),
                Qt.AlignmentFlag.AlignCenter,
                label,
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
        self._speed = 1
        self._entry_formula = None
        self._entry_fields = None
        self._saved_name = ""
        self._saved_entry = ""

        # Header: the title over its status line, then Restart, a speed picker
        # and the Run / Pause button, as in the mock.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        title = QLabel("BACKTEST")
        title.setObjectName("tileTitle")
        titles.addWidget(title)
        self.note = QLabel("idle — press Run")
        self.note.setObjectName("hintLabel")
        titles.addWidget(self.note)
        header.addLayout(titles)
        header.addStretch(1)

        self.restart_button = QPushButton("Restart")
        self.restart_button.setObjectName("restartButton")
        self.restart_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restart_button.setToolTip(
            "Start the walk over with the current span"
        )
        self.restart_button.clicked.connect(self.restart)
        header.addWidget(
            self.restart_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        self.speed = QComboBox()
        self.speed.setObjectName("speedSelect")
        self.speed.addItems(SPEEDS)
        self.speed.setFixedWidth(64)
        self.speed.setToolTip("How many candles each step walks")
        self.speed.currentTextChanged.connect(self._speed_changed)
        header.addWidget(self.speed, 0, Qt.AlignmentFlag.AlignVCenter)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.setToolTip("Start, pause and resume the walk")
        self.run_button.clicked.connect(self._on_run)
        header.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(header)

        # Progress: the bar and the bar count, as in the mock.
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setObjectName("playbackProgress")
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress_label = QLabel("—")
        self.progress_label.setObjectName("progressCount")
        self.progress_label.setFont(mono_font(7))
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.progress_label)
        self.body.addLayout(progress_row)

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
        # A one-shot to reveal a picked trade after the click has settled.
        self._pending_trade: dict | None = None
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.setInterval(0)
        self._reveal_timer.timeout.connect(self._reveal_pending)
        self._refresh_metrics()
        self._refresh_progress()

    def set_trade(self, trade: dict | None) -> None:
        """Bring a picked trade out on the chart, once the click has settled.

        Deferred to a timer the tile owns: revealing a trade may rewind the
        walk and refresh the results, and doing that inside the table's
        selection handler re-enters the table and can crash Qt.
        """
        self._pending_trade = trade
        self._reveal_timer.start()

    def _reveal_pending(self) -> None:
        self._reveal_trade(self._pending_trade)

    def _reveal_trade(self, trade: dict | None) -> None:
        """Show a picked trade on a fixed window of candles.

        It does **not** move the walk: a window of candles around the trade is
        read on demand and shown in place of the live tail, so a trade before
        the last candles can be looked at without cutting the run short.
        """
        if trade is None:
            self.player.set_view(None, None)
            return
        bars = window_around(
            self._wanted_years,
            self._wanted_resolution,
            int(trade.get("in_stamp", 0)),
        )
        if bars:
            self.player.set_view(bars, trade)
        else:
            self.player.set_trade(trade)
        self.player.update()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Stop the walk before the tile goes, so no tick lands on a dead widget."""
        self._timer.stop()
        self._reveal_timer.stop()
        super().closeEvent(event)

    # -- the loop ----------------------------------------------------------

    def _speed_changed(self, text: str) -> None:
        try:
            self._speed = max(1, int(text.lstrip("×x")))
        except ValueError:
            self._speed = 1

    def _tick(self) -> None:
        if self.playback.done:
            # It stops here. Starting over is a decision, not a loop.
            self.pause()
            self.note.setText(
                f"finished — {self.playback.trades:,} trades, "
                f"{self.playback.win_rate * 100:,.0f}% won, press Run to replay"
            )
            return
        self._elapsed += FRAME_MS
        if self._elapsed >= STEP_MS:
            self._elapsed -= STEP_MS
            for _ in range(self._speed):
                if self.playback.done:
                    break
                if self.session is not None:
                    self.session.advance()
                else:
                    self.playback.advance()
            self._refresh_metrics()
            self._refresh_progress()
            self.advanced.emit()
        # Every frame, not every candle: this is what makes it scroll.
        self.player.set_offset(self._elapsed / STEP_MS)
        self.player.update()

    def play(self) -> None:
        self.player.clear_view()  # back to the live tail
        self._timer.start()
        self.run_button.setText("Pause")

    def pause(self) -> None:
        self._timer.stop()
        self.run_button.setText("Run" if self.playback.done else "Resume")

    def playing(self) -> bool:
        return self._timer.isActive()

    def _on_run(self) -> None:
        """Run to start, then Pause and Resume; Run again once it is spent."""
        if not self._launched or self.playback.done:
            self.restart()
        elif self.playing():
            self.pause()
        else:
            self.play()

    def finish(self) -> None:
        """Walk straight to the end, so every result is there to look at."""
        if self.session is None:
            return
        self.pause()
        if self.session._core_ready():
            self.session.seek(self.session.total)  # one native walk
        else:
            while not self.playback.done:
                self.session.advance()
        self._elapsed = 0
        self.player.set_offset(0.0)
        self.player.reset_range()
        self._refresh_metrics()
        self._refresh_progress()
        self.player.update()
        self.run_button.setText("Run")
        self.note.setText(
            f"finished — {self.playback.trades:,} trades, "
            f"{self.playback.win_rate * 100:,.0f}% won, press Run to replay"
        )
        self.advanced.emit()

    def restart(self, to: int = 0, autoplay: bool = True) -> None:
        """Adopt the controls and start the walk over. The only way it resets.

        `to` fast-forwards to a bar first, for the replay scrubber; `autoplay`
        keeps a seek paused so the chosen stretch can be studied.
        """
        params = self._wanted_params or {
            "initial_capital": 10_000.0,
            "tp": 2.0,
            "sl": 1.0,
            "position": 10.0,
            "sizing": "balance",
            "cash": 2_000.0,
            "fee": 0.06,
        }
        self.session = build_session(
            self._wanted_years,
            params,
            self._wanted_rule,
            self._wanted_resolution,
            entry_formula=self._entry_formula,
            fields=self._entry_fields,
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
        # Fast-forward to the sought bar before anything is drawn.
        for _ in range(max(0, to)):
            if self.playback.done:
                break
            self.session.advance()
        self.player.set_offset(0.0)
        self.player.reset_range()
        self._describe()
        self._refresh_metrics()
        self._refresh_progress()
        self.player.update()
        self.restarted.emit(self.session)
        if autoplay:
            self.play()
        else:
            self.pause()
            self.run_button.setText("Run" if self.playback.done else "Resume")

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
        self._entry_formula = None
        self._entry_fields = None
        self._saved_name = ""
        self._saved_entry = ""
        self._describe()

    def rule_key(self) -> str:
        return self._wanted_rule

    def saved_entry(self) -> str:
        return self._saved_entry

    def set_saved_strategy(self, name: str, entry: str, fields=None) -> bool:
        """Point the run at a saved strategy's entry rule.

        The rule is parsed once, here; a rule the language cannot read is
        refused and the built-in is kept.
        """
        from lalala.formula import ENTRY_FIELDS, FUNCTIONS, FormulaError, parse

        try:
            formula = parse(entry, fields or ENTRY_FIELDS, FUNCTIONS)
        except FormulaError:
            self._describe()
            return False
        self._wanted_rule = "saved"
        self._entry_formula = formula
        self._entry_fields = tuple(fields or ENTRY_FIELDS)
        self._saved_name = name
        self._saved_entry = entry
        self._describe()
        return True

    def _describe(self) -> None:
        if not self._launched:
            self.note.setText("idle — press Run")
            return
        name = strategy_label(self._wanted_rule)
        if self._wanted_rule == "saved" and self._saved_name:
            name = self._saved_name
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

    def _refresh_progress(self) -> None:
        """The bar and the candle count."""
        play = self.playback
        if self._launched and play.total:
            self.progress.setValue(int(play.progress * 1000))
            self.progress_label.setText(
                f"{play.progress * 100:,.0f}% · "
                f"{play.index:,} / {play.total:,} candles"
            )
        else:
            self.progress.setValue(0)
            self.progress_label.setText("—")

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
