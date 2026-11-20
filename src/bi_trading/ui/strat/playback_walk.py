"""The streaming walk: one position at a time, bar by bar, with the figures kept live.

`Playback` is what the playback tile shows. No Qt; it steps a stream of Candles or a
`ColumnSpan`, or adopts a state the native core computed."""

from __future__ import annotations

from bi_trading.engine.core import DEFAULT_HOLD, exit_context
from bi_trading.engine.formula_eval import evaluate_scalar
from bi_trading.engine.stats import underwater_runs
from collections import deque
from collections.abc import Iterable
from collections.abc import Callable, Iterator

from bi_trading.ui.strat.playback_data import (BOLLINGER_DEVIATIONS, BOLLINGER_PERIOD, CHART_BARS, Candle, ColumnSpan, DEFAULT_STRATEGY, MAX_MARKERS, _feed_factory,)


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
        max_hold: int = DEFAULT_HOLD,
        rule: str = DEFAULT_STRATEGY,
        seed: int = 1234,
        entry_chance: float = 0.03,
        total: int | None = None,
        stride: int = 1,
        entries=None,
        dynamic_tp: bool = False,
        reverse: float = 0.0,
        span: ColumnSpan | None = None,
        side: str = "long",
        exit_formula=None,
        short_entries=None,
        slippage: float = 0.0,
        warmup: int = 0,
        step_ms: int = 60_000,
        participation: float = 0.0,
        entry_open: bool = False,
        through: float = 0.0,
    ) -> None:
        self.participation = participation
        # Fill an entry at the open of the bar after the signal, not at the
        # close of the bar that made it; and how far past a take profit's price
        # the market must trade before that limit order counts as filled.
        self.entry_open = entry_open
        self.through = through
        self.warmup = max(0, int(warmup))
        # How far apart two neighbouring bars are; further than that is a hole.
        self.step_ms = step_ms
        self._span = span
        self._feed_factory: Callable[[], Iterator[Candle]] | None = (
            None if span is not None else _feed_factory(candles)
        )
        self._feed: Iterator[Candle] | None = None
        self._entries: set[int] | None
        self._short_entries: set[int] | None
        if total is None:
            total = (
                span.length
                if span is not None
                else len(candles) if isinstance(candles, (list, tuple)) else 0
            )
        self.total = total
        self.stride = max(1, stride)
        # A rule-driven run hands over the exact bars to open on; otherwise the
        # rule name decides, bar by bar.
        # `side` says what `entries` open: longs, or shorts when it is `short`.
        # `short_entries` are further bars to short on, for a strategy that
        # trades both ways.
        self.side = "short" if side == "short" else "long"
        if self.side == "short":
            self._entries = set()
            self._short_entries = None if entries is None else set(entries)
        else:
            self._entries = None if entries is None else set(entries)
            self._short_entries = (
                None if short_entries is None else set(short_entries)
            )
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
        self.exit_formula = exit_formula
        self.slippage = slippage
        self.reset()

    # -- state -------------------------------------------------------------

    def _new_feed(self) -> Iterator[Candle]:
        factory = self._feed_factory
        assert factory is not None, "a span-backed run has no stream to restart"
        return factory()

    def reset(self) -> None:
        import numpy as np

        # One draw per bar, from the stream the core's baseline draws from.
        self._rng = np.random.default_rng(self.seed)
        self._u = 1.0
        self._feed = self._new_feed() if self._span is None else None
        self._ahead: Candle | None = None   # the next bar, read to see a hole
        self._pending = ""     # the side the last bar signalled, for the next open
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
        self.direction = "long"   # which way the open trade goes
        self._peak = 0.0
        self._path: list[float] = []
        self.peak = self.capital
        self.max_drawdown = 0.0
        self.max_gain = 0.0
        self._under = 0               # bars in the current run below the peak
        self.longest_underwater = 0   # the longest such run, in bars
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
        """The book: cash plus the open position marked at the latest close.

        A long is worth its quantity at the close; a short its margin plus what
        the price has fallen (never below nothing). This is the same figure the
        walk's equity curve holds, so drawdown counts an open loss.
        """
        if self.qty <= 0.0:
            return self.cash
        close = self.close_price()
        if self.direction == "short":
            held = max(0.0, self.qty * (2.0 * self.entry_price - close))
        else:
            held = self.qty * close
        return self.cash + held

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
        `bars` is a `ColumnSpan` or a Candle list.
        """
        span = bars if isinstance(bars, ColumnSpan) else None
        length = span.length if span is not None else len(bars)

        def stamp(i: int) -> int:
            return int(span.stamps[i]) if span is not None else bars[i].stamp

        def window(start: int, stop: int) -> list[Candle]:
            start, stop = max(0, start), min(stop, length)
            return (
                span.candles(start, stop) if span is not None else bars[start:stop]
            )

        self.index = max(0, min(index, length))
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
        self.direction = "long"
        self._peak = 0.0
        self._path = []
        self._exhausted = self.total > 0 and self.index >= length
        if span is not None:
            self._span = span
            self._feed = None
        else:
            self._feed = iter(bars[self.index :])
        self._ahead = None

        self._adopt_trades([t for t in trades if t[2] < self.index], stamp)

        if length:
            self.first_close = float(
                span.closes[0] if span is not None else bars[0].close
            )
            start = max(0, self.index - CHART_BARS)
            self._window = deque(window(start, self.index), maxlen=CHART_BARS)
            self._previous = (
                (span.candle(self.index - 1) if span is not None
                 else bars[self.index - 1])
                if self.index > 0 else None
            )
        self._closes = deque(maxlen=BOLLINGER_PERIOD)
        self._close_total = 0.0
        self._close_squares = 0.0
        for bar in window(max(0, self.index - BOLLINGER_PERIOD), self.index):
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
        self._under = 0
        self.longest_underwater = 0
        # The whole equity curve, in array maths: a decade is millions of bars,
        # and the figures are the same running peak, drawdown and return
        # moments the per-bar `_observe` would keep.
        if self.index > 0:
            import numpy as np

            values = np.asarray(equity[: self.index], dtype=float)
            running_peak = np.maximum.accumulate(
                np.maximum(values, self.capital)
            )
            with np.errstate(divide="ignore", invalid="ignore"):
                drawdowns = values / running_peak - 1.0
            self.peak = float(running_peak[-1])
            runs = underwater_runs(values < running_peak)
            self.longest_underwater = int(runs.max()) if runs.size else 0
            self._under = int(runs[-1]) if values[-1] < running_peak[-1] else 0
            self.max_drawdown = float(np.nanmin(drawdowns))
            self.max_gain = float(values.max() / self.capital - 1.0)

            series = np.concatenate(([self.capital], values))
            previous = series[:-1]
            with np.errstate(divide="ignore", invalid="ignore"):
                returns = np.where(
                    previous > 0, series[1:] / previous - 1.0, 0.0
                )
            self._returns = int(returns.size)
            self._return_mean = float(returns.mean()) if returns.size else 0.0
            self._return_m2 = (
                float(((returns - self._return_mean) ** 2).sum())
                if returns.size
                else 0.0
            )
            self._last_equity = float(values[-1])
        self._pend_from(
            self._previous,
            (window(self.index - 2, self.index - 1) or [None])[0],
        )

    def _adopt_trades(self, closed, stamp) -> None:
        """Rebuild the trade log, the markers and the streaks from closed trades."""
        self.trade_returns = [t[4] for t in closed]
        self.trades_log = []
        self.markers = deque(maxlen=MAX_MARKERS)
        self.streak = 0
        self.best_win = 0
        self.worst_loss = 0
        for (
            in_index, in_px, out_index, out_px, result, fees, notional, reason,
            direction,
        ) in closed:
            in_stamp = stamp(in_index)
            out_stamp = stamp(out_index)
            self.trades_log.append(
                (in_stamp, in_index, in_px, out_stamp, out_index, out_px,
                 result, notional, notional * result, reason, fees, [],
                 direction)
            )
            self.markers.append((in_index, "in", in_px))
            self.markers.append((out_index, "out", out_px))
            self._streak(result)
        self.fees = sum(t[5] for t in closed)

    def _streak(self, result: float) -> None:
        if result > 0:
            self.streak = self.streak + 1 if self.streak > 0 else 1
            self.best_win = max(self.best_win, self.streak)
        else:
            self.streak = self.streak - 1 if self.streak < 0 else -1
            self.worst_loss = min(self.worst_loss, self.streak)

    def adopt_stream(self, run, tail, index: int) -> None:
        """Take the state of a run walked in chunks (`ChunkRun`), flat at `index`.

        Like `adopt`, but the stamps are already on the trades and the figures
        were accumulated chunk by chunk, so no whole curve or whole span exists
        to rebuild them from: `tail` holds just the last bars, for the picture.
        """
        import itertools

        self.index = max(0, index)
        self.cash = run.last_equity
        self.qty = 0.0
        self.entry_price = 0.0
        self.entry_index = 0
        self.entry_cost = 0.0
        self.entry_stamp = 0
        self.entry_notional = 0.0
        self.entry_fee = 0.0
        self.direction = "long"
        self._peak = 0.0
        self._path = []
        self._exhausted = self.total > 0 and self.index >= self.total
        self._span = None
        self._feed = (
            iter(()) if self._exhausted
            else itertools.islice(self._new_feed(), self.index, None)
        )
        self._ahead = None
        rows = run.rows
        self.trade_returns = [row[6] for row in rows]
        self.trades_log = [tuple(row) for row in rows]
        self.markers = deque(maxlen=MAX_MARKERS)
        for row in rows[-MAX_MARKERS // 2 :]:
            self.markers.append((row[1], "in", row[2]))
            self.markers.append((row[4], "out", row[5]))
        self.streak = run.streak
        self.best_win = run.best_win
        self.worst_loss = run.worst_loss
        self.fees = run.fees
        self.first_close = tail.first_close
        bars = tail.candles()
        self._window = deque(bars, maxlen=CHART_BARS)
        self._previous = bars[-1] if bars else None
        self._closes = deque(maxlen=BOLLINGER_PERIOD)
        self._close_total = 0.0
        self._close_squares = 0.0
        for bar in bars[-BOLLINGER_PERIOD:]:
            self._closes.append(bar.close)
            self._close_total += bar.close
            self._close_squares += bar.close * bar.close
        self._band = self._compute_band()
        self._pend_from(self._previous, bars[-2] if len(bars) > 1 else None)
        self.peak = max(run.peak, self.capital)
        self.max_drawdown = run.max_drawdown
        self.max_gain = run.max_gain
        self.longest_underwater = run.longest_under
        self._under = run.under
        self._last_equity = run.last_equity
        self._returns = run.count
        self._return_mean = run.mean
        self._return_m2 = run.m2

    def _pend_from(self, last, before) -> None:
        """The signal the last adopted bar made, for the next bar's open."""
        self._pending = ""
        if self.entry_open and last is not None and self.index > 0:
            self._pending = self._wants(last, before or last, self.index - 1)

    def _compute_band(self):
        return _bollinger(
            self._closes, self._close_total, self._close_squares,
            BOLLINGER_PERIOD, BOLLINGER_DEVIATIONS,
        )

    def _advance_one(self) -> bool:
        next_stamp: int | None = None
        if self._span is not None:
            if self.index >= self._span.length:
                self._exhausted = True
                return False
            candle = self._span.candle(self.index)
            if self.index + 1 < self._span.length:
                next_stamp = int(self._span.stamps[self.index + 1])
        else:
            try:
                assert self._feed is not None
                if self._ahead is not None:
                    candle, self._ahead = self._ahead, None
                else:
                    candle = next(self._feed)
            except StopIteration:
                self._exhausted = True
                return False
            # Read the next bar too, to know whether the data stops after this one.
            try:
                self._ahead = next(self._feed)
                next_stamp = self._ahead.stamp
            except StopIteration:
                self._ahead = None
        # True when this is the last bar before a hole in the data.
        gap_after = (
            next_stamp is not None and next_stamp - candle.stamp > self.step_ms
        )

        if not self.first_close:
            self.first_close = candle.close
        self._update_band(candle.close)

        if self.rule == "random":
            self._u = float(self._rng.random())
        entered = False
        if not self.in_position:
            if self.entry_open:
                # The signal was the bar before's; it holds only if that bar
                # is the one right before this (no hole between them).
                side = self._pending
                if self._previous is None or candle.stamp - self._previous.stamp > self.step_ms:
                    side = ""
            else:
                side = self._wants(candle, self._previous or candle)
            if side and not gap_after:
                self._enter(candle, side)
                entered = self.in_position
        # A position opened at the close has nothing left of its bar to trade;
        # one opened at the open lives through the whole bar.
        if self.in_position and (not entered or self.entry_open):
            if not entered:
                self.bars_in_market += 1
            self._manage(candle, gap_after)
        if self.entry_open:
            self._pending = self._wants(candle, self._previous or candle)

        self._previous = candle
        self._window.append(candle)
        self.index += 1

        equity = self.equity
        self.peak = max(self.peak, equity)
        self._under = self._under + 1 if equity < self.peak else 0
        self.longest_underwater = max(self.longest_underwater, self._under)
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

    def _wants(self, candle: Candle, previous: Candle, index: int | None = None) -> str:
        """Which way to open on this bar, or "" for neither.

        `random` opens on a coin flip: the honest benchmark for any entry rule.
        `bollinger` buys mean reversion — the close has fallen below the lower
        band, so the bar is stretched away from its own average. A rule-driven
        run opens where its rules fire; a bar both its long and short rule
        fire on is left alone.
        """
        at = self.index if index is None else index
        if at == 0 or at < self.warmup:
            return ""
        if self._entries is not None or self._short_entries is not None:
            long = self._entries is not None and at in self._entries
            short = (
                self._short_entries is not None
                and at in self._short_entries
            )
            if long == short:
                return ""
            return "short" if short else "long"
        side = "short" if self.side == "short" else "long"
        if self.rule == "random":
            return side if self._u < self.entry_chance else ""
        if self.rule == "bollinger":
            on = self._band is not None and candle.close < self._band[2]
            return side if on else ""
        return ""

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

    def _enter(self, candle: Candle, side: str = "long") -> None:
        notional = self._budget()
        basis = candle.open if self.entry_open else candle.close
        if self.participation > 0.0:
            notional = min(notional, candle.volume * basis * self.participation)
        if notional <= 0.0 or basis <= 0.0:
            return
        self.direction = side
        cost = notional * self.fee
        # A market order: it fills a little worse than the close it was
        # decided on.
        fill = basis * (
            (1.0 - self.slippage) if side == "short" else (1.0 + self.slippage)
        )
        self.qty = notional / fill
        self.cash -= notional + cost
        self.fees += cost
        self.entry_price = fill
        self.entry_index = self.index
        self.entry_stamp = candle.stamp
        self.entry_notional = notional
        self.entry_fee = cost
        self.entry_cost = notional + cost
        self._peak = candle.low if side == "short" else candle.high
        self._path = [basis]
        self.markers.append((self.index, "in", basis))

    def _manage(self, candle: Candle, gap_after: bool = False) -> None:
        self._path.append(candle.close)
        short = self.direction == "short"
        prev_peak = self._peak   # the trail as the bars before this one left it
        if short:
            target = self.entry_price * (1.0 - self.tp / 100.0)
            stop = self.entry_price * (1.0 + self.sl / 100.0)
            if self.dynamic_tp and self.reverse > 0.0:
                self._peak = min(self._peak, candle.low)
            trail = (
                self._peak * (1.0 + self.reverse / 100.0) if self._peak else 0.0
            )
            hit_tp = self.tp > 0 and candle.low <= target * (1.0 - self.through)
            hit_sl = self.sl > 0 and candle.high >= stop
            hit_trail = (
                self.dynamic_tp and self.reverse > 0
                and 0 < self._peak < self.entry_price and candle.high >= trail
            )
        else:
            target = self.entry_price * (1.0 + self.tp / 100.0)
            stop = self.entry_price * (1.0 - self.sl / 100.0)
            if self.dynamic_tp and self.reverse > 0.0:
                self._peak = max(self._peak, candle.high)
            trail = (
                self._peak * (1.0 - self.reverse / 100.0) if self._peak else 0.0
            )
            hit_tp = self.tp > 0 and candle.high >= target * (1.0 + self.through)
            hit_sl = self.sl > 0 and candle.low <= stop
            hit_trail = (
                self.dynamic_tp and self.reverse > 0
                and self._peak > self.entry_price and candle.low <= trail
            )
        price: float | None = None
        reason = "time"
        # A candle that holds both the target and the stop cannot say which
        # came first, so the stop is taken: the cautious reading.
        # A bar that opened past the stop or trail fills at its open, not at the
        # price it jumped over; one that opened past the target gets the open.
        open_ = candle.open
        limit = False   # only the take profit is a resting limit order
        if hit_sl:
            price = max(stop, open_) if short else min(stop, open_)
            reason = "sl"
        elif hit_tp:
            price = min(target, open_) if short else max(target, open_)
            reason = "tp"
            limit = True
        elif hit_trail:
            # The trail is a stop that follows the price: a market exit.
            before = prev_peak * (
                1.0 + self.reverse / 100.0 if short else 1.0 - self.reverse / 100.0
            )
            gapped = open_ >= before if short else open_ <= before
            price = open_ if gapped else trail
            reason = "tp"
        elif self.exit_formula is not None and evaluate_scalar(
            self.exit_formula,
            exit_context(
                candle.close, self.entry_price, self.tp, self.sl,
                self.index - self.entry_index, short,
            ),
        ):
            price = candle.close
            reason = "rule"
        if (
            price is None
            and self.max_hold > 0
            and self.index - self.entry_index >= self.max_hold
        ):
            price = candle.close
            reason = "time"
        if price is None and gap_after:
            # The data stops after this bar: no holding through a hole.
            price = candle.close
            reason = "gap"
        if price is None:
            return
        if not limit:  # every exit but the take profit slips
            price *= (1.0 + self.slippage) if short else (1.0 - self.slippage)
        value = (
            max(0.0, self.qty * (2.0 * self.entry_price - price))
            if short
            else self.qty * price
        )
        cost = self.qty * price * self.fee
        self.cash += value - cost
        self.fees += cost
        invested = self.entry_cost
        self.qty = 0.0
        self.entry_cost = 0.0
        self.markers.append((self.index, "out", price))
        self._book(
            value - cost, invested, candle.stamp, price, reason,
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
                self.direction,
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
