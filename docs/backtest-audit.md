# Backtest audit

Date: 2026-11-19. Scope: the backtest engine and its run pipeline (`engine/core.py`,
`rust/bi_trading_core/src/lib.rs`, `ui/strat/playback_session.py`, `playback_data.py`,
`engine/stats.py`, `engine/formula_eval.py`, `data/candles.py`, `ml/store.py`) and
`docs/backtest.md`. Findings come from reading the code; the tests were not run and the
Python stepped walk (`playback_walk.py`) was not read in full.

Levels: **Critical** = results are wrong or misleading today. **High** = results are
biased in the strategy's favour or cannot support a decision. **Medium** = weak evidence
or a missing safeguard. **Low** = polish and upkeep.

Open the visual version: [backtest-audit.html](backtest-audit.html).

| # | Level | Finding |
| --- | --- | --- |
| 1 | Critical (fixed) | No gap handling, though the docs say there is |
| 2 | Critical (fixed) | Resampling ignores time |
| 3 | Critical (scoped, not built) | The traded venue is not modelled (Polymarket payoff, perp costs) |
| 4 | High (fixed) | Optimistic fills: entry at signal close, TP on touch, stops fill through gaps |
| 5 | High (fixed) | ML results are selection-biased (test set reused) |
| 6 | High (fixed) | The random benchmark is one draw and does not match the walk |
| 7 | High (partly fixed) | Data source differs from the venue (Binance spot vs Hyperliquid) |
| 8 | Medium (partly fixed) | No significance or robustness tooling |
| 9 | Medium (fixed) | Weak and inconsistent risk metrics |
| 10 | Medium (fixed) | Buy and hold ignores costs and uses a different capital base |
| 11 | Medium (fixed) | Warm-up is off by default |
| 12 | Medium (partly fixed) | Sizing and liquidity are unrealistic |
| 13 | Low | Two walks to keep in sync by hand (Python and Rust) |
| 14 | Low (fixed) | Docs contradict each other on TP and SL on one candle |
| 15 | Low | Compare page and walk-forward limits (TODO items) |

## Critical

### 1. No gap handling, though the docs say there is
**Status: fixed (2026-11-19).** The walk takes a per-bar `gaps` flag (the bar is the last
before a hole). An open position is closed at that bar's close as a market exit with
reason `gap`, and nothing opens on it; the random baseline does the same. Done in the Rust
core, the Python walk, the chunked walk (a hole between two year files is found by looking
at the next file's first bar) and the stepped playback, with tests in `tests/test_gaps.py`.
The text below is the original finding.

`docs/backtest.md` states "a trade is refused across a data gap rather than filled
through it", and `data/candles.py` says a run "refuses to trade across a gap". The walk
(`engine/core.py` `_python_walk`, `lib.rs` `run_walk`) never reads a timestamp. Entries,
the hold limit (7 bars by default) and TP / SL all count bar indices.

- A trade open before the 2017-09-06 Binance outage exits hours later at whatever price
  comes next, booked as an ordinary `time` or `sl` exit.
- The files keep their real gaps on purpose, so every gap is a hole the walk crosses.
- Fix: pass the timestamps into the walk (Python and Rust), and either refuse to enter
  when the next bars are not contiguous or force-close at the last bar before a gap.

### 2. Resampling ignores time
**Status: fixed (2026-11-19).** `_compact_arrays` buckets by `timestamp // period` and keeps
only buckets with every minute present, so bars stay on the clock after an outage and the
hole is visible to the gap rule. `count_bars`, `iter_candles` and the chunked stream agree.
The text below is the original finding.

`_compact_arrays` and `_iter_file` in `ui/strat/playback_data.py` merge every N
consecutive rows of a year file, by position.

- After any gap, every later 5m / 15m / 1h bucket is off the clock grid, and a bucket
  can straddle the gap.
- Each year is compacted on its own, so the last bucket of a year is short.
- The ML layer protects against holes in features; the backtest does not, so a model
  trained with that protection is scored on bars built without it.
- Fix: bucket by `timestamp // period`, drop or flag incomplete buckets.

### 3. The traded venue is not modelled
**Status: scoped, not built.** A binary-payoff simulator needs historical Polymarket
prices that the app does not store, so it cannot be done from the current data. What was
done: `docs/backtest.md` now has a "What this backtest is not" section that says it is a
spot-style BTC simulation and lists what it does not model. The fix below is still open.
The text below is the original finding.

The live targets are Polymarket 5-minute binary markets and Hyperliquid perps. The
backtest simulates a spot-style position with TP, SL and a hold limit.

- Polymarket pays 1 per share on a win and 0 on a loss, settled at the window end; the
  edge is `P - ask`. The backtest has no market price, so `min edge` is "not applied"
  there (`docs/ml.md`). A Polymarket strategy cannot be validated by this engine.
- Hyperliquid perps have funding, leverage, margin and liquidation. None exist here.
- Fix: a second simulator for the binary payoff (needs historical Polymarket prices, or
  an explicit fixed-price assumption), and a funding and liquidation model for perps.
  Until then, label the backtest as spot-style only.

## High

### 4. Optimistic fills
**Status: fixed (2026-11-20).** Entries fill at the next bar's open by default (`backtest.entry`; `close` brings the old behaviour back), and that bar's own range can stop them out. A stop or trail the market gapped past fills at the open; a target it gapped past at the better open. A take profit needs the market to trade through its price by `backtest.limit_through` (0.01% by default). The trailing stop is now a market exit and slips. Done in the Rust core, the Python walk, the whole-span and streamed seeks, the stepped playback and the ML builder's `rule_stats`, with tests in `tests/test_fills.py`. Not modelled: a maker fee for the take profit (every fill pays the one fee, which errs against the strategy) and queue position. The text below is the original finding.

- **Entry:** every entry fills at the close of the bar that produced the signal, with
  slippage only. No next-bar-open option.
- **Take profit:** fills at its exact price whenever a wick touches it, with no
  trade-through requirement and no queue position.
- **Stop and trail:** fill at the stop or trail price even if the bar gapped past it. The
  trailing stop is booked as `tp` and gets no slippage, though it behaves like a stop.
- **Fees:** one flat fee on every fill; no maker / taker split although TP is treated as
  a limit order.
- Fix: a next-bar-open entry mode, fill at `min(open, stop)` for stops, trade-through for
  limits, trail booked as a market exit.

### 5. ML results are selection-biased
**Status: fixed (2026-11-20).** The last 15% of the labelled bars are set aside before any fit, tune or threshold choice, and the test curve stops where they begin. *Score hold-out (once)* trades them with the model's own settings and keeps the answer; asking again returns it and never recomputes. Every training on the same data counts as a variant tried, and the hold-out's p-value is shown raw and multiplied by that count (`ml/holdout.py`, `tests/test_holdout.py`). Still true: the test part is re-traded as thresholds move and those moves are not counted, so read it as a development figure and the hold-out as the verdict. Models saved before this have no hold-out. The text below is the original finding.

A model only has a call on its test part, and the ML builder re-trades those bars while
you move the thresholds. Auto-tune, model choice and threshold choice all use the same
data, so the test set stops being out-of-sample after a few changes. There is no second
hold-out and no correction for the number of variants tried. `docs/ml.md` already notes
that honest models sit near 51 to 54% accuracy and lose money after costs.

- Fix: a locked final hold-out that the UI scores once, and a counter of variants tried.

### 6. The random benchmark is one draw and does not match the walk
**Status: fixed (2026-11-20).** The baseline is now random signals through the same walk (same fills, exits, sizing and costs) at the strategy's own signal rate and long/short mix. A finished run also walks 100 more random runs from their own seeds on a background thread and the results say *beats X% of 100 random runs*, with the 5th, median and 95th percentile (`tests/test_baseline.py`). Limits: a span streamed a year at a time has no signals to copy and uses 3% long only with no band, and a span too long for enough runs shows no band. The text below is the original finding.

`random_entries` uses a fixed seed (1234) and a fixed 3% entry chance.

- "Beats random" is a single sample, not a distribution.
- The baseline simulates its own occupancy from unslipped entry prices, with no exit rule
  and no trailing TP. The walk then ignores or reorders its entries, so the trade count
  and timing do not match the strategy it is compared with.
- A strategy that goes long and short is compared with a long-only baseline.
- Fix: run many seeds through the real walk and show a percentile band; match the
  strategy's trade count and side mix.

### 7. Data source differs from the venue
**Status: partly fixed (2026-11-20).** The venue serves only its latest ~5,000 candles, so its history cannot replace the stored one. `python -m bi_trading.data.basis` compares the stored Binance bars with Hyperliquid's over that window (close gap in basis points, relative bar width, how often a level is touched on one venue and not the other), saves the report and the backtest's evidence line shows it, or says the venue data was not compared (`tests/test_basis.py`). Still open: a backtest on the venue's own candles, which needs a stored feed over time. The text below is the original finding.

History is Binance spot BTCUSDT. Orders go to Hyperliquid perps and Polymarket, whose
prices, spreads and wicks differ, most of all on 1m bars. A fill that worked on Binance
data can be impossible on the venue.

- Fix: store the venue's own candles for the traded market, or at least report the basis
  between the two.

## Medium

### 8. No significance or robustness tooling
**Status: partly fixed (2026-11-19).** The results tile now shows the t-stat, p-value and 95% interval of the average trade, a per-trade Sharpe, a warning under 30 trades, and a by-year table. Still open: a bootstrap or permutation test, and a parameter sweep over the full span (the Compare page still covers the last 2,000 bars). The interval assumes independent trades.

No confidence interval, t-stat on expectancy, minimum trade count, bootstrap or
permutation test. The TP x SL sweep and walk-forward on the Compare page cover only the
last 2,000 bars, not the full span. There is no per-year or per-regime breakdown.

### 9. Weak and inconsistent risk metrics
**Status: fixed (2026-11-19).** Yearly Sharpe and Calmar (spans of 30 days or more), longest time under water, a per-trade Sharpe on the same basis as the Sortino, and PnL at 2x fees and slippage (a first-order estimate from the trade log).

Sharpe is per bar, not annualised, and includes flat bars. Sortino is per trade, so the
two cannot be compared. No Calmar, time under water, exposure-adjusted return, or a
costs-stress view (result at 2x fees and slippage).

### 10. Buy and hold ignores costs and uses a different capital base
**Status: fixed (2026-11-19).** The benchmark puts in `Max cash` (not the whole book), pays the same fee and slippage on entry, and keeps the rest in cash. No exit cost: it is marked to market.

The benchmark is `capital * close / first_close`: no fee, no slippage, whole book in. The
strategy trades a fraction (`max_cash`, default $2,000), so the percent comparison is
between different amounts of risk.

### 11. Warm-up is off by default
**Status: fixed (2026-11-19).** The default is 100 bars (the live chart keeps 300). A settings file that already says 0 keeps 0.

`warmup` defaults to 0, so indicator rules can fire on unsettled history at the start of
a run.

### 12. Sizing and liquidity are unrealistic
**Status: partly fixed (2026-11-19).** An entry is capped at a share of the entry bar's traded value (`backtest.participation`, 1% by default, in the walk in Rust and Python and the stepped playback; settings file only). Still open: minimum lot, tick rounding, market impact beyond flat slippage, and the ML builder's own simulator (`rule_stats`), which has neither this cap nor the data-gap rule.

One position at a time, sized from deployable cash and a `Max cash` cap, so returns
depend on the cap. No minimum lot, tick rounding, volume limit or market impact. Volume
is loaded but never used for fills.

## Low

### 13. Two walks to keep in sync by hand
`_python_walk` and `run_walk` are kept equal by tests. Any fix for gaps or fills (items
1 and 4) has to be made twice, plus in `run_random` and `_python_random_entries`.

### 14. Docs contradict each other
**Status: fixed (2026-11-20).** The playback section now says the stop is booked, as the code and the run controls do. The text below is the original finding.

The playback section of `docs/backtest.md` says a candle that touches both TP and SL
pays the target. The code, and the run-controls section, book the stop.

### 15. Compare page and walk-forward limits
From `TODO.md`: the Compare page runs on preview candles where `model_p` is unknown, and
walk-forward covers built-in models only, not custom torch networks.

## What is solid
- The Rust and Python walks mirror each other, and chunked walking carries state across
  pieces.
- Parquet storage is repaired and time-sorted.
- A stop wins on a candle that touches both stop and target.
- Slippage applies to market exits.
- ML splits are time-ordered and purged.

## Suggested order
Done: gaps and time-aligned resampling (1, 2), fill realism (4), the locked ML hold-out (5),
the Monte Carlo random baseline (6) and the cost stress (9).

Next:
1. Decide the target: add a binary-payoff simulator, or state spot-style only (item 3). It
   needs historical Polymarket prices, so start by recording the live ones.
2. Store the venue's own candles over time so the backtest can run on them (rest of item 7).
3. A bootstrap or permutation test and a full-span sweep (rest of item 8).
4. Minimum lot, tick rounding and market impact (rest of item 12).
