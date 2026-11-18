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
