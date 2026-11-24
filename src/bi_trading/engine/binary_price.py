"""A simulated price for a Polymarket five-minute BTC share, from BTC candles.

Used only where no real price history was downloaded. A binary share pays $1 if
BTC ends the window at or above where it opened, so its fair price is the
probability of that. With BTC as a random walk over the seconds left (zero
drift), the chance the move so far is not undone is

    P(up) = Phi( ln(S_now / S_open) / (sigma * sqrt(seconds_left)) )

with `sigma` the per-second volatility of recent one-minute returns. It is a
model, not a quote: the backtest says how many windows used it, and
`calibration` compares it with the real prices that exist.
"""

from __future__ import annotations

import math

import numpy as np

SIGMA_LOOKBACK = 60       # minutes of returns behind the volatility
SIGMA_FLOOR = 1e-6        # per second, so a flat spell cannot divide by zero
PRICE_FLOOR = 0.01
PRICE_CEIL = 0.99

_erf = np.frompyfunc(math.erf, 1, 1)


def minute_sigma(closes: np.ndarray, lookback: int = SIGMA_LOOKBACK) -> np.ndarray:
    """Per-second volatility at each minute, from the returns up to it."""
    closes = np.asarray(closes, dtype=float)
    returns = np.zeros(len(closes))
    if len(closes) > 1:
        returns[1:] = np.log(closes[1:] / closes[:-1])
    squares = np.concatenate(([0.0], np.cumsum(returns**2)))
    index = np.arange(len(closes))
    lo = np.maximum(0, index - lookback + 1)
    count = index - lo + 1
    total = squares[index + 1] - squares[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        per_second = np.sqrt(total / np.maximum(count, 1)) / math.sqrt(60.0)
    return np.where(count >= 5, np.maximum(per_second, SIGMA_FLOOR), SIGMA_FLOOR)


def fair_up(
    s_open: np.ndarray, s_now: np.ndarray, sigma: np.ndarray, seconds_left: np.ndarray
) -> np.ndarray:
    """The Up share's fair price, clipped to what a tick can show."""
    s_open = np.asarray(s_open, dtype=float)
    s_now = np.asarray(s_now, dtype=float)
    left = np.maximum(np.asarray(seconds_left, dtype=float), 1.0)
    z = np.log(s_now / s_open) / (np.asarray(sigma, dtype=float) * np.sqrt(left))
    phi = 0.5 * (1.0 + np.asarray(_erf(np.asarray(z) / math.sqrt(2.0)), dtype=float))
    return np.clip(phi, PRICE_FLOOR, PRICE_CEIL)


def calibration(
    predicted: np.ndarray, realised: np.ndarray, bins: int = 10
) -> list[tuple[float, float, int]]:
    """(mean predicted, share that went Up, count) per probability bin."""
    predicted = np.asarray(predicted, dtype=float)
    realised = np.asarray(realised, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    out: list[tuple[float, float, int]] = []
    for i in range(bins):
        top = predicted <= edges[i + 1] if i == bins - 1 else predicted < edges[i + 1]
        mask = (predicted >= edges[i]) & top
        if mask.any():
            out.append((float(predicted[mask].mean()), float(realised[mask].mean()), int(mask.sum())))
    return out
