# Backtest tile — ideas to come back to

Notes from building the `RESULTS` tile. Nothing here is built except the
example curve; the run itself (engine) does not exist yet.

## What the tile is

The bottom-right tile of the strategy window. It sits directly under
`BACKTEST VALUE`, so it is where a finished run's output belongs: the curve,
the headline numbers, and a log of what happened.

It currently paints a **sample** — a fixed-seed walk, marked "example data — no
run yet" — so the shape of the output can be judged before the engine exists.
Every number shown is derived from that same sample, so the line and the
metrics always agree (`lalala.strat_results`).

## Already decided (hard-coded, no switches)

- Fees **and slippage** are fixed.
- **One position at a time.**
- **No trade across a data gap** — the 1m files keep the real venue outages,
  and a run refuses to fill through them.
- **BTC only**; the entry rule lives in its own tile inside a run.

## Built so far

- **Left tile** — the playback: candles rolling past a playhead with the
  entries and exits marked, and live figures above it (PnL, equity, cash,
  drawdown, max drawdown, max gain, streak, best win, worst loss, trades, win
  rate, fees). Preview only: the entry rule is a placeholder and the candles
  come from the newest year on disk, or a fixed-seed sample. See
  `src/lalala/strat_playback.py`.
- **Right column** — `HISTORY` (span, resolution, download), `BACKTEST VALUE`
  (the parameter gallery), `RESULTS` (a sample equity curve and metrics).

## Ideas, in the order I would build them

### 1. Equity curve — done as an example
- [x] Strategy equity, with **buy & hold** faint behind it.
- [x] Mark where the worst drawdown bottomed.
- [ ] Replace the sample with a real run.
- [ ] Feed the curve from the playback's walk, so the left and right tiles
      tell the same story.

### 2. Metrics row — done as an example
- [x] Return, buy & hold, edge, max drawdown, Sharpe, trades, win rate,
      average hold, exposure.
- [ ] Decide which of these is the headline for a quick glance.

### 3. Trade log
- [ ] Every fill, newest first: entry time/price, exit time/price, size,
      P&L, and the exit reason (`TP`, `SL`, trailing reverse, end of data).
- [ ] This is where you spot *why* a run behaved oddly, not just that it did.

### 4. Run log
- [ ] One line per event: started, span, bars used, trades **refused at
      gaps**, finished. Makes the gap rule visible instead of a silent
      assumption.

### 5. Saved runs
- [ ] Each finished run as a row: timestamp, config snapshot (capital,
      TP/SL, sizing), and its headline metrics.
- [ ] Compare two parameter sets side by side instead of remembering numbers.
- [ ] Later: overlay one saved run's curve on the current one.

### 6. Open questions
- [ ] Where `Start backtest` lives. It is in the `HISTORY` tile today, but it
      starts the thing this tile shows — probably belongs here.
- [ ] Is the entry rule a field of *this* run, or a separately saved, named
      strategy picked before starting? The answer decides the data model.
- [ ] Sanity clamps once the engine exists: max cash ≤ capital, position
      value ≤ capital, and the reverse % only meaningful with dynamic TP on.
- [ ] Show the hard-coded fees/slippage somewhere in the UI, so a result is
      interpretable and shareable.
- [ ] Warm-up: if the dynamic TP ever uses ATR or a running peak, a signal
      needs N bars of history before it counts.

## Where things live

| File | What |
| --- | --- |
| `src/lalala/strat_window.py` | the window and the three-tile column |
| `src/lalala/strat_tiles.py` | `HISTORY`: span, resolution, coverage, download |
| `src/lalala/strat_params.py` | `BACKTEST VALUE`: the parameter gallery |
| `src/lalala/strat_results.py` | `RESULTS`: the sample curve and metrics |
| `src/lalala/candles.py` | the local 1m store and coverage rules |
| `src/lalala/candle_download.py` | the Binance fetcher |
