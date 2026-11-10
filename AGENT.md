# Making lalala agent-friendly

An **agent** (an LLM with tools) should be able to do three things without a
human clicking:

1. **create a strategy**,
2. **backtest it** over history,
3. **trade it** — place and manage orders.

This document is the plan. Nothing below is built yet except where it says so;
the branch is `agent`.

The good news: the hard parts already exist. The work is mostly a **headless
extraction**, a **thin agent interface**, and **guardrails**.

---

## Why the app is already close

| Piece | Where | State |
| --- | --- | --- |
| Strategy DSL | `engine/formula.py` | a **custom parser** (not `eval`) — safe to hand an agent; `parse()` validates |
| Backtest engine | `engine/core.py` (+ Rust `lalala_core`) | pure functions; the walk is native-or-Python |
| Formula evaluator | `engine/formula_eval.py` | NumPy entry signals, reason labels, report |
| Saved strategies / runs | `state/strategies.py`, `state/runs.py` | plain JSON files |
| Venue adapters | `venues/` | `submit` / `cancel` / `balances`, asyncio, no Qt |
| Order gate | `state/orders.py` | `config_for`, `armed`, `can_trade`; paper/dry-run by default |
| Candle store | `data/candles.py` | Parquet, read as arrays |

What's missing is a **display-free entry point** and a **protocol** an agent
speaks.

---

## Step 1 — Extract a headless engine (no Qt)

`ui/strat/strat_playback.py` imports PySide6 at the top, so `build_session(...)`
drags Qt in. Move the display-free half into `engine/`:

- `ColumnSpan`, `Playback`, `BacktestSession`, `build_session`,
  `bollinger_entries_columns`, `random_entries`, `load_span`.
- The tiles (`PlaybackTile`, `CandlePlayer`) stay in `ui/strat`.

Result: `import lalala.engine.session` works with **no display and no Qt**.

## Step 2 — A non-Qt order facade

`state/orders.py` is a `QObject` (Qt signals). Keep it for the GUI; add a plain
facade for agents that **returns** results instead of emitting:

```python
# engine or state, no Qt
def place(venue, order, config) -> OrderAck   # connects, submits, closes
def balances(venue, config) -> list[Balance]
def cancel(venue, instrument, venue_order_id, config) -> None
```

Both the GUI and the MCP server then call the same code.

## Step 3 — The agent interface (MCP server)

An **MCP server** is the natural fit (Claude and other agents speak it). A new
console script, `lalala-mcp`, exposing a small, guarded toolset:

| Tool | Arguments | Does |
| --- | --- | --- |
| `list_markets` | — | markets / spans available |
| `get_candles` | symbol, span, resolution | OHLCV as arrays (bounded) |
| `list_strategies` | — | saved strategies |
| `create_strategy` | name, timeframe, entry, exit | validate via `formula.parse`, save |
| `backtest` | strategy **or** formulas, span, params | run; return pnl, sharpe, max DD, trades, win rate, (optionally trades) |
| `list_runs` / `get_run` | — / name | saved runs |
| `account_status` | — | which venues are connected, armed? |
| `balances` | venue | free collateral |
| `positions` | venue | open positions (needs Step 5) |
| `place_order` | symbol, side, size, price?, reduce_only? | Hyperliquid perp |
| `place_bet` | market, outcome, stake, price? | Polymarket |
| `cancel_order` | venue, order id | (needs Step 5) |
| `panic_close_all` | — | cancel all + flatten (needs Step 5) |

Notes:

- **Backtest tools are always on. Trading tools are off by default** and only
  appear when the server is started with `--allow-trading`.
- Everything returns **structured JSON** so an agent can reason over it.
- The strategy DSL means the agent never runs arbitrary Python.

Alternatives if MCP is not wanted: a `lalala` **CLI** with `--json`, or a
JSON-RPC socket the GUI also uses. For a code-capable agent, exposing the
headless library plus this file may be enough.

## Step 4 — Guardrails (required before live trading)

An agent placing real orders is the risky part. Enforce **server-side**, not in
the prompt:

- **Dry-run by default.** `armed()` off means paper. A tool to arm must be
  explicit and logged.
- **A freeze flag + `panic_close_all`** (a kill switch that does not depend on
  the agent).
- **Limits**: max position, max stake per order, daily loss limit — already in
  the settings model; enforce them where the order is built, not in the UI.
- **Rate limits** per tool and per minute.
- **Idempotency**: a client id per order so a retry cannot double-fill.
- **Audit log**: append every tool call and every order (what, when, args,
  ack) to a file.
- **Symbol / venue allowlist**, and an optional **testnet-only** mode.
- Keys stay in the Keychain; the agent never receives them.

## Step 5 — Missing pieces before live trading is safe

- **Cancel + open-orders list** (there is no cancel UI yet).
- **Venue position sync** (the app currently shows a local proxy on a fill).
- **A true market order** (today it is an aggressive limit).
- **Headless backtest CLI** so runs are reproducible from a script.

---

## Connecting accounts

An agent does **not** get the keys — the human connects once, and the tools read
the saved account. Connecting is the same for the app or the agent.

### Polymarket

1. Install the SDK (needed to place orders and to check the balance):

   ```sh
   uv sync --extra venues
   ```

2. Open **Settings** (the gear in the hub's rail, `uv run lalala-hub`).

3. In the **Polymarket** card fill in:
   - **Private key** — the key that signs the order (`0x…`, 64 hex). Stored in
     the **macOS Keychain**, never in a settings file.
   - **Wallet address** — the **funder**: the address that actually holds the
     USDC.e used to buy shares.
   - **Wallet type**:
     - **EOA / wallet** — key and funds on the same address.
     - **Email / Magic** — a Magic/email proxy wallet (signature type 1).
     - **Browser proxy** — a browser proxy wallet (signature type 2).
     Choose the wrong one and the check will say the key signs as a different
     address than the funder.
4. **Test connection** — derives the API credentials and checks the signer
   against the funder; it must pass.
5. **Save**.

What is stored where:

- `~/.config/lalala/settings.json` — the **public** bits: funder address and
  signature type. Safe to read and sync.
- Keychain (or a `0600` `secrets.json` on non-macOS) — the **private key**.
- `LALALA_SECRETS`, `LALALA_KEYCHAIN=0`, `LALALA_SETTINGS` override the paths.

For an agent: after the account is connected and saved, `account_status` /
`balances` report it and `place_bet` can use it. The agent never sees the key.

### Hyperliquid

Same card flow: an **API wallet** address + its **private key** (a key that can
trade but not withdraw), **Mainnet/Testnet**, **Test connection**, **Save**.
Use **Testnet** while validating an agent.

---

## Definition of done

- [ ] `engine/` has a Qt-free session builder; `import lalala.engine.session`
      works headless.
- [ ] A non-Qt order facade shared by the GUI and the server.
- [ ] `lalala-mcp` server with the read/backtest tools.
- [ ] Trading tools behind `--allow-trading`, off by default.
- [ ] Guardrails: freeze flag, panic close, limits, rate limits, idempotency,
      audit log, allowlist.
- [ ] Cancel + open-orders + venue position sync.
- [ ] A headless backtest CLI.
- [ ] `AGENT.md` (this file) linked from `README.md`.
