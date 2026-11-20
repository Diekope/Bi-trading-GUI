# Web design sandbox

Static HTML/CSS/JS replica of every screen, fed by seeded synthetic data (`synth.js`). No build step, no network, no Python.

    cd web && python3 -m http.server 8000

Screens (hash routes, rail icons, `Ctrl/Cmd+1..7`): `#home`, `#live`, `#builder` (rules / formula / code, results overview and compare), `#backtest` (overview and trades), `#logs`, `#ml`, `#model`, `#settings`.

- `styles.css`: tokens from `src/bi_trading/ui/theme_colors.py` (terminal, builder, backtest) and `palette.py` (hub, logs, ML, settings, via `body.hub`).
- `views.js`: one entry per screen. `chart.js`: canvas drawing. `app.js`: router.
- Controls with `data-set="key=value"` or `data-flip="key"` change shared state and re-render.

Fonts (Inter, JetBrains Mono) are copied from `src/bi_trading/ui/assets/` into `web/assets/`.

Edit here to try a layout, then port the result to the Qt code.
