"""Pure Polymarket logic: slug math, parsing, formatting.

No Qt and no I/O, so everything here is unit-testable without a window or a
socket.

Slugs
    `btc-updown-5m-dynamic_time_utc` is a template, not a live market. The
    venue lists one market per five-minute window, named
    `btc-updown-5m-<unix ts aligned to 300s>`; `market_slug()` resolves the
    one containing "now". Windows are aligned to the epoch, so the same slug
    means the same wall clock everywhere.

Data
    Gamma  https://gamma-api.polymarket.com/markets?slug=…   market metadata
    CLOB   https://clob.polymarket.com/book                   full book snapshot
    WS     book / price_change / last_trade_price frames

The Gamma JSON is awkward: `clobTokenIds`, `outcomes` and `outcomePrices`
are JSON-encoded *strings*, and `volume` may be null on a fresh market.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable

SLUG_PREFIX = "btc-updown-5m"
WINDOW_SECONDS = 300
WINDOW_MS = WINDOW_SECONDS * 1000


# -- market -----------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """One side of a binary market, identified by its CLOB token id."""

    name: str
    token_id: str
    price: float                 # probability from Gamma, 0..1
    best_bid: float | None = None
    best_ask: float | None = None

    @property
    def mid(self) -> float | None:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return self.best_bid if self.best_bid is not None else self.best_ask


@dataclass(frozen=True)
class PolymarketMarket:
    slug: str
    question: str
    condition_id: str
    start_ms: int
    end_ms: int
    outcomes: tuple[Outcome, ...]
    liquidity: float
    volume: float
    spread: float
    tick_size: float
    accepting_orders: bool

    def outcome_for_token(self, token_id: str) -> Outcome | None:
        for outcome in self.outcomes:
            if outcome.token_id == token_id:
                return outcome
        return None

    def is_open(self, now: float | None = None) -> bool:
        seconds = time.time() if now is None else now
        return self.end_ms / 1000 > seconds


def market_slug(now: float | None = None) -> str:
    """Slug of the five-minute market containing `now` (default: this second)."""
    seconds = time.time() if now is None else now
    aligned = int(seconds) // WINDOW_SECONDS * WINDOW_SECONDS
    return f"{SLUG_PREFIX}-{aligned}"


def slug_window(slug: str) -> tuple[int, int] | None:
    """(start_ms, end_ms) encoded in a slug, or None if it is not ours."""
    prefix, _, stamp = slug.rpartition("-")
    if prefix != SLUG_PREFIX or not stamp.isdigit():
        return None
    start = int(stamp) * 1000
    return start, start + WINDOW_MS


def _json_list(value: Any) -> list[Any]:
    """Gamma stores arrays as JSON strings. Accept either form."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_ms(value: Any) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def parse_market(payload: Any) -> PolymarketMarket | None:
    """Parse one Gamma market (a list from ?slug= is accepted too)."""
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        return None

    token_ids = _json_list(payload.get("clobTokenIds"))
    names = _json_list(payload.get("outcomes"))
    prices = _json_list(payload.get("outcomePrices"))
    if not token_ids:
        return None

    outcomes: list[Outcome] = []
    for index, token_id in enumerate(token_ids):
        name = str(names[index]) if index < len(names) else f"Outcome {index + 1}"
        price = _number(prices[index]) if index < len(prices) else None
        outcomes.append(
            Outcome(
                name=name,
                token_id=str(token_id),
                price=price if price is not None else 0.0,
            )
        )

    # Gamma's bestBid/bestAsk belong to the first outcome token.
    best_bid = _number(payload.get("bestBid"))
    best_ask = _number(payload.get("bestAsk"))
    if best_bid is not None or best_ask is not None:
        outcomes[0] = replace(outcomes[0], best_bid=best_bid, best_ask=best_ask)

    slug = str(payload.get("slug") or "")
    window = slug_window(slug)
    end_ms = _iso_ms(payload.get("endDate"))
    if window is not None:
        start_ms, window_end = window
        end_ms = end_ms if end_ms is not None else window_end
    else:
        start_ms = _iso_ms(payload.get("startDate")) or 0
        if end_ms is None:
            end_ms = start_ms + WINDOW_MS

    return PolymarketMarket(
        slug=slug,
        question=str(payload.get("question") or slug or "Polymarket"),
        condition_id=str(payload.get("conditionId") or ""),
        start_ms=start_ms,
        end_ms=end_ms,
        outcomes=tuple(outcomes),
        liquidity=_number(payload.get("liquidity")) or 0.0,
        volume=_number(payload.get("volume")) or 0.0,
        spread=_number(payload.get("spread")) or 0.0,
        tick_size=_number(payload.get("orderPriceMinTickSize")) or 0.01,
        accepting_orders=bool(payload.get("acceptingOrders", True)),
    )


# -- books ------------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass(frozen=True)
class TokenBook:
    """One token's book, best level first on both sides."""

    token_id: str
    bids: tuple[Level, ...] = ()
    asks: tuple[Level, ...] = ()
    timestamp_ms: int = 0

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return self.best_bid if self.best_bid is not None else self.best_ask

    @property
    def spread(self) -> float | None:
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None

    @property
    def notional(self) -> float:
        """Resting dollars on both sides — the useful "depth" number."""
        return sum(level.price * level.size for level in self.bids + self.asks)


@dataclass(frozen=True)
class PriceChange:
    """An incremental level update pushed by the market web socket."""

    token_id: str
    price: float
    size: float
    side: str                    # BUY touches the bid side, SELL the ask side
    best_bid: float | None = None
    best_ask: float | None = None
    timestamp_ms: int = 0


@dataclass(frozen=True)
class Trade:
    token_id: str
    price: float
    size: float
    side: str
    timestamp_ms: int = 0


@dataclass(frozen=True)
class PricePoint:
    """One sample of a price, for the reference chart."""

    timestamp_ms: int
    price: float


BAR_MS = 60_000


def window_price_points(
    candles: Iterable[Any],
    start_ms: int,
    end_ms: int,
    now_ms: int | None = None,
) -> tuple[float | None, tuple[PricePoint, ...]]:
    """Turn 1m BTC candles into the reference line for one window.

    Returns `(target, points)`. The target is the open of the bar containing
    the window start — the price the binary market compares its close against.
    Each completed bar's close becomes a point stamped at the end of its
    minute, and the window start itself is seeded with the target so the line
    begins at the left edge. The bar still forming is left to the live
    sampler, which stamps points at the actual time rather than in the future.
    A response entirely older than the window yields `(None, ())`, so a late
    fetch cannot leak into the next window.
    """
    if now_ms is None:
        now_ms = end_ms
    bars = sorted(
        (bar for bar in candles if getattr(bar, "t", None) is not None),
        key=lambda bar: bar.t,
    )
    target: float | None = None
    for bar in bars:
        if bar.t <= start_ms < bar.t + BAR_MS:
            target = float(bar.o)
            break
    if target is None and bars and bars[0].t >= start_ms:
        # The venue usually starts exactly on the window; tolerate a minute
        # of slack rather than leaving the target blank.
        target = float(bars[0].o)
    if target is None:
        return None, ()

    points = [PricePoint(start_ms, target)]
    for bar in bars:
        stamp = bar.t + BAR_MS
        if stamp > now_ms or stamp <= start_ms:
            continue
        points.append(PricePoint(min(stamp, end_ms), float(bar.c)))
    points.sort(key=lambda point: point.timestamp_ms)
    return target, tuple(points)


def _levels(raw: Any, *, descending: bool) -> tuple[Level, ...]:
    levels: list[Level] = []
    for item in raw or ():
        if not isinstance(item, dict):
            continue
        price = _number(item.get("price"))
        size = _number(item.get("size"))
        if price is None or size is None or size <= 0:
            continue
        levels.append(Level(price, size))
    levels.sort(key=lambda level: level.price, reverse=descending)
    return tuple(levels)


def _stamp(value: Any) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def parse_book(payload: Any) -> TokenBook | None:
    """Parse a CLOB `/book` response or a WS `book` frame.

    The venue sends bids ascending and asks descending. Both are normalised
    here so `bids[0]` and `asks[0]` are the best prices.
    """
    if not isinstance(payload, dict):
        return None
    token_id = str(payload.get("asset_id") or payload.get("token_id") or "")
    if not token_id:
        return None
    return TokenBook(
        token_id=token_id,
        bids=_levels(payload.get("bids"), descending=True),
        asks=_levels(payload.get("asks"), descending=False),
        timestamp_ms=_stamp(payload.get("timestamp")),
    )


def apply_price_change(book: TokenBook, change: PriceChange) -> TokenBook:
    """Return `book` with one level replaced, removed, or inserted.

    A size of zero removes the level, which is how the venue says a price is
    no longer resting. The best bid/ask on the change are a fallback for the
    first update after a gap, when the held book may not know a level yet.
    """
    levels = list(book.bids if change.side == "BUY" else book.asks)
    for index, level in enumerate(levels):
        if level.price == change.price:
            if change.size <= 0:
                levels.pop(index)
            else:
                levels[index] = Level(level.price, change.size)
            break
    else:
        if change.size > 0:
            levels.append(Level(change.price, change.size))

    levels.sort(key=lambda level: level.price, reverse=change.side == "BUY")
    updated = replace(
        book,
        bids=tuple(levels) if change.side == "BUY" else book.bids,
        asks=tuple(levels) if change.side == "SELL" else book.asks,
        timestamp_ms=change.timestamp_ms or book.timestamp_ms,
    )
    return updated


def parse_price_changes(message: Any) -> tuple[PriceChange, ...]:
    if not isinstance(message, dict):
        return ()
    stamp = _stamp(message.get("timestamp"))
    changes: list[PriceChange] = []
    for item in message.get("price_changes") or ():
        if not isinstance(item, dict):
            continue
        token_id = item.get("asset_id")
        price = _number(item.get("price"))
        size = _number(item.get("size"))
        if not token_id or price is None or size is None:
            continue
        side = str(item.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            continue
        changes.append(
            PriceChange(
                token_id=str(token_id),
                price=price,
                size=size,
                side=side,
                best_bid=_number(item.get("best_bid")),
                best_ask=_number(item.get("best_ask")),
                timestamp_ms=stamp,
            )
        )
    return tuple(changes)


def parse_last_trade(message: Any) -> Trade | None:
    if not isinstance(message, dict):
        return None
    token_id = message.get("asset_id")
    price = _number(message.get("price"))
    if not token_id or price is None:
        return None
    return Trade(
        token_id=str(token_id),
        price=price,
        size=_number(message.get("size")) or 0.0,
        side=str(message.get("side") or "").upper(),
        timestamp_ms=_stamp(message.get("timestamp")),
    )


# -- display ----------------------------------------------------------------


def format_cents(price: float | None) -> str:
    """0.67 -> '67¢'. Keeps a decimal only when the price is not on a cent."""
    if price is None:
        return "—"
    cents = price * 100.0
    if abs(cents - round(cents)) < 0.05:
        return f"{round(cents):.0f}¢"
    return f"{cents:.1f}¢"


def format_compact(value: float | None) -> str:
    """Dollars in a width that fits a stat column: $6.3M, $16.6k, $842."""
    if value is None or value <= 0:
        return "—"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}k"
    return f"${value:.0f}"


def format_shares(size: float | None) -> str:
    """Trade and ladder sizes. Polymarket trades are fractional shares."""
    if size is None:
        return "—"
    if size >= 1_000:
        return f"{size:,.0f}"
    if size >= 10:
        return f"{size:.1f}"
    text = f"{size:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def format_countdown(seconds: float | None) -> str:
    """mm:ss, or h:mm:ss when there is an hour or more left."""
    if seconds is None:
        return "—"
    if seconds <= 0:
        return "closed"
    remaining = int(seconds + 0.999)  # a visible second is never 00:00
    minutes, secs = divmod(remaining, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
