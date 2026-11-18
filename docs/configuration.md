# Configuration

Settings, trading safety, saved state, tests and logging. Back to the [README](../README.md).

### Settings

The hub's Settings view (the gear in the rail) is live:

- **Accounts** — a Hyperliquid API-wallet address + key, and a Polymarket key +
  funder address. Addresses, network and signature type go to
  `~/.config/bi-trading/settings.json`; private keys go to the **macOS Keychain**
  (a `0600` `secrets.json` is the fallback elsewhere, and in tests). **Test
  connection** really connects through the venue adapters and reports the
  balance or the reason it failed. **Disconnect** signs a venue out — it drops
  the key and the address and saves.
- **Backtest defaults** — capital, sizing, TP/SL, cash cap, timeframe and span,
  fees, and Dynamic TP. These seed the backtest window.
- **Trading defaults** — the trade form's size and leverage, the confirm/stake
  limits, and **live orders** (off by default — see below).
- **General** — the hub's start page and where downloaded candles live.

`settings.json` is safe to read and sync; the keys never touch it.

### Trading

Orders are **dry-run by default**. The trade form's Buy / Sell and the
Polymarket column's bet buttons keep a paper position unless you turn on
**Place real orders** in Settings → Trading defaults *and* the venue is
connected. With it on, an order still waits for the confirm dialog (unless you
turn that off), stakes are capped at the max stake, and the order is signed and
submitted through the venue adapter on a worker thread — the same adapters the
Connection test uses. The result (fill, rejection, or the reason) shows under
the buttons, and every failure is also written to the log
(`~/.local/share/bi-trading/bi-trading.log`) with its full reason. Wiring is in
`bi-trading/state/orders.py`.

A **Polymarket bet** is a dollar amount, not a share count: *Bet UP* with a
$20 stake buys $20 of the UP token at the best prices on offer, up to the ask
plus three cents, and cancels whatever the book cannot fill at once
(fill-and-kill). It takes a position now or tells you why it could not —
*nothing on offer at that price*, *not enough USDC*, *the window has ended*,
*the smallest bet is $1* — and never leaves a half-priced order resting. The
ask comes from the live book, then Gamma's quote, then the other side's bid.

### Saved state

`~/.config/bi-trading/` holds `settings.json`, `strategies.json`, `runs.json` and
the key store, and `runs_data/` beside it with each saved run's trades and
equity curves as Parquet. Point these elsewhere with `BI_TRADING_SETTINGS`, `BI_TRADING_SECRETS`,
`BI_TRADING_STRATEGIES`, `BI_TRADING_RUNS`, `BI_TRADING_MODELS` (trained ML models) and
`BI_TRADING_ARCHITECTURES` (custom layer stacks; see [ml.md](ml.md)); `BI_TRADING_KEYCHAIN=0` forces the file
store, and `BI_TRADING_DATA` overrides the candle folder.

Tests (headless, no network, no sockets):

```sh
uv run pytest -q
```

Lint and tests, exactly as CI runs them:

```sh
uv run ruff check src tests
uv run pytest -q -n auto   # xdist: the suite is embarrassingly parallel
```


The images in this file live in `docs/images/`; regenerate them offscreen with:

```sh
uv run python tools/screenshots.py
```

## Logging

Silent by design. The app is a GUI, so anything writing to the terminal it was
launched from scribbles over work in progress — a stray `print`, a logging
handler on stderr, or Qt's own chatter. `logs.py` points the root logger at a
rotating file and routes Qt's messages into it too, so the process stays quiet.

| Variable | Effect |
| --- | --- |
| `BI_TRADING_LOG` | path to the file (`~/.local/share/bi-trading/bi-trading.log`) |
| `BI_TRADING_LOG=off` | no file at all |
| `BI_TRADING_LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

The file rotates at a megabyte, keeping three. `httpx`, `websockets` and
`asyncio` are held at `WARNING` unless the level is `DEBUG`, because their
output at `INFO` is rarely what is wanted. A second `setup()` is a no-op rather
than a second handler, and any console handler a library installed first is
dropped.

## Look and layout

**Theme.** There is one, dark. Its colours are in `ui/theme_colors.py` and the sheet in
`ui/theme_qss.py` (and its parts).

**Layout memory.** The splitters remember where they were left: the terminal's
two columns and the backtest window's two splits are saved (as ratios, so a
different window size keeps the same split) a moment after you stop dragging, under
`layout` in the settings file. The hub window's size is saved on quit, as before,
and the standalone windows (`bi-trading`, `bi-trading-strat`, `bi-trading-builder`)
keep theirs too. The terminal reopens on the timeframe it was left on, and the Logs
table keeps the widths its columns were dragged to. A damaged `layout` entry is ignored
and the default layout is used. The builder's three columns are locked, so there is
nothing of theirs to keep.

**Keyboard.** Press **?** or **F1** (outside a text field) for the list, with the
view you are in first; it is the same list as here.

| Where | Keys |
| --- | --- |
| Everywhere | **Ctrl+1 … Ctrl+5** Home, Live, Builder, Backtest, Logs · **Ctrl+,** Settings |
| Live | **1–6** timeframe · **← →** pan (Shift: ten) · **↑ ↓** zoom · **Home / End / 0** |
| Backtest | **Space** run, pause, resume · **R** restart · **1–6** resolution |
| Builder | **Ctrl+S** save · **Ctrl+N** fresh draft · **Alt+1/2/3** Rules · Formula · Code |
| Logs | **Ctrl+F** or **/** search · **Esc** clear it · **Ctrl+P** pause · **Ctrl+E** export · **Ctrl+Shift+Backspace** clear the log |

The backtest keys act only when no field has focus, so typing a digit into a field is
left alone. Clear has no confirm, which is why its key is hard to hit by accident.
The terminal keeps its own **1–6** for the card timeframe.
