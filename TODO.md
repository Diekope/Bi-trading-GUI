# To-do

What is still open, roughly by value. Nothing here is promised; it is a menu.
Each item carries a priority: `[high]`, `[med]` or `[low]`.
Done work is not listed: the Rust walk core, long-span `ColumnSpan` support,
the Parquet candle store, the fee as a run input, the equity curve, the trade
log and the run log all exist.

## Design
- [med] **Merge `dev` and `ml`.** The design and the venue switch are on `dev`; the ML screens,
  the backtest fixes and the manual-bet settlement are on `ml`. Merge them, then restyle the ML
  screens and the Model builder from the screenshots (`web/docs/screens/15`, `16` and `20` on
  `planning`).
- [med] **Portfolio screen and the PAPER chip.** The design has a Portfolio screen (the live and
  paper books, day PnL with a percent) and a PAPER equity chip in the top bar. There is no paper
  account here, only one paper position.
- [med] **Polymarket backtest.** The design's "Bet value" card (max entry price, min edge, fee on
  wins, slippage in cents, exit mode, daily loss limit, max bets per day) and its Brier and
  resolved win and loss figures need a binary-payoff simulator, which needs historical
  Polymarket prices. Only the card's title follows the venue today.
- [low] **Per-venue variables in the Builder.** Polymarket should offer price, model_p, edge,
  spread, liquidity, days_left, btc and target; Hyperliquid open, high, low, close, volume,
  funding, oi and model_p. It is one mixed list now; only the wording follows the venue.
- [low] **Model and edge on the Polymarket Live screen.** Model P(up) and Edge show a dash
  until there is a model on this branch.
- [low] **Hyperliquid screen details.** The design has coin pills (HYPE, ETH, SOL) and TP % and
  SL % fields; the terminal is BTC only and an order has no take profit or stop yet.
- [low] **Backtest column without scrolling.** The right column (History, values, Strategy,
  Save and Load run) still scrolls as one block; fit it, or let only its lists scroll.
- [low] **PAPER / LIVE switch.** It shows whether real orders are armed but cannot change it:
  arming stays in Settings. Decide whether a switch in the top bar is safe.
- [low] **Strategy tiles with a result.** Home's tiles show a return only when there is candle
  history on disk to score the rule with.
- [low] **Number fields.** The design right-aligns numbers in Settings; they are left-aligned.

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

## Quality
- [low] **Goldens for the screenshot tests on Linux.** `tests/golden/` was drawn on
  macOS. The comparison is coarse (8px blocks) so another system's fonts should pass,
  but CI has never run it: if it fails there, redraw the goldens on that system
  (`UPDATE_GOLDEN=1`) and keep both sets.
