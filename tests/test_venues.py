"""The Polymarket adapter, against the unified SDK's current shape."""

from __future__ import annotations

import asyncio
import types

import pytest
from PySide6.QtWidgets import QApplication

from bi_trading.venues.base import Instrument, OrderRequest

polymarket = pytest.importorskip("polymarket")

TOKEN = "123456789"


def _venue_with(client):
    from bi_trading.venues.polymarket import PolymarketVenue

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
    from bi_trading.venues.base import VenueError

    class FakeClient:
        async def place_limit_order(self, **kwargs):
            raise RuntimeError("boom")

    with pytest.raises(VenueError):
        asyncio.run(_venue_with(FakeClient()).submit(_order()))


def test_submit_turns_a_region_block_into_a_clear_message() -> None:
    from bi_trading.venues.base import VenueError

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
    from bi_trading.venues.polymarket import PolymarketVenue

    captured: dict = {}

    async def fake_create(*, private_key, wallet=None, api_key=None, **kwargs):
        captured["private_key"] = private_key
        captured["wallet"] = wallet
        captured["api_key"] = api_key
        return types.SimpleNamespace()

    monkeypatch.setattr(
        polymarket.AsyncSecureClient, "create", staticmethod(fake_create)
    )
    from bi_trading.venues.polymarket import key_wallets

    own = key_wallets("0x" + "ab" * 32)["safe"]  # a wallet this key controls
    venue = PolymarketVenue(private_key="0x" + "ab" * 32, funder=own)

    asyncio.run(venue.connect())

    assert captured["wallet"] == own
    assert captured["private_key"].startswith("0x")
    assert captured["api_key"] is None


def test_the_client_is_created_with_the_builder_key(monkeypatch) -> None:
    from bi_trading.venues.polymarket import PolymarketVenue

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
    from bi_trading.ui.hub.settings_widgets import _ConnectionTester

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


# -- a bet: dollars in, a position out ---------------------------------------


def _bet(notional: float = 2.0, price: float = 0.54) -> OrderRequest:
    return OrderRequest(
        instrument=Instrument(venue="polymarket", symbol=TOKEN, tick=0.01, size_step=0.01),
        side="buy",
        price=price,
        size=0.0,
        notional=notional,
    )


def test_a_bet_spends_dollars_with_a_price_cap_and_kills_the_rest() -> None:
    calls: list[dict] = []

    class FakeClient:
        async def place_market_order(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                ok=True, order_id="0xbet", status="matched",
                making_amount=2.0, taking_amount=3.85,
            )

    ack = asyncio.run(_venue_with(FakeClient()).submit(_bet()))

    assert calls == [
        {"token_id": TOKEN, "side": "BUY", "amount": 2.0, "max_price": 0.54,
         "order_type": "FAK"}
    ]
    assert ack.accepted is True
    assert ack.detail == "matched · 3.85 shares for $2.00"


def test_a_bet_that_finds_nothing_to_buy_says_so_in_words() -> None:
    class FakeClient:
        async def place_market_order(self, **kwargs):
            return types.SimpleNamespace(
                ok=False, code="fak_not_filled",
                message="no orders found to match with FAK order. FAK orders ...",
            )

    ack = asyncio.run(_venue_with(FakeClient()).submit(_bet()))

    assert ack.accepted is False
    assert "book moved" in ack.reason


def test_a_bet_without_the_balance_says_so() -> None:
    class FakeClient:
        async def place_market_order(self, **kwargs):
            return types.SimpleNamespace(
                ok=False, code="not_enough_balance", message="not enough balance"
            )

    ack = asyncio.run(_venue_with(FakeClient()).submit(_bet()))
    assert "Not enough USDC" in ack.reason


def test_a_bet_under_a_dollar_never_leaves_the_machine() -> None:
    from bi_trading.venues.base import VenueError

    class FakeClient:
        async def place_market_order(self, **kwargs):  # pragma: no cover
            raise AssertionError("must not be sent")

    with pytest.raises(VenueError, match=r"smallest bet is \$1"):
        asyncio.run(_venue_with(FakeClient()).submit(_bet(notional=0.5)))


def test_a_limit_order_still_rests_at_its_price() -> None:
    calls: list[dict] = []

    class FakeClient:
        async def place_limit_order(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                ok=True, order_id="0xrest", status="live",
                making_amount=0, taking_amount=0,
            )

    ack = asyncio.run(_venue_with(FakeClient()).submit(_order()))
    assert ack.accepted is True
    assert ack.detail == "live"
    assert calls and "amount" not in calls[0]


def test_the_calls_match_the_installed_sdk() -> None:
    """The fakes above cannot notice the SDK renaming an argument; this can."""
    import inspect

    client = polymarket.AsyncSecureClient
    market = inspect.signature(client.place_market_order).parameters
    limit = inspect.signature(client.place_limit_order).parameters
    create = inspect.signature(client.create).parameters

    for name in ("token_id", "side", "amount", "max_price", "order_type"):
        assert name in market, name
    for name in ("token_id", "price", "size", "side"):
        assert name in limit, name
    for name in ("private_key", "wallet", "api_key"):
        assert name in create, name
    assert "order_id" in inspect.signature(client.cancel_order).parameters
    assert "asset_type" in inspect.signature(client.get_balance_allowance).parameters


# -- a wallet the key does not control ---------------------------------------

KEY = "0x" + "ab" * 32


def test_a_key_lists_the_wallets_it_controls() -> None:
    from bi_trading.venues.polymarket import key_wallets

    wallets = key_wallets(KEY)
    assert set(wallets) == {"key", "deposit", "deposit (older)", "proxy", "safe"}
    assert all(address.startswith("0x") and len(address) == 42 for address in wallets.values())
    assert len(set(wallets.values())) == 5  # five different addresses
    assert KEY not in "".join(wallets.values())  # only public addresses


def test_the_keys_own_wallets_and_a_blank_are_accepted() -> None:
    from bi_trading.venues.polymarket import check_wallet, key_wallets

    check_wallet(KEY, "")
    for address in key_wallets(KEY).values():
        check_wallet(KEY, address)
        check_wallet(KEY, address.lower())  # case does not matter


def test_an_unrelated_wallet_is_refused_with_the_ones_that_would_work() -> None:
    from bi_trading.venues.base import VenueError
    from bi_trading.venues.polymarket import check_wallet, key_wallets

    with pytest.raises(VenueError) as caught:
        check_wallet(KEY, "0x" + "cd" * 20)

    text = str(caught.value)
    assert "is not one this private key controls" in text
    assert key_wallets(KEY)["deposit"] in text
    assert KEY not in text


def test_connecting_with_an_unrelated_wallet_never_reaches_polymarket(monkeypatch) -> None:
    from bi_trading.venues.base import VenueError
    from bi_trading.venues.polymarket import PolymarketVenue

    async def fake_create(**kwargs):  # pragma: no cover
        raise AssertionError("must not be reached")

    monkeypatch.setattr(polymarket.AsyncSecureClient, "create", staticmethod(fake_create))
    venue = PolymarketVenue(private_key=KEY, funder="0x" + "cd" * 20)

    with pytest.raises(VenueError, match="not one this private key controls"):
        asyncio.run(venue.connect())


def test_the_check_is_skipped_when_the_sdk_internals_move(monkeypatch) -> None:
    from bi_trading.venues import polymarket as module

    monkeypatch.setattr(module, "key_wallets", lambda key: None)
    module.check_wallet(KEY, "0x" + "cd" * 20)  # nothing to compare against: allowed


def test_what_polymarket_said_is_kept_when_it_names_a_deposit_wallet() -> None:
    from bi_trading.venues.base import friendly_message

    text = friendly_message(Exception("maker not allowed: use the deposit wallet flow"))
    assert "maker not allowed: use the deposit wallet flow" in text
    assert "blank" in text.lower()


def test_a_sell_takes_the_bids_at_once_with_a_price_floor() -> None:
    calls: list[dict] = []

    class FakeClient:
        async def place_market_order(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                ok=True, order_id="0xsell", status="matched",
                making_amount=4.0, taking_amount=2.1,   # gave 4 shares, got $2.10
            )

    order = OrderRequest(
        instrument=Instrument(venue="polymarket", symbol=TOKEN, tick=0.01, size_step=0.01),
        side="sell", price=0.49, size=4.0, market=True,
    )
    ack = asyncio.run(_venue_with(FakeClient()).submit(order))

    assert calls == [
        {"token_id": TOKEN, "side": "SELL", "shares": 4.0, "min_price": 0.49,
         "order_type": "FAK"}
    ]
    assert (ack.shares, ack.dollars) == (4.0, 2.1)
    assert ack.detail == "matched · 4 shares → $2.10"


def test_a_buy_reports_the_shares_and_dollars_it_got() -> None:
    class FakeClient:
        async def place_market_order(self, **kwargs):
            return types.SimpleNamespace(
                ok=True, order_id="0xbet", status="matched",
                making_amount=2.0, taking_amount=3.85,
            )

    ack = asyncio.run(_venue_with(FakeClient()).submit(_bet()))
    assert (ack.shares, ack.dollars) == (3.85, 2.0)
