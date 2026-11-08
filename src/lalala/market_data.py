"""Pure market-data logic: parsing, formatting, search.

No Qt and no I/O here, so it is all unit-testable without a window or network.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, log10

DEFAULT_MARKET = "BTC"
XYZ_PREFIX = "xyz:"
XYZ_DEX = "xyz"
MAIN_DEX = ""

# Hyperliquid perps allow at most 6 - szDecimals decimals, and 5 significant
# figures, whichever binds first. Used for display only.
MAX_PRICE_DECIMALS = 6

# Plain-language queries that should not rely on the ticker name. Real perps
# are crypto; the commodities and equities live on the HIP-3 "xyz" dex.
ALIASES: dict[str, tuple[str, ...]] = {
    # -- commodities / raw materials --------------------------------------
    "oil": ("xyz:CL", "xyz:BRENTOIL"),
    "crude": ("xyz:CL",),
    "wti": ("xyz:CL",),
    "brent": ("xyz:BRENTOIL",),
    "gold": ("xyz:GOLD",),
    "silver": ("xyz:SILVER",),
    "platinum": ("xyz:PLATINUM",),
    "palladium": ("xyz:PALLADIUM",),
    "gas": ("xyz:NATGAS",),
    "natgas": ("xyz:NATGAS",),
    "ttf": ("xyz:TTF",),
    "copper": ("xyz:COPPER",),
    "aluminium": ("xyz:ALUMINIUM",),
    "uranium": ("xyz:URANIUM",),
    "wheat": ("xyz:WHEAT",),
    "corn": ("xyz:CORN",),
    # -- indices / ETFs ---------------------------------------------------
    # SPY and QQQ themselves are not listed; these are the index products
    # Hyperliquid does quote, which is what the ETFs track.
    "spy": ("xyz:SP500",),
    "spx": ("xyz:SP500",),
    "sp500": ("xyz:SP500",),
    "s&p": ("xyz:SP500",),
    "qqq": ("xyz:XYZ100",),
    "nasdaq": ("xyz:XYZ100",),
    "ndx": ("xyz:XYZ100",),
    "index": ("xyz:XYZ100", "xyz:SP500"),
    "vix": ("xyz:VIX",),
    "volatility": ("xyz:VIX",),
    "semis": ("xyz:SMH", "xyz:SOXL"),
    "semiconductor": ("xyz:SMH",),
    "smh": ("xyz:SMH",),
    "soxl": ("xyz:SOXL",),
    "mags": ("xyz:MAGS",),
    "megacap": ("xyz:MAGS",),
    "energy": ("xyz:XLE",),
    "xle": ("xyz:XLE",),
    "bonds": ("xyz:TLT",),
    "treasuries": ("xyz:TLT",),
    "tlt": ("xyz:TLT",),
    "biotech": ("xyz:XBI",),
    "xbi": ("xyz:XBI",),
    "japan": ("xyz:EWJ", "xyz:JP225"),
    "nikkei": ("xyz:JP225",),
    "korea": ("xyz:KR200",),
    "india": ("xyz:NIFTY",),
    "brazil": ("xyz:IBOV", "xyz:EWZ"),
    "taiwan": ("xyz:EWT",),
    "etf": (
        "xyz:SP500",
        "xyz:XYZ100",
        "xyz:SMH",
        "xyz:XLE",
        "xyz:TLT",
        "xyz:XBI",
        "xyz:MAGS",
        "xyz:SOXL",
    ),
    "etfs": (
        "xyz:SP500",
        "xyz:XYZ100",
        "xyz:SMH",
        "xyz:XLE",
        "xyz:TLT",
        "xyz:XBI",
    ),
    # -- FX ---------------------------------------------------------------
    "dollar": ("xyz:DXY",),
    "dxy": ("xyz:DXY",),
    "eur": ("xyz:EUR",),
    "euro": ("xyz:EUR",),
    "jpy": ("xyz:JPY",),
    "yen": ("xyz:JPY",),
    "gbp": ("xyz:GBP",),
    "pound": ("xyz:GBP",),
    "krw": ("xyz:KRW",),
    # -- single names, by company rather than ticker ----------------------
    "apple": ("xyz:AAPL",),
    "microsoft": ("xyz:MSFT",),
    "nvidia": ("xyz:NVDA",),
    "tesla": ("xyz:TSLA",),
    "amazon": ("xyz:AMZN",),
    "google": ("xyz:GOOGL",),
    "alphabet": ("xyz:GOOGL",),
    "meta": ("xyz:META",),
    "facebook": ("xyz:META",),
    "netflix": ("xyz:NFLX",),
    "intel": ("xyz:INTC",),
    "amd": ("xyz:AMD",),
    "micron": ("xyz:MU",),
    "qualcomm": ("xyz:QCOM",),
    "broadcom": ("xyz:AVGO",),
    "oracle": ("xyz:ORCL",),
    "ibm": ("xyz:IBM",),
    "dell": ("xyz:DELL",),
    "palantir": ("xyz:PLTR",),
    "coinbase": ("xyz:COIN",),
    "robinhood": ("xyz:HOOD",),
    "microstrategy": ("xyz:MSTR",),
    "reddit": ("xyz:RDDT",),
    "snap": ("xyz:SNAP",),
    "alibaba": ("xyz:BABA",),
    "taiwan semi": ("xyz:TSM",),
    "asml": ("xyz:ASML",),
    "arm": ("xyz:ARM",),
    "gamestop": ("xyz:GME",),
    "crowdstrike": ("xyz:CRWD",),
    "servicenow": ("xyz:NOW",),
    "cloudflare": ("xyz:NET",),
    "micron tech": ("xyz:MU",),
    "lam research": ("xyz:LRCX",),
    "applied materials": ("xyz:AMAT",),
    "western digital": ("xyz:WDC",),
    "chevron": ("xyz:CVX",),
    "nubank": ("xyz:NU",),
    "mercadolibre": ("xyz:MELI",),
    "moderna": ("xyz:MRNA",),
    "nokia": ("xyz:NOK",),
}


@dataclass(frozen=True, slots=True)
class Market:
    coin: str
    dex: str = MAIN_DEX
    sz_decimals: int = 0
    max_leverage: int = 0

    @property
    def display(self) -> str:
        """Ticker without the dex namespace."""
        return self.coin.removeprefix(XYZ_PREFIX)

    @property
    def is_hip3(self) -> bool:
        return self.dex != MAIN_DEX


@dataclass(frozen=True, slots=True)
class Level:
    px: float
    sz: float
    n: int = 0


@dataclass(frozen=True, slots=True)
class Book:
    coin: str
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    ts_ms: int = 0

    @property
    def best_bid(self) -> Level | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Level | None:
        return self.asks[0] if self.asks else None

    @property
    def mid(self) -> float | None:
        bid, ask = self.best_bid, self.best_ask
        if bid is None or ask is None:
            return None
        return (bid.px + ask.px) / 2

    @property
    def spread_bps(self) -> float | None:
        bid, ask = self.best_bid, self.best_ask
        if bid is None or ask is None or bid.px <= 0:
            return None
        mid = (bid.px + ask.px) / 2
        if mid <= 0:
            return None
        return (ask.px - bid.px) / mid * 10_000


def format_price(px: float | None, sz_decimals: int = 0) -> str:
    if px is None or px <= 0:
        return "—"
    allowed = max(0, MAX_PRICE_DECIMALS - sz_decimals)
    magnitude = floor(log10(abs(px)))
    sig_decimals = max(0, 5 - (magnitude + 1))
    decimals = min(allowed, sig_decimals)
    return f"{px:,.{decimals}f}"


def format_size(sz: float, sz_decimals: int = 0) -> str:
    return f"{sz:,.{max(0, sz_decimals)}f}"


def format_bps(bps: float | None) -> str:
    if bps is None:
        return ""
    return f"{bps:.1f} bps"


def parse_universe(payload: dict, dex: str = MAIN_DEX) -> list[Market]:
    """Parse a `meta` response into markets."""
    markets: list[Market] = []
    for asset in payload.get("universe", []):
        name = asset.get("name")
        if not name:
            continue
        markets.append(
            Market(
                coin=name,
                dex=dex,
                sz_decimals=int(asset.get("szDecimals", 0) or 0),
                max_leverage=int(asset.get("maxLeverage", 0) or 0),
            )
        )
    return markets


def parse_all_mids(payload: dict) -> dict[str, float]:
    """Parse an `allMids` message. Both dexs use the same `mids` shape."""
    mids = payload.get("mids") if isinstance(payload, dict) else None
    if not isinstance(mids, dict):
        return {}
    out: dict[str, float] = {}
    for coin, px in mids.items():
        try:
            out[coin] = float(px)
        except (TypeError, ValueError):
            continue
    return out


def parse_bbo(payload: dict) -> tuple[str, float] | None:
    """Parse a `bbo` message into `(coin, mid)`.

    The frame carries the best bid then the best ask. This is the fast path
    for the Polymarket column: `allMids` can be several seconds apart, while
    BTC's best bid/offer moves continuously.
    """
    if not isinstance(payload, dict):
        return None
    coin = str(payload.get("coin") or "")
    levels = payload.get("bbo") or ()
    if not coin or len(levels) < 2:
        return None
    try:
        bid = float(levels[0]["px"])
        ask = float(levels[1]["px"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if bid <= 0 or ask <= 0:
        return None
    return coin, (bid + ask) / 2.0


def parse_book(payload: dict) -> Book:
    levels = payload.get("levels") or [[], []]
    while len(levels) < 2:
        levels.append([])

    def to_levels(raw: list) -> tuple[Level, ...]:
        out = []
        for row in raw:
            try:
                out.append(
                    Level(
                        px=float(row["px"]),
                        sz=float(row["sz"]),
                        n=int(row.get("n", 0) or 0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(out)

    bids = tuple(sorted(to_levels(levels[0]), key=lambda lv: lv.px, reverse=True))
    asks = tuple(sorted(to_levels(levels[1]), key=lambda lv: lv.px))
    return Book(
        coin=str(payload.get("coin", "")),
        bids=bids,
        asks=asks,
        ts_ms=int(payload.get("time", 0) or 0),
    )


def search_markets(
    markets: list[Market] | dict[str, Market],
    query: str,
    limit: int = 8,
) -> list[Market]:
    """Rank: alias hits, then exact, prefix, substring. Empty query → nothing."""
    q = query.strip().lower()
    if not q:
        return []

    pool = list(markets.values()) if isinstance(markets, dict) else list(markets)
    by_coin = {m.coin: m for m in pool}

    alias_coins: list[str] = []
    for key, coins in ALIASES.items():
        if key.startswith(q) or q in key:
            alias_coins.extend(coins)

    exact: list[Market] = []
    prefix: list[Market] = []
    contains: list[Market] = []
    for market in pool:
        name = market.display.lower()
        coin = market.coin.lower()
        if q in (name, coin):
            exact.append(market)
        elif name.startswith(q) or coin.startswith(q):
            prefix.append(market)
        elif q in name or q in coin:
            contains.append(market)

    head = [by_coin[c] for c in dict.fromkeys(alias_coins) if c in by_coin]
    head_coins = {m.coin for m in head}
    tail = [m for m in exact + prefix + contains if m.coin not in head_coins]
    return (head + tail)[:limit]


# -- candles ---------------------------------------------------------------

TIMEFRAMES: tuple[str, ...] = ("1m", "3m", "5m", "15m", "30m", "1h")
DEFAULT_TIMEFRAME = "1m"

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
}


@dataclass(frozen=True, slots=True)
class Candle:
    t: int          # open time, ms since epoch
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0

    @property
    def is_up(self) -> bool:
        return self.c >= self.o


@dataclass(frozen=True, slots=True)
class CandleSeries:
    coin: str
    interval: str
    candles: tuple[Candle, ...]

    @property
    def last_price(self) -> float | None:
        return self.candles[-1].c if self.candles else None


def candle_window_ms(interval: str, count: int = 120) -> int:
    """How far back to ask for `count` candles of `interval`."""
    return INTERVAL_MS.get(interval, 60_000) * max(1, count)


def bollinger_bands(
    candles: tuple[Candle, ...] | list[Candle],
    period: int = 20,
    deviations: float = 2.0,
) -> tuple[tuple[float, float, float] | None, ...]:
    """Rolling (middle, upper, lower) bands over close prices.

    Aligned with `candles`: the first `period - 1` entries are None because
    there is not enough history yet. Uses a rolling sum so a 300-candle series
    costs one pass rather than 300 slices.
    """
    if period < 1:
        raise ValueError("period must be at least 1")

    closes = [candle.c for candle in candles]
    total = 0.0
    total_sq = 0.0
    out: list[tuple[float, float, float] | None] = []

    for index, close in enumerate(closes):
        total += close
        total_sq += close * close
        if index >= period:
            dropped = closes[index - period]
            total -= dropped
            total_sq -= dropped * dropped

        if index < period - 1:
            out.append(None)
            continue

        middle = total / period
        variance = max(0.0, total_sq / period - middle * middle)
        spread = variance ** 0.5 * deviations
        out.append((middle, middle + spread, middle - spread))

    return tuple(out)


def parse_candles(payload: list) -> tuple[Candle, ...]:
    if not isinstance(payload, list):
        return ()
    out: list[Candle] = []
    for row in payload:
        try:
            out.append(
                Candle(
                    t=int(row["t"]),
                    o=float(row["o"]),
                    h=float(row["h"]),
                    l=float(row["l"]),
                    c=float(row["c"]),
                    v=float(row.get("v", 0.0) or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(out, key=lambda c: c.t))
