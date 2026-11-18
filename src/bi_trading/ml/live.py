"""A saved model's call on the live chart, and what to bet on it.

`live_call` scores the newest **closed** bar: the bar still forming is left out,
because a backtest only ever sees bars that have closed and a call made on a half
bar would not be the call the model was judged on. `decide` turns a call into a
side, or into the reason there is none, by the strategy's two thresholds and the
model's *min edge* against Polymarket's price.

A model's P(up) is a probability over its own horizon (`horizon` bars of its
timeframe). Polymarket's window is five minutes, so the edge is only a like for like
comparison for a 5m model with a horizon of 1; `horizon_note` says so otherwise.

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

__all__ = ["Decision", "LiveCall", "decide", "horizon_note", "live_call"]

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


def horizon_note(trained: TrainedModel) -> str:
    """A caution when the model's horizon is not Polymarket's five minutes."""
    config = trained.config
    minutes = TIMEFRAME_MINUTES.get(config.timeframe, 1) * config.horizon
    if minutes == 5:
        return ""
    return (
        f"the model looks {minutes} min ahead ({config.horizon} x {config.timeframe}), "
        "not this 5-minute window"
    )
