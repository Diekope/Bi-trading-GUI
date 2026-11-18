"""A saved model's call on the live chart, and what to bet on it.

`live_call` scores the newest **closed** bar: the bar still forming is left out,
because a backtest only ever sees bars that have closed and a call made on a half
bar would not be the call the model was judged on. `decide` turns a call into a
side, or into the reason there is none, by the strategy's two thresholds and the
model's *min edge* against Polymarket's price.

A model's P(up) is a probability over its own horizon (`horizon` bars of its
timeframe), counted from the close of the bar it was made on. A Polymarket window
asks whether BTC ends five minutes above where the window opened, so a call is a
call on that window only when two things hold, and `window_reason` checks both:

* the horizon is five minutes (5m x 1, 1m x 5, 15m is too long, and so on), and
* the call was made on the bar that closed exactly as the window opened, so its
  horizon is the window itself and not a stretch that began earlier.

A 5m model stays valid for the whole window; a 1m model only for the first minute.
Otherwise there is no bet, and the bar says why.

Qt-free; scikit-learn and torch are imported only when a model scores.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bi_trading.ml.features import feature_matrix, gap_invalid
from bi_trading.ml.train import (
    INPUT_BARS,
    LOOKBACK,
    TIMEFRAME_MINUTES,
    MLError,
    TrainedModel,
)

__all__ = [
    "Decision",
    "LiveCall",
    "WINDOW_MINUTES",
    "decide",
    "horizon_minutes",
    "horizon_note",
    "live_call",
    "window_reason",
]

WINDOW_MINUTES = 5   # the Polymarket up/down window

# Bars handed to the features: the longest look-back, a network's window, and room.
MIN_BARS = LOOKBACK + INPUT_BARS + 40
TAIL = 400


@dataclass(frozen=True)
class LiveCall:
    p: float | None = None
    stamp: int = 0          # the closed bar it was made on (its open time, ms)
    reason: str = ""        # why there is no call


@dataclass(frozen=True)
class Decision:
    side: str | None = None  # "up", "down" or None
    reason: str = ""
    edge: float | None = None


def live_call(trained: TrainedModel, candles, now_ms: int) -> LiveCall:
    """P(up) on the newest closed bar of `candles` (objects with t, o, h, l, c, v)."""
    config = trained.config
    step = TIMEFRAME_MINUTES.get(config.timeframe, 1) * 60_000
    bars = list(candles)
    if bars and bars[-1].t + step > now_ms:
        bars = bars[:-1]                          # the forming bar
    if len(bars) < MIN_BARS:
        return LiveCall(reason=f"warming up: {len(bars)} of {MIN_BARS} bars")
    bars = bars[-TAIL:]
    stamps = np.array([bar.t for bar in bars], dtype=np.int64)
    if (np.diff(stamps) != step).any():
        # A hole in the recent bars: a backtest would not trade across it either.
        window = LOOKBACK + (INPUT_BARS if config.spec.is_custom else 1)
        if gap_invalid(stamps, window)[-1]:
            return LiveCall(reason="a gap in the recent bars")
    columns = {
        "open": np.array([bar.o for bar in bars]),
        "high": np.array([bar.h for bar in bars]),
        "low": np.array([bar.l for bar in bars]),
        "close": np.array([bar.c for bar in bars]),
        "volume": np.array([bar.v for bar in bars]),
    }
    if trained.predictor is None:
        raise MLError("the model has no weights")
    try:
        matrix = feature_matrix(columns, config.features, config.custom)
    except (KeyError, ValueError) as exc:
        return LiveCall(reason=f"a feature could not be built: {exc}")
    window = INPUT_BARS if config.spec.is_custom else 1
    last = len(matrix) - 1
    if not np.isfinite(matrix[last - window + 1 : last + 1]).all():
        return LiveCall(reason="warming up: a feature is not ready")
    p = float(trained.predictor.predict_up(matrix, np.array([last]))[0])
    return LiveCall(p=p, stamp=int(stamps[-1]))


def decide(
    p: float | None,
    up: float,
    down: float,
    min_edge: float,
    up_ask: float | None,
    down_ask: float | None,
) -> Decision:
    """The side to bet, by the thresholds and the edge over the market's price.

    UP when P(up) >= `up`, DOWN when P(up) <= `down`. The edge is how far the
    model's probability for that side sits above the ask: P(up) - ask(UP), or
    1 - P(up) - ask(DOWN). Below `min_edge` there is no bet.
    """
    if p is None:
        return Decision(reason="no call yet")
    if p >= up:
        side, probability, ask = "up", p, up_ask
    elif p <= down:
        side, probability, ask = "down", 1.0 - p, down_ask
    else:
        return Decision(reason=f"P(up) {p:.2f} is between {down:.2f} and {up:.2f}")
    if min_edge <= 0:
        return Decision(side=side)
    if ask is None or ask <= 0:
        return Decision(reason="no price to compare with", edge=None)
    edge = probability - ask
    if edge < min_edge:
        return Decision(reason=f"edge {edge:+.2f} is below {min_edge:.2f}", edge=edge)
    return Decision(side=side, edge=edge)


def horizon_minutes(timeframe: str, horizon: int) -> int:
    """How far ahead a model looks, in minutes."""
    return TIMEFRAME_MINUTES.get(timeframe, 1) * int(horizon)


def horizon_note(trained: TrainedModel) -> str:
    """A caution when the model's horizon is not Polymarket's five minutes."""
    config = trained.config
    minutes = horizon_minutes(config.timeframe, config.horizon)
    if minutes == WINDOW_MINUTES:
        return ""
    return (
        f"the model looks {minutes} min ahead ({config.horizon} x {config.timeframe}), "
        f"not this {WINDOW_MINUTES}-minute window: no bets"
    )


def window_reason(trained: TrainedModel, call_stamp: int, window_start_ms: int) -> str:
    """Why this call is not a call on this window, or "" when it is.

    `call_stamp` is the open time of the bar the call was made on; that bar must
    close exactly as the window opens.
    """
    config = trained.config
    note = horizon_note(trained)
    if note:
        return note
    step = TIMEFRAME_MINUTES.get(config.timeframe, 1) * 60_000
    ends = call_stamp + step
    if ends == window_start_ms:
        return ""
    if ends < window_start_ms:
        return "the model has no call for this window yet"
    minutes = (ends - window_start_ms) / 60_000
    return f"this call was made {minutes:g} min into the window: waiting for the next one"
