"""The Binance 1m fetcher: paging, resuming, and dropping unclosed bars."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from lalala import candles
from lalala.candle_download import CandleDownloader, _clean
from lalala.candles import candle_file, last_timestamp, row_count

JAN_2024_MS = 1_704_067_200_000  # 2024-01-01T00:00Z
MINUTE = 60_000


def now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


class FakeResponse:
    def __init__(self, payload: list) -> None:
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> list:
        return self._payload


class FakeClient:
    """Serves klines from a fixed series, one page of `limit` at a time."""

    def __init__(self, bars: list[tuple]) -> None:
        self.bars = sorted(bars, key=lambda bar: bar[0])
        self.calls: list[dict] = []

    async def get(self, url: str, params: dict) -> FakeResponse:
        self.calls.append(dict(params))
        start = params["startTime"]
        limit = params["limit"]
        page = [bar for bar in self.bars if bar[0] >= start][:limit]
        return FakeResponse([list(bar) for bar in page])


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    monkeypatch.setattr("lalala.candle_download.PAUSE_S", 0)
    candles._ROW_CACHE.clear()


def _bar(stamp: int) -> tuple:
    return (stamp, 1.0, 2.0, 0.5, 1.5, 10.0)


def test_a_year_is_fetched_in_pages_and_appended() -> None:
    bars = [_bar(JAN_2024_MS + i * MINUTE) for i in range(2500)]
    client = FakeClient(bars)

    asyncio.run(CandleDownloader()._fetch_year(client, 2024))

    assert row_count(candle_file(2024)) == 2500
    assert last_timestamp(candle_file(2024)) == JAN_2024_MS + 2499 * MINUTE
    # Three pages of data plus a final empty page that ends the year.
    assert len(client.calls) == 4
    assert client.calls[0]["startTime"] == JAN_2024_MS
    assert client.calls[1]["startTime"] == JAN_2024_MS + 1000 * MINUTE


def test_a_second_pass_resumes_and_adds_nothing() -> None:
    bars = [_bar(JAN_2024_MS + i * MINUTE) for i in range(100)]
    client = FakeClient(bars)
    downloader = CandleDownloader()

    asyncio.run(downloader._fetch_year(client, 2024))
    assert row_count(candle_file(2024)) == 100

    client.calls.clear()
    asyncio.run(downloader._fetch_year(client, 2024))

    # It asks from the row after the last one, gets nothing, and stops.
    assert client.calls[0]["startTime"] == JAN_2024_MS + 100 * MINUTE
    assert row_count(candle_file(2024)) == 100


def test_the_bar_still_forming_is_left_out() -> None:
    this_minute = now_ms() // MINUTE * MINUTE  # its minute has not closed
    assert _clean(list(_bar(this_minute))) is None
    assert _clean(list(_bar(this_minute - MINUTE))) is not None
    # Malformed rows are dropped rather than crashing the download.
    assert _clean(["nope"]) is None
    assert _clean(["1", "x", "y", "z", "w", "v"]) is None


def test_only_btc_is_asked_for() -> None:
    client = FakeClient([_bar(JAN_2024_MS)])
    asyncio.run(CandleDownloader()._fetch_year(client, 2024))

    assert client.calls[0]["symbol"] == "BTCUSDT"
    assert client.calls[0]["interval"] == "1m"
