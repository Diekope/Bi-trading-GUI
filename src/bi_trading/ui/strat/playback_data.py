"""The bars a run walks: the store read as Candles or as columns, a year at a time.

No Qt. A span is streamed off disk, or loaded as arrays (`ColumnSpan`) when it is
small enough to hold, and the constants that size the picture and the pace live here."""

from __future__ import annotations

import random
from bi_trading.data.candles import candle_file
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime


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


@dataclass(frozen=True, slots=True)
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


def _iter_file(path, factor: int) -> Iterator[Candle]:
    """One year, compacted `factor`-to-one, read straight from Parquet arrays."""
    from bi_trading.data import candles

    data = candles.arrays(path)
    if data is None:
        return
    stamps, opens, highs, lows, closes, volumes = data
    size = len(stamps)
    index = 0
    while index < size:
        end = min(index + factor, size) if factor > 1 else index + 1
        yield Candle(
            int(stamps[index]),
            float(opens[index]),
            float(highs[index:end].max() if factor > 1 else highs[index]),
            float(lows[index:end].min() if factor > 1 else lows[index]),
            float(closes[end - 1]),
            float(volumes[index:end].sum() if factor > 1 else volumes[index]),
        )
        index = end


def iter_candles(years: list[int], resolution: str) -> Iterator[Candle]:
    """The whole span, one bar at a time, compacted to `resolution`."""
    factor = FACTOR.get(resolution, 1)
    for year in sorted(years):
        yield from _iter_file(candle_file(year), factor)


def count_bars(years: list[int], resolution: str) -> int:
    """How many bars the span holds at `resolution`.

    Counted per file and rounded up, because bars are compacted within a year:
    a file whose row count is not a multiple of the factor still yields one
    more, shorter bar. The total therefore matches what `iter_candles` yields,
    which matters: progress is measured against it.
    """
    from bi_trading.data import candles

    factor = FACTOR.get(resolution, 1)
    bars = 0
    for year in sorted(years):
        rows = candles.row_count(candle_file(year))
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

# The whole span, keyed by (years, resolution) with the files' signatures, so a
# re-run (Run, Restart, a seek-heavy session) does not re-read and re-parse the
# CSV from disk every time.
_SPAN_CACHE: dict[tuple, tuple] = {}


def _span_signature(years: list[int]) -> tuple:
    from bi_trading.data import candles

    signature = []
    for year in sorted(years):
        path = candle_file(year)
        signature.append((str(path), candles.store_signature(path)))
    return tuple(signature)


def load_all_candles(years: list[int], resolution: str) -> list[Candle]:
    """The whole span in memory, for a rule-driven run.

    A saved strategy is a formula, and a formula is checked over a whole
    series rather than streamed, so this one run reads the span into a list.
    Memoised on the files' signatures: a re-run of the same span is served from
    memory. The list is copied out, so a caller cannot scribble on the cache.
    """
    key = (tuple(sorted(years)), resolution)
    signature = _span_signature(years)
    cached = _SPAN_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return list(cached[1])
    bars = list(iter_candles(years, resolution))
    _SPAN_CACHE[key] = (signature, bars)
    return bars


class ColumnSpan:
    """A loaded span as parallel arrays.

    A long span is held as six arrays, not a Candle per bar: the walk and the
    core read columns, and a Candle is built only for the few bars a picture
    needs. Immutable; a Candle from it is a throwaway view.
    """

    __slots__ = (
        "stamps", "opens", "highs", "lows", "closes", "volumes", "length",
    )

    def __init__(self, bars: list[Candle]) -> None:
        import numpy as np

        length = len(bars)
        self.length = length
        self.stamps = np.fromiter((b.stamp for b in bars), np.int64, length)
        self.opens = np.fromiter((b.open for b in bars), float, length)
        self.highs = np.fromiter((b.high for b in bars), float, length)
        self.lows = np.fromiter((b.low for b in bars), float, length)
        self.closes = np.fromiter((b.close for b in bars), float, length)
        self.volumes = np.fromiter((b.volume for b in bars), float, length)

    def candle(self, index: int) -> Candle:
        return Candle(
            int(self.stamps[index]),
            float(self.opens[index]),
            float(self.highs[index]),
            float(self.lows[index]),
            float(self.closes[index]),
            float(self.volumes[index]),
        )

    @classmethod
    def from_arrays(cls, data: tuple) -> ColumnSpan:
        """A span from (stamps, open, high, low, close, volume) arrays."""
        span = cls.__new__(cls)
        (span.stamps, span.opens, span.highs, span.lows, span.closes,
         span.volumes) = data
        span.length = len(span.stamps)
        return span

    def candles(self, start: int, stop: int) -> list[Candle]:
        return [self.candle(index) for index in range(max(0, start), min(stop, self.length))]


def window_around(
    years: list[int], resolution: str, stamp: int, count: int = 400
) -> list[Candle]:
    """A window of `count` bars around `stamp`, read from the year it is in.

    Read on demand, so a picked trade can be shown without keeping the whole
    span in memory.
    """
    if not years or not stamp:
        return []
    year = datetime.fromtimestamp(stamp / 1000, tz=UTC).year
    if year not in years:
        year = min(years, key=lambda value: abs(value - year))
    path = candle_file(year)
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


# A year's columns, kept after they are read: picking a trade, or filling a table of
# them, would otherwise read the same Parquet file once per trade.
_YEAR_CACHE: dict[tuple[int, int], tuple] = {}
YEARS_KEPT = 3


def _year_columns(year: int, factor: int):
    """A year's columns compacted `factor`-to-one, or None. Memoised on the file."""
    from bi_trading.data import candles

    path = candle_file(year)
    signature = candles.store_signature(path)
    key = (year, factor)
    hit = _YEAR_CACHE.get(key)
    if hit is not None and hit[0] == signature:
        return hit[1]
    data = candles.arrays(path)
    if data is None or not len(data[0]):
        return None
    if factor > 1:
        data = _compact_arrays(data, factor)
    while len(_YEAR_CACHE) >= YEARS_KEPT:
        _YEAR_CACHE.pop(next(iter(_YEAR_CACHE)))
    _YEAR_CACHE[key] = (signature, data)
    return data


def _slice_of(data: tuple, start: int, end: int, margin: int) -> tuple[int, int]:
    import numpy as np

    stamps = data[0]
    first = int(np.searchsorted(stamps, start, side="left"))
    last = int(np.searchsorted(stamps, end, side="right"))
    return max(0, first - margin), min(len(stamps), last + margin)


def bars_between(
    years: list[int], resolution: str, start: int, end: int, margin: int = 4
) -> list[Candle]:
    """The bars from `start` to `end` (stamps, ms) plus `margin` either side.

    Read from the year `start` falls in, as columns, so a picked trade's candles
    cost a slice of a year already in memory, not a Candle per bar of the year.
    Empty when the span is not on disk (a sample run).
    """
    if not years or not start:
        return []
    year = datetime.fromtimestamp(start / 1000, tz=UTC).year
    if year not in years:
        return []
    data = _year_columns(year, FACTOR.get(resolution, 1))
    if data is None:
        return []
    first, last = _slice_of(data, start, end, margin)
    return [
        Candle(
            int(data[0][i]), float(data[1][i]), float(data[2][i]),
            float(data[3][i]), float(data[4][i]), float(data[5][i]),
        )
        for i in range(first, last)
    ]


def trade_strips(
    years: list[int], resolution: str, spans: list[tuple[int, int]],
    margin: int = 2, limit: int = 32,
) -> list[list[tuple] | None]:
    """A small strip of `(open, high, low, close)` per trade, for the table rows.

    `spans` are `(entry stamp, exit stamp)` pairs. Each year is read once however
    many trades fall in it, and a trade longer than `limit` bars is squeezed to
    `limit` (a group of bars becomes one: its open, its extremes, its close), so a
    row is always a few dozen numbers. None where the bars are not on disk.
    """
    factor = FACTOR.get(resolution, 1)
    out: list[list[tuple] | None] = []
    for start, end in spans:
        year = datetime.fromtimestamp(start / 1000, tz=UTC).year if start else 0
        data = _year_columns(year, factor) if year in years else None
        if data is None:
            out.append(None)
            continue
        first, last = _slice_of(data, start, end, margin)
        if last - first < 2:
            out.append(None)
            continue
        group = -(-(last - first) // limit)
        strip = []
        for i in range(first, last, group):
            j = min(last, i + group)
            strip.append((
                float(data[1][i]), float(data[2][i:j].max()),
                float(data[3][i:j].min()), float(data[4][j - 1]),
            ))
        out.append(strip)
    return out


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

# The whole span as columns, keyed like the bar cache, so a run over the same
# span is not re-read from disk.
_SPAN_ARRAY_CACHE: dict[tuple, tuple] = {}


def load_span(years: list[int], resolution: str) -> ColumnSpan | None:
    """The span as a `ColumnSpan`, read a year at a time.

    A year's bars become arrays and are let go before the next year is read, so
    a decade never holds a Candle per minute. None when nothing is on disk.
    """
    import numpy as np

    from bi_trading.data import candles

    key = (tuple(sorted(years)), resolution)
    signature = _span_signature(years)
    cached = _SPAN_ARRAY_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    factor = FACTOR.get(resolution, 1)
    parts: list[tuple] = []
    for year in sorted(years):
        data = candles.arrays(candle_file(year))
        if data is not None and len(data[0]):
            parts.append(_compact_arrays(data, factor))
    span: ColumnSpan | None = None
    if parts:
        span = ColumnSpan.from_arrays(
            tuple(np.concatenate([part[i] for part in parts]) for i in range(6))
        )
    _SPAN_ARRAY_CACHE[key] = (signature, span)
    return span


def _compact_arrays(data: tuple, factor: int) -> tuple:
    """Compact a year's columns `factor`-to-one, without building Candles."""
    import numpy as np

    if factor <= 1:
        return data
    stamps, opens, highs, lows, closes, volumes = data
    size = len(stamps)
    out_stamp: list[int] = []
    out_open: list[float] = []
    out_high: list[float] = []
    out_low: list[float] = []
    out_close: list[float] = []
    out_volume: list[float] = []
    index = 0
    while index < size:
        end = min(index + factor, size)
        out_stamp.append(int(stamps[index]))
        out_open.append(float(opens[index]))
        out_high.append(float(highs[index:end].max()))
        out_low.append(float(lows[index:end].min()))
        out_close.append(float(closes[end - 1]))
        out_volume.append(float(volumes[index:end].sum()))
        index = end
    return (
        np.array(out_stamp, np.int64),
        np.array(out_open, float),
        np.array(out_high, float),
        np.array(out_low, float),
        np.array(out_close, float),
        np.array(out_volume, float),
    )


def span_columns(span: ColumnSpan) -> dict:
    return {
        "open": span.opens,
        "high": span.highs,
        "low": span.lows,
        "close": span.closes,
        "volume": span.volumes,
    }


def _stream_chunks(years: list[int], resolution: str, target: int):
    """The span a year at a time as column tuples, stopping at bar `target`."""
    from bi_trading.data import candles

    factor = FACTOR.get(resolution, 1)
    seen = 0
    for year in sorted(years):
        if seen >= target:
            return
        data = candles.arrays(candle_file(year))
        if data is None or not len(data[0]):
            continue
        data = _compact_arrays(data, factor)
        take = min(len(data[0]), target - seen)
        yield seen, tuple(column[:take] for column in data)
        seen += take
