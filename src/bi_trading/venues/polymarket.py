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

from bi_trading.venues.base import (
    Balance,
    Instrument,
    OrderAck,
    OrderRequest,
    VenueError,
    friendly_message,
)

REST_URL = "https://clob.polymarket.com"

USDC_DECIMALS = 6

# The smallest marketable buy the CLOB takes, in dollars.
MIN_MARKET_BUY = 1.0

# Why an order was refused, in words, by the SDK's rejection code.
_REJECTIONS = {
    "fak_not_filled": "Nothing is on offer at that price any more — the book moved.",
    "fok_not_filled": "The order could not be filled in full at that price.",
    "not_enough_balance": "Not enough USDC (or allowance) in the wallet for this order.",
    "market_not_ready": "This market is not ready for orders yet.",
    "post_only_mode": "Polymarket is in post-only mode right now.",
}


def _require_sdk() -> Any:
    try:
        import polymarket
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise VenueError(
            "polymarket-client is not installed: uv sync --extra venues"
        ) from exc
    return polymarket


def key_wallets(private_key: str) -> dict[str, str] | None:
    """The addresses a key controls on Polymarket, by kind, or None.

    `{"key": …, "deposit": …, "proxy": …, "safe": …}`, all public addresses
    worked out from the key alone, with no network. It leans on the SDK's
    internals, so if those move this returns None and callers just skip the
    check it feeds.
    """
    try:
        from eth_account import Account
        from polymarket._internal import wallet as w
        from polymarket._internal.environment import get_environment_config
        from polymarket.environments import PRODUCTION

        signer = Account.from_key(private_key).address
        config = get_environment_config(PRODUCTION).wallet_derivation
        return {
            "key": signer,
            "deposit": w.derive_beacon_deposit_wallet_address(signer, config),
            "deposit (older)": w.derive_uups_deposit_wallet_address(signer, config),
            "proxy": w.derive_proxy_wallet_address(signer, config),
            "safe": w.derive_safe_wallet_address(signer, config),
        }
    except Exception:  # noqa: BLE001 - a missing or changed SDK internal
        return None


def check_wallet(private_key: str, wallet: str) -> None:
    """Refuse a wallet address the key does not control, and say which it does.

    Without this the SDK treats an unrelated address as a session key for a
    deposit wallet, and the order is only refused later, by Polymarket, with a
    message that does not say the address is simply the wrong one.
    """
    wallets = key_wallets(private_key)
    if not wallets or not wallet.strip():
        return
    if wallet.strip().lower() in {address.lower() for address in wallets.values()}:
        return
    own = "; ".join(f"{kind} {address}" for kind, address in wallets.items())
    raise VenueError(
        f"The wallet address in Settings ({wallet.strip()}) is not one this "
        f"private key controls. This key's Polymarket wallets are: {own}. "
        "Clear the address to use the deposit wallet, or enter the one that "
        "holds your funds — if your funds sit in a wallet that is not listed, "
        "this is not the key that owns it."
    )


class PolymarketVenue:
    name = "polymarket"

    def __init__(
        self,
        *,
        private_key: str | None = None,
        funder: str | None = None,
        signature_type: int = 0,  # accepted, unused: the SDK infers the wallet
        host: str = REST_URL,
        builder: dict | None = None,
    ) -> None:
        self.private_key = private_key
        self.funder = funder
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
        check_wallet(self.private_key, self.funder or "")
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
        """Place an order: a marketable buy by dollars, or a limit order.

        With `order.notional` set it buys that many dollars at the best prices
        on offer, up to `order.price`, and anything the book cannot fill at
        once is cancelled (fill-and-kill) — so a bet either takes a position
        now or says it could not. Without it, a limit order rests at its price.
        """
        await self.connect()
        token = order.instrument.symbol
        try:
            if order.notional is not None:
                if order.side != "buy":
                    raise VenueError("a dollar order can only buy")
                if order.notional < MIN_MARKET_BUY:
                    raise VenueError(
                        f"the smallest bet is ${MIN_MARKET_BUY:g} "
                        f"(you asked for ${order.notional:g})"
                    )
                result = await self._client.place_market_order(
                    token_id=token,
                    side="BUY",
                    amount=order.notional,
                    max_price=order.price,
                    order_type="FAK",
                )
            else:
                result = await self._client.place_limit_order(
                    token_id=token,
                    price=order.price,
                    size=order.size,
                    side="BUY" if order.side == "buy" else "SELL",
                )
        except VenueError:
            raise
        except Exception as exc:  # the SDK raises a wide variety of types
            raise VenueError(friendly_message(exc)) from exc
        return _ack(result, order)

    async def cancel(self, instrument: Instrument, venue_order_id: str) -> None:
        await self.connect()
        try:
            await self._client.cancel_order(order_id=venue_order_id)
        except Exception as exc:
            raise VenueError(friendly_message(exc)) from exc


def _ack(result: Any, order: OrderRequest) -> OrderAck:
    """The SDK's accepted-or-rejected answer as an `OrderAck`."""
    if getattr(result, "ok", False):
        return OrderAck(
            venue_order_id=str(getattr(result, "order_id", "")),
            client_id=order.client_id,
            accepted=True,
            detail=_detail(result),
        )
    code = str(getattr(result, "code", ""))
    message = getattr(result, "message", None)
    return OrderAck(
        venue_order_id="",
        client_id=order.client_id,
        accepted=False,
        reason=_REJECTIONS.get(code) or message or "the order was rejected",
    )


def _detail(result: Any) -> str:
    """`matched · 3.92 shares for $2.00`, or `resting` for an order on the book."""
    status = str(getattr(result, "status", "") or "accepted")
    spent = float(getattr(result, "making_amount", 0) or 0)
    shares = float(getattr(result, "taking_amount", 0) or 0)
    if spent > 0 and shares > 0:
        return f"{status} · {shares:g} shares for ${spent:,.2f}"
    return status


__all__ = ["MIN_MARKET_BUY", "PolymarketVenue", "check_wallet", "key_wallets"]
