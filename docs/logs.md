# Logs

The Logs view (the list icon on the rail, or Ctrl+5) is the session's trading
record: what was sent, what became of it, what the strategy fired, and what
the connections did. Back to the [README](../README.md).

It is not the debug log. That is `~/.local/share/bi-trading/bi-trading.log`, a
file for developers (see [configuration](configuration.md)); this one is the
user's own, and the figures above the table come from it.

## The screen

- **Figures** for today: orders sent, filled, rejected, warnings, and the day's
  PnL (the sum of the closes and results logged today).
- **Filters:** a search box, a source pick (All, Polymarket, Hyperliquid,
  Strategy, System), an origin (Manual or Auto), a level (Info, Warn, Error)
  and a **strategy**. The strategy pick lists every strategy seen in the log,
  and the figures above the table then count that strategy alone (its orders,
  fills, rejections, warnings and PnL), so one strategy's day can be read apart
  from the rest. Manual actions carry no strategy.
  **Pause** holds the table still while events keep arriving; **Clear** empties
  the log; **Export** writes a CSV.
- **The table**, newest first: time, level, source, origin, event and message.
  Up to 1,000 rows are shown. Only the newest 500 events are loaded at launch
  (a day with more than 500 is loaded whole, so its figures are right);
  **Load older**, in the footer, brings in 500 more each press, and the footer
  says how many are stored. **Export** writes everything stored, not just what
  is loaded.
- **Details** for the picked row: time, source, origin (and the strategy for an
  automatic one), latency, **Why it fired** (the lines behind a strategy
  signal) and **Request / response** (what was sent, and the venue's answer or
  error). **Copy** puts the row on the clipboard; **Open in Live** jumps to the
  terminal.
- **Auto-scroll** keeps the newest row in view.

## What is logged

| Event | When |
| --- | --- |
| `ORDER` | an order is sent (manual from the trade form or a bet button) |
| `FILLED` / `ACCEPTED` | the venue took it (`FILLED` when it reports a match) |
| `REJECTED` | the venue refused it, or the call failed; the reason is in the details |
| `OPENED` / `CLOSED` | a paper position opens or closes; a close carries its PnL |
| `SIGNAL` | the strategy's signal turns true (with why it did) |
| `ARMED` / `DISARMED` | the Auto-bet box is ticked or cleared |
| `RESOLVED` | an auto-bet's window ended; carries the bet's result (see Auto-bet) |
| `LIMIT` | 70% of the daily loss limit is gone (once a day) |
| `LATENCY` | a venue's round trip crosses 250 ms, and when it recovers |
| `CONNECTION` | a feed connects, drops or reconnects |

## Where it lives

`src/bi_trading/state/events.py` holds the `Event` and the `EventLog` (any
thread may record; the view hears about it on the main one). The view is
`src/bi_trading/ui/hub/logs_view.py`, built from a design mockup.

Events are appended to `~/.local/share/bi-trading/events.jsonl`
(`BI_TRADING_EVENTS` moves it) as they happen. How they are stored depends on
how many there are:

- **A short history stays in JSON lines**, one event a line, easy to read and
  to append to.
- **A long one moves to Parquet.** When that file passes 2,000 lines or 1 MB at
  launch, everything but the newest 500 events is moved into
  `events.parquet` beside it (compressed, columnar). The file read at launch
  stays small however long the app has been used, and the archive is only read
  when you ask for older events or export.

**Clear** removes both files.

## Icons

Where the app used coloured dots it now draws the venue's own mark — Hyperliquid's
mint mark and Polymarket's — on the rail, the Home balance cards, the Settings
headers and latency pills, and the Source column here. The files are in
`src/bi_trading/ui/assets/venues/` (taken from each venue's site; they are the
venues' trademarks, used only to say which venue a number belongs to).
Polymarket's is black on transparent, so it is tinted white for the dark UI; if
a file is missing the old dot is drawn. `src/bi_trading/ui/venue_icons.py` loads
and caches them. Warnings and errors use a triangle and a crossed circle from
the rail's stroke-icon set instead of the `●` and `▼` glyphs.

## Auto-bet

The **Auto-bet** box in the terminal's strategy bar (off by default; its starting
state is the `auto_bet` setting) bets UP on its own when the strategy's signal turns
true. The rules are in `src/bi_trading/state/autobet.py`:

- One bet per five-minute window, however long the signal stays true.
- The stake is the bar's size, capped at the **max stake**; never under $1.
- Nothing once today's net result is down by the **daily loss limit**
  (Settings → Trading defaults); a `LIMIT` warning at 70% of it.
- A **real order** only when live orders are armed *and* Polymarket is connected,
  with no confirm dialog (it cannot wait for one). Otherwise it is a **paper bet**:
  nothing is sent, but it is logged and settled like a real one, so a strategy can
  be judged without risk. Both carry the strategy's name, so the Strategy filter
  shows its own orders and results.
- When the window ends the bet is settled from BTC against the window's opening
  target: UP wins at or above it. A share pays $1, so a win is
  `stake / price − stake` and a loss is the stake. Polymarket settles on its own
  price, so this is an estimate; a real bet's result is marked `≈ … · estimated`.
  Results count towards the Day PnL, and towards the daily loss limit.
- A **real** bet is not settled from BTC. The stake and price are the venue's own fill
  (shares and dollars from its answer), and the result waits for **Polymarket's own
  settlement**: every 15 seconds the terminal asks Gamma (public, no key) how each
  finished window closed, and logs `RESOLVED … settled by Polymarket` once it says. Only
  if that has not come 10 minutes after the window ended does the bet fall back to the
  BTC estimate, marked `≈ … · estimated`. Paper bets are still settled from BTC.
- A bet you place **by hand** (the Up and Down buttons) is closed the same way. It is
  kept when its order **fills**, at the venue's own stake and price (a failed order makes
  nothing, and partial fills add up), logged as `manual`, and settled by its window with
  Polymarket's own result. It does not use up the window for auto-bets. If you **sell**
  shares before the window ends, the profit on those shares (what came in, less what
  they cost) is logged at once as `Sold early`, and only the shares left settle at the
  window's end. Not modelled: Polymarket's own fees, if any apply to a market.
