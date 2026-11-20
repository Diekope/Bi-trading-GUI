# Web design sandbox

Static HTML/CSS/JS replica of every screen, fed by seeded synthetic data (`synth.js`). No build step, no network, no Python.

    uv run python web/serve.py      # then open http://localhost:8000

**Venue context.** The rail's top switch picks Polymarket (PM), Hyperliquid (HL) or both (`Alt+1/2/3`). Each screen adapts: Live (PM bets and edge, or HL book and trade form), Builder (variables and wording), Backtest (bet value or position value), ML, Settings, Logs. Builder and Backtest need one venue, so with "both" a PM/HL pill picks it. The PAPER / LIVE switch (top right) chooses which book receives orders; `#portfolio` shows both books side by side, updating every 1.5 s.

Screens (hash routes, rail icons, `Ctrl/Cmd+1..8`): `#home`, `#portfolio`, `#live`, `#builder` (rules / formula / code, results overview and compare), `#backtest` (overview and trades), `#logs`, `#ml`, `#model`, `#settings`.

- `styles.css`: tokens from `src/bi_trading/ui/theme_colors.py` (terminal, builder, backtest) and `palette.py` (hub, logs, ML, settings, via `body.hub`).
- `views.js`: one entry per screen. `chart.js`: canvas drawing. `app.js`: router.
- Controls with `data-set="key=value"` or `data-flip="key"` change shared state and re-render.

Fonts (Inter, JetBrains Mono) are copied from `src/bi_trading/ui/assets/` into `web/assets/`.

## Live feeds and paper trading

`feeds.js` connects to the public endpoints the Qt app uses (Hyperliquid `info` + WebSocket: candles, `l2Book`, `allMids`, `bbo`; Polymarket Gamma + the market WebSocket for the current 5-minute BTC window). `paper.js` fills paper orders against those live books: Polymarket bets walk the ask side and settle on Gamma's resolved outcome (falling back to BTC vs the window-open price after 30 s, flagged "est."); Hyperliquid perps walk the book, charge 0.06% per side, and close on TP, SL or at 90% of margin lost. The paper account (PM $1,000, HL $10,000) is saved in `localStorage`; **Reset paper account** is on the Portfolio.

- **Run `web/serve.py`** (not `file://`, not `http.server`). Browsers cannot call Polymarket's Gamma API directly (it allows only its own origin, so the market is never found and prices stay on demo data). `serve.py` serves the page and relays, server-side and read-only, Gamma `/markets`, CLOB `/time` and `/book`, Hyperliquid `/info`, and the Polymarket market socket (`ws://localhost:8001/pm`). It binds to 127.0.0.1, only forwards an allowlist of paths, and forwards none of the browser's headers. Hyperliquid's own socket is still reached directly.
- A feed that is not delivering shows a chip in the top bar (`PM STALE`, `HL CONNECTING`, ...) and the screen says `demo data`; the cause is in Logs. Without the relay, the page falls back to calling the venues directly.
- If a feed cannot connect (offline, or the browser blocks a cross-origin call), the screen says so in its status chip and falls back to synthetic data.
- `test/mock.html` runs the same app against fake endpoints, for working offline: open `http://localhost:8000/test/mock.html`.
- `uv run python -m unittest web/test/test_serve.py` tests the relay against local fake upstreams.
- `node --test test/feeds.test.mjs` checks the parsers, dispatchers, subscriptions and paper fills.
- **Balances** sit in the top bar of every screen: PAPER (cash plus open positions, marked live, with PnL since start) and LIVE. The live figure is Hyperliquid's perps account value, read from a public wallet address entered in Settings (`clearinghouseState`, no key, saved in the browser). Polymarket has no public balance, so it shows n/a.
- **Polymarket chart:** `btcchart.js` animates the BTC line like the Qt `PriceChart` (rolling 15-minute axis, smoothed curve, eased range, pulsing tip, target growing from the window start). The axis is a rolling minute; the animation never restarts at a market rollover (earlier windows keep their dashed target and scroll left); the line is backfilled from 1-minute candles so it spans the whole plot. The screen is patched in place on each live update (`morph` in `app.js`), so hover, focus and scroll survive. Click the UP or DOWN tile to select it: spread, return and per-$100 follow the selected side. Volume and Bollinger toggles are hidden on Polymarket.
- **PnL %** appears next to every cash PnL: on a position it is the return on margin (perp) or on stake (bet); on the account and the day it is a share of start equity; on a book it is the total over the margin and stakes at risk.
- LIVE mode is read-only here: no keys, no real orders.

Edit here to try a layout, then port the result to the Qt code.
