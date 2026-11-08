# To-do

Ideas for what can be added or changed, roughly by value. Nothing here is
promised; it is a menu. The Rust core for the walk is **done** (see
`rust/lalala_core`, wired for short/medium spans), and the **fee** is now a run
input.

## Backtest engine
- **Wire the core for long spans too.** Today a span is streamed above a cap
  (`CORE_MAX` bars) and the core only drives short/medium runs. Move the bar
  loop fully into Rust (array-backed candle store) so a decade of minutes uses
  the core as well.
- **Honour a saved strategy's exit rule.** An applied strategy uses its entry
  only; exits are the params' TP / SL / hold. Run the exit formula in the walk.
- **Slippage** on top of the fee, and **per-venue fees**.
- **Risk % and Fixed $ sizing** exercised in the walk (the modes exist in the
  tile; the walk reads `balance` and `fixed`).
- **Shorting** and **more than one position** (the mock hints at "Short" and
  "one position at a time").
- **A worker thread for the run.** `finish()` and `seek` block the UI; move the
  walk off the main thread.

## Results & visualisation
- **Store the curves in a saved run** (span, params, strategy and trades now)
  so Load redraws the Overview instantly instead of re-running.
- **Export trades to CSV**.
- **A Compare part in the backtest window** — it lives only in the builder.
- **Real candles in the trade detail** (a tiny candle strip) instead of the
  price line, and a candle sparkline per row.
- **More stats:** Sortino, exposure, average hold, expectancy.

## Strategy & builder
- **Sweeps / walk-forward in the backtest window**, again builder-only today.
- **Rename and edit a run's strategy inline**, without going to the builder.

## Workflow & feel
- **Remember window sizes** (the splitters) between sessions.
- **Keyboard shortcuts** for Run / Pause / Restart and the timeframe pills.
- **A different candle store** (parquet / arrays) than the per-year CSV, to
  speed the reads the trade view and coverage do.
- **A light theme.**

## Quality
- **Visual regression / screenshot tests** for the two windows.
- **A build check** for the Rust extension in CI (it is optional; the Python
  fallback runs when it is absent).
