"""The local candle store: paths, coverage, and CSV append/read helpers.

History is kept as one OHLCV file per year, always at `1m`: the finest
resolution is the only one worth keeping, because anything coarser can be
compacted from it later. Everything here is pure — no Qt, no network — so the
coverage rules can be tested against a temp directory.

The files carry real venue gaps (Binance was down for hours on 2017-09-06,
and briefly twice in December). They are left as they are: a run refuses to
trade across a gap rather than inventing the missing minutes.

    data/candles/BTC-2017-1m.csv
    timestamp,open,high,low,close,volume
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

ASSET = "BTC"
RESOLUTION = "1m"          # the only resolution ever downloaded
COMPLETE = 0.99            # a full year with a few venue outages is "complete"
MINUTE_MS = 60_000
HEADER = "timestamp,open,high,low,close,volume\n"

# The BTCUSDT spot pair opened on this minute. Nothing exists before it, so
# 2017 is only expected from here — otherwise the first year could never be
# called complete and its Download would never clear.
HISTORY_START_MS = 1_502_942_400_000  # 2017-08-17T04:00Z

REPO_ROOT = Path(__file__).resolve().parents[2]

# Row counts are stable between writes, so a span change does not re-scan a
# half-million-line file every time the picker moves.
_ROW_CACHE: dict[tuple[str, float], int] = {}

MISSING = "missing"
PARTIAL = "partial"
COMPLETE_STATE = "complete"


def candles_dir() -> Path:
    """Where the OHLCV files live. `LALALA_DATA` overrides the default."""
    return Path(os.environ.get("LALALA_DATA", REPO_ROOT / "data" / "candles"))


def candle_file(year: int, resolution: str = RESOLUTION) -> Path:
    return candles_dir() / f"{ASSET}-{year}-{resolution}.csv"


def ensure_data_dir() -> Path:
    """Create the folder on first use so a download has somewhere to go."""
    target = candles_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return target


def _stamp(year: int, month: int, day: int) -> int:
    return int(
        datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000
    )


def expected_rows(year: int, now: datetime | None = None) -> int:
    """One-minute bars a year should hold, clipped to what can exist.

    The span starts at the pair's listing, not at the calendar, and the
    current year only counts up to today, so a run still collecting this year
    is not called short.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)
    start = max(_stamp(year, 1, 1), HISTORY_START_MS)
    end = _stamp(year + 1, 1, 1)
    if year == now.year:
        end = min(end, int(now.timestamp() * 1000))
    if end <= start:
        return 0
    return (end - start) // MINUTE_MS


def row_count(path: Path) -> int:
    """Data rows in a CSV, minus the header. Zero when the file is absent."""
    try:
        stat = path.stat()
    except OSError:
        return 0
    key = (str(path), stat.st_mtime)
    cached = _ROW_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        with path.open("rb") as handle:
            lines = 0
            while True:
                block = handle.read(1 << 20)
                if not block:
                    break
                lines += block.count(b"\n")
    except OSError:
        return 0
    count = max(0, lines - 1)
    _ROW_CACHE[key] = count
    return count


def tail_rows(path: Path, count: int) -> list[tuple]:
    """The last `count` rows of a CSV, oldest first.

    Seeks to the tail rather than reading the file, so a preview does not walk
    a year of minutes to show the last few hundred.
    """
    if count <= 0:
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            block = min(size, max(4096, count * 90))
            handle.seek(size - block)
            data = handle.read().decode("ascii", "ignore")
    except OSError:
        return []
    lines = data.splitlines()
    if block < size:
        lines = lines[1:]  # the seek is not line aligned
    rows: list[tuple] = []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            rows.append(
                (
                    int(parts[0]),
                    float(parts[1]),
                    float(parts[2]),
                    float(parts[3]),
                    float(parts[4]),
                    float(parts[5]),
                )
            )
        except ValueError:
            continue  # the header, or a torn line
    return rows[-count:]


def last_timestamp(path: Path) -> int | None:
    """The newest timestamp in a file, so a download can resume from it."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size == 0:
                return None
            block = min(size, 4096)
            handle.seek(size - block)
            tail = handle.read().decode("ascii", "ignore")
    except OSError:
        return None
    lines = [line for line in tail.splitlines() if line.strip()]
    if not lines:
        return None
    # A partial first line is likely, since the seek is not line aligned.
    for line in reversed(lines):
        head = line.split(",", 1)[0]
        if head.isdigit():
            return int(head)
    return None

def append_rows(path: Path, rows: list[tuple[int, float, float, float, float, float]]) -> int:
    """Append OHLCV rows, writing the header when the file is new."""
    if not rows:
        return 0
    ensure_data_dir()
    fresh = not path.exists() or path.stat().st_size == 0
    with path.open("a") as handle:
        if fresh:
            handle.write(HEADER)
        for stamp, open_, high, low, close, volume in rows:
            handle.write(
                f"{stamp},{open_:g},{high:g},{low:g},{close:g},{volume:g}\n"
            )
    _ROW_CACHE.pop((str(path), path.stat().st_mtime), None)
    return len(rows)


def year_state(year: int, now: datetime | None = None) -> str:
    """`missing`, `partial` or `complete` for one year at 1m."""
    rows = row_count(candle_file(year))
    if rows == 0:
        return MISSING
    if rows < expected_rows(year, now) * COMPLETE:
        return PARTIAL
    return COMPLETE_STATE


def coverage(
    start_year: int, end_year: int, now: datetime | None = None
) -> tuple[list[int], list[int]]:
    """(years with no file at all, years whose file is short of full)."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    missing: list[int] = []
    partial: list[int] = []
    for year in range(start_year, end_year + 1):
        state = year_state(year, now)
        if state == MISSING:
            missing.append(year)
        elif state == PARTIAL:
            partial.append(year)
    return missing, partial


def format_years(years: list[int]) -> str:
    """`2017 2018 2019` as `2017–2019`, gaps kept explicit."""
    if not years:
        return ""
    if len(years) == 1:
        return str(years[0])
    if years == list(range(years[0], years[-1] + 1)):
        return f"{years[0]}–{years[-1]}"
    return ", ".join(str(year) for year in years)
