# ML strategies

Train a model to call the next move, then trade its calls. Back to the [README](../README.md).

Two views, both under **ML** in the hub's rail (`Ctrl+6`):

- the **ML strategy builder**: data, features, target, model, validation and a trading rule, in
  one page;
- the **model builder**: design your own network, layer by layer, and save it for the first.

They need the optional `ml` extra: `uv sync --extra ml` (scikit-learn, SciPy, torch). The
rest of the app starts without it; training says what is missing instead of failing.

## The ML strategy builder

Three columns and a results panel, as in the mock.

**Data & features.** BTC candles from the local store (see [backtest](backtest.md)), at the
timeframe you pick, over every year on disk. The bars are split **by time, never shuffled**:
the first 60% train, the next 20% validate, the last 20% test, and the test part is only
looked at once the model is chosen. Ten features are offered, each computed from bars up to
the current one and never beyond (return over 1, 5 and 15 bars, volatility σ(20), ATR(14),
EMA 20/50 ratio, z-score(20), Bollinger %B, RSI(14), volume z-score); eight are on by default.
**+ Custom feature** takes a formula in the [rule language](formulas.md) over the bar's own
columns, e.g. `(high - low) / close`, checked as you type.

**Target & model.** *Predict* up / down or up / flat / down over a *horizon* of bars. For
up / down, a move smaller than *Min move %* is left out of training, since it is closer to
noise than to a direction; for three classes it is the *flat* class. Pick a model:

| Model | What it is |
| --- | --- |
| Gradient boosting | scikit-learn `HistGradientBoostingClassifier` (trees, depth, learning rate) |
| Random forest | `RandomForestClassifier` (trees, depth, min leaf) |
| Logistic regression | a standardised linear baseline |
| Neural net (MLP) | scikit-learn's MLP (units, layers, learning rate) |
| *your own* | a custom network from the model builder, trained with torch |

*Auto-tune* tries a handful of settings and keeps the one with the lowest validation loss.
Training runs on a worker thread; **Stop** takes effect at the next batch or retrain.
A run fits on at most 300,000 bars (strided across the training part), which keeps a decade of
minutes tractable.

**Trading rule.** The model's output is **`model_p` = P(up)**. *Bet UP / Long if P(up) ≥* and
*Bet DOWN / Short if P(up) ≤* are the two thresholds; saving writes them as an ordinary
strategy that goes both ways: entry `model_p >= 0.60`, short entry `model_p <= 0.40`.
*Edit exit rules* sets its exit rule; *Open in formula* opens it in the strategy builder.
Moving a threshold re-trades the test bars at once, without retraining.

*Min edge vs market price* is stored with the model for live Polymarket bets. A backtest has
no market price to compare with, so it is **not applied there** (and not yet in auto-bet).

*Walk-forward retraining* re-scores the test part with models refitted every *N* days on the
past only (the last `horizon` labelled bars before each stretch are held out, since their label
needs bars from the stretch itself). It is slower, built-in models only, and is the better
estimate of what live trading would have done.

**Results · test set.** Accuracy, AUC (up against the rest) and log loss for train, valid and
test. A train − test accuracy gap above 5 points is flagged as overfitting. *Feature
importance* is permutation importance on the validation part: how much shuffling a feature
raises the log loss, scaled so the top one is 100. The curve trades the calls over the test
bars **by the backtest's own rules**, with the take profit, stop loss, hold limit, fee,
slippage, position size and Max cash from Settings (a bar that reaches both stop and target books the
stop; the target fills at its price; every other exit slips), one trade at a time, against buy
and hold. *Signals* is the number of trades and *Hit rate* the share that ended in profit after
costs, so the screen and a backtest of the saved strategy tell the same story.

**The hold-out.** The last 15% of the labelled bars (`holdout` in the training config) are
set aside before anything else: no fit, auto-tune, threshold or model choice reads them, and
the test curve above stops where they begin. *Score hold-out (once)* (after saving) trades
them with the model's own thresholds, costs and fills and keeps the answer in the model's file;
asking again returns that answer and never recomputes it. *Models tried* counts every training
on this data (the same resolution and hold-out), and the hold-out's p-value (a coin-flip test
on the hit rate) is shown both raw and multiplied by that count. The test part is still
re-traded as thresholds move, so after a few changes read it as a development figure and the
hold-out as the verdict. Models saved before this have no hold-out: retrain them.

Read those figures for what they are. On real BTC candles an honest model usually sits at 51 to
54% accuracy, and after costs a strategy that trades every call loses money. The screen is
built to show that, not to hide it.

### Data hygiene

Training and scoring refuse to learn from what a backtest would not trade through:

- rows out of time order (a stray stamp of 0, a block written twice) are dropped when the
  candles are read; `candles.repair` cuts them from a year's file for good;
- no feature or window is built across a hole in the candles: the bars after a hole, for as
  long as the longest look-back, have no call, and a bar whose target lies across a hole is not
  labelled;
- the parts are **purged**: a label looks `horizon` bars ahead, so the last labels of train
  and of valid are left out, and the parts share no price.

## Saving, and the backtest

*Save* writes two things: the trained model, and a saved strategy whose rules read `model_p`
and which carries the model's name (`model` in `strategies.json`). From then on it is a normal
strategy: the backtest picker lists it, the builder opens it, and re-saving it in the builder
keeps the link as long as a rule still names `model_p`. *Run full backtest* saves, opens the
backtest on it and starts a run.

In a backtest, `model_p` is the saved model's P(up) for every bar of the span, and it is
**unknown where the model could have learned from the bar**: before the model's test part
began there is no call, so a rule on `model_p` cannot trade there. The run is set to the years
of the test part for you, and its note says so (`model … scores 68,240 bars (from 2024-11-23)`).
Where walk-forward predictions exist they replace the single model's. A model trained on 5m
bars cannot score a 1m run; the note says that too and the run trades nothing. Scoring a span
takes seconds on a long one, so it runs on a worker when the backtest is pointed at the
strategy (the note reads `scoring the span with …`), and the scores are cached: a second run on
the same span, or after changing parameters, costs nothing. A saved run remembers when its
model was trained and says so when it is loaded after the model was retrained.

A rule that only compares `model_p` (`model_p >= 0.6`, `model_p - 0.5 > 0.1`) uses the fast
vectorised path. One that puts it through a window (`sma(model_p, 3)`) falls back to the
bar-by-bar walk, which is slower on a long span.

## The model builder

*Layers* on the left (Dense, Dropout, BatchNorm, Activation; LSTM, GRU, Conv1D, Attention) are
clicked into the stack, or moved by dragging a layer's handle. The input is always the last 30
bars of the chosen features; the output layer is added for you, sized by the target (one
sigmoid unit for up / down, three softmax units for up / flat / down). *Start from* loads a
preset (an MLP, an LSTM, a Conv1D, or a blank stack). *Code* shows the PyTorch module the stack
stands for, read-only. *Training* sets loss, optimizer, learning rate, epochs, batch size and
early stopping (on the validation loss, patience three).

The **layer guide** explains the layer picked, and the **validator** says what would fail
before anything trains: shapes that do not line up, a sequence layer after a Dense, dropout of
1 or more, attention channels that do not split into the heads, a learning rate outside (0, 1].
Errors disable *Save to my models* and *Use in strategy*; warnings (a Dense that flattens the
bars, a capacity above 1,000 parameters per feature) do not.

A saved model is an architecture only: it is trained in the ML builder, on the features and
target picked there, and appears in its model list with an *Edit* button.

## Where things are

```
src/bi_trading/ml/        Qt-free: features.py, spec.py (layers, validator), models.py
                          (scikit-learn), nets.py (torch), train.py, store.py
src/bi_trading/ui/ml/     ml_builder.py, model_builder.py, ml_style.py, workers.py
~/.config/bi-trading/architectures.json   custom layer stacks (BI_TRADING_ARCHITECTURES)
~/.config/bi-trading/models/<name>-<digest>.json   a trained model's settings and figures (BI_TRADING_MODELS)
~/.config/bi-trading/models/<name>-<digest>.bin    its weights (joblib); .wf.npz holds walk-forward calls
```

The file name carries a digest of the exact name, so "A b" and "a-b" are two models. The weights
are a pickle, so the figures file stores their SHA-256 and a model whose weights no longer match
is refused before anything is unpickled. Even so, do not drop a file from somewhere you do not
trust into the models folder. Deleting an ML strategy in the builder deletes its model, unless
another strategy still uses it, and saving will not replace a strategy that is not this model's.

## Live: the terminal's strategy bar

Saved ML strategies are listed in the Live view's strategy picker as `ML · name`. Picking one
moves the chart to the model's timeframe, and the bar then shows the model's **P(up)** where the
Bollinger band was, and `UP`, `DOWN` or `FALSE` as the signal.

- **The call** is the model scored on the newest **closed** bar. The bar still forming is left
  out, because a backtest only sees closed bars. It is scored once per bar. With too few bars,
  a hole in the recent ones, or a feature not ready, there is no call and the bar says why.
- **The side** is `UP` at P(up) at or above the strategy's upper threshold and `DOWN` at or below
  the lower one. A long-only strategy never bets down, a short-only one never bets up.
- **Min edge** now applies here: UP needs P(up) minus the UP ask to reach it, DOWN needs
  (1 minus P(up)) minus the DOWN ask. Below it the bar says `edge +0.02 is below 0.05`. With no
  price there is no bet when an edge is asked for.
- **Auto-bet** takes the call through the same path as the Bollinger one: at most one bet per
  five-minute window, the max stake, the daily loss limit, and a **paper** bet unless live orders
  are armed and Polymarket is connected. It fires when the side turns on and again on each new
  bar that still calls it. Every call is logged as a signal with its reasons.

**The horizon must be the window.** A model's P(up) is a probability over its own horizon,
counted from the close of the bar it was made on, and a Polymarket window asks whether BTC ends
five minutes above where it opened. So a call is a call on a window only if:

- the model looks **five minutes** ahead (`5m` x 1, or `1m` x 5; the ML builder says how far ahead
  it looks next to the horizon field), and
- the call was made on the bar that **closed exactly as the window opened**.

A 5m model stays valid for the whole window; a 1m model only for the window's first minute. Any
other horizon, or a call made later in the window, gets no bet and the bar says why (`the model
looks 15 min ahead (3 x 5m), not this 5-minute window: no bets`, `this call was made 3 min into
the window: waiting for the next one`); the P(up) is still shown. The edge compares the model's
probability from the window's open with the ask now, so it is a rough guide late in a window.
Test a model in paper mode before arming real orders.

## Elsewhere in the app

Home has an **ML strategies** card listing them with their model's return on its test part, and
the saved-strategy list marks them `ML`; neither can score them on the preview candles, where
`model_p` does not exist. The builder's report and Compare page say the same instead of showing
an empty result. "ML strategy builder" is a start page in Settings. Training and saving write to
the trading log (Logs view, source `system`, origin `ml`).
