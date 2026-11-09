"""Placing orders: the service, its config, and the arming gate."""

from __future__ import annotations

import asyncio
import json

import pytest

from lalala import orders
from lalala.accounts import (
    Accounts,
    HL_KEY,
    PM_KEY,
    HyperliquidAccount,
    PolymarketAccount,
    save_accounts,
    set_secret,
)
from lalala.settings import Settings, save_trading_defaults, TradingDefaults
from lalala.venues.base import OrderAck, OrderRequest


@pytest.fixture
def paths(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    secrets = tmp_path / "secrets.json"
    monkeypatch.setenv("LALALA_SETTINGS", str(settings))
    monkeypatch.setenv("LALALA_SECRETS", str(secrets))
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
    assert holder["venue"].connected and holder["venue"].closed
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


class _BalanceVenue:
    def __init__(self, free: float, **config) -> None:
        self.free = free

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def balances(self):
        from lalala.venues.base import Balance

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
