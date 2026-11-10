"""The Polymarket adapter's submit, against the SDK's current signature."""

from __future__ import annotations

import asyncio

import pytest

from lalala.venues.base import Instrument, OrderRequest

py_clob_client = pytest.importorskip("py_clob_client")

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


def test_submit_passes_one_argument_to_create_and_post_order() -> None:
    # Since py-clob-client 0.3x the second parameter is a PartialCreateOrder
    # options object; passing the order type there made the SDK read
    # `.tick_size` off a string.
    calls: list[tuple] = []

    class FakeClient:
        def create_and_post_order(self, *args):
            calls.append(args)
            return {"success": True, "orderID": "0xabc"}

    ack = asyncio.run(_venue_with(FakeClient()).submit(_order()))

    assert ack.accepted is True
    assert ack.venue_order_id == "0xabc"
    assert len(calls) == 1 and len(calls[0]) == 1


def test_submit_reports_the_sdk_error() -> None:
    class FakeClient:
        def create_and_post_order(self, *args):
            return {"error": "not enough balance"}

    ack = asyncio.run(_venue_with(FakeClient()).submit(_order()))

    assert ack.accepted is False
    assert ack.reason == "not enough balance"


def test_submit_wraps_an_sdk_exception() -> None:
    from lalala.venues.base import VenueError

    class FakeClient:
        def create_and_post_order(self, *args):
            raise RuntimeError("boom")

    with pytest.raises(VenueError):
        asyncio.run(_venue_with(FakeClient()).submit(_order()))


def test_submit_turns_a_region_block_into_a_clear_message() -> None:
    from lalala.venues.base import VenueError

    class FakeClient:
        def create_and_post_order(self, *args):
            raise Exception(
                "PolyApiException[status_code=403, error_message={'error': "
                "'Trading restricted in your region'}]"
            )

    with pytest.raises(VenueError) as info:
        asyncio.run(_venue_with(FakeClient()).submit(_order()))

    assert "region" in str(info.value).lower()
    assert "docs.polymarket.com" in str(info.value)
