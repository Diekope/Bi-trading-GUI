# Architecture

Why Python, the source layout, and where data comes from. Back to the [README](../README.md).

## Why Python here

| Need | Consequence |
| --- | --- |
| Polymarket order signing is EIP-712 over secp256k1, plus L2 API creds derived from the wallet | Reimplementing this in C/C++ is the main source of rejected orders; `polymarket-client` is the maintained path (CLOB V2) |
| Hyperliquid signing and WS framing | `hyperliquid-python-sdk` for orders; public data needs no SDK at all |
| GUI must stay smooth while sockets stream | Qt6 renders in C++; Python only orchestrates, and all venue I/O lives on a separate asyncio thread |

The GUI thread never awaits network calls. `MarketFeed` runs on the
`AsyncRunner` loop and publishes Qt signals, which Qt delivers queued onto the
main thread. The chart itself is hand-painted with `QPainter` — no charting
dependency.

## Layout

```
src/bi_trading/
  __main__.py      entry point for `bi-trading` and `python -m bi_trading`
  app.py           QApplication bootstrap for the terminal
  logs.py          the silent log: a rotating file, never the console

  data/            market data, storage and feeds (parsers are Qt-free)
    candles.py         the local 1m store: Parquet paths, coverage, helpers
    candle_download.py Binance 1m fetch, paged and resumable, on its own loop
    market_data.py     parsing, price formatting, candles, bands, search
    polymarket_data.py slugs, Gamma/CLOB/WS parsing, formatting
    jsonio.py          JSON parsing: orjson when installed, stdlib otherwise
    feed.py            Hyperliquid streams, latency probe
    polymarket_feed.py one 5m market: resolve, snapshot, stream, roll over

  engine/          the pure backtest engine (no Qt)
    core.py            the walk: the Rust core when built, Python fallback
    formula.py         the entry/exit formula language: parse and check
    formula_eval.py    run a formula over bars: indicators, signals, the walk
    formula_palettes.py the builder's palettes: the sources you drag from

  state/           config and what persists between runs
    settings.py        chart feel + defaults from ~/.config/bi-trading/settings.json
    accounts.py        public account settings + the private keys, in the keychain
    orders.py          placing orders: the worker, the arming gate, the adapters
    positions.py       the one open paper position, shared across the hub's views
    strategies.py      saved strategies: one JSON file, read and replaced by name
    runs.py            saved backtest runs: span, params, strategy and trades

  ui/              everything Qt
    theme.py           the terminal palette + the stylesheet it applies
    theme_colors.py, theme_qss.py  the palette and the sheet, split out
    palette.py         the hub's palette (shared by the hub and Settings)
    fonts.py           the bundled Inter / JetBrains Mono, registered at startup
    panels.py, cards.py             card chrome, the candle chart and market card
    polymarket_panel.py             outcome tiles, countdown, BTC/target chart, tape
    main_window.py                  the terminal: window, top bar, feed wiring
    strategy_bar.py, trade_form.py  the bar under the charts and the trade form
    syntax.py, autocomplete.py      editor highlighting and completion
    hub/           the hub shell
      main_hub.py        rail, in-place views, feed wiring
      hub_widgets.py     the hub's small builders and self-painted widgets
      settings_view.py   the Settings screen
      settings_widgets.py its builders and the venue connection tester
    strat/         the backtest + builder windows
      strat.py, strat_window.py, strat_tiles.py, strat_params.py,
      strat_strategy.py, strat_results.py, strat_playback.py, strat_report.py,
      strat_compare.py, strat_builder.py, strat_rules.py, strat_conditions.py,
      strat_saved.py, strat_runs.py, formula_builder.py

  venues/          order placement adapters
    base.py, hyperliquid.py, polymarket.py, runner.py

tests/             ~520 tests: parsing/search/aliases, slug math, candle + book
                   routing, chart pan/zoom, axis zoom, backfill paging,
                   shortcuts, overlays, the Polymarket panel, the split
                   strategy window and its tiles, the streaming walk over a
                   whole span, its strategy picker and benchmark curves, the
                   strategy builder window, its locked 21/47/32 columns, its
                   compact STRATEGY tile, the one rules tile and its switch, their rules
                   gallery and their code refusal, the footer that resets and
                   saves a draft, the saved strategies file, the drag-and-drop
                   formula builder, the formula language, its evaluator, the
                   results tile, the chart and backtest settings, the silent
                   log, and the candle store and downloader, the hub and its
                   in-place navigation, the paper position, and the Settings
                   screen and its account store

Downloaded history lives in `data/candles/` — one OHLCV Parquet file per
year, `BTC-<year>-1m.parquet`, with columns
`timestamp, open, high, low, close, volume`. A legacy `BTC-<year>-1m.csv` is
converted to Parquet the first time its year is read. Only BTC is fetched, and only at
1m: a 3m / 5m / 15m / 30m / 1h series can be compacted from it later, so the
store never holds the same data twice. The history tile reads those files to
report which years of the selected span are missing (red) or only partly
downloaded (amber), and offers the same set of resolutions — `1m`, `3m`, `5m`,
`15m`, `30m`, `1h` — to run at.

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
