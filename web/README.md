# Web design sandbox

Static HTML/CSS/JS replica of the terminal and backtest screens, fed by seeded synthetic data (`synth.js`). No build step, no network, no Python.

    cd web && python3 -m http.server 8000

Colour tokens in `styles.css` mirror `src/bi_trading/ui/theme_colors.py`. Edit here to try a layout, then port the result to the Qt code.
