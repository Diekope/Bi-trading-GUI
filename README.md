# lalala

Dark trading terminal. Hyperliquid candles are live on the right; the left
column tracks the current Polymarket five-minute BTC up/down market.

## Run

```sh
uv sync          # PySide6, httpx, websockets
uv run lalala
```

A second window, split in two empty halves, is set aside for the
backtest/strategy work:

```sh
uv run lalala-strat
```

The strategy builder is a third window for now, split into three vertical tiles
at 21 / 47 / 32 of the width and launched on its own so it can be worked on
without the backtest window:

```sh
uv run lalala-builder
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
  logs.py          the silent log: a rotating file, never the console
  strat.py         entry point for the blank backtest/strategy window
  strat_window.py  second window, split in two, for backtest + strategy work
  strat_tiles.py   the history tile: span picker, resolution, coverage, actions
  strat_playback.py the left tile: a streamed walk over the whole span
  strat_params.py  the backtest tile: a gallery of run inputs
  strat_strategy.py the strategy tile: which entry rule to run
  strat_builder.py the builder window: strategy, entry and exit rules
  strat_rules.py   one rules tile: Formulas/Code tabs over one formula
  formula.py       the entry/exit formula language: parse and check (no Qt)
  formula_builder.py the drag-and-drop formula builder (pills, chips, slots)
  strat_results.py the results tile: three live curves, legend underneath
  candles.py       the local 1m candle store: paths, coverage, CSV helpers
  candle_download.py  Binance 1m fetch, paged and resumable, on its own loop
  main_window.py   window, top bar, feed wiring, tile lifecycle, watch set
  panels.py        Card chrome, MAX_TILES
  cards.py         CandleChart, Timeframes, MarketSearch, MarketCard
  market_data.py   parsing, price formatting, candles, bands, search (no Qt)
  feed.py          Hyperliquid streams, latency probe (QObject + asyncio)
  polymarket_data.py   slugs, Gamma/CLOB/WS parsing, formatting (no Qt)
  polymarket_feed.py   one 5m market: resolve, snapshot, stream, roll over
  polymarket_panel.py  outcome tiles, countdown, BTC/target chart, tape (QPainter)
  settings.py      chart feel from ~/.config/lalala/settings.json + env overrides
  venues/
    base.py         Venue protocol for order placement (not used by the UI yet)
    hyperliquid.py  authenticated REST/WS adapter (orders, balances)
    polymarket.py   CLOB adapter (orders, books)
    runner.py       asyncio loop on a worker thread
tests/             371 tests: parsing/search/aliases, slug math, candle + book
                   routing, chart pan/zoom, axis zoom, backfill paging,
                   shortcuts, overlays, the Polymarket panel, the split
                   strategy window and its tiles, the streaming walk over a
                   whole span, its strategy picker and benchmark curves, the
                   strategy builder window, its locked 21/47/32 columns, its
                   compact STRATEGY tile, the two rules tiles, their presets and
                   their code
                   refusal, the drag-and-drop formula builder, the formula
                   language itself, the chart and backtest settings, the
                   silent log, and the candle store and downloader

Downloaded history lives in `data/candles/` — one OHLCV CSV per year,
`BTC-<year>-1m.csv`, with a header row and columns
`timestamp, open, high, low, close, volume`. Only BTC is fetched, and only at
1m: a 5m or 1h series can be compacted from it later, so the store never holds
the same data twice. The history tile reads those files to report which years
of the selected span are missing (red) or only partly downloaded (amber).

**Download** (`data/candles`) pulls the missing years from Binance's public
`klines` endpoint, a thousand bars a page, resuming from the last row already
on disk and appending each page as it arrives, so an interrupted download keeps
what it got. The bar still forming is dropped, so the newest row is always a
closed candle. Progress reads as a percentage of the year being fetched; a
complete span hides Download and offers Start backtest instead.

The 1m store starts when BTCUSDT did (2017-08-17), so 2017 is only expected
from that day and its Download can still finish. A year is complete at 99% of
its expected minutes, which leaves room for the handful of venue outages even
a good year has.

## Strategy tile

The entry rule the run is pointed at, with a **Create a strategy** button on
the right. The button is still a placeholder and opens nothing; the builder
window it will open exists separately (`uv run lalala-builder`). Two rules so
far:

| Rule | What it does |
| --- | --- |
| `Random buy` | opens on a coin flip (3% of flat bars). Kept in the list on purpose: it is the baseline an entry rule has to beat, not a fallback. |
| `Bollinger reversion` | buys when the close falls below the lower band of a 20-bar, 2σ channel. |

Like the span and the parameters, a change here is only remembered until
**Run** / **Start backtest** is pressed.

## Strategy builder

A window of its own, not opened by the backtest window and connected to
nothing in it:

```sh
uv run lalala-builder
```

Three vertical tiles side by side, splitting the width **21 / 47 / 32** — a
narrow rail, the working area, a wider rail — sharing the height and separated
by the same 8 px gap and nothing else. The split is **locked**: dragging a
handle does nothing, so the share changes only when the window is resized. The
tiles lower their minimum width to 120 px so the 21% rail is not clamped by the
card default.

The middle column stacks three tiles. The compact **STRATEGY** tile on top is
titled `STRATEGY` and holds one row: a text field (`name` as its placeholder)
taking the slack, and a dropdown of `1m`, `5m`, `15m` and `1h` at its own
width, defaulting to `1m`. It is only as tall as the title and that row.

Under it, two tiles share the rest of the column **evenly**: **ENTRY RULES**
and **EXIT RULES**. They are the same widget — `strat_rules.RulesTile` — each
with its own formula, its own title row of `Presets` / `Formulas` / `Code`
pills, and nothing shared between them.

Each tile has **three tabs** — `Presets`, `Formulas`, `Code` — and starts on
`Presets`, where ready-made rules are shown as centred cards with a line about
each.
Picking one fills the tile and the rule is editable from there like any other.
`Formulas` is the drag-and-drop builder and `Code` the same formula as text.

| Tile | Presets |
| --- | --- |
| `ENTRY RULES` | Bollinger reversion, SMA above, Breakout, RSI dip, Volume spike, Dip + volume |
| `EXIT RULES` | Take profit, Stop loss, TP or SL, Time stop, Target, stop or time |

The **STRATEGY** tile also carries a submenu, `load an existing strategy…`, for
whole strategies rather than one rule: picking one fills the name, the
timeframe and *both* rules at once. The five in the library — Bollinger
reversion, SMA trend, Breakout, RSI dip and Volume pop — are ordinary formulas,
so they are checked by the same parser as anything typed by hand.

The two read **different vocabularies**:

| Tile | May use |
| --- | --- |
| `ENTRY RULES` | the bar — `open high low close volume` — and the indicators |
| `EXIT RULES` | the open trade — `price entry tp sl pnl bars` — and plain maths only |

`pnl`, `tp` and `sl` are percentages; `price` is the close while the trade is
open; `bars` is how long it has been open. An indicator in an exit rule is
refused with `not here, this rule takes no indicators`, and a bar name like
`close` is an unknown name there.

Nothing is saved yet, and nothing is wired to the walk.

### The formula builder

The `Formulas` page is a drag-and-drop builder. A card holds the sources —
three rows of draggable **blocks**, then a box to type a number into:

| Row | Blocks |
| --- | --- |
| `DATA` | `close`, `open`, `high`, `low`, `volume` |
| `INDICATORS` | `SMA`, `EMA`, `RSI`, `Highest`, `Lowest`, `Change`, `Shift`, and the three Bollinger bands — each drops as one tile with its numbers inside |
| `LOGIC & MATHS` | `AND`, `OR`, `NOT`, `=`, parentheses, comma, arithmetic, comparisons |
| number box | type a value, `+ Add` puts it on the active line, `↺ Reset` clears every line |

Each block is a pill with a drag handle, coloured by what it is — data in
indigo, indicators in amber, `AND`/`OR`/`NOT` in green, maths neutral — and
each row wraps when the tile is narrow. The rows are **not** scrollable: the
card is only as tall as the rows it holds.

The entry tile is **only as tall as its content needs** and the exit tile takes
the rest of the column. That height is fixed by the content and follows it as
the window changes: narrow the window and the palette wraps onto more rows, so
the entry tile grows and the exit tile gives up the difference. It never
stretches just to fill the column.

Under the card are the lines, one strip of chips each, read left to right. The
last line is captioned `IF` and is the condition; the ones above are `LET` and
are named series. A line wraps rather than clipping, and the entry tile grows
to hold however many rows the lines take:

```
LET  [band] [=] [Boll low 20 2]
IF   [close] [<] [band]
```

An **indicator drops as a single tile** and nothing else comes with it: the
tile holds its own number — one for `SMA`, two for a Bollinger band — so `Boll
low` with `20` and `2` reads as `bollinger_lower(close, 20, 2)`. Edit a number
by typing in the tile; it rewrites the formula as you go.

A chip drags by its handle to reorder or move between lines, and its `×` takes
it off; `+ add a line` adds a line and each line carries its own `×` to remove
it (the last one stays). A drag carries a picture of the block itself, so what
is moving is visible under the cursor, and the line it is over lights up as the
drop target. Long lines **wrap** rather than clipping. A blank run shows a
dashed `drag a block here`, and a live pill reads `✓ valid`, `✗ not valid` or
`— empty`.

The chips are only an editor. The formula **text** is the truth: it is rebuilt
from the chips and handed to `lalala.formula.parse`, so the same checker still
reports `line 2, column 9: unknown name 'clsoe'`, and the text is what a run
would use.

### The code view

`Code` is the same formula as text in a monospace editor. It is filled from the
tiles, and it can be typed in directly: whatever is written there is scanned,
checked, and rebuilt into tiles, so the two views never disagree. A name that
was never defined is flagged with its place, and defining it on a line above
clears it — the same rules the language has always had.

A line the language cannot even read — a stray character like `@` — is
**refused**: the previous code is put back and the reason is shown, rather than
leaving the tiles and the code out of step.

Reading text back keeps indicators whole: `bollinger_lower(close, 20, 2)` comes
back as one tile holding `20` and `2`, not a run of separate chips.

### The formula language

The text a build produces is parsed and checked as it is built: a sound formula
gets no error line, a typo gets its place — `line 2, column 9: unknown name
'clsoe'`, or `fill the empty slot before this can be read` while a slot is
blank.

A formula is a list of lines. All but the last define named series; the last is
the condition, evaluated once per bar:

```
mid = sma(close, 20)
close < bollinger_lower(close, 20, 2) and volume > 2 * sma(volume, 50)
```

The names are the bar's own fields — `open`, `high`, `low`, `close`, `volume` —
plus anything a line above defined; an exit rule is given the trade's words
instead (see above). Operators, loosest first: `or`, `and`, `not`, the
comparisons (`< <= > >= == !=`), then `+ -`, `* / %`, a right-associative `^`,
and a unary minus. `#` starts a comment and `;` separates lines. The functions
are `sma`, `ema`, `rsi`, `highest`, `lowest`, `change`, `shift`,
`bollinger_lower`, `bollinger_middle`, `bollinger_upper`, `abs`, `min`, `max`,
`sqrt` — the last four alone for an exit rule.

The checker reports syntax errors, unknown names, unknown functions, the wrong
number of arguments, reassigning a field, redefining a name, and a line that is
not the last but holds the condition. It does **not** type-check: a number where
a truth belongs is the author's business, and it evaluates nothing — that is the
walk's job, later.

`formula.py` has no Qt and no candle data, so the same parser can drive the
walk when the two are joined.

## Results tile

Under the parameters, three curves are drawn live as the loop walks:
**strategy** (amber), **random buy** (indigo) and **buy & hold** (grey dashed),
with a running total for each in a legend along the bottom.

Everything is drawn as **return from the start**, not as a dollar balance. Over
a long span buy and hold compounds many times over while a strategy that
deploys a fraction of the book per trade barely moves; in dollars the first
flattens the others into the axis. In percent the two strategies stay readable,
and buy and hold is left to run off the top, with its number in the legend and
a note when it does.

Random buy is the benchmark that matters: it opens on a coin flip with the same
exits, sizing and fees, so an entry rule that cannot beat it has no edge. Buy
and hold puts the whole book in at the first bar and never sells.

The curves are sampled **once per tick**, not once per bar — a run can be
millions of bars and the chart cannot use more points than it has pixels.

`Sizing` percentages are a share of what `Max cash $` allows the run to trade
with, not of the whole book: with a $2,000 cap, a 10% position is $200 a
trade.

## Backtest tile

Below the history controls sits a gallery of the run's inputs — three or four
to a line, wrapping with the tile's width:

| Field | Meaning |
| --- | --- |
| `Initial capital $` | the book the run starts with |
| `Sizing` | how `Position` is read: `Balance %`, `Fixed $` or `Risk %` |
| `Position` | the value itself; its caption and its bounds follow `Sizing` |
| `TP %` / `SL %` | take profit and stop loss, percent from entry |
| `Max cash $` | most cash the run may trade with; anything above it is set aside |
| `Dynamic TP` | switch: let the take profit trail |
| `Reverse % to close` | pull-back from the peak that closes a trailing TP; only live while the switch is on |

Only BTC is in scope. The starting values live in the same
`~/.config/lalala/settings.json`, under `backtest` (or `LALALA_BACKTEST_*`),
and are clamped on the way in — an unknown `sizing` mode falls back to
`balance`. Numeric fields take a dot as the decimal mark whatever the system
locale, and are bounded so a percentage cannot exceed the whole book.

Both the history tile and the parameters tile keep only the height their
content needs; the results tile below them takes the rest of the column.

Decided and hard-coded for the run (no switches in the UI): fees and slippage
are fixed, one position is held at a time, and a trade is refused across a
data gap rather than filled through it. The entry rule is a separate tile.

## Playback tile

The left half holds the run as a moving picture: bare candles scroll past a
playhead while a row of figures above recomputes on every candle — PnL,
equity, progress (`30% · 120/400`), Sharpe, drawdown, max drawdown, max gain,
the current streak, the best winning and worst losing streak, trades, win rate,
fees.

- **Equity is realised only.** An open position is carried at what it cost, so
  entering a trade moves nothing but its fee; the result lands when it closes.
  Unrealised profit is deliberately not shown.
- **Sharpe is not annualised** — the walk is minutes long, so multiplying by
  the square root of a year would produce a meaningless number. It is the mean
  over deviation of the per-bar book returns.
- **The marks**: an amber ▲ under a candle is an entry, a grey ▼ above one is
  an exit.
- **It stops at the end** of its series rather than looping, and says how the
  run finished. Starting over is a button, never automatic.

**What the loop covers.** The **whole selected span**, streamed off disk bar by
bar — never loaded into memory. A decade of one-minute bars is 4.8M rows and
about 240 MB; holding them as objects would cost far more than the walk does,
so only what the picture and the figures need is kept: a rolling window of the
last `CHART_BARS` (600) bars, the most recent entries and exits, and running
totals. The Sharpe is a running mean and variance rather than a stored series.
Peak memory for a full 2017–2026 walk is around 60 MB.

**It fast-forwards.** A run over any amount of data is watched in about
`WATCH_MS` (two minutes): `stride` bars are consumed per tick, so a few hundred
bars play one at a time and a decade of minutes advances in jumps. The note
says which — `fast-forward ×2,017`. Bar-by-bar over ten years of minutes would
otherwise take about two and a half days to watch.

A span with nothing on disk falls back to a fixed-seed sample and says so.

Fills are the optimistic kind — the target and the stop are both read off one
candle's range, so a candle that touches both pays the target.

Nothing runs when the window opens: the tile sits idle until **Run** (in its
header) or **Start backtest** (in the history tile) is pressed. A change of
span, resolution, strategy or parameter is only remembered — the walk keeps
its place and the note says what is ready — so those buttons are the only
thing that starts a run over.

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
|  PM DELAY ● 26 ms       |  |╿╽│╿╽ ...                       |
|  BTC chart + tape       |                                   |
+-------------------------+-----------------------------------+
```

Palette (`theme.py`):

| Token | Hex | Role |
| --- | --- | --- |
| `CANVAS` | `#0b0b0d` | main window, darkest |
| `PANEL` | `#17181b` | floating cards, a shade lighter |
| `BORDER` | `#25262a` | card edge |
| `ACCENT` | `#e0b341` | amber accent, last-price line |
| `UP` / `DOWN` | `#3ddc84` / `#ff5c5c` | candles, latency colours, Polymarket sides |

## Tuning the chart

The feel of the Polymarket chart comes from `~/.config/lalala/settings.json`,
written on first launch. Point `LALALA_SETTINGS` elsewhere to keep a different
profile, or override any key with `LALALA_<KEY>`. Restart after an edit; the
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
  endpoint, with `interval: "1m"`, supplies the Polymarket window's target
  and the line's backfill once per five-minute rollover.

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

## Logging

Silent by design. The app is a GUI, so anything writing to the terminal it was
launched from scribbles over work in progress — a stray `print`, a logging
handler on stderr, or Qt's own chatter. `logs.py` points the root logger at a
rotating file and routes Qt's messages into it too, so the process stays quiet.

| Variable | Effect |
| --- | --- |
| `LALALA_LOG` | path to the file (`~/.local/share/lalala/lalala.log`) |
| `LALALA_LOG=off` | no file at all |
| `LALALA_LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

The file rotates at a megabyte, keeping three. `httpx`, `websockets` and
`asyncio` are held at `WARNING` unless the level is `DEBUG`, because their
output at `INFO` is rarely what is wanted. A second `setup()` is a no-op rather
than a second handler, and any console handler a library installed first is
dropped.

## Not implemented yet

- The strategy builder window. It launches on its own and divides into three
  locked columns: the two rules tiles check a formula but nothing defines or
  runs one yet, and nothing in the backtest window opens it.
- Order entry. `venues/hyperliquid.py` can sign and submit, but nothing in the
  UI calls it — deliberately, and it needs a key.
- Account balance / positions.
- Polymarket order entry. The column reads the market live; nothing places an
  order, and `PolymarketVenue.balances()` still raises with the endpoint it
  needs.
- Volume/hover readouts on the chart; candles are OHLC only.
- `l2Book` support still exists in `feed.py` (tested) but no widget subscribes
  to it any more, since the order book was replaced by candles.
