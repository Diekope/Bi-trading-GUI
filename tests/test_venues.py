"""The Polymarket adapter, against the unified SDK's current shape."""

from __future__ import annotations

import asyncio
import types

import pytest
from PySide6.QtWidgets import QApplication

from lalala.venues.base import Instrument, OrderRequest

polymarket = pytest.importorskip("polymarket")

TOKEN = "123456789"


def _venue_with(client):
    from lalala.venues.polymarket import PolymarketVenue

    venue = PolymarketVenue(
        private_key="0x" + "ab" * 32, funder="0x" + "cd" * 20, signature_type=0
    )

    async def connected() -> None:
        return None

    venue.connect = connected  # type: ignore[method-assign]
    venue._client = client
    return venue


def _order() -> OrderRequest:
    return OrderRequest(
        instrument=Instrument(venue="polymarket", symbol=TOKEN, tick=0.01, size_step=0.01),
        side="buy",
        price=0.5,
        size=2.0,
    )


def test_submit_places_a_limit_order_and_reports_the_id() -> None:
    calls: list[dict] = []

    class FakeClient:
        async def place_limit_order(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(ok=True, order_id="0xabc", status="live")

    ack = asyncio.run(_venue_with(FakeClient()).submit(_order()))

    assert ack.accepted is True
    assert ack.venue_order_id == "0xabc"
    assert calls[0]["token_id"] == TOKEN
    assert calls[0]["side"] == "BUY"
    assert calls[0]["price"] == 0.5


def test_submit_reports_a_rejection() -> None:
    class FakeClient:
        async def place_limit_order(self, **kwargs):
            return types.SimpleNamespace(ok=False, code="unmatched", message="no match")

    ack = asyncio.run(_venue_with(FakeClient()).submit(_order()))

    assert ack.accepted is False
    assert ack.reason == "no match"


def test_submit_wraps_an_sdk_exception() -> None:
    from lalala.venues.base import VenueError

    class FakeClient:
        async def place_limit_order(self, **kwargs):
            raise RuntimeError("boom")

    with pytest.raises(VenueError):
        asyncio.run(_venue_with(FakeClient()).submit(_order()))


def test_submit_turns_a_region_block_into_a_clear_message() -> None:
    from lalala.venues.base import VenueError

    class FakeClient:
        async def place_limit_order(self, **kwargs):
            raise Exception("403 Trading restricted in your region")

    with pytest.raises(VenueError) as info:
        asyncio.run(_venue_with(FakeClient()).submit(_order()))

    assert "region" in str(info.value).lower()
    assert "docs.polymarket.com" in str(info.value)


def test_balances_read_the_collateral_in_usdc() -> None:
    seen: dict = {}

    class FakeClient:
        async def get_balance_allowance(self, *, asset_type):
            seen["asset_type"] = asset_type
            return types.SimpleNamespace(balance=5_000_000, allowances={})

    balances = asyncio.run(_venue_with(FakeClient()).balances())

    assert balances[0].asset == "USDC"
    assert balances[0].free == pytest.approx(5.0)
    assert seen["asset_type"] == "COLLATERAL"


def test_the_client_is_created_with_the_funder(monkeypatch) -> None:
    from lalala.venues.polymarket import PolymarketVenue

    captured: dict = {}

    async def fake_create(*, private_key, wallet=None, api_key=None, **kwargs):
        captured["private_key"] = private_key
        captured["wallet"] = wallet
        captured["api_key"] = api_key
        return types.SimpleNamespace()

    monkeypatch.setattr(
        polymarket.AsyncSecureClient, "create", staticmethod(fake_create)
    )
    venue = PolymarketVenue(
        private_key="0x" + "ab" * 32, funder="0x" + "cd" * 20, signature_type=0
    )

    asyncio.run(venue.connect())

    assert captured["wallet"] == "0x" + "cd" * 20
    assert captured["private_key"].startswith("0x")
    assert captured["api_key"] is None


def test_the_client_is_created_with_the_builder_key(monkeypatch) -> None:
    from lalala.venues.polymarket import PolymarketVenue

    captured: dict = {}

    async def fake_create(*, private_key, wallet=None, api_key=None, **kwargs):
        captured["api_key"] = api_key
        return types.SimpleNamespace()

    monkeypatch.setattr(
        polymarket.AsyncSecureClient, "create", staticmethod(fake_create)
    )
    venue = PolymarketVenue(
        private_key="0x" + "ab" * 32,
        funder="",
        builder={"key": "k", "secret": "s", "passphrase": "p"},
    )

    asyncio.run(venue.connect())

    assert captured["api_key"] == polymarket.BuilderApiKey("k", "s", "p")


def test_minting_a_builder_key_reports_it(monkeypatch) -> None:
    from lalala.ui.hub.settings_widgets import _ConnectionTester

    class FakeClient:
        async def create_builder_api_key(self):
            return types.SimpleNamespace(key="bk", secret="bs", passphrase="bp")

        async def close(self):
            return None

    async def fake_create(*, private_key, wallet=None, api_key=None, **kwargs):
        return FakeClient()

    monkeypatch.setattr(
        polymarket.AsyncSecureClient, "create", staticmethod(fake_create)
    )
    QApplication.instance() or QApplication([])
    tester = _ConnectionTester()
    seen: list[tuple] = []
    tester.builder_ready.connect(lambda k, s, p: seen.append((k, s, p)))
    try:
        asyncio.run(tester._mint_builder_key({"private_key": "0x" + "ab" * 32}))
    finally:
        tester.shutdown()

    assert seen == [("bk", "bs", "bp")]
