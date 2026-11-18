# To-do

What is still open, roughly by value. Nothing here is promised; it is a menu.
Each item carries a priority: `[high]`, `[med]` or `[low]`.
Done work is not listed: the Rust walk core, long-span `ColumnSpan` support,
the Parquet candle store, the fee as a run input, the equity curve, the trade
log and the run log all exist.

## Backtest engine
- [low] **Formula strategies on spans over `CORE_MAX`.** The two built-in rules now
  walk a long span in pieces (see the backtest docs), but a formula strategy still
  loads the whole span, because an indicator needs its look-back: a piece would have
  to be handed the last N bars of the one before it, N being the longest window the
  formula uses. Out of reach with today's data (BTC 1m since 2017 is about 5M bars).

## Results & visualisation
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
