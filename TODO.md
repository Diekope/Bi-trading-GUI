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

## Trading speed
- [med] **Fast buy and sell on Hyperliquid.** Possible: the warm, reused client already
  covers it (it is shared by every venue), but the order itself is not as quick as
  Polymarket's yet. It is a resting limit order (`Gtc`), sent through the SDK's
  blocking call on a thread, and its answer carries no fill. To do: a marketable
  order (`Ioc` at a price a little through the book, as Sell does on Polymarket), a
  one-click **Close** that reads the open position from the venue and sells exactly
  that (reduce-only), the fill (size and price) read from the answer so it logs
  `FILLED`, and the same Sell/Close buttons in the terminal. Try it on the testnet
  first (Settings → Accounts → Network).
- [low] **A TESTNET badge** wherever orders can go out, so the network is never in doubt.

## Quality
- [low] **Goldens for the screenshot tests on Linux.** `tests/golden/` was drawn on
  macOS. The comparison is coarse (8px blocks) so another system's fonts should pass,
  but CI has never run it: if it fails there, redraw the goldens on that system
  (`UPDATE_GOLDEN=1`) and keep both sets.
