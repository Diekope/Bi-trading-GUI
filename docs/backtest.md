# Backtest

The backtest window: results, run controls, playback and layout. Back to the [README](../README.md).

## Results tile

![The backtest window's results tile: the three curves revealed as the walk runs](images/part-results.png)

The results tile has **two parts**, picked by the pills in its header.
**Overview** shows the figures (PnL, Sharpe, Max DD, Trades, Win rate, Fees),
the three curves — **strategy** (amber), **random buy** (indigo) and **buy &
hold** (grey dashed) with a running total each in a legend — a **drawdown**
curve under them, and, down the right column, **how trades end** (a bar per
exit — take profit, stop loss, time) with the **PnL distribution** of the trade
returns beneath it. **Trades** is a filterable table —
`Entry · Market · Side · In → Out · Size · PnL · Exit` — with a search box and
side / result / exit filters, and a detail panel for the picked trade: its
entry and exit (time · price), the reason, how long it ran and its fees, its
return, and a little line of the price through the trade. **Picking a row
brings that trade out on the candle chart** — a violet band over the stretch it
held, a line across it, and its entry and exit prices marked. A window of
candles around the trade is read on demand and shown in place of the live
tail, so a trade well before the last candles can be looked at **without
moving the run**. It reads the newest `SHOWN` (400) trades so a long run stays
light.

Everything is drawn as **return from the start**, not as a dollar balance. Over
a long span buy and hold compounds many times over while a strategy that
deploys a fraction of the book per trade barely moves; in dollars the first
flattens the others into the axis. In percent the two strategies stay readable,
and buy and hold is left to run off the top, with its number in the legend and
a note when it does.

Random buy is the benchmark that matters: it opens on a coin flip with the same
exits, sizing and fees, so an entry rule that cannot beat it has no edge. Buy
and hold puts the whole book in at the first bar and never sells.

The curves are sampled **once per tick**, not once per bar — a run can be
millions of bars and the chart cannot use more points than it has pixels.

`Sizing` percentages are a share of what `Max cash $` allows the run to trade
with, not of the whole book: with a $2,000 cap, a 10% position is $200 a
trade.

## Backtest tile

![The backtest window: the walk and its figures across the top left, the span, parameters and strategy in a narrow column, and the results full width along the bottom](images/backtest.png)

The window is two rows, as in the mock. The **top row** is the run: the
playback panel on the left, and a narrow column on the right stacking the
history controls, the run's inputs and the strategy. The **bottom row** is the
results tile, spanning the full width under both.

Below the history controls sits a gallery of the run's inputs — three or four
to a line, wrapping with the tile's width:

| Field | Meaning |
| --- | --- |
| `Initial capital $` | the book the run starts with |
| `Sizing` | how `Position` is read: `Balance %`, `Fixed $` or `Risk %` |
| `Position` | the value itself; its caption and its bounds follow `Sizing` |
| `TP %` / `SL %` | take profit and stop loss, percent from entry |
| `Max cash $` | most cash the run may trade with; anything above it is set aside |
| `Fee %` | commission each way, percent of the notional |
| `Dynamic TP` | switch: let the take profit trail |
| `Reverse % to close` | pull-back from the peak that closes a trailing TP; only live while the switch is on |

Only BTC is in scope. The starting values live in the same
`~/.config/bi-trading/settings.json`, under `backtest` (or `BI_TRADING_BACKTEST_*`),
and are clamped on the way in — an unknown `sizing` mode falls back to
`balance`. Numeric fields take a dot as the decimal mark whatever the system
locale, and are bounded so a percentage cannot exceed the whole book.

The right column's tiles **share its whole height** — the inputs take the most,
the small tiles the least — so they always fill it and never scroll. The
results tile spans the window's full width below.

Decided and hard-coded for the run: one position is held at a time, and a trade
is refused across a data gap rather than filled through it.

**Slippage** is what a market fill gives away, per side, in percent (the
*Slippage %* parameter, `slippage` in the settings file; 0.01 by default). An
entry fills that much worse than the close it was decided on — higher for a
long, lower for a short — and every exit slips against the trade, except the
take profit, which is a resting limit order and fills at its price. The fee is
charged on top. The builder's previews use the same 0.01%.

A trade ends at the first of: its **stop**, its **take profit**, the strategy's
**exit rule**, or the **hold limit** — by default **7 candles** (the *Hold
(candles)* parameter, `hold` in the settings file; 0 means no limit). When one
candle reaches both the stop and the take profit, the candle cannot say which
came first, so the **stop is booked**.

The **strategy tile** picks the entry rule: the two built-ins (**Random buy**,
the baseline, and **Bollinger reversion**), then every **saved strategy** from
`strategies.json`. Picking a saved one points the run at its entry rule — the
rule is checked over the whole span and the walk opens on the bars it fires on
and so does its **exit rule**, checked at each bar's close while a trade is
open, after the params' take profit and stop loss (which still act inside the
bar) and before the hold limit; a trade it closes reads `Rule`. A saved
strategy's side is honoured too. **SAVE RUN** keeps the run under a name: the
span, resolution, parameters, the strategy (name, entry, short entry, exit, side), and what
it produced. The small facts go in `~/.config/bi-trading/runs.json`
(`BI_TRADING_RUNS` overrides it); the trades and both equity curves go in Parquet
files in `runs_data/` beside it, so the index stays a few kilobytes. An older
`runs.json` with its trades inline is migrated on first read (the original is
kept as `runs.json.bak`). **LOAD RUN** opens one again: the controls are set
back, including the saved strategy's exit and side, and the run is **walked
straight to the end**, so every result and trade is there at once.

The bar loop has a **native core** in Rust (`rust/bi_trading_core`, a PyO3
extension wrapped by `bi_trading.engine.core`). A span small enough to hold in memory
(≤ `CORE_MAX`, 1.5M bars) is loaded and its entries worked out up front, so the
walk and every seek are a slice plus one native pass — **Finish** and a jump
are instant. The native pass does everything the Python one does: long and
short, both ways at once, risk sizing, the trailing take profit, and the exit
rule, which is compiled to a small program the core runs bar by bar
(`compile_exit`). A longer span is streamed off disk and stepped in Python. When the
extension is not built, `bi_trading.engine.core` falls back to the same walk in Python, so
nothing depends on it. Build and install it with `uv sync --extra native`
(uv rebuilds it when `rust/bi_trading_core/src` changes).

## Playback tile

The left half holds the run as a moving picture: bare candles scroll past a
playhead while a row of figures above recomputes on every candle — PnL,
equity, Sharpe, drawdown, max drawdown, max gain, the current streak, the best
winning and worst losing streak, trades, win rate, fees.

Its header carries **Restart**, a **speed** picker (`×1 ×2 ×4 ×8`), and the
**Run** button, which turns into **Pause** while the walk plays (then
**Resume**, and back to **Run** once it is spent). Under the header a **progress
bar** and its readout count the candles — `100% · 196,496 / 196,496 candles`.
The trail always follows the newest candle; a trade picked in the results
rewinds the walk to it so it is on screen.

- **Equity is realised only.** An open position is carried at what it cost, so
  entering a trade moves nothing but its fee; the result lands when it closes.
  Unrealised profit is deliberately not shown.
- **Sharpe is not annualised** — the walk is minutes long, so multiplying by
  the square root of a year would produce a meaningless number. It is the mean
  over deviation of the per-bar book returns.
- **The marks**: an amber ▲ under a candle is an entry, a grey ▼ above one is
  an exit.
- **It stops at the end** of its series rather than looping, and says how the
  run finished. Starting over is a button, never automatic.

**What the loop covers.** The **whole selected span**, streamed off disk bar by
bar — never loaded into memory. A decade of one-minute bars is 4.8M rows and
about 240 MB; holding them as objects would cost far more than the walk does,
so only what the picture and the figures need is kept: a rolling window of the
last `CHART_BARS` (600) bars, the most recent entries and exits, and running
totals. The Sharpe is a running mean and variance rather than a stored series.
Peak memory for a full 2017–2026 walk is around 60 MB.

**It fast-forwards.** A run over any amount of data is watched in about
`WATCH_MS` (two minutes): `stride` bars are consumed per tick, so a few hundred
bars play one at a time and a decade of minutes advances in jumps. The note
says which — `fast-forward ×2,017`. Bar-by-bar over ten years of minutes would
otherwise take about two and a half days to watch.

A span with nothing on disk falls back to a fixed-seed sample and says so.

Fills are the optimistic kind — the target and the stop are both read off one
candle's range, so a candle that touches both pays the target.

Nothing runs when the window opens: the tile sits idle until **Run** (in its
header) or **Start backtest** (in the history tile) is pressed. A change of
span, resolution, strategy or parameter is only remembered — the walk keeps
its place and the note says what is ready — so those buttons are the only
thing that starts a run over.

## Window layout

```
+-------------------------------------------------------------+
|        Volume  Bollinger                       HL ● 210 ms  |
+-------------------------+-----------------------------------+
|                         |  HYPE                       84.6  |
|                         |  1m 3m 5m 15m 30m 1h              |
|                         |  |╿╽│╿╽ ...              │ 85.3   |
|                         |  |╿╽│╿╽                  │        |
|        Polymarket       +-----------------------------------+
|  UP 64.5¢  DOWN 35.5¢   |  xyz:CL  [XYZ]               96.7 +|
|  19:35–19:40  closes…   |  1m 3m 5m 15m 30m 1h              |
|  PM DELAY ● 26 ms       |  |╿╽│╿╽ ...                       |
|  BTC chart + tape       |                                   |
+-------------------------+-----------------------------------+
```

Palette (`theme.py`):

| Token | Hex | Role |
| --- | --- | --- |
| `CANVAS` | `#0b0b0d` | main window, darkest |
| `PANEL` | `#17181b` | floating cards, a shade lighter |
| `BORDER` | `#25262a` | card edge |
| `ACCENT` | `#e0b341` | amber accent, last-price line |
| `UP` / `DOWN` | `#3ddc84` / `#ff5c5c` | candles, latency colours, Polymarket sides |
