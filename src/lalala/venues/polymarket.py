"""Polymarket adapter (CLOB).

Transport
    REST  https://clob.polymarket.com
    WS    wss://ws-subscriptions-clob.polymarket.com/ws/market

SDK     py-clob-client  (uv sync --extra venues)

Polymarket signs orders with EIP-712 over secp256k1 and requires L2 API creds
derived from the wallet — this is exactly why the SDK does the work instead of
hand-rolled crypto. `signature_type` is 0 for an EOA, 1 for a Magic/email
proxy wallet, 2 for a browser proxy wallet.

Instruments here are CLOB token ids (the YES/NO outcome token), not tickers.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from lalala.venues.base import (
    Balance,
    Instrument,
    OrderAck,
    OrderRequest,
    Quote,
    VenueError,
    friendly_message,
)

REST_URL = "https://clob.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

POLYGON_CHAIN_ID = 137


def _require_sdk() -> Any:
    try:
        import py_clob_client  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise VenueError(
            "py-clob-client is not installed: uv sync --extra venues"
        ) from exc
    from py_clob_client.client import ClobClient

    return ClobClient


class PolymarketVenue:
    name = "polymarket"

    def __init__(
        self,
        *,
        private_key: str | None = None,
        funder: str | None = None,
        signature_type: int = 0,
        host: str = REST_URL,
    ) -> None:
        self.private_key = private_key
        self.funder = funder
        self.signature_type = signature_type
        self.host = host
        self.ws_url = WS_URL
        self._client: Any = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        if self._client is not None:
            return
        ClobClient = _require_sdk()

        def build() -> Any:
            client = ClobClient(
                self.host,
                key=self.private_key,
                chain_id=POLYGON_CHAIN_ID,
                signature_type=self.signature_type,
                funder=self.funder,
            )
            # Requires no funds, only a wallet capable of signing.
            client.set_api_creds(client.create_or_derive_api_creds())
            return client

        self._client = await asyncio.to_thread(build)

    async def close(self) -> None:
        self._client = None

    # -- reads -------------------------------------------------------------

    async def balances(self) -> list[Balance]:
        await self.connect()
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        def read() -> Any:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            return self._client.get_balance_allowance(params)

        try:
            data = await asyncio.to_thread(read)
        except Exception as exc:  # SDK raises a wide variety of types
            raise VenueError(friendly_message(exc)) from exc
        # The collateral balance comes back in USDC's 6-decimal base units.
        raw = data.get("balance") if isinstance(data, dict) else None
        free = float(raw) / 1e6 if raw is not None else 0.0
        return [Balance(asset="USDC", free=free)]

    async def quotes(self, instrument: Instrument) -> AsyncIterator[Quote]:
        await self.connect()
        import websockets

        async with websockets.connect(self.ws_url) as ws:
            await ws.send(
                {
                    "assets_ids": [instrument.symbol],
                    "type": "market",
                }
            )
            async for raw in ws:
                import json

                msg = json.loads(raw)
                if not isinstance(msg, dict) or msg.get("event_type") != "book":
                    continue
                bids = msg.get("bids") or []
                asks = msg.get("asks") or []
                if not bids or not asks:
                    continue
                # Polymarket sends bids descending and asks ascending.
                best_bid = max(bids, key=lambda lvl: float(lvl["price"]))
                best_ask = min(asks, key=lambda lvl: float(lvl["price"]))
                yield Quote(
                    instrument=instrument,
                    bid=float(best_bid["price"]),
                    ask=float(best_ask["price"]),
                    bid_size=float(best_bid["size"]),
                    ask_size=float(best_ask["size"]),
                    ts_ms=int(msg.get("timestamp", 0)),
                )

    # -- writes ------------------------------------------------------------

    async def submit(self, order: OrderRequest) -> OrderAck:
        await self.connect()
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY, SELL

        args = OrderArgs(
            token_id=order.instrument.symbol,
            price=order.price,
            size=order.size,
            side=BUY if order.side == "buy" else SELL,
        )
        try:
            # The SDK resolves the market's tick size itself (a network read)
            # when no options are given; the 2nd argument is that options
            # object, not the order type, since py-clob-client 0.3x.
            response = await asyncio.to_thread(
                self._client.create_and_post_order, args
            )
        except Exception as exc:  # SDK raises a wide variety of types
            raise VenueError(friendly_message(exc)) from exc
        if not isinstance(response, dict):
            return OrderAck("", order.client_id, False, str(response))
        reason = response.get("errorMsg") or response.get("error")
        return OrderAck(
            venue_order_id=str(response.get("orderID") or response.get("orderId") or ""),
            client_id=order.client_id,
            accepted=bool(response.get("success")) and not reason,
            reason=reason,
        )

    async def cancel(self, instrument: Instrument, venue_order_id: str) -> None:
        await self.connect()
        await asyncio.to_thread(self._client.cancel, venue_order_id)
