# lalala

Dark trading terminal. Hyperliquid candles are live on the right; the left
column tracks the current Polymarket five-minute BTC up/down market.

## Run

```sh
uv sync          # PySide6, httpx, websockets
uv run lalala
```

Tests (headless, no network, no sockets):

```sh
uv run pytest -q
```

## What works now

**Top bar** — Hyperliquid's own WebSocket ping/pong round-trip, measured on
the real socket path rather than an HTTP timer, so it reflects what order flow
would experience. Refreshed every 2s. Green ≤120ms, amber ≤300ms, red above.
Polymarket's equivalent sits at the top of its column, above the tiles,
refreshed every 5s while a market is open.

The two numbers differ because the venues answer at different speeds, not
because one probe is broken: from the same machine, TCP + TLS to both edge
endpoints completes in ~25ms, while Hyperliquid's `/info` takes 250–370ms to
first byte and Polymarket's CLOB `/time` takes 75–110ms. The extra time is the
venue's application/origin, and the WebSocket pings show the same split.

**Market cards** (right side)

- Main card opens on `HYPE` (`DEFAULT_MARKET`); click its name to change it.
- Candlestick chart, 1m by default, switchable to 3m / 5m / 15m / 30m / 1h —
  by pill or with the `1`-`6` keys. Bars are pushed by the venue's `candle`
  stream as trades print, so the last bar updates sub-second.
- 300 bars of history arrive with the card; panning to the left edge asks the
  venue for the next 300 and appends them. The viewport does not jump when a
  page lands — the new bars sit off-screen to the left, ready for the next
  drag. When the venue returns nothing older, the chart stops asking.
- Live mid price in the card header, refreshed from `allMids`.
- **+** sits on the newest card; **⌘T** does the same. Up to 3 tiles
  (`MAX_TILES`), each with its own market and timeframe.
- Any card can be closed while another survives, including the first one; the
  next card takes over the main-card slot.
- Picking a market collapses the search row. Click the coin name to reopen it.
- Time axis along the bottom: `HH:MM` for intraday and `dd Mon HH:MM` at 1h.
- Every split uses the same 8px transparent gap, horizontally and vertically,
  so all cards sit identically on the canvas.
- Cards share the stack proportionally as the window resizes. The window
  minimum is 620×520 so four cards always fit; below that the splitter would
  stop distributing and the last card would overflow.

No drop shadows: a `QGraphicsDropShadowEffect` re-renders the entire card into
a pixmap on every repaint, which is an extra full-card pass per market update.
The dark panel against the lighter canvas already separates them.

**Chart overlays** — two checkboxes in the top bar, next to the latency
readout. They are global: toggling one applies to every card, including tiles
created later.

| Toggle | Default | What it draws |
| --- | --- | --- |
| Volume | on | Per-candle volume as a strip under the price plot, scaled to the visible peak, coloured by candle direction |
| Bollinger | off | 20-period, 2σ bands over closes: shaded envelope, upper/lower edges, dotted middle |

Bands stretch the price scale only by up to half the candle range in each
direction. A wide envelope after a gap would otherwise flatten the candles into
a single line; past that cap the bands clip at the plot edge. Volume needs
about 90px of chart height, so it hides itself in very short cards rather than
squeezing the candles.

**Chart navigation**

| Input | Action |
| --- | --- |
| Wheel over the price axis | stretch / squash the price range |
| Wheel over the time axis | zoom the time range |
| Wheel over the plot | zoom the time range |
| Shift + wheel | pan two candles per notch |
| Drag | pan, 0.75 candles per candle-width |
| ← / → | pan one candle (Shift: ten) |
| ↑ / ↓ | zoom the time range |
| Home | jump to the oldest candle, loading a page if needed |
| End, `0`, double-click | reset: live edge, default range, 1.0 price zoom |
| `1` … `6` | switch timeframe (1m, 3m, 5m, 15m, 30m, 1h) |

The two axes are separate. The price gutter on the right changes only the
vertical scale — how far apart prices sit — and leaves the number of candles
alone; each wheel notch is 10%, clamped between 0.2× and 20×. The bottom time
axis changes only the time range. The pointer turns into a vertical resize
cursor over the price gutter and a horizontal one over the time axis, so it is
clear which wheel you are about to use.

Zooming out stops at 600 bars (`MAX_VISIBLE`). Before that cap the requested
window kept growing while the series was short — invisibly, since only the
existing bars can be drawn — and then paging in history made every repaint
draw thousands of bars: 25ms at 3000, 51ms at 6000. Bounded, a repaint is ~5ms
no matter how far back the chart is paged.

The vertical scale pivots on the centre of the natural price range, so zooming
does not make the chart jump. Scrolling back freezes the viewport — new bars no
longer drag the view forward — and shows `N back · double-click for live`. Until
then it is pinned to the newest candle.

**Deeper history.** The first 300 bars cover roughly 5 hours at 1m. Reaching
the left edge (drag, wheel, `Home`, or the panning keys) fires one REST
`candleSnapshot` request for the 300 bars before the oldest one held. Requests
are serialised per (coin, interval) and a burst of drag events collapses into
one, because the venue answers bursts with HTTP 429. A page that comes back
empty means the market has no older data and the chart stops asking; a page
that fails leaves the chart free to retry on the next pan. A landing page never
moves the viewport: the new bars sit off-screen to the left, and the next drag
walks into them.

Digits `1`-`6` switch the timeframe on whichever card has focus; the chart
takes focus when you click it. Inside the search box they type normally — the
window-level fallback only sees keys the focused widget already declined.

**Search** covers 377 markets: 235 main perps plus 142 HIP-3 markets on the
`xyz` dex, which is where commodities and equities live. Results render as a
list inside the card, not a popup — a popup grabs the keyboard on macOS after
the first keystroke.

Plain language and classic names are aliased (97 entries): `oil` → `xyz:CL`,
`gold` → `xyz:GOLD`, `apple` → `xyz:AAPL`, `semis` → `xyz:SMH`,
`bonds` → `xyz:TLT`. Trading 212–style ETF tickers map onto the index products
Hyperliquid actually quotes: `spy`/`s&p` → `xyz:SP500`, `qqq`/`nasdaq` →
`xyz:XYZ100`. Note that **SPY, QQQ, GLD, IWM, VOO and DIA are not listed at
all** — those exact contracts do not exist on the venue, so the alias is the
closest tradable equivalent.

**Polymarket column** (left) — one market at a time: the five-minute Bitcoin
up/down window that is open right now.

- `btc-updown-5m-dynamic_time_utc` is the template. Real slugs are
  `btc-updown-5m-<unix ts>`, with the timestamp aligned to 300 seconds, so the
  panel derives the slug from the clock and rolls to the next window by itself.
  Nothing to configure; the countdown and question change on the boundary.
- **Outcome tiles** — UP and DOWN in cents, with a probability bar and the best
  bid/ask on each. Click a tile to make its book the one the spread and depth
  stats describe.
- **Clock** — the window in UTC and a live countdown; white, amber inside a
  minute, red inside 30 seconds.
- **Venue delay** — Polymarket's WebSocket ping/pong, top-left above the tiles;
  green ≤120ms, amber ≤300ms, red above.
- **Stats** — spread, Gamma liquidity, top-of-book depth (the price × size of
  the best eight levels on each side), the window-open **target**, the live
  Hyperliquid BTC perp mid, and the signed percent from the target to it.
  Above-target reads green, below reads red.
- **BTC chart** — a rolling fifteen-minute view of the underlying, with the
  current window's target as a dashed line and the gap shaded green above / red
  below. A rollover does not reset the line: the previous windows scroll left
  while the new target segment grows from the right edge. Five-minute
  boundaries get a tick and a time label, not a full-height rule, so the line
  stays one unbroken curve. The view ends ~0.7s behind live and the tip is
  interpolated between one-second samples and the newest quote, then eased, so
  it glides instead of snapping on every update. The y-range eases too. An hour
  of samples is retained.
- **Tape** — the last twelve prints, newest first, with the outcome, price and
  fractional share size.

Sources: Gamma for the market and its tokens, CLOB `/book` for the initial
snapshot, then one WebSocket subscription to both tokens (`book`,
`price_change`, `last_trade_price`). Separately, one Hyperliquid `1m`
`candleSnapshot` per window seeds the target and backfills the pre-launch part
of the price line; live BTC quotes come from the `bbo` channel, because
`allMids` can be several seconds apart on a quiet book. Books and the tape are
cleared when the window rolls; the price line keeps rolling. The socket
reconnects within the same window on a drop. Order placement is deliberately
not wired — the column is read-only.

The target is the open of the Hyperliquid bar at the window start. Polymarket
resolves on Chainlink's BTC/USD TWAP, not on Hyperliquid, so within a few
dollars of the line the venue can disagree with the chart; the level is a
reference, not the settlement print.

The wire is fast: a busy five-minute market pushes several hundred book frames
a second. All of them are folded into the held books and the tiles, but the
price chart is painted from the `bbo` stream at its own pace, so a live column
costs roughly the same as the candle feed instead of pinning a core.

## Why Python here

| Need | Consequence |
| --- | --- |
| Polymarket order signing is EIP-712 over secp256k1, plus L2 API creds derived from the wallet | Reimplementing this in C/C++ is the main source of rejected orders; `py-clob-client` is the maintained path |
| Hyperliquid signing and WS framing | `hyperliquid-python-sdk` for orders; public data needs no SDK at all |
| GUI must stay smooth while sockets stream | Qt6 renders in C++; Python only orchestrates, and all venue I/O lives on a separate asyncio thread |

The GUI thread never awaits network calls. `MarketFeed` runs on the
`AsyncRunner` loop and publishes Qt signals, which Qt delivers queued onto the
main thread. The chart itself is hand-painted with `QPainter` — no charting
dependency.

## Layout

```
src/lalala/
  app.py           QApplication bootstrap
  theme.py         colours + the whole stylesheet (app-level, so popups inherit)
  main_window.py   window, top bar, feed wiring, tile lifecycle, watch set
  panels.py        Card chrome, MAX_TILES
  cards.py         CandleChart, Timeframes, MarketSearch, MarketCard
  market_data.py   parsing, price formatting, candles, bands, search (no Qt)
  feed.py          Hyperliquid streams, latency probe (QObject + asyncio)
  polymarket_data.py   slugs, Gamma/CLOB/WS parsing, formatting (no Qt)
  polymarket_feed.py   one 5m market: resolve, snapshot, stream, roll over
  polymarket_panel.py  outcome tiles, countdown, BTC/target chart, tape (QPainter)
  venues/
    base.py         Venue protocol for order placement (not used by the UI yet)
    hyperliquid.py  authenticated REST/WS adapter (orders, balances)
    polymarket.py   CLOB adapter (orders, books)
    runner.py       asyncio loop on a worker thread
tests/             174 tests: parsing/search/aliases, slug math, candle + book
                   routing, chart pan/zoom, axis zoom, backfill paging,
                   shortcuts, overlays, the Polymarket panel
```

## Window layout

```
+-------------------------------------------------------------+
|        Volume  Bollinger                       HL ● 210 ms  |
+-------------------------+-----------------------------------+
|                         |  HYPE                       84.6  |
|                         |  1m 3m 5m 15m 30m 1h              |
|                         |  |╿╽│╿╽ ...              │ 85.3   |
|                         |  |╿╽│╿╽                  │        |
|        Polymarket       +-----------------------------------+
|  UP 64.5¢  DOWN 35.5¢   |  xyz:CL  [XYZ]               96.7 +|
|  19:35–19:40  closes…   |  1m 3m 5m 15m 30m 1h              |
|  PM ● 26 ms             |  |╿╽│╿╽ ...                       |
|  BTC chart + tape       |                                   |
+-------------------------+-----------------------------------+
```

Palette (`theme.py`):

| Token | Hex | Role |
| --- | --- | --- |
| `CANVAS` | `#17181b` | main window, lighter |
| `PANEL` | `#0b0b0d` | floating cards, darker |
| `BORDER` | `#25262a` | card edge |
| `ACCENT` | `#1793d1` | Arch cyan, last-price line |
| `UP` / `DOWN` | `#3ddc84` / `#ff5c5c` | candles, latency colours, Polymarket sides |

## Data sources

Public endpoints only, no key, no signing:

- `POST /info {"type":"meta"}` and `{"type":"meta","dex":"xyz"}` — universe
- `wss://api.hyperliquid.xyz/ws` — `allMids` (main + `xyz`) and WS ping/pong.
  A `bbo` subscription for BTC feeds the Polymarket panel's live price; it
  moves far more often than `allMids` on a quiet market.
- `wss://api.hyperliquid.xyz/ws` `candle` — one subscription per (coin,
  interval) on screen, pushed on every trade. No polling.
- `POST /info {"type":"candleSnapshot", ...}` — initial history for a newly
  watched (coin, interval) pair, plus a 60s reconcile. Polling this every second
  drew HTTP 429s, which is why the stream carries the live updates. The same
  endpoint, with `interval: "1m"`, seeds the Polymarket window's target and
  price backfill once per five-minute rollover.

Reconnects with exponential backoff (1s → 10s) and re-subscribes on reconnect.

Polymarket, also public:

- `GET https://gamma-api.polymarket.com/markets?slug=…` — one market per
  five-minute window: question, condition id, two CLOB token ids, prices,
  liquidity, tick size, close time.
- `GET https://clob.polymarket.com/book?token_id=…` — a full book for each
  outcome token, before the stream starts.
- `wss://ws-subscriptions-clob.polymarket.com/ws/market` — one subscription to
  both tokens; `book`, `price_change` and `last_trade_price` frames. The socket
  is dropped at the window boundary and reopened on the next slug.

## Not implemented yet

- Order entry. `venues/hyperliquid.py` can sign and submit, but nothing in the
  UI calls it — deliberately, and it needs a key.
- Account balance / positions.
- Polymarket order entry. The column reads the market live; nothing places an
  order, and `PolymarketVenue.balances()` still raises with the endpoint it
  needs.
- Volume/hover readouts on the chart; candles are OHLC only.
- `l2Book` support still exists in `feed.py` (tested) but no widget subscribes
  to it any more, since the order book was replaced by candles.
