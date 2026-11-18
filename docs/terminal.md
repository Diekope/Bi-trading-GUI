# The terminal

The live view: Hyperliquid candles on the right, the Polymarket 5-minute BTC column on the left. Back to the [README](../README.md).

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
| Drag | grab the trail: sideways walks through time, up / down moves the price window |
| ← / → | pan one candle (Shift: ten) |
| ↑ / ↓ | zoom the time range |
| Home | jump to the oldest candle, loading a page if needed |
| End, `0`, double-click | reset: live edge, fitted price range, 1.0 price zoom |
| `1` … `6` | switch timeframe (1m, 3m, 5m, 15m, 30m, 1h) |

The two axes are separate. The price gutter on the right changes only the
vertical scale — how far apart prices sit — and leaves the number of candles
alone; each wheel notch is 10%, clamped between 0.2× and 20×. The bottom time
axis changes only the time range. The pointer turns into a vertical resize
cursor over the price gutter and a horizontal one over the time axis, so it is
clear which wheel you are about to use. Over the plot it is an open hand: the
whole trail can be grabbed.

Dragging moves the chart with the pointer. Sideways walks one candle per
on-screen slot, so a deep zoom needs a longer drag but still lands exactly on a
bar. Up and down pull the price window with the pointer, one pixel for one
pixel, and the grab is not undone by the next tick. That is what recovers the
live bars when a deep zoom plus a price stretch has pushed them out of view. If
the live price is off the plot, its label and a small wedge stay pinned to the
edge it left through, so it is obvious which way to drag back. Double-click (or
`End` / `0`) releases the grab and fits the range again. A press that moves
less than a few pixels stays a click.

Zooming out stops at 600 bars (`MAX_VISIBLE`). Before that cap the requested
window kept growing while the series was short — invisibly, since only the
existing bars can be drawn — and then paging in history made every repaint
draw thousands of bars: 25ms at 3000, 51ms at 6000. Bounded, a repaint is ~5ms
no matter how far back the chart is paged.

The vertical scale pivots on the centre of the natural price range, so zooming
does not make the chart jump. Scrolling back freezes the viewport — new bars no
longer drag the view forward — and shows `N back · double-click to reset`; the
same hint says `price grabbed` after a vertical drag. Until then it is pinned to
the newest candle.

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
- **PM delay** — a bold `PM DELAY ● NN ms` readout at the top of the column,
  above the tiles: Polymarket's own WebSocket ping/pong, green ≤120ms, amber
  ≤300ms, red above. It runs on a second, subscription-free socket, so a busy
  market that trips the venue's slow-consumer guard cannot blank it.
- **Stats** — spread, Gamma liquidity, top-of-book depth (the price × size of
  the best eight levels on each side), the window-open **target**, the live
  Hyperliquid BTC perp mid, and the signed percent from the target to it.
  Above-target reads green, below reads red.
- **Return** — what the selected outcome pays if it wins: `RETURN` is the
  profit at its ask, `PER $100` the cash back on a $100 stake. A winning binary
  share always settles at $1.00, so a 64-cent buy returns $1.56, or +56%. The
  price comes from the live book (its mid when the book is one-sided), never
  from Gamma's listing snapshot, which drifts late in a window. Each tile also
  carries its own multiple when the column is wide enough to fit it without
  clipping the quotes.
- **BTC chart** — a rolling fifteen-minute view of the underlying, with the
  current window's target as a dashed line and the gap shaded green above / red
  below. A rollover does not reset the line: the previous windows scroll left
  while the new target segment grows from the right edge. Five-minute
  boundaries get a tick and a time label, not a full-height rule, so the line
  stays one unbroken curve. The view ends ~1.5s behind live — more than the
  one-second sample interval — so a fresh sample always lands ahead of the
  cursor. The newest 130 seconds take most of the plot width, so the live
  edge advances a few pixels a second instead of crawling sub-pixel; older
  data keeps even spacing and only boundaries clear of that slice are labelled.
  One-minute bars fill the span before live sampling begins, so the line
  starts at the left edge of the view from the first second instead of
  growing in from the right.
  The tip is interpolated between stored samples, then eased, and each sample
  is eased from the one before it, so a one-tick spike reads as a bend instead
  of a needle. The polyline then runs through a quadratic curve at every
  corner. The y-range eases too. An hour of samples is retained.
- **Tape** — the last twelve prints, newest first, with the outcome, price and
  fractional share size.

Sources: Gamma for the market and its tokens, CLOB `/book` for the initial
snapshot, then one WebSocket subscription to both tokens (`book`,
`price_change`, `last_trade_price`). Separately, one Hyperliquid `1m`
`candleSnapshot` per window supplies the target (the window open) and
backfills the line across the visible span; live BTC quotes come from the
`bbo` channel, because
`allMids` can be several seconds apart on a quiet book. Books and the tape are
cleared when the window rolls; the price line keeps rolling. The socket
reconnects within the same window on a drop. Bets are placed from the stake row
under the outcome tiles — dry-run unless live orders are armed (see Trading).

The target is the open of the Hyperliquid bar at the window start. Polymarket
resolves on Chainlink's BTC/USD TWAP, not on Hyperliquid, so within a few
dollars of the line the venue can disagree with the chart; the level is a
reference, not the settlement print.

The wire is fast: a busy five-minute market pushes several hundred book frames
a second. All of them are folded into the held books and the tiles, but the
price chart is painted from the `bbo` stream at its own pace, so a live column
costs roughly the same as the candle feed instead of pinning a core.

**Fast orders.** The first order used to pay for signing in (key derivation, a TLS
handshake, a credentials round trip) every time. Now one signed-in client per venue is
kept open and reused: the terminal signs in to Polymarket when it opens (if live orders
are on and the venue is connected), so even the first bet goes straight out. A failed
order throws the client away and the next one rebuilds it. The latency in the Logs
details is the order's round trip alone.

**Selling.** *Sell UP* / *Sell DOWN*, beside the bet buttons, sell every share held of
that side at the best bids, now: a fill-and-kill market sell with a floor three cents
under the bid. They light up (with the share count) once a bet has filled and stay
available until the window ends. There is no confirm dialog, on purpose: a sell only
closes what a bet opened, and it should be as quick as pressing the button. Shares are
counted from this session's fills.

**Hyperliquid, the same way.** Buy / Sell in the trade form send a **fill-or-cancel** order
priced 0.2% through the price on screen: it takes what the book offers up to that price
right now and never rests, so it either fills or tells you why not (the old order was a
resting limit that could sit on the book). The venue's answer carries the fill, so the
log says `FILLED` with the size and average price, and the form's position takes the
venue's price as its entry. **Close**, when live orders are on, reads the whole position
from the venue and closes it at once: the opposite side, reduce-only and fill-or-cancel,
1% through the live price. It closes exactly what is open however it was opened, can never
open the other way, and has no confirm dialog (it only ever shrinks a position). With live
orders off, Close is the paper close as before. Two calls go out (the position, then the
order), on the warm client.

**Testnet.** When the Hyperliquid account is set to the test network (Settings → Accounts →
Network), an amber **TESTNET** badge shows beside the trade form's status, on the Settings
card as soon as the network is picked, and in the Home balance card; every order the log
records carries `· testnet` and a `network: testnet` line in its details.

## Tuning the chart

The feel of the Polymarket chart comes from `~/.config/bi-trading/settings.json`,
written on first launch. Point `BI_TRADING_SETTINGS` elsewhere to keep a different
profile, or override any key with `BI_TRADING_<KEY>`. Restart after an edit; the
file is read once at startup.

| Key | Default | Effect |
| --- | --- | --- |
| `view_ms` | `900000` | total span on screen (fifteen minutes) |
| `focus_ms` | `130000` | length of the fast live slice |
| `focus_share` | `0.85` | share of the plot width that slice gets |
| `lag_ms` | `1500` | how far behind live the tip sits; must exceed `sample_every_ms` |
| `sample_every_ms` | `1000` | resolution of the stored line |
| `smooth` | `0.30` | per-sample damping; lower is rounder |
| `ease_tip` | `0.18` | per-frame glide toward the target |
| `ease_range` | `0.08` | per-frame glide of the y-scale |
| `frame_ms` | `33` | repaint interval (~30 fps) |

The live edge travels `width × focus_share ÷ (focus_ms / 1000)` pixels a second
— about 3.8 px/s on a wide column, 2.0 px/s on a narrow one. Every value is
clamped to a drawable range, and a corrupt file falls back to the defaults
instead of refusing to start.
