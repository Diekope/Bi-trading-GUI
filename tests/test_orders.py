"""Placing orders: the service, its config, and the arming gate."""

from __future__ import annotations

import asyncio
import json

import pytest

from bi_trading.state import orders
from bi_trading.state.accounts import (
    Accounts,
    HL_KEY,
    PM_KEY,
    HyperliquidAccount,
    PolymarketAccount,
    save_accounts,
    set_secret,
)
from bi_trading.state.settings import Settings, save_trading_defaults, TradingDefaults
from bi_trading.venues.base import Instrument, OrderAck, OrderRequest


@pytest.fixture
def paths(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    secrets = tmp_path / "secrets.json"
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(settings))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(secrets))
    return settings, secrets


def _connect_hyperliquid() -> None:
    set_secret(HL_KEY, "0x" + "ab" * 32)
    save_accounts(
        Accounts(hyperliquid=HyperliquidAccount(address="0x" + "cd" * 20))
    )


def test_config_is_none_until_an_account_is_saved(paths) -> None:
    assert orders.config_for("hyperliquid") is None
    assert orders.config_for("polymarket") is None


def test_config_reads_the_saved_account(paths) -> None:
    _connect_hyperliquid()

    config = orders.config_for("hyperliquid")

    assert config is not None
    assert config["account_address"] == "0x" + "cd" * 20
    assert config["private_key"].startswith("0x")
    assert config["testnet"] is False


def test_live_orders_are_off_until_armed(paths) -> None:
    _connect_hyperliquid()

    assert orders.armed() is False
    assert orders.can_trade("hyperliquid") is False

    save_trading_defaults(TradingDefaults(live_orders=True))

    assert orders.armed() is True
    assert orders.can_trade("hyperliquid") is True


def test_can_trade_needs_both_a_connection_and_the_arm(paths) -> None:
    save_trading_defaults(TradingDefaults(live_orders=True))
    assert orders.can_trade("hyperliquid") is False  # armed, but not connected

    _connect_hyperliquid()
    save_trading_defaults(TradingDefaults(live_orders=False))
    assert orders.can_trade("hyperliquid") is False  # connected, not armed


class _FakeVenue:
    """A stand-in adapter: records what it was asked to do, returns a canned ack."""

    def __init__(self, ack: OrderAck, **config) -> None:
        self.ack = ack
        self.config = config
        self.connected = False
        self.closed = False
        self.placed: list[OrderRequest] = []

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def submit(self, order: OrderRequest) -> OrderAck:
        self.placed.append(order)
        return self.ack


def _service(monkeypatch, ack: OrderAck):
    holder = {}

    def build(name, **config):
        venue = _FakeVenue(ack, **config)
        holder["venue"] = venue
        return venue

    monkeypatch.setattr(orders, "get_venue", build)
    svc = orders.OrderService()
    return svc, holder


def test_the_service_places_and_reports(monkeypatch) -> None:
    svc, holder = _service(monkeypatch, OrderAck("oid-1", accepted=True))
    seen: list[tuple[str, str]] = []
    svc.placed.connect(lambda venue, text: seen.append((venue, text)))
    order = OrderRequest(instrument=orders.HL_BTC, side="buy", price=100.0, size=2.0)

    try:
        asyncio.run(svc._place("hyperliquid", order, {}))
    finally:
        svc.shutdown()

    assert seen and seen[0][0] == "hyperliquid"
    assert "Buy" in seen[0][1]
    assert holder["venue"].connected and holder["venue"].closed  # signed out at shutdown, not after the order
    assert holder["venue"].placed == [order]


def test_the_service_reports_a_rejection(monkeypatch) -> None:
    svc, _ = _service(monkeypatch, OrderAck("", accepted=False, reason="no funds"))
    failed: list[tuple[str, str]] = []
    svc.failed.connect(lambda venue, text: failed.append((venue, text)))
    order = OrderRequest(instrument=orders.HL_BTC, side="sell", price=100.0, size=1.0)

    try:
        asyncio.run(svc._place("hyperliquid", order, {}))
    finally:
        svc.shutdown()

    assert failed == [("hyperliquid", "no funds")]


def test_the_service_reports_a_transport_error(monkeypatch) -> None:
    def boom(name, **config):
        raise RuntimeError("no sdk")

    monkeypatch.setattr(orders, "get_venue", boom)
    svc = orders.OrderService()
    failed: list[tuple[str, str]] = []
    svc.failed.connect(lambda venue, text: failed.append((venue, text)))
    order = OrderRequest(instrument=orders.HL_BTC, side="buy", price=1.0, size=1.0)

    try:
        asyncio.run(svc._place("hyperliquid", order, {}))
    finally:
        svc.shutdown()

    assert failed and failed[0][0] == "hyperliquid"
    assert "RuntimeError" in failed[0][1]


def test_the_polymarket_config_uses_the_signature_type(paths) -> None:
    set_secret(PM_KEY, "0x" + "ef" * 32)
    save_accounts(
        Accounts(
            polymarket=PolymarketAccount(
                address="0x" + "11" * 20, signature_type=2
            )
        )
    )

    config = orders.config_for("polymarket")

    assert config is not None
    assert config["funder"] == "0x" + "11" * 20
    assert config["signature_type"] == 2


def test_a_live_orders_flag_round_trips_through_settings(paths) -> None:
    save_trading_defaults(TradingDefaults(live_orders=True))
    assert Settings.load().trading.live_orders is True

    raw = json.loads(paths[0].read_text())
    assert raw["trading"]["live_orders"] is True


def test_a_region_block_reads_plainly() -> None:
    from bi_trading.venues.base import friendly_message

    text = friendly_message(
        Exception(
            "PolyApiException[status_code=403, error_message={'error': "
            "'Trading restricted in your region, please refer to available regions'}]"
        )
    )

    assert "region" in text.lower()
    assert "docs.polymarket.com" in text


def test_a_plain_error_passes_through() -> None:
    from bi_trading.venues.base import friendly_message

    assert friendly_message(ValueError("boom")) == "boom"


def test_a_stale_clob_client_reads_plainly() -> None:
    from bi_trading.venues.base import friendly_message

    text = friendly_message(
        Exception(
            "PolyApiException[status_code=400, error_message={'error': "
            "'invalid order version, please use the latest clob-client'}]"
        )
    )

    assert "out of date" in text.lower()
    assert "clob v2" in text.lower()


def test_a_deposit_wallet_mismatch_reads_plainly() -> None:
    from bi_trading.venues.base import friendly_message

    text = friendly_message(
        Exception(
            "Wallet 0x8c40… does not match the expected Deposit Wallet "
            "0xa17F… for this signer, nor a deployed wallet address"
        )
    )

    assert "deposit wallet" in text.lower()
    assert "blank" in text.lower()


def test_the_polymarket_config_carries_the_builder_key(paths) -> None:
    from bi_trading.state.accounts import (
        PM_BUILDER_KEY,
        PM_BUILDER_PASSPHRASE,
        PM_BUILDER_SECRET,
    )

    set_secret(PM_KEY, "0x" + "ab" * 32)
    assert orders.config_for("polymarket")["builder"] is None

    set_secret(PM_BUILDER_KEY, "bk")
    set_secret(PM_BUILDER_SECRET, "bs")
    set_secret(PM_BUILDER_PASSPHRASE, "bp")

    assert orders.config_for("polymarket")["builder"] == {
        "key": "bk",
        "secret": "bs",
        "passphrase": "bp",
    }


class _BalanceVenue:
    def __init__(self, free: float, **config) -> None:
        self.free = free

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def balances(self):
        from bi_trading.venues.base import Balance

        return [Balance(asset="USDC", free=self.free)]


def test_the_service_reports_a_balance(monkeypatch) -> None:
    monkeypatch.setattr(orders, "get_venue", lambda name, **kw: _BalanceVenue(42.5))
    svc = orders.OrderService()
    seen: list[tuple[str, float]] = []
    svc.balance_ready.connect(lambda venue, free: seen.append((venue, free)))

    try:
        asyncio.run(svc._fetch_balance("hyperliquid", {}))
    finally:
        svc.shutdown()

    assert seen == [("hyperliquid", 42.5)]


def test_a_balance_request_needs_a_connection(paths) -> None:
    svc = orders.OrderService()
    failed: list[tuple[str, str]] = []
    svc.balance_failed.connect(lambda venue, reason: failed.append((venue, reason)))

    try:
        svc.request_balance("hyperliquid")
    finally:
        svc.shutdown()

    assert failed == [("hyperliquid", "not connected")]


def test_a_bet_is_summarised_in_dollars_and_what_it_got(monkeypatch) -> None:
    ack = OrderAck("oid", accepted=True, detail="matched · 3.85 shares for $2.00")
    svc, _ = _service(monkeypatch, ack)
    seen: list[str] = []
    svc.placed.connect(lambda venue, text: seen.append(text))
    order = OrderRequest(
        instrument=orders.HL_BTC, side="buy", price=0.54, size=0.0, notional=2.0
    )

    try:
        asyncio.run(svc._place("polymarket", order, {}))
    finally:
        svc.shutdown()

    assert seen == ["Buy $2.00 · matched · 3.85 shares for $2.00"]


def test_a_failed_order_is_kept_in_the_log(monkeypatch, caplog) -> None:
    import logging

    def boom(name, **config):
        raise RuntimeError("the wallet does not exist")

    monkeypatch.setattr(orders, "get_venue", boom)
    svc = orders.OrderService()
    order = OrderRequest(instrument=orders.HL_BTC, side="buy", price=1.0, size=1.0)

    try:
        with caplog.at_level(logging.WARNING, logger="bi_trading.state.orders"):
            asyncio.run(svc._place("polymarket", order, {}))
    finally:
        svc.shutdown()

    assert any("the wallet does not exist" in record.getMessage() for record in caplog.records)


class _CountingVenue:
    built = 0

    def __init__(self) -> None:
        type(self).built += 1
        self.closed = False

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    async def submit(self, order):
        return OrderAck("oid", accepted=True, detail="matched · 2 shares for $1.00",
                        shares=2.0, dollars=1.0)

    async def balances(self):
        return []


def test_orders_reuse_one_signed_in_client(monkeypatch) -> None:
    _CountingVenue.built = 0
    monkeypatch.setattr(orders, "get_venue", lambda name, **kw: _CountingVenue())
    svc = orders.OrderService()
    order = OrderRequest(
        instrument=orders.HL_BTC, side="buy", price=0.5, size=0.0, notional=1.0
    )

    async def three() -> None:
        for _ in range(3):
            await svc._place("polymarket", order, {"k": 1})

    try:
        asyncio.run(three())
    finally:
        svc.shutdown()

    assert _CountingVenue.built == 1       # not one per order


def test_a_new_account_replaces_the_client(monkeypatch) -> None:
    _CountingVenue.built = 0
    monkeypatch.setattr(orders, "get_venue", lambda name, **kw: _CountingVenue())
    svc = orders.OrderService()

    async def two() -> None:
        first = await svc._adapter("polymarket", {"k": 1})
        await svc._adapter("polymarket", {"k": 1})
        await svc._adapter("polymarket", {"k": 2})
        assert first.closed

    try:
        asyncio.run(two())
    finally:
        svc.shutdown()
    assert _CountingVenue.built == 2


def test_a_failure_rebuilds_the_client_next_time(monkeypatch) -> None:
    _CountingVenue.built = 0
    monkeypatch.setattr(orders, "get_venue", lambda name, **kw: _CountingVenue())
    svc = orders.OrderService()
    order = OrderRequest(
        instrument=orders.HL_BTC, side="buy", price=0.5, size=0.0, notional=1.0
    )

    async def run() -> None:
        await svc._place("polymarket", order, {})
        adapter = svc._adapters["polymarket"][1]

        async def boom(_order):
            raise RuntimeError("socket closed")

        adapter.submit = boom
        await svc._place("polymarket", order, {})
        assert "polymarket" not in svc._adapters and adapter.closed
        await svc._place("polymarket", order, {})

    try:
        asyncio.run(run())
    finally:
        svc.shutdown()
    assert _CountingVenue.built == 2


def test_fills_keep_count_of_the_shares_held(monkeypatch) -> None:
    monkeypatch.setattr(orders, "get_venue", lambda name, **kw: _CountingVenue())
    svc = orders.OrderService()
    filled: list = []
    svc.filled.connect(lambda *args: filled.append(args))
    instrument = Instrument(venue="polymarket", symbol="tok", tick=0.01, size_step=0.01)
    buy = OrderRequest(instrument=instrument, side="buy", price=0.5, size=0.0, notional=1.0)
    sell = OrderRequest(instrument=instrument, side="sell", price=0.4, size=2.0, market=True)

    try:
        asyncio.run(svc._place("polymarket", buy, {}))
        assert svc.held("tok") == 2.0
        asyncio.run(svc._place("polymarket", sell, {}))
        assert svc.held("tok") == 0.0
    finally:
        svc.shutdown()
    assert filled[0] == ("polymarket", "tok", "buy", 2.0, 1.0)
