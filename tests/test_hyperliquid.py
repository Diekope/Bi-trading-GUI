"""Hyperliquid orders: fill-or-cancel entries, the fill read from the answer, and a
one-click close that reads the position from the venue. No network: the SDK's
exchange and info objects are replaced."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from bi_trading.state import orders  # noqa: E402
from bi_trading.venues.base import Instrument, OrderRequest, VenueError  # noqa: E402
from bi_trading.venues.hyperliquid import HyperliquidVenue, _ack  # noqa: E402

BTC = Instrument(venue="hyperliquid", symbol="BTC", tick=0.1, size_step=0.00001)


def _answer(status: dict) -> dict:
    return {"status": "ok", "response": {"type": "order", "data": {"statuses": [status]}}}


FILLED = _answer({"filled": {"totalSz": "0.002", "avgPx": "75600.5", "oid": 77}})
RESTING = _answer({"resting": {"oid": 12}})
NO_MATCH = _answer({"error": "Order could not immediately match against any resting orders."})


class FakeExchange:
    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.sent: list[dict] = []
        self.prices: list[tuple] = []
        self.leverage: list[tuple] = []

    def update_leverage(self, leverage, name, is_cross=True):
        self.leverage.append((leverage, name, is_cross))
        return {"status": "ok"}

    def order(self, name, is_buy, sz, limit_px, order_type, reduce_only=False):
        self.sent.append(dict(name=name, is_buy=is_buy, sz=sz, limit_px=limit_px,
                              order_type=order_type, reduce_only=reduce_only))
        return self.answer

    def _slippage_price(self, name, is_buy, slippage, px=None):
        self.prices.append((name, is_buy, slippage, px))
        return round((px or 75_000.0) * ((1 + slippage) if is_buy else (1 - slippage)), 1)


class FakeInfo:
    def __init__(self, size: float | None) -> None:
        self.size = size

    def user_state(self, address):
        positions = [] if self.size is None else [
            {"position": {"coin": "ETH", "szi": "9"}},
            {"position": {"coin": "BTC", "szi": str(self.size)}},
        ]
        return {"assetPositions": positions}


def _venue(answer=FILLED, size: float | None = None) -> HyperliquidVenue:
    venue = HyperliquidVenue(private_key="0x" + "ab" * 32, account_address="0x" + "cd" * 20)

    async def connected() -> None:
        return None

    venue.connect = connected            # type: ignore[method-assign]
    venue._exchange = FakeExchange(answer)
    venue._info = FakeInfo(size)
    return venue


def _order(**kw) -> OrderRequest:
    return OrderRequest(instrument=BTC, side="buy", price=75_700.0, size=0.002, **kw)


# -- the answer ----------------------------------------------------------------


def test_a_fill_carries_its_size_and_average_price() -> None:
    ack = _ack(FILLED, _order(market=True))
    assert ack.accepted and ack.venue_order_id == "77"
    assert (ack.shares, ack.dollars) == (0.002, pytest.approx(151.201))
    assert ack.detail == "filled · 0.002 BTC @ 75,600.5"


def test_a_resting_order_and_a_refusal_are_told_apart() -> None:
    resting = _ack(RESTING, _order())
    assert resting.accepted and resting.detail == "resting" and resting.shares == 0
    refused = _ack(NO_MATCH, _order(market=True))
    assert not refused.accepted and "could not immediately match" in refused.reason
    # `status: ok` alone is not enough: a bad request is a refusal too.
    assert not _ack({"status": "err", "response": "bad nonce"}, _order()).accepted


# -- submitting ------------------------------------------------------------------


def test_a_market_order_is_fill_or_cancel_and_a_plain_one_rests() -> None:
    venue = _venue()
    fast = asyncio.run(venue.submit(_order(market=True)))
    rest = asyncio.run(venue.submit(_order()))

    sent = venue._exchange.sent
    assert sent[0]["order_type"] == {"limit": {"tif": "Ioc"}}
    assert sent[1]["order_type"] == {"limit": {"tif": "Gtc"}}
    assert sent[0]["limit_px"] == 75_700.0 and sent[0]["sz"] == 0.002
    assert fast.shares == 0.002 and rest.shares == 0.002     # FILLED answered both


def test_an_ioc_that_finds_nothing_says_so() -> None:
    ack = asyncio.run(_venue(NO_MATCH).submit(_order(market=True)))
    assert not ack.accepted and "could not immediately match" in ack.reason


# -- closing -----------------------------------------------------------------------


def test_a_close_reads_the_position_and_sends_the_opposite_reduce_only() -> None:
    venue = _venue(size=0.013)                                 # a long: close by selling
    ack, sent = asyncio.run(venue.close_position(BTC, price=75_000.0, slippage=0.01))

    (order,) = venue._exchange.sent
    assert order["is_buy"] is False and order["sz"] == 0.013 and order["reduce_only"] is True
    assert order["order_type"] == {"limit": {"tif": "Ioc"}}
    assert order["limit_px"] == pytest.approx(74_250.0)        # 1% through the live price
    assert venue._exchange.prices == [("BTC", False, 0.01, 75_000.0)]
    assert sent.reduce_only and sent.market and sent.size == 0.013
    assert ack.accepted


def test_a_short_is_closed_by_buying() -> None:
    venue = _venue(size=-0.5)
    asyncio.run(venue.close_position(BTC, price=75_000.0))
    (order,) = venue._exchange.sent
    assert order["is_buy"] is True and order["sz"] == 0.5 and order["reduce_only"] is True
    assert order["limit_px"] > 75_000.0


def test_closing_with_nothing_open_sends_nothing() -> None:
    for size in (None, 0.0):
        venue = _venue(size=size)
        with pytest.raises(VenueError, match="no open BTC position"):
            asyncio.run(venue.close_position(BTC, price=75_000.0))
        assert venue._exchange.sent == []


def test_the_position_is_read_signed() -> None:
    assert asyncio.run(_venue(size=-0.25).position("BTC")) == -0.25
    assert asyncio.run(_venue(size=None).position("BTC")) == 0.0


# -- through the order service -------------------------------------------------------


class _ServiceVenue:
    def __init__(self, answer=FILLED, size=0.01) -> None:
        self.venue = _venue(answer, size)

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def submit(self, order):
        return await self.venue.submit(order)

    async def close_position(self, instrument, price=None):
        return await self.venue.close_position(instrument, price)


@pytest.fixture
def log(tmp_path, monkeypatch):
    from bi_trading.state import events

    log = events.EventLog(tmp_path / "events.jsonl")
    monkeypatch.setattr(events, "_log", log)
    return log


def test_the_service_closes_and_logs_it(monkeypatch, log) -> None:
    fake = _ServiceVenue()
    monkeypatch.setattr(orders, "get_venue", lambda name, **config: fake)
    svc = orders.OrderService()
    seen: list = []
    svc.placed.connect(lambda venue, text: seen.append(text))
    config = {"private_key": "k"}

    async def run():
        await svc._execute(
            "hyperliquid", config,
            lambda adapter: adapter.close_position(BTC, 75_000.0),
            "Close BTC (whole position)", "manual", "", None,
        )

    try:
        asyncio.run(run())
    finally:
        svc.shutdown()

    kinds = [event.kind for event in log.events()]
    assert kinds == ["FILLED"]
    (event,) = log.events()
    assert "Sell 0.01 BTC" in event.message and "filled" in event.message
    assert "reduce only" in event.detail["request"]            # the details say what was sent
    assert seen and "filled" in seen[0]


def test_a_failed_close_is_logged_under_its_own_label(monkeypatch, log) -> None:
    fake = _ServiceVenue(size=None)                           # nothing to close
    monkeypatch.setattr(orders, "get_venue", lambda name, **config: fake)
    svc = orders.OrderService()
    failed: list = []
    svc.failed.connect(lambda venue, reason: failed.append(reason))

    async def run():
        await svc._execute(
            "hyperliquid", {}, lambda adapter: adapter.close_position(BTC, None),
            "Close BTC (whole position)", "manual", "", None,
        )

    try:
        asyncio.run(run())
    finally:
        svc.shutdown()
    (event,) = log.events()
    assert event.kind == "REJECTED" and event.message.startswith("Close BTC (whole position)")
    assert failed and "no open BTC position" in failed[0]


def test_testnet_orders_are_marked_in_the_log(monkeypatch, log) -> None:
    fake = _ServiceVenue()
    monkeypatch.setattr(orders, "get_venue", lambda name, **config: fake)
    svc = orders.OrderService()
    order = _order(market=True)
    try:
        asyncio.run(svc._place("hyperliquid", order, {"testnet": True}))
        asyncio.run(svc._place("hyperliquid", order, {"testnet": False}))
    finally:
        svc.shutdown()
    first, second = log.events()
    assert first.message.endswith("· testnet") and "network: testnet" in " ".join(first.detail["request"])
    assert "testnet" not in second.message


def test_leverage_is_set_isolated_before_an_opening_order() -> None:
    import asyncio

    venue = _venue()
    asyncio.run(venue.submit(_order(leverage=7)))
    assert venue._exchange.leverage == [(7, "BTC", False)]
    assert len(venue._exchange.sent) == 1


def test_no_leverage_call_without_leverage_or_on_a_reduce_only_order() -> None:
    import asyncio

    venue = _venue()
    asyncio.run(venue.submit(_order()))
    asyncio.run(venue.submit(_order(leverage=7, reduce_only=True)))
    assert venue._exchange.leverage == []
