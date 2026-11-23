# To-do

What is still open, roughly by value. Nothing here is promised; it is a menu.
Each item carries a priority: `[high]`, `[med]` or `[low]`.
Done work is not listed: the Rust walk core, long-span `ColumnSpan` support,
the Parquet candle store, the fee as a run input, the equity curve, the trade
log and the run log all exist.

## Logs
- [low] **Polymarket holdings from the venue.** Sell works on the shares this session
  bought (counted from the fills); read the wallet's positions so a restart, or a bet
  placed elsewhere, can be sold from here too.
- [low] **Auto-sell.** Auto-bet holds to settlement; let a strategy's exit rule (or a
  take profit) sell early through the same fast path.
- [low] **Auto-bet beyond UP.** It bets UP on a mean-reversion signal; let a strategy
  choose the side, and size the stake from the strategy rather than the bar.
- [low] **Hyperliquid fills.** Its orders log as `ACCEPTED`, never `FILLED`, because
  the answer carries no match. Read the fills (or user events) to log them.
- [low] **Archive during a session.** Older rows move to Parquet only at launch, so
  a very long session keeps appending to one JSON file until the next start.
- [low] **Strategy stats beyond today.** The strategy filter and its figures are for
  today; add a range (week, all) and a per-strategy summary.

## Backtest
- [high] **Polymarket payoff simulator.** The backtest is spot-style: a share that pays $1 or
  nothing, and the edge over the ask, cannot be tested. It needs historical Polymarket prices,
  which the app does not store: start by recording the live ones to disk (audit item 3).
- [med] **Venue candles over time.** Hyperliquid serves only its latest ~5,000 candles. Store
  its own as they arrive so a backtest can run on them; `python -m bi_trading.data.basis`
  reports the gap to the Binance history meanwhile (audit item 7).
- [med] **Significance tests.** A bootstrap or permutation test, and a take profit x stop loss
  sweep over the whole span instead of the last 2,000 bars (audit item 8).
- [med] **Execution realism.** Minimum lot, tick rounding and market impact. Give the ML
  builder's own simulator the data-gap rule, the volume cap and the trailing stop too (audit
  item 12).
- [low] **Count threshold moves.** The ML test part is re-traded as thresholds move, and those
  moves are not counted against the hold-out's p-value (audit item 5).
- [low] **Maker fee and queue.** A take profit pays the one flat fee and fills with no queue
  position (audit item 4).
- [low] **Baseline on streamed spans.** A span read a year at a time has no signal rate to
  copy and no random band (audit item 6).
- [low] **Remove the old random-entry code.** `random_entries*` in Rust and Python is unused;
  remove it when the shared native module can be rebuilt without breaking another branch
  (audit item 13).
- [low] **Polymarket fees on settled bets.** A settled bet pays $1 a share or loses its stake;
  any fee the market charges is not taken off, for manual and automatic bets alike.

## ML
- [med] **Auto-sell for ML bets.** A model bet holds to settlement; let a model flip, or a call
  that turns back inside its thresholds, sell early through the fast path.
- [low] **Live scoring off the main thread.** A call is computed once per bar on the GUI thread;
  a large custom network could make that bar visibly slow.
- [low] **Walk-forward for custom networks.** Only built-in models retrain through time; a
  torch network would need a warm start per stretch to stay tractable.
- [low] **Other markets.** Training reads the BTC store only; Hyperliquid candles for other
  coins would need their own history.
- [low] **Compare page with a model.** The builder's compare page runs the rule on the
  preview candles, where `model_p` is unknown, so a model strategy shows no trades there.
- [low] **Code mode in the model builder.** It shows the PyTorch module read-only; a blank,
  editable code model is not offered.

## Quality
- [low] **Goldens for the screenshot tests on Linux.** `tests/golden/` was drawn on
  macOS. The comparison is coarse (8px blocks) so another system's fonts should pass,
  but CI has never run it: if it fails there, redraw the goldens on that system
  (`UPDATE_GOLDEN=1`) and keep both sets.
