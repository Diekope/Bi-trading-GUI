"""Fetch BTC one-minute candles from Binance into the local store.

Only BTC, and only 1m: the finest bars are the ones worth keeping, because a
5m or 1h series can be compacted from them later without another round trip.
A year is fetched in pages of a thousand bars, resuming from the last row
already on disk, and every page is appended as it arrives so an interrupted
download keeps what it got.

Network work runs on its own asyncio loop; results come back as Qt signals.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from PySide6.QtCore import QObject, Signal

from lalala.data.candles import (
    MINUTE_MS,
    _stamp,
    append_rows,
    candle_file,
    last_timestamp,
    row_count,
)
from lalala.venues.runner import AsyncRunner

log = logging.getLogger(__name__)

API = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
LIMIT = 1000

# klines at limit=1000 weighs 5 against Binance's 6000/min budget, so a
# quarter second between calls stays well inside it.
PAUSE_S = 0.25
MAX_RETRIES = 5

# Parquet has no append, so a page is buffered and the year is rewritten every
# so many rows. A crash then loses at most this many, and the file is not
# rewritten once per page.
FLUSH_ROWS = 50_000


class CandleDownloader(QObject):
    """One download at a time, live on its own asyncio loop."""

    progressed = Signal(int, int)  # year, rows now on disk for it
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("candles")
        self._busy = False

    def busy(self) -> bool:
        return self._busy

    def start(self, years: list[int]) -> bool:
        """Begin fetching the given years. False when one is already running."""
        if self._busy or not years:
            return False
        self._busy = True
        self._runner.submit(self._run(years))
        return True

    # -- asyncio side ------------------------------------------------------

    async def _run(self, years: list[int]) -> None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                for year in years:
                    await self._fetch_year(client, year)
            self.finished.emit()
        except Exception as exc:  # network, parse, rate limit: all the same
            log.warning("candle download stopped: %s", exc)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._busy = False

    async def _fetch_year(self, client: httpx.AsyncClient, year: int) -> None:
        path = candle_file(year)
        start = _stamp(year, 1, 1)
        end = min(_stamp(year + 1, 1, 1) - 1, _now_ms())

        cursor = start
        resume = last_timestamp(path)
        if resume is not None and resume >= start:
            cursor = resume + MINUTE_MS

        total = row_count(path)
        pending: list[tuple] = []
        while cursor <= end:
            batch = await self._klines(client, cursor, end)
            rows = [row for row in (_clean(k) for k in batch) if row is not None]
            if not rows:
                break
            pending.extend(rows)
            cursor = rows[-1][0] + MINUTE_MS
            if len(pending) >= FLUSH_ROWS:
                total = row_count(path) + append_rows(path, pending)
                pending = []
            self.progressed.emit(year, total + len(pending))
            await asyncio.sleep(PAUSE_S)
        if pending:
            total = row_count(path) + append_rows(path, pending)
            self.progressed.emit(year, total)

    async def _klines(
        self, client: httpx.AsyncClient, start_ms: int, end_ms: int
    ) -> list[list]:
        params = {
            "symbol": SYMBOL,
            "interval": "1m",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": LIMIT,
        }
        for _ in range(MAX_RETRIES):
            response = await client.get(API, params=params)
            if response.status_code in (429, 418):
                wait = float(response.headers.get("Retry-After", "5"))
                await asyncio.sleep(min(wait, 30.0))
                continue
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else []
        raise RuntimeError("binance kept rate limiting")


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _clean(raw: list) -> tuple[int, float, float, float, float, float] | None:
    """One kline as an OHLCV row, dropping a bar that has not closed yet."""
    if not isinstance(raw, list) or len(raw) < 6:
        return None
    try:
        stamp = int(raw[0])
        open_, high, low, close, volume = (float(value) for value in raw[1:6])
    except (TypeError, ValueError):
        return None
    if stamp + MINUTE_MS > _now_ms():
        return None
    return stamp, open_, high, low, close, volume
