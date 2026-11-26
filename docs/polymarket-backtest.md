# Polymarket backtest

Bets on the five-minute BTC up/down markets, run against the real past markets.
Back to the [README](../README.md). It is the Backtest view while the venue
switch is on **Polymarket**; with Hyperliquid on, the Backtest view is the candle
walk described in [backtest.md](backtest.md).

A Polymarket strategy does not go long or short. It buys an **Up** or a **Down**
share at the market price (0 to 1), then either **cashes out** early, when the
exit rule fires, or holds to **settlement**: a share pays $1 if its side won
and $0 if not. One bet at most per market.

In the Builder (venue switch on Polymarket) a strategy has three rules:
**BET UP WHEN**, **BET DOWN WHEN** and **CASH OUT WHEN**. An empty rule never
bets, so a strategy can be UP only, DOWN only or both. The first minute either
bet rule is true places the bet; a minute at which both are true places none (the
rules disagree). The variables rail keeps the Binance candle (`open high low close
volume`), the Polymarket market (`up_price down_price minute seconds_left`) and,
in the cash-out rule, the open bet (`price entry pnl tp sl bars`) in separate groups.
The bet-down rule is stored as the strategy's second entry rule (`short_entry`).

## The data

| Source | What | Where |
| --- | --- | --- |
| Binance 1m candles | the same files the other backtest uses | `data/candles/BTC-<year>-1m.parquet` |
| Polymarket history | per settled market: outcome, volume, and the Up share's price samples | `data/candles/PM-<year>-5m.parquet` |

The Polymarket files come from two public endpoints (no key): Gamma
`/markets?closed=true&slug=…` for the market, its token ids and how it settled,
and CLOB `/prices-history?market=<up token>&fidelity=1` for the prices. The
**Download Polymarket prices** button fetches every missing market since
2026-02-12, the earliest one Polymarket has (about 82,000 markets, about an hour),
resumable and safe to stop. A market Polymarket does not know is stored as
"not found", so it is not asked for again, and nothing is invented for it.

`data/polymarket_history.py` is the downloader and the store; the parsing and the
store are pure and tested against fake endpoints.

## The window

The Backtest view on the Polymarket venue is laid out like the Hyperliquid one:

| Area | What it holds |
| --- | --- |
| BACKTEST (top left) | the status line, Run (Space), a progress bar, the figures (PnL, equity, max drawdown, ROI on stake, bets, win rate, cashed out, average buy price, share of bets at a real price), and the picked bet's Up price over its five minutes with the buy and the sale marked |
| HISTORY | what is on disk for Polymarket and Binance, a span (all history, 90, 30 or 7 days), **Download Polymarket prices** (stop it by pressing it again) |
| BET VALUE | start capital, stake % of equity, first decision minute, half spread in cents, fee %, TP and SL in % of the share price |
| STRATEGY | a saved strategy, **Create a strategy** (opens the Builder), and its three rules |
| RESULTS | Overview: figures, the strategy's equity against always-UP and always-DOWN, drawdown, how bets end, PnL distribution. Bets: the table, newest first; pick a row to see it above |

There is no Save run / Load run, Compare or playback here yet (see TODO.md). Opening the
window is not a run: nothing is computed until Run.

## What a run does

For every market whose five minutes of candles are all there, one row per minute:
the Binance bar and the Up price at that minute's close. A rule runs on those rows,
so it can mix the two (see [formulas.md](formulas.md)):

    close < bollinger_lower(close, 20, 2) and up_price < 0.45

| Word | Meaning |
| --- | --- |
| `up_price`, `down_price` | the share prices, 0 to 1 (`down_price` is `1 - up_price`) |
| `minute` | 1 to 4: how far into the market the decision is |
| `seconds_left` | seconds until it settles |
| `open high low close volume` | the Binance bar that just closed |

A decision at minute `k` sees the candle that closed at that moment and the last
price sampled at or before it, never anything later. The first minute the entry
rule is true (from the "first decision minute" you set) buys the share. From then
on the exit rule is checked each minute; it also sees `price` (what a sale fetches
now), `entry`, `pnl` (in %), `tp`, `sl` and `bars`. If it fires the shares are sold
at the **bid**; otherwise they are held to settlement. Settlement uses how
Polymarket resolved the market, and where that is unknown, Binance's close against
the open (marked "est.").

Buying costs the price plus the **half spread** you set; selling returns the price
minus it; the **fee %** is taken on the stake and on a sale's proceeds.

## Where a price is simulated

A market with no downloaded prices, or a minute before its first sample, gets a
fair price from the Binance candles (`engine/binary_price.py`): a share is the
chance the move so far is not undone,

    P(up) = Phi( ln(S_now / S_open) / (sigma * sqrt(seconds_left)) )

with `sigma` the per-second volatility of the last hour of 1-minute returns. The
result says how many bets were entered at a real price and how many outcomes were
estimated.

## What it cannot tell you

- **No order book.** Depth and spread were never recorded; the half spread is an
  assumption you set, and a large stake would move the price.
- **Samples are sparse and can be stale.** About one price a minute, and a sample is
  the last trade or quote at or before the decision, up to a minute old. A rule
  that finds "cheap" shares may be seeing a stale price that was gone when the order
  would have filled. Measured on the first 8,000 markets (2026-11-24), the model's
  Brier score at minute 2 is 0.160 against 0.190 for the downloaded prices, so the
  prices are *noisier* than a simple model, not sharper. Both are well calibrated
  on average (a 0.30 price went Up 29% of the time, a 0.70 price 69%).
- **Settlement source differs.** Polymarket resolves on its own reference price;
  the candles are Binance spot. Where they disagree a bet can look wrong.
- **One regime.** The history starts 2026-02-12. A t-stat from a few thousand
  bets in one market is a hint, not a proof.
- Baselines in the result (always UP, always DOWN at the same minute, held to
  settlement) show what the market pays with no rule. Over the first 8,000 markets
  Up won 50.6% and always-UP returned +0.3% on stake at zero spread.

## Files

    data/polymarket_history.py   download + Parquet store
    engine/binary_price.py       the fair price and its calibration
    engine/binary.py             the walk (no Qt)
    ui/strat/strat_pm.py         the window
