"""Polymarket adapter (CLOB V2, via the unified `polymarket` SDK).

Transport
    REST  https://clob.polymarket.com

SDK     polymarket-client  (uv sync --extra venues)

Polymarket migrated to **CLOB V2** in April 2026; the legacy `py-clob-client`
(V1) can no longer place orders against production — it is rejected with
"invalid order version". This uses the unified client, `AsyncSecureClient`,
which signs V2 orders.

Instruments here are CLOB token ids (the UP/DOWN outcome token), not tickers.
`funder` is the wallet the funds sit in; it is the wallet the client acts for,
and the SDK infers the wallet type from it (an EOA signs for itself, a proxy
wallet is reached through the deposit/proxy flow).
"""

from __future__ import annotations

from typing import Any

from lalala.venues.base import (
    Balance,
    Instrument,
    OrderAck,
    OrderRequest,
    VenueError,
    friendly_message,
)

REST_URL = "https://clob.polymarket.com"

USDC_DECIMALS = 6


def _require_sdk() -> Any:
    try:
        import polymarket
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise VenueError(
            "polymarket-client is not installed: uv sync --extra venues"
        ) from exc
    return polymarket


class PolymarketVenue:
    name = "polymarket"

    def __init__(
        self,
        *,
        private_key: str | None = None,
        funder: str | None = None,
        signature_type: int = 0,
        host: str = REST_URL,
        builder: dict | None = None,
    ) -> None:
        self.private_key = private_key
        self.funder = funder
        # Kept for the settings model; the unified SDK infers the wallet type
        # from `funder` against the signer, so it is not sent order by order.
        self.signature_type = signature_type
        self.host = host
        # The V2 gasless steps (creating the deposit wallet, approvals) need a
        # Builder API Key; {"key", "secret", "passphrase"}.
        self.builder = builder
        self._client: Any = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        if self._client is not None:
            return
        polymarket = _require_sdk()
        if not self.private_key:
            raise VenueError("connect requires a private key")
        api_key = None
        if self.builder:
            api_key = polymarket.BuilderApiKey(
                self.builder["key"],
                self.builder["secret"],
                self.builder["passphrase"],
            )
        try:
            self._client = await polymarket.AsyncSecureClient.create(
                private_key=self.private_key,
                wallet=self.funder or None,
                api_key=api_key,
            )
        except Exception as exc:  # auth, region, transport: all the same here
            raise VenueError(friendly_message(exc)) from exc

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass

    # -- reads -------------------------------------------------------------

    async def balances(self) -> list[Balance]:
        await self.connect()
        try:
            info = await self._client.get_balance_allowance(
                asset_type="COLLATERAL"
            )
        except Exception as exc:
            raise VenueError(friendly_message(exc)) from exc
        return [Balance(asset="USDC", free=float(info.balance) / 10**USDC_DECIMALS)]

    # -- writes ------------------------------------------------------------

    async def submit(self, order: OrderRequest) -> OrderAck:
        await self.connect()
        side = "BUY" if order.side == "buy" else "SELL"
        try:
            result = await self._client.place_limit_order(
                token_id=order.instrument.symbol,
                price=order.price,
                size=order.size,
                side=side,
            )
        except Exception as exc:  # the SDK raises a wide variety of types
            raise VenueError(friendly_message(exc)) from exc
        if getattr(result, "ok", False):
            return OrderAck(
                venue_order_id=str(getattr(result, "order_id", "")),
                client_id=order.client_id,
                accepted=True,
            )
        return OrderAck(
            venue_order_id="",
            client_id=order.client_id,
            accepted=False,
            reason=getattr(result, "message", None) or "the order was rejected",
        )

    async def cancel(self, instrument: Instrument, venue_order_id: str) -> None:
        await self.connect()
        try:
            await self._client.cancel_order(order_id=venue_order_id)
        except Exception as exc:
            raise VenueError(friendly_message(exc)) from exc


__all__ = ["PolymarketVenue"]
