"""Features and targets: what a model reads and what it is asked to predict.

Every feature is causal: the value at bar `t` uses bars `0..t` only, so a
model never sees the future through its inputs. The first bars, where a window
has not filled yet, are NaN and are left out of training.

The target looks forward on purpose: for the bar at `t`, did the close `h`
bars later end above or below it. The last `h` bars have no answer and carry
the label -1, like a move too small to call.

Pure NumPy, no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

import numpy as np

__all__ = [
    "CUSTOM_PREFIX",
    "FEATURES",
    "Feature",
    "TARGETS",
    "class_balance",
    "custom_feature",
    "default_features",
    "feature_label",
    "feature_matrix",
    "gap_invalid",
    "horizon_gap",
    "ordered_mask",
    "make_target",
    "time_split",
]

Columns = dict  # field name -> 1-D array: open, high, low, close, volume

# A custom feature is named `custom:<name>` and carries its formula elsewhere.
CUSTOM_PREFIX = "custom:"


# -- rolling helpers (causal, NaN until the window is full) -----------------


def _rolling_mean(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if period < 1 or len(values) < period:
        return out
    total = np.cumsum(np.insert(values.astype(float), 0, 0.0))
    out[period - 1 :] = (total[period:] - total[:-period]) / period
    return out


def _rolling_std(values: np.ndarray, period: int) -> np.ndarray:
    """Population std over `period` bars, computed in blocks so a decade of
    minutes never builds a (bars × period) array at once."""
    out = np.full(len(values), np.nan)
    if period < 2 or len(values) < period:
        return out
    values = values.astype(float)
    block = 200_000
    for start in range(0, len(values) - period + 1, block):
        stop = min(len(values), start + block + period - 1)
        windows = np.lib.stride_tricks.sliding_window_view(values[start:stop], period)
        out[start + period - 1 : stop] = windows.std(axis=1, ddof=0)
    return out


def _smooth(values: np.ndarray, alpha: float, seed: float) -> np.ndarray:
    """out[0] = seed, then out[i] = alpha * values[i] + (1 - alpha) * out[i-1]."""
    from scipy.signal import lfilter

    out = np.empty(len(values))
    out[0] = seed
    if len(values) > 1:
        out[1:], _ = lfilter(
            [alpha], [1.0, -(1.0 - alpha)], values[1:], zi=[(1.0 - alpha) * seed]
        )
    return out


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    if not len(values):
        return np.empty(0)
    out = _smooth(values.astype(float), 2.0 / (period + 1.0), float(values[0]))
    out[: period - 1] = np.nan
    return out


def _shifted(values: np.ndarray, bars: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if bars < len(values):
        out[bars:] = values[:-bars] if bars else values
    return out


def _ret(close: np.ndarray, bars: int) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return close / _shifted(close, bars) - 1.0


def _zscore(values: np.ndarray, period: int) -> np.ndarray:
    mean = _rolling_mean(values, period)
    std = _rolling_std(values, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(std > 0, (values - mean) / std, 0.0)
    out[np.isnan(std)] = np.nan
    return out


def _volatility(columns: Columns) -> np.ndarray:
    return _rolling_std(_ret(columns["close"], 1), 20)


def _atr(columns: Columns) -> np.ndarray:
    high, low, close = columns["high"], columns["low"], columns["close"]
    previous = _shifted(close, 1)
    true_range = np.fmax(
        high - low, np.fmax(np.abs(high - previous), np.abs(low - previous))
    )
    true_range[0] = high[0] - low[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        return _rolling_mean(true_range, 14) / close


def _ema_ratio(columns: Columns) -> np.ndarray:
    close = columns["close"]
    with np.errstate(divide="ignore", invalid="ignore"):
        return _ema(close, 20) / _ema(close, 50) - 1.0


def _bollinger_pct_b(columns: Columns) -> np.ndarray:
    close = columns["close"]
    mean, std = _rolling_mean(close, 20), _rolling_std(close, 20)
    width = 4.0 * std
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(width > 0, (close - (mean - 2.0 * std)) / width, 0.5)
    out[np.isnan(std)] = np.nan
    return out


def _rsi(columns: Columns) -> np.ndarray:
    close = columns["close"]
    change = np.diff(close, prepend=close[0])
    gain, loss = np.clip(change, 0, None), np.clip(-change, 0, None)
    average_gain, average_loss = _wilder(gain, 14), _wilder(loss, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        strength = average_gain / average_loss
        value = np.where(average_loss == 0, 100.0, 100.0 - 100.0 / (1.0 + strength))
    value[np.isnan(average_loss)] = np.nan
    return value


def _wilder(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) <= period:
        return out
    out[period:] = _smooth(
        values[period:].astype(float), 1.0 / period, float(values[1 : period + 1].mean())
    )
    return out


def _volume_z(columns: Columns) -> np.ndarray:
    return _zscore(columns["volume"], 20)


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    compute: Callable[[Columns], np.ndarray]
    default: bool = True


FEATURES: tuple[Feature, ...] = (
    Feature("ret1", "Return 1 bar", lambda c: _ret(c["close"], 1)),
    Feature("ret5", "Return 5 bars", lambda c: _ret(c["close"], 5)),
    Feature("ret15", "Return 15 bars", lambda c: _ret(c["close"], 15)),
    Feature("vol20", "Volatility σ(20)", _volatility),
    Feature("atr14", "ATR(14)", _atr, default=False),
    Feature("ema_ratio", "EMA 20/50 ratio", _ema_ratio),
    Feature("zscore20", "Z-score(20)", lambda c: _zscore(c["close"], 20)),
    Feature("bb_pctb", "Bollinger %B", _bollinger_pct_b),
    Feature("rsi14", "RSI(14)", _rsi, default=False),
    Feature("vol_z", "Volume z-score", _volume_z),
)

_BY_KEY = {feature.key: feature for feature in FEATURES}


def default_features() -> list[str]:
    return [feature.key for feature in FEATURES if feature.default]


def custom_feature(name: str) -> str:
    return f"{CUSTOM_PREFIX}{name}"


def feature_label(key: str) -> str:
    if key.startswith(CUSTOM_PREFIX):
        return key[len(CUSTOM_PREFIX) :]
    feature = _BY_KEY.get(key)
    return feature.label if feature else key


def feature_matrix(
    columns: Columns, keys: list[str], custom: dict[str, str] | None = None
) -> np.ndarray:
    """One row per bar, one column per feature, NaN where a window is unfilled.

    `custom` maps a custom feature's key to its formula text (a rule in the
    formula language, evaluated over the bar's own columns).
    """
    length = len(columns["close"])
    out = np.full((length, len(keys)), np.nan, dtype=np.float64)
    for position, key in enumerate(keys):
        if key.startswith(CUSTOM_PREFIX):
            out[:, position] = _custom_column(columns, (custom or {})[key], length)
        elif key in _BY_KEY:
            out[:, position] = _BY_KEY[key].compute(columns)
        else:
            raise KeyError(f"unknown feature {key!r}")
    out[~np.isfinite(out)] = np.nan
    return out


def _custom_column(columns: Columns, text: str, length: int) -> np.ndarray:
    from bi_trading.engine.formula import FIELDS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import evaluate_columns

    formula = parse(text, FIELDS, FUNCTIONS)
    values = evaluate_columns(formula, columns)
    return np.asarray(values, dtype=float).reshape(length)


# -- the target ---------------------------------------------------------------

# kind -> (label, number of classes)
TARGETS: dict[str, tuple[str, int]] = {
    "binary": ("Direction (up / down)", 2),
    "ternary": ("Direction (up / flat / down)", 3),
}


def forward_return(close: np.ndarray, horizon: int) -> np.ndarray:
    """The move from each bar's close to the close `horizon` bars later."""
    out = np.full(len(close), np.nan)
    if 0 < horizon < len(close):
        with np.errstate(divide="ignore", invalid="ignore"):
            out[:-horizon] = close[horizon:] / close[:-horizon] - 1.0
    return out


def make_target(
    close: np.ndarray, horizon: int, min_move_pct: float, kind: str = "binary"
) -> np.ndarray:
    """Class labels per bar; -1 where the bar cannot be labelled.

    binary:  1 = up, 0 = down; a move smaller than `min_move_pct` is dropped
             (-1), since it is closer to noise than to a direction.
    ternary: 2 = up, 1 = flat (inside the band), 0 = down.
    """
    move = forward_return(close, horizon) * 100.0
    labels = np.full(len(close), -1, dtype=np.int8)
    known = np.isfinite(move)
    band = max(0.0, float(min_move_pct))
    if kind == "ternary":
        labels[known & (move > band)] = 2
        labels[known & (move < -band)] = 0
        labels[known & (np.abs(move) <= band)] = 1
    else:
        labels[known & (move > band)] = 1
        labels[known & (move < -band)] = 0
    return labels


def class_balance(labels: np.ndarray, kind: str = "binary") -> dict[str, float]:
    """The share of each class among labelled bars, as fractions."""
    used = labels[labels >= 0]
    if not len(used):
        return {}
    names = ("down", "flat", "up") if kind == "ternary" else ("down", "up")
    return {
        name: float((used == index).mean()) for index, name in enumerate(names)
    }


def ordered_mask(stamps: np.ndarray) -> np.ndarray:
    """True for the bars that are strictly later than every bar before them.

    A stray row (a stamp of 0, a block written twice) is False; everything that
    reads a span in time order drops those rows first.
    """
    stamps = np.asarray(stamps)
    if not len(stamps):
        return np.zeros(0, dtype=bool)
    running = np.maximum.accumulate(stamps)
    keep = np.ones(len(stamps), dtype=bool)
    keep[1:] = stamps[1:] > running[:-1]
    return keep


def _step(stamps: np.ndarray) -> float:
    gaps = np.diff(stamps)
    return float(np.median(gaps)) if len(gaps) else 0.0


def gap_invalid(stamps: np.ndarray, lookback: int) -> np.ndarray:
    """Bars whose look-back window reaches across a hole in the data.

    A hole is a step longer than 1.5 bars. The `lookback` bars after it are
    marked, so no feature or window is built from bars on both sides of it (a
    backtest refuses to trade across a hole too).
    """
    stamps = np.asarray(stamps)
    bad = np.zeros(len(stamps), dtype=bool)
    step = _step(stamps)
    if step <= 0:
        return bad
    for first in np.nonzero(np.diff(stamps) > 1.5 * step)[0] + 1:
        bad[first : first + lookback] = True
    return bad


def horizon_gap(stamps: np.ndarray, horizon: int) -> np.ndarray:
    """Bars whose target, `horizon` bars on, lies across a hole."""
    stamps = np.asarray(stamps)
    bad = np.zeros(len(stamps), dtype=bool)
    step = _step(stamps)
    if step <= 0 or not 0 < horizon < len(stamps):
        return bad
    bad[:-horizon] = (stamps[horizon:] - stamps[:-horizon]) > 1.5 * step * horizon
    return bad


def time_split(
    indices: np.ndarray, train: float = 0.6, valid: float = 0.2
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split sample indices by time, in order, with no shuffling."""
    count = len(indices)
    first = int(count * train)
    second = int(count * (train + valid))
    return indices[:first], indices[first:second], indices[second:]
