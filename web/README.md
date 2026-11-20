# Web design sandbox

Static HTML/CSS/JS replica of every screen, fed by seeded synthetic data (`synth.js`). No build step, no network, no Python.

    cd web && python3 -m http.server 8000

**Venue context.** The rail's top switch picks Polymarket (PM), Hyperliquid (HL) or both (`Alt+1/2/3`). Each screen adapts: Live (PM bets and edge, or HL book and trade form), Builder (variables and wording), Backtest (bet value or position value), ML, Settings, Logs. Builder and Backtest need one venue, so with "both" a PM/HL pill picks it. The PAPER / LIVE switch (top right) chooses which book receives orders; `#portfolio` shows both books side by side, updating every 1.5 s.

Screens (hash routes, rail icons, `Ctrl/Cmd+1..8`): `#home`, `#portfolio`, `#live`, `#builder` (rules / formula / code, results overview and compare), `#backtest` (overview and trades), `#logs`, `#ml`, `#model`, `#settings`.

- `styles.css`: tokens from `src/bi_trading/ui/theme_colors.py` (terminal, builder, backtest) and `palette.py` (hub, logs, ML, settings, via `body.hub`).
- `views.js`: one entry per screen. `chart.js`: canvas drawing. `app.js`: router.
- Controls with `data-set="key=value"` or `data-flip="key"` change shared state and re-render.

Fonts (Inter, JetBrains Mono) are copied from `src/bi_trading/ui/assets/` into `web/assets/`.

Edit here to try a layout, then port the result to the Qt code.
