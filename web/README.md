# Web design sandbox

HTML/CSS/JS replica of every screen. The live screens read the venues' public feeds; Builder and Backtest run the real engine (`src/bi_trading/engine`) through `serve.py`. Screens with nothing live behind them still use seeded synthetic data (`synth.js`). No build step.

    uv run python web/serve.py      # then open http://localhost:8000

**Venue context.** The rail's top switch picks Polymarket (PM), Hyperliquid (HL) or both (`Alt+1/2/3`). Each screen adapts: Live (PM bets and edge, or HL book and trade form), Builder (variables and wording), Backtest (bet value or position value), ML, Settings, Logs. Strategy work is per venue: in "general" (both) the Builder, Backtest and ML tabs are hidden (and their routes redirect home), and Home shows a portfolio card instead. The general Live screen trades both venues: a Polymarket bet bar and a Hyperliquid order bar (size, leverage, TP, SL, Buy/Long, Sell/Short) in the footer, with each venue's open paper positions listed under its chart. The PAPER / LIVE switch (top right) chooses which book receives orders; `#portfolio` shows both books side by side, updating every 1.5 s.

Screens (hash routes, rail icons, `Ctrl/Cmd+1..8`): `#home`, `#portfolio`, `#live`, `#builder` (rules / formula / code, results overview and compare), `#backtest` (overview and trades), `#logs`, `#ml`, `#model`, `#settings`.

- `styles.css`: tokens from `src/bi_trading/ui/theme_colors.py` (terminal, builder, backtest) and `palette.py` (hub, logs, ML, settings, via `body.hub`).
- `views.js`: one entry per screen. `chart.js`: canvas drawing. `app.js`: router.
- Controls with `data-set="key=value"` or `data-flip="key"` change shared state and re-render.

Fonts (Inter, JetBrains Mono) are copied from `src/bi_trading/ui/assets/` into `web/assets/`.

## The engine

`serve.py` answers `/api/...` with `engine_api.py`, which calls the same Qt-free code as the desktop app. Run it with `uv run` so `bi_trading` and numpy are importable.

| Route | What it does |
| --- | --- |
| `GET /api/status` | candles and Polymarket prices on disk, and the data folder |
| `GET /api/strategies`, `POST /api/strategies` | the saved strategies, the same file as the desktop app (`~/.config/bi-trading/strategies.json`, or `BI_TRADING_STRATEGIES`) |
| `POST /api/parse` | checks a rule; the Builder shows the verdict as you type |
| `POST /api/backtest` | the Hyperliquid-style run (`formula_eval.backtest`) over Binance 1m candles, resampled to 1m to 4h |
| `POST /api/backtest/polymarket` | the binary run (`engine.binary.run_binary`) over the past five-minute markets, with the always-UP and always-DOWN baselines |

- **Data.** The candle store is `BI_TRADING_DATA`, else this checkout's `data/candles`, else the main checkout's (`../bi-trading/data/candles`). Downloading stays in the desktop app (its downloaders run on Qt).
- **Builder.** The text of each rule (bet UP, bet DOWN, cash out; or entry, exit) belongs to the selected strategy. Edit it in Code or Formula; Save writes it to the shared strategies file, Run backtest runs it. The tiles in Formula and Rules are still illustrative.
- **Backtest.** History (span, timeframe), Strategy and the value card feed the run; results, curves, drawdown, how trades end and the trade or bet table come from the engine. An empty Hyperliquid exit rule means `pnl >= tp or pnl <= -sl`, since TP and SL only act through the exit rule.
- **Not wired yet.** Compare (walk-forward, TP × SL sweep), Save / Load run, ML and Model builder still show demo content.
- **Safety.** POSTs from another origin are refused; nothing here places an order.
- Tests: `uv run python -m unittest web/test/test_engine_api.py` (a throwaway candle store and strategies file).

## Live feeds and paper trading

`feeds.js` connects to the public endpoints the Qt app uses (Hyperliquid `info` + WebSocket: candles, `l2Book`, `allMids`, `bbo`; Polymarket Gamma + the market WebSocket for the current 5-minute BTC window). `paper.js` fills paper orders against those live books: Polymarket bets walk the ask side and settle on Gamma's resolved outcome (falling back to BTC vs the window-open price after 30 s, flagged "est."); Hyperliquid perps walk the book, charge 0.06% per side, and close on TP, SL or at 90% of margin lost. The paper account (PM $1,000, HL $10,000) is saved in `localStorage`; **Reset paper account** is on the Portfolio.

- **Run `web/serve.py`** (not `file://`, not `http.server`). Browsers cannot call Polymarket's Gamma API directly (it allows only its own origin, so the market is never found and prices stay on demo data). `serve.py` serves the page and relays, server-side and read-only, Gamma `/markets`, CLOB `/time` and `/book`, Hyperliquid `/info`, and the Polymarket market socket (`ws://localhost:8001/pm`). It binds to 127.0.0.1, only forwards an allowlist of paths, and forwards none of the browser's headers. Hyperliquid's own socket is still reached directly.
- A feed that is not delivering shows a chip in the top bar (`PM STALE`, `HL CONNECTING`, ...) and the screen says `demo data`; the cause is in Logs. Without the relay, the page falls back to calling the venues directly.
- If a feed cannot connect (offline, or the browser blocks a cross-origin call), the screen says so in its status chip and falls back to synthetic data.
- `test/mock.html` runs the same app against fake endpoints, for working offline: open `http://localhost:8000/test/mock.html`.
- `uv run python -m unittest web/test/test_serve.py` tests the relay against local fake upstreams.
- `node --test test/feeds.test.mjs` checks the parsers, dispatchers, subscriptions and paper fills.
- **Balances** sit in the top bar of every screen: PAPER (cash plus open positions, marked live, with PnL since start) and LIVE. The live figure is Hyperliquid's perps account value, read from a public wallet address entered in Settings (`clearinghouseState`, no key, saved in the browser). Polymarket's USDC cash is not public, so its card reads the value of the open positions of a public wallet address instead (Data API `/v2/value`, relayed by `serve.py`); the chip then shows that value (in general, the sum of both, with the Portfolio detailing each).
- **Polymarket chart:** `btcchart.js` animates the BTC line like the Qt `PriceChart` (rolling 15-minute axis, smoothed curve, eased range, pulsing tip, target growing from the window start). The axis is a rolling minute; the animation never restarts at a market rollover (earlier windows keep their dashed target and scroll left); the line is backfilled from 1-minute candles so it spans the whole plot. The screen is patched in place on each live update (`morph` in `app.js`), so hover, focus and scroll survive. Click the UP or DOWN tile to select it: spread, return and per-$100 follow the selected side. Volume and Bollinger toggles are hidden on Polymarket.
- **PnL %** appears next to every cash PnL: on a position it is the return on margin (perp) or on stake (bet); on the account and the day it is a share of start equity; on a book it is the total over the margin and stakes at risk.
- LIVE mode is read-only here: no keys, no real orders.

Edit here to try a layout, then port the result to the Qt code.
