"""A run as a session: the live walk, the random baseline and buy and hold.

`build_session` decides how a span is walked: held whole and handed to the native
core, or read a year at a time and walked in pieces when it is too long to hold.
No Qt."""

from __future__ import annotations

from typing import Any

import random
from bi_trading.engine.core import DEFAULT_HOLD
from collections import deque
from dataclasses import dataclass, field
from bi_trading.ui.strat.playback_data import (BOLLINGER_DEVIATIONS, BOLLINGER_PERIOD, CHART_BARS, Candle, ColumnSpan, DEFAULT_STRATEGY, _stream_chunks, count_bars, iter_candles, load_span, plan_stride, sample_candles, span_columns,)
from bi_trading.ui.strat.playback_walk import (Playback, _bollinger,)


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


def _random_draws(size: int, seed: int = 1234):
    """One uniform per bar, from the fixed seed, for the coin-flip baseline.

    Drawn up front so the native and Python baselines consume the same values
    in the same order — a draw only on the bars that are flat.
    """
    import numpy as np

    rng = random.Random(seed)
    return np.fromiter((rng.random() for _ in range(size)), float, size)


def bollinger_entries_columns(closes) -> list[bool]:
    """The built-in rule's entries over a closes array (close below the band).

    Each bar's band is worked out from its own window of closes, not from a
    running sum over the whole array. A running sum drifts over millions of
    bars and would put a bar on one side of the band or the other depending on
    where the array began; this way a span walked in pieces (each given the
    last `period - 1` closes of the one before) gets exactly the same entries
    as the span walked whole.
    """
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    values = np.asarray(closes, dtype=float)
    size = len(values)
    entries = np.zeros(size, dtype=bool)
    period = BOLLINGER_PERIOD
    if size <= period:
        return entries.tolist()
    windows = sliding_window_view(values, period)
    lower = windows.mean(axis=1) - windows.std(axis=1) * BOLLINGER_DEVIATIONS
    entries[period - 1 :] = values[period - 1 :] < lower
    return entries.tolist()


def random_entries(
    highs, lows, closes, settings, seed: int = 1234, chance: float = 0.03
) -> list[bool]:
    """The coin-flip baseline over the span's columns, via the core when built."""
    from bi_trading.engine import core

    draws = _random_draws(len(closes), seed)
    return core.random_entries(
        highs,
        lows,
        closes,
        draws,
        settings["tp"],
        settings["sl"],
        settings.get("max_hold", DEFAULT_HOLD),
        chance,
        settings.get("side") == "short",
    )


class ChunkRun:
    """One walk over a span read in pieces: its trades and its running figures.

    What a whole equity curve would give — the peak, the drawdown, the Sharpe's
    mean and variance — is accumulated piece by piece instead, so nothing the
    size of the span is ever held but the trades themselves.
    """

    def __init__(self, capital: float) -> None:
        self.capital = capital
        self.state = None          # the book, as `core.walk_chunk` carries it
        self.rows: list[tuple] = []  # closed trades, as the playback's log rows
        self.open_entry: tuple[int, int] | None = None  # (index, stamp) of the open trade
        self.last_equity = capital
        self.peak = capital
        self.max_drawdown = 0.0
        self.max_gain = 0.0
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.streak = 0
        self.best_win = 0
        self.worst_loss = 0
        self.fees = 0.0

    def take(self, trades, equity, stamps, offset: int, end_state) -> None:
        """Fold in a piece's trades and equity (one value per bar)."""
        import numpy as np

        for (
            in_index, in_px, out_index, out_px, result, fees, notional, reason,
            direction,
        ) in trades:
            in_stamp = (
                int(stamps[in_index - offset]) if in_index >= offset
                else (self.open_entry or (0, 0))[1]
            )
            self.rows.append(
                (in_stamp, in_index, in_px, int(stamps[out_index - offset]),
                 out_index, out_px, result, notional, notional * result, reason,
                 fees, [], direction)
            )
            self.fees += fees
            if result > 0:
                self.streak = self.streak + 1 if self.streak > 0 else 1
                self.best_win = max(self.best_win, self.streak)
            else:
                self.streak = self.streak - 1 if self.streak < 0 else -1
                self.worst_loss = min(self.worst_loss, self.streak)
        # The trade still open at the end of the piece keeps its entry's stamp,
        # for the piece that closes it.
        if end_state[1] > 0.0:
            entry_index = int(end_state[4])
            if entry_index >= offset:
                self.open_entry = (entry_index, int(stamps[entry_index - offset]))
        else:
            self.open_entry = None
        self.state = end_state

        values = np.asarray(equity, dtype=float)
        if not values.size:
            return
        running = np.maximum.accumulate(np.maximum(values, self.peak))
        with np.errstate(divide="ignore", invalid="ignore"):
            self.max_drawdown = min(
                self.max_drawdown, float(np.nanmin(values / running - 1.0))
            )
        self.peak = float(running[-1])
        self.max_gain = max(self.max_gain, float(values.max() / self.capital - 1.0))
        series = np.concatenate(([self.last_equity], values))
        previous = series[:-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = np.where(previous > 0, series[1:] / previous - 1.0, 0.0)
        n = int(returns.size)
        mean = float(returns.mean())
        m2 = float(((returns - mean) ** 2).sum())
        total = self.count + n
        delta = mean - self.mean
        self.m2 += m2 + delta * delta * self.count * n / total
        self.mean += delta * n / total
        self.count = total
        self.last_equity = float(values[-1])


class ChunkTail:
    """The last few bars of a chunked walk, and the first close: what the
    picture and the band need once the walk is over."""

    def __init__(self) -> None:
        self.first_close = 0.0
        self._columns: tuple | None = None

    def add(self, data: tuple) -> None:
        import numpy as np

        if self._columns is None:
            self.first_close = float(data[4][0])
            joined = data
        else:
            joined = tuple(np.concatenate((a, b)) for a, b in zip(self._columns, data, strict=True))
        self._columns = tuple(column[-CHART_BARS:] for column in joined)

    def candles(self) -> list[Candle]:
        if self._columns is None:
            return []
        span = ColumnSpan.from_arrays(self._columns)
        return span.candles(0, span.length)


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
    span: ColumnSpan | None = None
    closes: Any = None
    highs: Any = None
    lows: Any = None
    settings: dict[str, Any] | None = None
    strategy_entries: list | None = None
    short_entries: list | None = None
    random_entries: list | None = None
    strategy_entries_arr: Any = None
    random_entries_arr: Any = None
    exit_formula: Any = None
    short_entries_arr: Any = None
    # A span too long to hold is walked in pieces: (years, resolution, rule).
    stream: tuple | None = None

    def _settings(self) -> dict[str, Any]:
        """The walk settings; a session that walks has them."""
        assert self.settings is not None, "this session has nothing to walk"
        return self.settings

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
        if self._fast_ready():
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
        """True when a seek can be one walk over the span.

        It is a native walk where the Rust core is built, and the same walk in
        Python where it is not — either way the curves are rebuilt in one pass,
        not stepped bar by bar.
        """
        return (
            self.span is not None
            and self.settings is not None
            and self.strategy_entries_arr is not None
            and self.random_entries_arr is not None
        )

    def _chunk_ready(self) -> bool:
        """True for a span too long to hold, which the core walks in pieces."""
        return (
            self.span is None
            and self.stream is not None
            and self.settings is not None
        )

    def _fast_ready(self) -> bool:
        """A seek or a finish can be done by the core, whole or in pieces."""
        return self._core_ready() or self._chunk_ready()

    def _core_seek(self, target: int) -> None:
        self._core_apply(target, self._core_compute(target))

    def _core_compute(self, target: int):
        """The two walks to `target`. Reads the session, changes nothing.

        That makes it safe off the main thread: the finish button runs it on a
        worker, and `_core_apply` then lands the result on the main thread.
        """
        from bi_trading.engine import core

        if self.span is None:
            return self._chunk_compute(target)

        s = self._settings()
        # The span's columns go straight to the walk (a NumPy slice is a view).
        assert self.span is not None
        closes = self.span.closes[:target]
        highs = self.span.highs[:target]
        lows = self.span.lows[:target]
        args = (closes, highs, lows)

        def run(entries, exit_formula, shorts=None):
            return core.walk(
                *args,
                entries[:target],
                s["capital"], s["tp"], s["sl"], s["position"], s["sizing"],
                s["max_cash"], s["fee"], s.get("max_hold", DEFAULT_HOLD),
                s.get("dynamic_tp", False), s.get("reverse", 0.0),
                s.get("side", "long"), exit_formula, shorts,
                s.get("slippage", 0.0),
            )

        strategy_trades, strategy_equity = run(
            self.strategy_entries_arr, self.exit_formula,
            None if self.short_entries_arr is None
            else self.short_entries_arr[:target],
        )
        random_trades, random_equity = run(self.random_entries_arr, None)
        return strategy_trades, strategy_equity, random_trades, random_equity

    def _core_apply(self, target: int, walked) -> None:
        if self.span is None:
            self._chunk_apply(target, walked)
            return
        strategy_trades, strategy_equity, random_trades, random_equity = walked
        self._settle(target, strategy_trades, strategy_equity,
                     random_trades, random_equity)

    def _chunk_compute(self, target: int):
        """The two walks to `target` over a span read a year at a time.

        Each piece is walked by the core with the book carried over from the
        last, so a trade may open in one year and close in the next and the
        result is the same as one walk over the whole span. Reads the session,
        changes nothing, so it can run off the main thread.
        """
        import numpy as np

        from bi_trading.engine import core

        assert self.stream is not None
        years, resolution, rule = self.stream
        s = self._settings()
        warmup = int(s.get("warmup", 0))
        capital = s["capital"]
        stride = max(1, self.strategy.stride)
        short = s.get("side") == "short"
        strategy = ChunkRun(capital)
        baseline = ChunkRun(capital)
        tail = ChunkTail()
        rng = random.Random(1234)
        spare = np.empty(0)         # draws made but not yet used, in stream order
        carry = np.empty(0)         # the last bars' closes, for the band
        random_state = None
        # The curves open at the capital, then hold one point per tick: the
        # book after each `stride` bars, as stepping the run would have sampled.
        strategy_curve = [capital]
        random_curve = [capital]
        benchmark = [capital]
        next_tick = stride
        walked = 0
        last_close = 0.0

        def walk(run, entries, closes, highs, lows, offset):
            trades, equity, end = core.walk_chunk(
                closes, highs, lows, entries, capital, s["tp"], s["sl"],
                s["position"], s["sizing"], s["max_cash"], s["fee"],
                s.get("max_hold", DEFAULT_HOLD), s.get("dynamic_tp", False),
                s.get("reverse", 0.0), s.get("side", "long"), None, None,
                s.get("slippage", 0.0), offset, run.state,
            )
            return trades, np.asarray(equity, dtype=float), end

        for offset, data in _stream_chunks(years, resolution, target):
            stamps, _opens, highs, lows, closes, _volumes = data
            size = len(stamps)
            tail.add(data)

            if rule == "bollinger":
                joined = np.concatenate((carry, closes))
                mine = np.asarray(
                    bollinger_entries_columns(joined)[len(carry):], dtype=bool
                )
                carry = joined[-(BOLLINGER_PERIOD - 1):]
            else:
                mine = np.zeros(size, dtype=bool)
            if offset < warmup:
                mine[: warmup - offset] = False

            need = size - len(spare)
            if need > 0:
                spare = np.concatenate(
                    (spare, np.fromiter((rng.random() for _ in range(need)), float, need))
                )
            flags, random_state = core.random_entries_chunk(
                highs, lows, closes, spare, s["tp"], s["sl"],
                s.get("max_hold", DEFAULT_HOLD), 0.03, short, offset, random_state,
            )
            spare = spare[random_state[3]:]
            other = np.asarray(flags, dtype=bool)
            if offset < warmup:
                other[: warmup - offset] = False

            equities = []
            for run, entries in ((strategy, mine), (baseline, other)):
                trades, equity, end = walk(run, entries, closes, highs, lows, offset)
                run.take(trades, equity, stamps, offset, end)
                equities.append(equity)
            walked = offset + size
            last_close = float(closes[-1])

            # The ticks that fall inside this piece: the book at each tick's last bar.
            while next_tick <= walked:
                position = next_tick - offset - 1
                strategy_curve.append(float(equities[0][position]))
                random_curve.append(float(equities[1][position]))
                benchmark.append(capital * float(closes[position]) / tail.first_close)
                next_tick += stride
        # A last, shorter tick when the walk does not end on a multiple of the stride.
        if walked and next_tick - stride < walked:
            strategy_curve.append(strategy.last_equity)
            random_curve.append(baseline.last_equity)
            benchmark.append(capital * last_close / tail.first_close)
        return strategy, baseline, tail, walked, strategy_curve, random_curve, benchmark

    def _chunk_apply(self, target: int, walked) -> None:
        strategy, baseline, tail, reached, curve, random_curve, benchmark = walked
        self.strategy.adopt_stream(strategy, tail, reached)
        self.random.adopt_stream(baseline, tail, reached)
        self.strategy_curve = curve
        self.random_curve = random_curve
        self.benchmark = benchmark
        self.low = self.high = self.capital
        for values in (self.strategy_curve, self.random_curve):
            if values:
                self.low = min(self.low, min(values))
                self.high = max(self.high, max(values))

    def adopt_saved(self, records, strategy_curve, random_curve) -> bool:
        """Show a saved run whole from its stored trades and curves.

        No walk: the trades and the equity curves were kept when the run was
        saved, so they are put back as they were. False when they do not fit
        this span (another length, or nothing stored), and the caller walks.
        """
        total = self.strategy.total
        if (
            self.span is None
            or not records
            or len(strategy_curve) != total
            or len(random_curve) != total
        ):
            return False
        # A stored record is the playback's log row; the walk's is shorter.
        trades = [
            (r[1], r[2], r[4], r[5], r[6], r[10], r[7], r[9], r[12])
            for r in records
        ]
        self._settle(total, trades, list(strategy_curve), [], list(random_curve))
        return True

    def _settle(
        self, target, strategy_trades, strategy_equity, random_trades, random_equity
    ) -> None:
        s = self._settings()
        assert self.span is not None
        closes = self.span.closes[:target]
        self.strategy.adopt(strategy_trades, strategy_equity, self.span, target)
        self.random.adopt(random_trades, random_equity, self.span, target)
        self.strategy_curve = strategy_equity
        self.random_curve = random_equity
        # The benchmark and the scale, over the whole span, in array maths
        # rather than a Python pass per bar.
        if len(closes):
            self.benchmark = (s["capital"] * closes / float(closes[0])).tolist()
        else:
            self.benchmark = []
        self.low = self.high = s["capital"]
        for curve in (strategy_equity, random_equity):
            if curve:
                self.low = min(self.low, min(curve))
                self.high = max(self.high, max(curve))


def _after_warmup(entries, warmup: int):
    """`entries` with the first `warmup` bars switched off."""
    if warmup <= 0:
        return entries
    entries = list(entries)
    for index in range(min(warmup, len(entries))):
        entries[index] = False
    return entries


def walk_clamps(params: dict) -> list[str]:
    """What the walk will not take at face value, in words.

    A max cash above the capital, a fixed dollar position above it, and a
    reverse percent with the dynamic take profit off all describe something the
    walk cannot do, so `_walk_settings` brings them back and this says so.
    """
    capital = float(params.get("initial_capital") or 0.0)
    notes = []
    if capital > 0 and float(params.get("cash") or 0.0) > capital:
        notes.append("max cash capped at the capital")
    if (
        capital > 0
        and str(params.get("sizing")) == "fixed"
        and float(params.get("position") or 0.0) > capital
    ):
        notes.append("position capped at the capital")
    if float(params.get("dyn_tp_reverse") or 0.0) > 0 and not params.get("dynamic_tp"):
        notes.append("reverse % ignored: dynamic TP is off")
    return notes


def _walk_settings(params: dict) -> dict:
    capital = float(params["initial_capital"] or 0.0)
    position = float(params["position"] or 0.0)
    max_cash = float(params["cash"] or 0.0)
    if capital > 0:
        max_cash = min(max_cash, capital)
        if str(params["sizing"]) == "fixed":
            position = min(position, capital)
    dynamic_tp = bool(params.get("dynamic_tp"))
    return {
        # Bars of history before a signal counts; 0 is off.
        "warmup": max(0, int(params.get("warmup") or 0)),
        "capital": capital,
        "tp": float(params["tp"] or 0.0),
        "sl": float(params["sl"] or 0.0),
        "position": position,
        "sizing": str(params["sizing"]),
        "max_cash": max_cash,
        # The tile takes a percent; the walk a fraction per side.
        "fee": float(params.get("fee") or 0.0) / 100.0,
        "slippage": float(params.get("slippage") or 0.0) / 100.0,
        "dynamic_tp": dynamic_tp,
        "reverse": float(params.get("dyn_tp_reverse") or 0.0) if dynamic_tp else 0.0,
        "side": "short" if params.get("side") == "short" else "long",
        # Candles a trade may run; 0 is no limit.
        "max_hold": (
            DEFAULT_HOLD
            if params.get("hold") is None
            else max(0, int(params["hold"] or 0))
        ),
    }

# Above this many bars a span is streamed rather than held in memory. The
# array-backed span is six float64 columns plus two bool entry columns — about
# fifty bytes a bar — so twelve million bars is roughly 600 MB, comfortably
# more than a decade of minutes with room for the store to keep growing.
CORE_MAX = 12_000_000


def build_session(
    years: list[int],
    params: dict,
    rule: str = DEFAULT_STRATEGY,
    resolution: str = "1m",
    fallback: list[Candle] | None = None,
    entry_formula=None,
    fields=None,
    exit_formula=None,
    side: str = "long",
    short_entry_formula=None,
) -> BacktestSession:
    """A run over the whole span.

    A span small enough to hold is loaded as columns and its entries worked out
    up front, so the walk (and every seek) can be done by the core. A longer
    span is streamed off disk and stepped in Python.
    """
    settings = _walk_settings(params)
    warmup = settings["warmup"]
    # `side` is long, short, or both. The settings' side is what the strategy
    # trades alone, and what the random baseline copies: a strategy that goes
    # both ways is measured against a baseline that goes long.
    settings["side"] = "short" if side == "short" else "long"
    span: ColumnSpan | None = None
    total = count_bars(years, resolution)
    if entry_formula is not None or (total and total <= CORE_MAX):
        span = load_span(years, resolution)
        if span is None or span.length == 0:
            span = ColumnSpan(fallback if fallback is not None else sample_candles())
        total = span.length
    if not total:
        span = ColumnSpan(fallback if fallback is not None else sample_candles())
        total = span.length

    stride = plan_stride(total)
    session = BacktestSession(strategy=None, random=None)  # type: ignore[arg-type]  # set below
    if span is not None:
        session.settings = settings
        session.exit_formula = exit_formula
        session.span = span
        session.closes = span.closes
        session.highs = span.highs
        session.lows = span.lows
        short_entries = None
        if entry_formula is not None:
            from bi_trading.engine.formula import ENTRY_FIELDS
            from bi_trading.engine.formula_eval import entry_signals

            columns = span_columns(span)
            indices = set(
                entry_signals(
                    entry_formula, columns, fields or ENTRY_FIELDS, warmup
                )
            )
            strategy_entries = [i in indices for i in range(total)]
            if short_entry_formula is not None and side == "both":
                shorting = set(
                    entry_signals(
                        short_entry_formula, columns, fields or ENTRY_FIELDS,
                        warmup,
                    )
                )
                short_entries = [i in shorting for i in range(total)]
        elif rule == "bollinger":
            strategy_entries = _after_warmup(
                bollinger_entries_columns(span.closes), warmup
            )
        else:
            strategy_entries = [False] * total
        session.strategy_entries = strategy_entries
        session.short_entries = short_entries
        session.random_entries = _after_warmup(
            random_entries(span.highs, span.lows, span.closes, settings), warmup
        )
        import numpy as np

        session.strategy_entries_arr = np.asarray(strategy_entries, dtype=bool)
        session.short_entries_arr = (
            None if short_entries is None
            else np.asarray(short_entries, dtype=bool)
        )
        session.random_entries_arr = np.asarray(
            session.random_entries, dtype=bool
        )
        strategy = Playback(
            None, rule=rule, total=total, stride=stride, span=span,
            entries=set(i for i, on in enumerate(strategy_entries) if on),
            short_entries=(
                None if short_entries is None
                else set(i for i, on in enumerate(short_entries) if on)
            ),
            exit_formula=exit_formula,
            **settings,
        )
        random_buy = Playback(
            None, rule="random", total=total, stride=stride, span=span,
            entries=set(i for i, on in enumerate(session.random_entries) if on),
            **settings,
        )
    else:
        feeds = [lambda: iter_candles(years, resolution) for _ in range(2)]
        strategy = Playback(
            feeds[0], rule=rule, total=total, stride=stride,
            exit_formula=exit_formula, **settings,
        )
        random_buy = Playback(
            feeds[1], rule="random", total=total, stride=stride, **settings
        )
        # Too long to hold, so the core walks it a year at a time.
        session.settings = settings
        session.stream = (list(years), resolution, rule)
    session.strategy = strategy
    session.random = random_buy
    session.low = session.high = settings["capital"]
    session._sample()
    return session
