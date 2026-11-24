from __future__ import annotations

import asyncio
import json

import httpx
import pytest

pytest.importorskip("pyarrow")

from bi_trading.data import polymarket_history as ph  # noqa: E402

START = 1_795_532_400_000  # a window boundary, in ms


def _market(start_ms: int, closed: bool = True, prices=("1", "0")) -> dict:
    return {
        "slug": ph.window_slug(start_ms),
        "closed": closed,
        "outcomes": json.dumps(["Up", "Down"]),
        "outcomePrices": json.dumps(list(prices)),
        "clobTokenIds": json.dumps([f"up{start_ms}", f"down{start_ms}"]),
        "volume": "123.5",
        "endDate": "2026-11-24T00:05:00Z",
    }


def _client(known: set[int]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("gamma"):
            slugs = request.url.params.get_list("slug")
            out = [_market(int(s.rsplit("-", 1)[1]) * 1000) for s in slugs
                   if int(s.rsplit("-", 1)[1]) * 1000 in known]
            return httpx.Response(200, json=out)
        start = int(request.url.params["startTs"])
        pts = [{"t": start + 20, "p": 0.5}, {"t": start + 80, "p": 0.62}, {"t": start + 999, "p": 0.9}]
        return httpx.Response(200, json={"history": pts})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_history_keeps_only_the_window() -> None:
    payload = {"history": [{"t": 1000 + 5, "p": 0.4}, {"t": 1000 + 400, "p": 0.9}, {"t": "x"}]}
    offsets, prices = ph.parse_history(payload, 1_000_000)
    assert offsets == (5,) and prices == (pytest.approx(0.4),)
    assert ph.parse_history(None, 0) == ((), ())


def test_fetch_windows_reads_outcome_prices_and_marks_missing(monkeypatch) -> None:
    monkeypatch.setattr(ph, "PAUSE_S", 0)
    starts = [START, START + 300_000]

    async def go():
        async with _client({START}) as client:
            return await ph.fetch_windows(client, starts)

    first, second = asyncio.run(go())
    assert first.outcome == ph.UP and first.volume == pytest.approx(123.5)
    assert first.offsets == (20, 80) and first.prices[1] == pytest.approx(0.62)
    assert second.outcome == ph.NOT_FOUND and second.prices == ()


def test_store_round_trips_and_a_refetch_replaces(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path))
    path = ph.history_file(2026)
    ph.append_rows(path, [ph.WindowRow(START, ph.UP, 1.0, (20,), (0.5,))])
    ph.append_rows(path, [ph.WindowRow(START, ph.DOWN, 2.0, (30,), (0.4,)),
                          ph.WindowRow(START + 300_000, ph.NOT_FOUND, 0.0, (), ())])
    rows = ph.load_rows(START, START + 600_000)
    assert [r.start_ms for r in rows] == [START, START + 300_000]
    assert rows[0].outcome == ph.DOWN and rows[0].prices == (pytest.approx(0.4),)
    assert ph.coverage()[:2] == (1, 1)
    assert ph.PolymarketHistoryDownloader.missing(START, START + 900_000) == [
        START + 600_000, START + 900_000]
