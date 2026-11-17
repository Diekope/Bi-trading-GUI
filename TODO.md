# To-do

What is still open, roughly by value. Nothing here is promised; it is a menu.
Each item carries a priority: `[high]`, `[med]` or `[low]`.
Done work is not listed: the Rust walk core, long-span `ColumnSpan` support,
the Parquet candle store, the fee as a run input, the equity curve, the trade
log and the run log all exist.

## Backtest engine
- [med] **Per-venue fees**, and a fee/slippage line in the results so a result is
  interpretable and shareable.
- [med] **The streamed walk** (spans over `CORE_MAX` bars) still steps in Python.
- [med] **A worker thread for `seek`.** `finish()` already walks off the main thread;
  the replay scrubber's `seek` still blocks the UI; move the
  walk off the main thread.
- [high] **Sanity clamps:** max cash <= capital, position value <= capital, and the
  reverse % only meaningful with dynamic TP on.
- [med] **Warm-up:** if the dynamic TP ever uses ATR or a running peak, a signal
  needs N bars of history before it counts.

## Results & visualisation
- [med] **Overlay a saved run's curve** on the current one.
- [low] **Export trades to CSV**.
- [low] **A Compare part in the backtest window** — it lives only in the builder.
- [low] **Real candles in the trade detail** (a tiny candle strip) instead of the
  price line, and a candle sparkline per row.
- [med] **More stats:** Sortino, exposure, average hold, expectancy. Decide which
  figure is the headline for a quick glance.

## Strategy & builder
- [low] **Sweeps / walk-forward in the backtest window**, builder-only today.
- [low] **Rename and edit a run's strategy inline**, without going to the builder.
- [med] **Open question:** is the entry rule a field of a run, or a separately saved,
  named strategy picked before starting? The answer decides the data model.

## Workflow & feel
- [low] **Remember window sizes** (the splitters) between sessions.
- [low] **Keyboard shortcuts** for Run / Pause / Restart and the timeframe pills.
- [low] **A light theme.**

## Quality
- [low] **Visual regression / screenshot tests** for the two windows.
- [med] **Stricter lint rules** (`UP`, `B905`, `SIM105`) and a type checker in CI.
- [med] **Narrow the broad `except Exception` handlers** in the venues, feeds and
  order store, and log what they swallow.
- [low] **Split the largest modules** (`strat_playback.py`, `formula_builder.py`,
  `theme_qss.py`, `cards.py`).
