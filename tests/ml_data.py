"""A synthetic market the ML tests share: returns that undo themselves.

Each bar's return is minus 0.4 times the one before plus noise, so the sign of
the last return says something about the next one (about 63 percent of the time)
and a model that reads `ret1` can find it. No candle files, no network.
"""

from __future__ import annotations

import numpy as np


def make_market(bars: int = 6000, seed: int = 7, step_ms: int = 60_000):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.002, bars)
    returns = np.zeros(bars)
    for index in range(1, bars):
        returns[index] = -0.4 * returns[index - 1] + noise[index]
    close = 100.0 * np.cumprod(1.0 + returns)
    open_ = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0.0, 0.001, bars)) * close
    columns = {
        "open": open_,
        "high": np.maximum(open_, close) + spread,
        "low": np.minimum(open_, close) - spread,
        "close": close,
        "volume": rng.uniform(1.0, 10.0, bars),
    }
    stamps = 1_700_000_000_000 + np.arange(bars, dtype=np.int64) * step_ms
    return columns, stamps
