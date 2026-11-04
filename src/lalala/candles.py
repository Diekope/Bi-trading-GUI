"""The local candle store: paths, coverage, and CSV append/read helpers.

History is kept as one OHLCV file per year, always at `1m`: the finest
resolution is the only one worth keeping, because anything coarser can be
compacted from it later. Everything here is pure — no Qt, no network — so the
coverage rules can be tested against a temp directory.

    data/candles/BTC-2017-1m.csv
    timestamp,open,high,low,close,volume
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

ASSET = "BTC"
RESOLUTION = "1m"          # the only resolution ever downloaded
CANDLES_PER_DAY = 1440     # one-minute bars
COMPLETE = 0.99            # a full year with a few venue outages is "complete"
MINUTE_MS = 60_000
HEADER = "timestamp,open,high,low,close,volume\n"

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


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def expected_rows(year: int, now: datetime | None = None) -> int:
    """One-minute bars a whole year holds, or the part already elapsed.

    The current year is only expected up to today, so a run that is still
    collecting this year is not called short.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)
    days = 366 if _is_leap(year) else 365
    if year == now.year:
        days = max(1, now.timetuple().tm_yday)
    return days * CANDLES_PER_DAY


def expected_until(year: int, moment_ms: int) -> int:
    """Bars a year should hold given a wall-clock cutoff."""
    moment = datetime.fromtimestamp(moment_ms / 1000, tz=timezone.utc)
    return expected_rows(year, moment)


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
            lines = sum(1 for _ in handle)
    except OSError:
        return 0
    count = max(0, lines - 1)
    _ROW_CACHE[key] = count
    return count


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
