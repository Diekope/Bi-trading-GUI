# To-do

What is still open, roughly by value. Nothing here is promised; it is a menu.
Done work is not listed: the Rust walk core, long-span `ColumnSpan` support,
the Parquet candle store, the fee as a run input, the equity curve, the trade
log and the run log all exist.

## Backtest engine
- **Honour a saved strategy's exit rule.** An applied strategy uses its entry
  only; exits are the params' TP / SL / hold. Run the exit formula in the walk.
- **Slippage** on top of the fee, and **per-venue fees**. Show whatever fees
  and slippage are applied somewhere in the UI, so a result is interpretable
  and shareable.
- **Risk % and Fixed $ sizing** exercised in the walk (the modes exist in the
  tile; the walk reads `balance` and `fixed`).
- **Shorting** and **more than one position**.
- **A worker thread for the run.** `finish()` and `seek` block the UI; move the
  walk off the main thread.
- **Sanity clamps:** max cash <= capital, position value <= capital, and the
  reverse % only meaningful with dynamic TP on.
- **Warm-up:** if the dynamic TP ever uses ATR or a running peak, a signal
  needs N bars of history before it counts.

## Results & visualisation
- **Store the curves in a saved run** (span, params, strategy and trades now)
  so Load redraws the Overview instantly instead of re-running.
- **Overlay a saved run's curve** on the current one.
- **Export trades to CSV**.
- **A Compare part in the backtest window** — it lives only in the builder.
- **Real candles in the trade detail** (a tiny candle strip) instead of the
  price line, and a candle sparkline per row.
- **More stats:** Sortino, exposure, average hold, expectancy. Decide which
  figure is the headline for a quick glance.

## Strategy & builder
- **Sweeps / walk-forward in the backtest window**, builder-only today.
- **Rename and edit a run's strategy inline**, without going to the builder.
- **Open question:** is the entry rule a field of a run, or a separately saved,
  named strategy picked before starting? The answer decides the data model.

## Workflow & feel
- **Remember window sizes** (the splitters) between sessions.
- **Keyboard shortcuts** for Run / Pause / Restart and the timeframe pills.
- **A light theme.**

## Quality
- **Visual regression / screenshot tests** for the two windows.
- **Stricter lint rules** (`UP`, `B905`, `SIM105`) and a type checker in CI.
- **Narrow the broad `except Exception` handlers** in the venues, feeds and
  order store, and log what they swallow.
- **Split the largest modules** (`strat_playback.py`, `formula_builder.py`,
  `theme_qss.py`, `cards.py`).
