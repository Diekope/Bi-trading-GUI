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
