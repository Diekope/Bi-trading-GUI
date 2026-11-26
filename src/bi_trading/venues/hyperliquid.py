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

import logging
import asyncio
from typing import Any
from collections.abc import AsyncIterator

from bi_trading.venues.base import (
    Balance,
    Instrument,
    OrderAck,
    OrderRequest,
    Quote,
    VenueError,
    friendly_message,
)

log = logging.getLogger(__name__)

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
        except (ValueError, TypeError):  # not a private key
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
        except Exception:  # the SDK's own errors, and the network's
            log.warning("could not list the authorized agents", exc_info=True)
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
        """Place an order. With `order.market` it is fill-or-cancel at its limit
        price (`Ioc`): it takes what the book offers up to that price right now and
        never rests, so it either fills or says why it could not. Without it, it is
        a resting limit order (`Gtc`)."""
        await self.connect()
        if self._exchange is None:
            raise VenueError("submit requires private_key and account_address")
        try:
            if order.leverage and not order.reduce_only:
                # Isolated, so the margin is exactly size / leverage as shown.
                await asyncio.to_thread(
                    self._exchange.update_leverage,
                    order.leverage,
                    order.instrument.symbol,
                    False,
                )
            result = await asyncio.to_thread(
                self._exchange.order,
                order.instrument.symbol,
                is_buy=order.side == "buy",
                sz=order.size,
                limit_px=order.price,
                order_type={"limit": {"tif": "Ioc" if order.market else "Gtc"}},
                reduce_only=order.reduce_only,
            )
        except Exception as exc:  # region blocks, rejects, transport
            raise VenueError(friendly_message(exc)) from exc
        return _ack(result, order)

    async def position(self, symbol: str) -> float:
        """The signed size held in `symbol`: positive long, negative short, 0 flat."""
        await self.connect()
        if not self.account_address:
            raise VenueError("a position needs the account address")
        try:
            state = await asyncio.to_thread(self._info.user_state, self.account_address)
        except Exception as exc:
            raise VenueError(friendly_message(exc)) from exc
        for entry in state.get("assetPositions", []):
            item = entry.get("position", {})
            if item.get("coin") == symbol:
                return float(item.get("szi", 0.0))
        return 0.0

    async def close_position(
        self, instrument: Instrument, price: float | None = None, slippage: float = 0.01
    ) -> tuple[OrderAck, OrderRequest]:
        """Close the whole position in `instrument` at once.

        Reads the size from the venue (so it closes exactly what is open, however
        it was opened), then sends the opposite side reduce-only and fill-or-cancel,
        priced `slippage` through `price` (the live mid; the venue's own mid when
        none is given). Returns the ack and the order that was sent.
        """
        size = await self.position(instrument.symbol)
        if abs(size) < 1e-12:
            raise VenueError(f"no open {instrument.symbol} position to close")
        if self._exchange is None:
            raise VenueError("closing requires private_key and account_address")
        buy = size < 0
        try:
            limit = await asyncio.to_thread(
                self._exchange._slippage_price, instrument.symbol, buy, slippage, price
            )
        except Exception as exc:
            raise VenueError(friendly_message(exc)) from exc
        order = OrderRequest(
            instrument=instrument, side="buy" if buy else "sell", price=float(limit),
            size=abs(size), reduce_only=True, market=True,
        )
        return await self.submit(order), order

    async def cancel(self, instrument: Instrument, venue_order_id: str) -> None:
        await self.connect()
        if self._exchange is None:
            raise VenueError("cancel requires private_key and account_address")
        await asyncio.to_thread(
            self._exchange.cancel, instrument.symbol, int(venue_order_id)
        )


def _ack(result: Any, order: OrderRequest) -> OrderAck:
    """The exchange's answer as an `OrderAck`, with the fill when there is one.

    `status: ok` only says the request was well formed; each order inside has its
    own status: `filled` (with the size and the average price), `resting` (on the
    book) or `error`.
    """
    if not isinstance(result, dict) or result.get("status") != "ok":
        return OrderAck("", order.client_id, False, str(result))
    try:
        status = result["response"]["data"]["statuses"][0]
    except (KeyError, IndexError, TypeError):
        return OrderAck("", order.client_id, True)
    if "error" in status:
        return OrderAck("", order.client_id, False, str(status["error"]))
    if "filled" in status:
        filled = status["filled"]
        size = float(filled.get("totalSz", 0.0))
        average = float(filled.get("avgPx", 0.0))
        return OrderAck(
            str(filled.get("oid", "")), order.client_id, True,
            detail=f"filled · {size:g} {order.instrument.symbol} @ {average:,.1f}",
            shares=size, dollars=size * average,
        )
    resting = status.get("resting", {})
    return OrderAck(
        str(resting.get("oid", "")), order.client_id, True, detail="resting"
    )
