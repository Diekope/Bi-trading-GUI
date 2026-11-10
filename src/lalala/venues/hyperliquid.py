"""Hyperliquid adapter.

Transport
    REST  https://api.hyperliquid.xyz
    WS    wss://api.hyperliquid.xyz/ws

SDK     hyperliquid-python-sdk  (uv sync --extra venues)

Auth is a single EVM private key. Reads (`Info`) work unauthenticated; orders
(`Exchange`) are EIP-712 signed by the SDK. Nothing here blocks: every method
is a coroutine meant to run on the asyncio worker thread.
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

REST_URL = "https://api.hyperliquid.xyz"
WS_URL = "wss://api.hyperliquid.xyz/ws"

# Decimals per perp, used to normalise SDK float output. Extend as markets grow.
SIZE_DECIMALS = {"BTC": 5, "ETH": 4, "SOL": 2}


def _require_sdk() -> Any:
    try:
        import hyperliquid  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise VenueError(
            "hyperliquid-python-sdk is not installed: uv sync --extra venues"
        ) from exc
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info

    return Info, Exchange


class HyperliquidVenue:
    name = "hyperliquid"

    def __init__(
        self,
        *,
        private_key: str | None = None,
        account_address: str | None = None,
        testnet: bool = False,
    ) -> None:
        self.private_key = private_key
        self.account_address = account_address
        self.base_url = (
            "https://api.hyperliquid-testnet.xyz" if testnet else REST_URL
        )
        self.ws_url = (
            "wss://api.hyperliquid-testnet.xyz/ws" if testnet else WS_URL
        )
        self._info: Any = None
        self._exchange: Any = None
        self._ws: Any = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        if self._info is not None:
            return
        Info, Exchange = _require_sdk()
        self._info = await asyncio.to_thread(Info, self.base_url, skip_ws=True)
        if self.private_key and self.account_address:
            self._exchange = await asyncio.to_thread(
                Exchange,
                self.private_key,
                self.base_url,
                account_address=self.account_address,
            )

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self._info = None
        self._exchange = None

    # -- reads -------------------------------------------------------------

    async def balances(self) -> list[Balance]:
        await self.connect()
        if not self.account_address:
            return []
        state = await asyncio.to_thread(
            self._info.user_state, self.account_address
        )
        summary = state.get("marginSummary", {})
        return [
            Balance(
                asset="USDC",
                free=float(summary.get("accountValue", 0.0)),
                locked=float(summary.get("totalMarginUsed", 0.0)),
            )
        ]

    async def signer_address(self) -> str | None:
        """The address the private key signs as (an EOA or an API wallet)."""
        if not self.private_key:
            return None
        try:
            from eth_account import Account
        except ModuleNotFoundError:  # noqa: BLE001 - optional extra
            return None
        try:
            return await asyncio.to_thread(
                lambda: Account.from_key(self.private_key).address
            )
        except Exception:
            return None

    async def authorized_agents(self) -> list[str]:
        """API wallets approved to trade this account."""
        await self.connect()
        if not self.account_address:
            return []
        try:
            rows = await asyncio.to_thread(
                self._info.extra_agents, self.account_address
            )
        except Exception:
            return []
        agents: list[str] = []
        for row in rows or []:
            address = row.get("address") if isinstance(row, dict) else row
            if isinstance(address, str):
                agents.append(address)
        return agents

    async def quotes(self, instrument: Instrument) -> AsyncIterator[Quote]:
        """Stream L2 book updates over the public WebSocket."""
        await self.connect()
        import websockets

        async with websockets.connect(self.ws_url) as ws:
            self._ws = ws
            await ws.send(
                {
                    "method": "subscribe",
                    "subscription": {"type": "l2Book", "coin": instrument.symbol},
                }
            )
            async for raw in ws:
                import json

                msg = json.loads(raw)
                if msg.get("channel") != "l2Book":
                    continue
                book = msg["data"]
                bids, asks = book["levels"][0], book["levels"][1]
                if not bids or not asks:
                    continue
                yield Quote(
                    instrument=instrument,
                    bid=float(bids[0]["px"]),
                    ask=float(asks[0]["px"]),
                    bid_size=float(bids[0]["sz"]),
                    ask_size=float(asks[0]["sz"]),
                    ts_ms=int(book["time"]),
                )

    # -- writes ------------------------------------------------------------

    async def submit(self, order: OrderRequest) -> OrderAck:
        await self.connect()
        if self._exchange is None:
            raise VenueError("submit requires private_key and account_address")
        try:
            result = await asyncio.to_thread(
                self._exchange.order,
                order.instrument.symbol,
                is_buy=order.side == "buy",
                sz=order.size,
                limit_px=order.price,
                order_type={"limit": {"tif": "Gtc"}},
                reduce_only=order.reduce_only,
            )
        except Exception as exc:  # region blocks, rejects, transport
            raise VenueError(friendly_message(exc)) from exc
        if result.get("status") != "ok":
            return OrderAck("", order.client_id, False, str(result))
        statuses = result["response"]["data"]["statuses"]
        venue_id = str(statuses[0].get("resting", {}).get("oid", ""))
        return OrderAck(venue_id, order.client_id, True)

    async def cancel(self, instrument: Instrument, venue_order_id: str) -> None:
        await self.connect()
        if self._exchange is None:
            raise VenueError("cancel requires private_key and account_address")
        await asyncio.to_thread(
            self._exchange.cancel, instrument.symbol, int(venue_order_id)
        )
