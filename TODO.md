# To-do

What is still open, roughly by value. Nothing here is promised; it is a menu.
Each item carries a priority: `[high]`, `[med]` or `[low]`.
Done work is not listed: the Rust walk core, long-span `ColumnSpan` support,
the Parquet candle store, the fee as a run input, the equity curve, the trade
log and the run log all exist.

## Backtest engine
- [low] **Use the chunked walk for streamed spans.** `core.walk_chunk` can now
  walk a long span in pieces, carrying the book from one piece to the next
  (tested equal to one whole walk, native and Python). What is left is the
  session side: spans over `CORE_MAX` (12M bars) still step in Python because
  `adopt` wants the whole span's stamps and candles, and a formula strategy
  cannot be chunked (an indicator needs its look-back). Out of reach with
  today's data (BTC 1m since 2017 is about 5M bars).

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
