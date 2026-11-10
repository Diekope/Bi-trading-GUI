"""The local candle store: paths, coverage, and Parquet read/append helpers.

History is kept as one OHLCV **Parquet** file per year, always at `1m`: the
finest resolution is the only one worth keeping, because anything coarser can
be compacted from it later, and a columnar file reads a whole span as arrays
without parsing a line at a time. Everything here is pure — no Qt, no network —
so the coverage rules can be tested against a temp directory.

A legacy CSV store (`BTC-<year>-1m.csv`) is read and migrated in place: the
first time a year is touched, its CSV is converted to Parquet and, once the row
counts agree, the CSV is removed.

The files carry real venue gaps (Binance was down for hours on 2017-09-06, and
briefly twice in December). They are left as they are: a run refuses to trade
across a gap rather than inventing the missing minutes.

    data/candles/BTC-2017-1m.parquet
    timestamp, open, high, low, close, volume
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ASSET = "BTC"
RESOLUTION = "1m"          # the only resolution ever downloaded
COMPLETE = 0.99            # a full year with a few venue outages is "complete"
MINUTE_MS = 60_000
HEADER = "timestamp,open,high,low,close,volume\n"

# The BTCUSDT spot pair opened on this minute. Nothing exists before it, so
# 2017 is only expected from here — otherwise the first year could never be
# called complete and its Download would never clear.
HISTORY_START_MS = 1_502_942_400_000  # 2017-08-17T04:00Z

REPO_ROOT = Path(__file__).resolve().parents[3]

# pyarrow is a heavy import and the GUI should not pay for it until a candle
# file is read or written, so it is imported on first use.
_pa: tuple | None = None


def _arrow() -> tuple:
    global _pa
    if _pa is None:
        import pyarrow
        import pyarrow.parquet

        _pa = (pyarrow, pyarrow.parquet)
    return _pa


_SCHEMA = None


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        pa, _ = _arrow()
        _SCHEMA = pa.schema(
            [
                ("timestamp", pa.int64()),
                ("open", pa.float64()),
                ("high", pa.float64()),
                ("low", pa.float64()),
                ("close", pa.float64()),
                ("volume", pa.float64()),
            ]
        )
    return _SCHEMA


COLUMNS = ("open", "high", "low", "close", "volume")

# Row counts are stable between writes, so a span change does not re-scan a
# half-million-line file every time the picker moves.
_ROW_CACHE: dict[tuple[str, float], int] = {}

MISSING = "missing"
PARTIAL = "partial"
COMPLETE_STATE = "complete"


def candles_dir() -> Path:
    """Where the OHLCV files live. `LALALA_DATA` overrides the setting."""
    override = os.environ.get("LALALA_DATA")
    if override:
        return Path(override)
    from lalala.state.settings import configured_data_folder

    folder = configured_data_folder()
    if folder:
        return Path(folder).expanduser()
    return default_candles_dir()


def default_candles_dir() -> Path:
    """The candle store inside the repo, used when no folder is configured."""
    return REPO_ROOT / "data" / "candles"


def candle_file(year: int, resolution: str = RESOLUTION) -> Path:
    return candles_dir() / f"{ASSET}-{year}-{resolution}.parquet"


def legacy_csv(year: int, resolution: str = RESOLUTION) -> Path:
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


# -- reading -----------------------------------------------------------------


def _migrate(path: Path) -> None:
    """Convert the legacy CSV beside `path` to Parquet, then drop the CSV."""
    csv = path.with_suffix(".csv")
    if not csv.exists():
        return
    table = _csv_table(csv)
    _write_table(path, table)
    # Only remove the source once the new file holds every row.
    if row_count(path) >= len(table):
        try:
            csv.unlink()
        except OSError:
            pass


def _ensure(path: Path) -> None:
    if not path.exists():
        _migrate(path)


def store_signature(path: Path) -> tuple[int, int] | None:
    """(mtime, size) for a year's Parquet file, migrating a CSV first."""
    _ensure(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def table(path: Path) -> "object | None":
    """The year's table, migrating a legacy CSV first. None when absent."""
    pa, pq = _arrow()
    _ensure(path)
    try:
        return pq.read_table(path)
    except (OSError, pa.ArrowInvalid):
        return None


def arrays(path: Path) -> tuple[np.ndarray, ...] | None:
    """The year's columns as arrays: (timestamp, open, high, low, close, volume)."""
    data = table(path)
    if data is None or data.num_rows == 0:
        return None
    stamp = data.column("timestamp").to_numpy(zero_copy_only=False)
    columns = [data.column(name).to_numpy(zero_copy_only=False) for name in COLUMNS]
    return (stamp, *columns)


def row_count(path: Path) -> int:
    """Data rows in a store file. Zero when the file is absent."""
    try:
        stat = path.stat()
    except OSError:
        _migrate(path)
        try:
            stat = path.stat()
        except OSError:
            return 0
    key = (str(path), stat.st_mtime)
    cached = _ROW_CACHE.get(key)
    if cached is not None:
        return cached
    pa, pq = _arrow()
    try:
        count = pq.read_metadata(path).num_rows
    except (OSError, pa.ArrowInvalid):
        return 0
    _ROW_CACHE[key] = count
    return count


def tail_rows(path: Path, count: int) -> list[tuple]:
    """The last `count` rows, oldest first."""
    if count <= 0:
        return []
    data = table(path)
    if data is None:
        return []
    total = data.num_rows
    start = max(0, total - count)
    rows: list[tuple] = []
    for row in data.slice(start, total - start).to_pylist():
        rows.append(
            (
                int(row["timestamp"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            )
        )
    return rows


def last_timestamp(path: Path) -> int | None:
    """The newest timestamp in a file, so a download can resume from it."""
    data = table(path)
    if data is None or data.num_rows == 0:
        return None
    return int(data.column("timestamp")[-1].as_py())


def append_rows(
    path: Path, rows: list[tuple[int, float, float, float, float, float]]
) -> int:
    """Append OHLCV rows to a year's Parquet file, creating it when new.

    Parquet has no append, so the rows are folded into the year: read, concat,
    write to a temp file, then replace. The downloader flushes in batches so a
    whole year is not rewritten once per page.
    """
    if not rows:
        return 0
    ensure_data_dir()
    pa, _ = _arrow()
    stamps, opens, highs, lows, closes, volumes = zip(*rows)
    fresh = pa.table(
        {
            "timestamp": pa.array(stamps, pa.int64()),
            "open": pa.array(opens, pa.float64()),
            "high": pa.array(highs, pa.float64()),
            "low": pa.array(lows, pa.float64()),
            "close": pa.array(closes, pa.float64()),
            "volume": pa.array(volumes, pa.float64()),
        },
        schema=_schema(),
    )
    existing = table(path)
    combined = fresh if existing is None else pa.concat_tables([existing, fresh])
    _write_table(path, combined)
    _ROW_CACHE.clear()
    return len(rows)


def _write_table(path: Path, data) -> None:
    _, pq = _arrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(data, tmp, compression="zstd")
    os.replace(tmp, path)


def _csv_table(path: Path):
    """Read a legacy CSV into a Table (used only for migration)."""
    pa, _ = _arrow()
    stamps: list[int] = []
    columns: dict[str, list[float]] = {name: [] for name in COLUMNS}
    try:
        with path.open() as handle:
            next(handle, None)  # the header
            for line in handle:
                parts = line.split(",")
                if len(parts) < 6:
                    continue
                try:
                    stamps.append(int(parts[0]))
                    for index, name in enumerate(COLUMNS, start=1):
                        columns[name].append(float(parts[index]))
                except ValueError:
                    continue
    except OSError:
        return pa.table({}, schema=_schema())
    return pa.table(
        {
            "timestamp": pa.array(stamps, pa.int64()),
            **{name: pa.array(values, pa.float64()) for name, values in columns.items()},
        },
        schema=_schema(),
    )


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
