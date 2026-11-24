"""Past Polymarket five-minute BTC markets, kept locally like the candles.

Each settled window `btc-updown-5m-<ts>` is one row: how it settled, its volume,
and the Up share's price samples (about one a minute) from CLOB `prices-history`.
Down is not stored: a Down share is `1 - Up` (the spread is an assumption the
backtest adds, because no book history exists).

    Gamma  /markets?closed=true&slug=a&slug=b…   token ids and the settled outcome
    CLOB   /prices-history?market=<up token>&startTs&endTs&fidelity=1

A window Gamma does not know is stored as `NOT_FOUND` so a resumed download does
not ask again; nothing is ever invented for it.

    data/candles/PM-<year>-5m.parquet
    window_start_ms, outcome, volume, offsets (s since start), prices (Up)

The parsing and the store are pure; the downloader at the bottom runs on its
own asyncio loop and reports through Qt signals, like `CandleDownloader`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PySide6.QtCore import QObject, Signal

from bi_trading.data import candles
from bi_trading.data.polymarket_data import (
    SLUG_PREFIX,
    WINDOW_MS,
    WINDOW_SECONDS,
    parse_market,
    resolved_side,
)
from bi_trading.venues.runner import AsyncRunner

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com/prices-history"

UP, DOWN, UNKNOWN, NOT_FOUND = 1, 0, -1, -2

# The first five-minute market found on Gamma (probed 2026-11): the search for
# older ones stops here. Earlier windows come back empty and are not stored.
HISTORY_START_MS = 1_770_854_400_000  # 2026-02-12T00:00Z, a window boundary

GAMMA_BATCH = 40          # slugs per Gamma call (a multi-slug query works)
CONCURRENCY = 4           # history calls in flight
PAUSE_S = 0.1
MAX_RETRIES = 5
FLUSH_ROWS = 2_000


def history_file(year: int) -> Path:
    return candles.candles_dir() / f"PM-{year}-5m.parquet"


def window_slug(start_ms: int) -> str:
    return f"{SLUG_PREFIX}-{start_ms // 1000}"


def window_starts(first_ms: int, last_ms: int) -> list[int]:
    """Every window start in [first_ms, last_ms], aligned to five minutes."""
    first = -(-first_ms // WINDOW_MS) * WINDOW_MS
    return list(range(first, last_ms + 1, WINDOW_MS))


# -- parsing ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowRow:
    start_ms: int
    outcome: int
    volume: float
    offsets: tuple[int, ...]      # seconds after the window start
    prices: tuple[float, ...]     # the Up share's price at each offset


def parse_history(payload: Any, start_ms: int) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """The Up price samples inside the window, as (offsets, prices)."""
    points = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(points, list):
        return (), ()
    start_s = start_ms // 1000
    pairs: list[tuple[int, float]] = []
    for point in points:
        try:
            offset = int(point["t"]) - start_s
            price = float(point["p"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= offset <= WINDOW_SECONDS and 0.0 <= price <= 1.0:
            pairs.append((offset, price))
    pairs.sort()
    return tuple(p[0] for p in pairs), tuple(p[1] for p in pairs)


def outcome_code(payload: Any) -> int:
    side = resolved_side(payload)
    return UP if side == "up" else DOWN if side == "down" else UNKNOWN


def up_token(payload: dict) -> str | None:
    """The Up share's CLOB token id from a Gamma market."""
    market = parse_market(payload)
    if market is None or not market.outcomes:
        return None
    for outcome in market.outcomes:
        if outcome.name.strip().lower() == "up":
            return outcome.token_id
    return market.outcomes[0].token_id


# -- the store ----------------------------------------------------------------

_SCHEMA = None


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        pa, _ = candles._arrow()
        _SCHEMA = pa.schema(
            [
                ("window_start_ms", pa.int64()),
                ("outcome", pa.int8()),
                ("volume", pa.float64()),
                ("offsets", pa.list_(pa.int16())),
                ("prices", pa.list_(pa.float32())),
            ]
        )
    return _SCHEMA


def append_rows(path: Path, rows: Sequence[WindowRow]) -> int:
    """Fold rows into a year's file (Parquet has no append), newest wins."""
    if not rows:
        return 0
    candles.ensure_data_dir()
    pa, pq = candles._arrow()
    fresh = pa.table(
        {
            "window_start_ms": pa.array([r.start_ms for r in rows], pa.int64()),
            "outcome": pa.array([r.outcome for r in rows], pa.int8()),
            "volume": pa.array([r.volume for r in rows], pa.float64()),
            "offsets": pa.array([list(r.offsets) for r in rows], pa.list_(pa.int16())),
            "prices": pa.array([list(r.prices) for r in rows], pa.list_(pa.float32())),
        },
        schema=_schema(),
    )
    existing = read_table(path)
    combined = fresh if existing is None else pa.concat_tables([existing, fresh])
    # A window fetched again replaces its old row.
    starts = combined.column("window_start_ms").to_numpy(zero_copy_only=False)
    order = np.argsort(starts, kind="stable")
    keep: dict[int, int] = {}
    for position in order:
        keep[int(starts[position])] = int(position)
    indices = sorted(keep.values(), key=lambda i: starts[i])
    combined = combined.take(pa.array(indices, pa.int64()))
    candles._write_table(path, combined)
    return len(rows)


def read_table(path: Path) -> Any | None:
    pa, pq = candles._arrow()
    try:
        return pq.read_table(path)
    except (OSError, pa.ArrowInvalid):
        return None


def known_starts(path: Path) -> set[int]:
    data = read_table(path)
    if data is None:
        return set()
    return {int(v) for v in data.column("window_start_ms").to_numpy(zero_copy_only=False)}


def load_rows(first_ms: int, last_ms: int) -> list[WindowRow]:
    """Stored windows whose start is in [first_ms, last_ms], oldest first."""
    rows: list[WindowRow] = []
    first_year = datetime.fromtimestamp(first_ms / 1000, UTC).year
    last_year = datetime.fromtimestamp(last_ms / 1000, UTC).year
    for year in range(first_year, last_year + 1):
        data = read_table(history_file(year))
        if data is None:
            continue
        starts = data.column("window_start_ms").to_pylist()
        outcomes = data.column("outcome").to_pylist()
        volumes = data.column("volume").to_pylist()
        offsets = data.column("offsets").to_pylist()
        prices = data.column("prices").to_pylist()
        for i, start in enumerate(starts):
            if first_ms <= start <= last_ms:
                rows.append(
                    WindowRow(
                        start, outcomes[i], volumes[i],
                        tuple(offsets[i] or ()), tuple(float(p) for p in prices[i] or ()),
                    )
                )
    return rows


def coverage() -> tuple[int, int, int]:
    """(windows with prices, windows not found, newest window start) on disk."""
    have = missing = 0
    newest = 0
    for path in sorted(candles.candles_dir().glob("PM-*-5m.parquet")):
        data = read_table(path)
        if data is None:
            continue
        outcomes = data.column("outcome").to_numpy(zero_copy_only=False)
        starts = data.column("window_start_ms").to_numpy(zero_copy_only=False)
        missing += int((outcomes == NOT_FOUND).sum())
        have += int((outcomes != NOT_FOUND).sum())
        if len(starts):
            newest = max(newest, int(starts.max()))
    return have, missing, newest


# -- fetching -----------------------------------------------------------------


async def _get(client: httpx.AsyncClient, url: str, params: Any) -> Any:
    for _ in range(MAX_RETRIES):
        response = await client.get(url, params=params)
        if response.status_code in (429, 503):
            wait = float(response.headers.get("Retry-After", "3"))
            await asyncio.sleep(min(wait, 30.0))
            continue
        if response.status_code == 400:
            return None
        response.raise_for_status()
        return response.json()
    raise RuntimeError("polymarket kept rate limiting")


async def fetch_windows(client: httpx.AsyncClient, starts: Sequence[int]) -> list[WindowRow]:
    """One batch: Gamma for the markets, then CLOB for each Up token's prices."""
    params = [("closed", "true"), ("limit", str(len(starts)))]
    params += [("slug", window_slug(s)) for s in starts]
    markets = await _get(client, GAMMA, params)
    by_slug = {m.get("slug"): m for m in markets or [] if isinstance(m, dict)}
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(start: int) -> WindowRow:
        market = by_slug.get(window_slug(start))
        token = up_token(market) if market else None
        if market is None or token is None:
            return WindowRow(start, NOT_FOUND, 0.0, (), ())
        async with gate:
            history = await _get(
                client,
                CLOB,
                {
                    "market": token,
                    "startTs": start // 1000,
                    "endTs": start // 1000 + WINDOW_SECONDS,
                    "fidelity": 1,
                },
            )
            await asyncio.sleep(PAUSE_S)
        offsets, prices = parse_history(history, start)
        try:
            volume = float(market.get("volume") or 0.0)
        except (TypeError, ValueError):
            volume = 0.0
        return WindowRow(start, outcome_code(market), volume, offsets, prices)

    return list(await asyncio.gather(*(one(s) for s in starts)))


class PolymarketHistoryDownloader(QObject):
    """Fetch every missing window since `HISTORY_START_MS`, resumable."""

    progressed = Signal(int, int)  # windows done, windows to do
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("polymarket-history")
        self._busy = False
        self._stop = False

    def busy(self) -> bool:
        return self._busy

    def cancel(self) -> None:
        self._stop = True

    def start(self, first_ms: int = HISTORY_START_MS, last_ms: int | None = None) -> bool:
        if self._busy:
            return False
        self._busy = True
        self._stop = False
        self._runner.submit(self._run(first_ms, last_ms))
        return True

    async def _run(self, first_ms: int, last_ms: int | None) -> None:
        try:
            # Only windows that have settled: the last full one is two back.
            newest = int(time.time() * 1000) // WINDOW_MS * WINDOW_MS - 2 * WINDOW_MS
            last = newest if last_ms is None else min(last_ms, newest)
            todo = self.missing(first_ms, last)
            done = 0
            pending: dict[Path, list[WindowRow]] = {}
            async with httpx.AsyncClient(timeout=30.0) as client:
                for at in range(0, len(todo), GAMMA_BATCH):
                    if self._stop:
                        break
                    rows = await fetch_windows(client, todo[at : at + GAMMA_BATCH])
                    for row in rows:
                        year = datetime.fromtimestamp(row.start_ms / 1000, UTC).year
                        pending.setdefault(history_file(year), []).append(row)
                    done += len(rows)
                    if sum(len(v) for v in pending.values()) >= FLUSH_ROWS:
                        self._flush(pending)
                    self.progressed.emit(done, len(todo))
            self._flush(pending)
            self.finished.emit()
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            log.warning("polymarket history stopped: %s", exc)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._busy = False

    @staticmethod
    def _flush(pending: dict[Path, list[WindowRow]]) -> None:
        for path, rows in pending.items():
            append_rows(path, rows)
        pending.clear()

    @staticmethod
    def missing(first_ms: int, last_ms: int) -> list[int]:
        """Windows in the span that are not on disk yet."""
        wanted = window_starts(first_ms, last_ms)
        have: set[int] = set()
        for year in {datetime.fromtimestamp(s / 1000, UTC).year for s in wanted}:
            have |= known_starts(history_file(year))
        return [s for s in wanted if s not in have]


__all__ = [
    "DOWN", "NOT_FOUND", "UNKNOWN", "UP", "HISTORY_START_MS",
    "PolymarketHistoryDownloader", "WindowRow", "coverage", "fetch_windows",
    "history_file", "load_rows", "parse_history", "window_slug",
]
