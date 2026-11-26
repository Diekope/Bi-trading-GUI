"""A locked final hold-out, and a count of the variants tried before it.

The test part is looked at again and again while a model is built (thresholds
move, models are swapped), so after a few changes it is no longer out of sample.
The hold-out is the last slice of the data: no fit, tune, threshold or model
choice ever reads it. It is scored once, by name, and the answer is kept; asking
again returns the kept answer and never recomputes. Each training on the same
data counts as one variant tried, and the reported p-value is multiplied by that
count (a Bonferroni correction, the blunt and honest one), so ten tries need a
much stronger result than one.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

import numpy as np

__all__ = [
    "HoldoutResult",
    "adjusted_p",
    "binomial_p",
    "bump_trials",
    "score_holdout",
    "trial_key",
    "trials",
]


def _path():
    from bi_trading.ml.store import models_dir

    return models_dir() / "variants.counts"


def _read() -> dict:
    try:
        raw = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): int(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def trial_key(timeframe: str, holdout_start: int) -> str:
    """What the variants are counted against: the data's hold-out and resolution."""
    return f"{timeframe}:{int(holdout_start)}"


def trials(key: str) -> int:
    """How many models have been trained against this hold-out."""
    return _read().get(key, 0)


def bump_trials(key: str) -> int:
    """Count one more training against `key`; returns the new count."""
    counts = _read()
    counts[key] = counts.get(key, 0) + 1
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(counts, indent=2) + "\n")
    except OSError:
        pass  # the count is a safeguard, not a reason to fail a training
    return counts[key]


def binomial_p(hits: int, count: int) -> float | None:
    """One-sided p that a coin that wins half the time does at least this well.

    A normal approximation with continuity correction, enough for the dozens of
    trades and up that a rule makes. None for no trades.
    """
    if count <= 0:
        return None
    z = (hits - 0.5 - count / 2.0) / math.sqrt(count / 4.0)
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def adjusted_p(p: float | None, tried: int) -> float | None:
    """`p` times the variants tried, at most 1."""
    return None if p is None else min(1.0, p * max(1, int(tried)))


@dataclass
class HoldoutResult:
    signals: int
    hit_rate: float | None
    strategy_return: float
    hold_return: float
    p_value: float | None
    adjusted_p: float | None
    trials: int
    start: int
    end: int
    scored_at: float
    again: bool = False     # True when this is the kept answer, not a new score

    def as_dict(self) -> dict:
        data = dict(self.__dict__)
        data.pop("again")
        return data


def score_holdout(name: str, columns: dict, stamps) -> HoldoutResult:
    """Score a saved model on its hold-out, once.

    The bars are every bar from the hold-out's start to the end of the data. The
    first call computes the rule's figures with the model's own thresholds, costs
    and fills, stores them in the model's file, and counts the variants tried;
    every later call returns that stored answer (`again` is set) and changes
    nothing, so the hold-out cannot be tuned against.
    """
    from bi_trading.ml.store import _paths, load_model, scored
    from bi_trading.ml.train import MLError, rule_stats

    trained = load_model(name)
    info, _, _ = _paths(name)
    body = json.loads(info.read_text())
    kept = body.get("holdout")
    if kept:
        return HoldoutResult(**kept, again=True)
    config = trained.config
    start, end = int(body.get("holdout_start") or 0), int(body.get("holdout_end") or 0)
    if not start or config.holdout <= 0:
        raise MLError(f"{name!r} was trained without a hold-out: retrain it to get one")
    stamps = np.asarray(stamps)
    first = int(np.searchsorted(stamps, start))
    if first >= len(stamps) - 1:
        raise MLError("the hold-out's bars are not in this data")
    p = np.asarray(scored(name, columns, stamps, config.timeframe), dtype=float)[first:]
    stats = rule_stats(
        p,
        np.asarray(columns["close"], dtype=float)[first:],
        np.asarray(columns["high"], dtype=float)[first:],
        np.asarray(columns["low"], dtype=float)[first:],
        config.up, config.down, tp=config.tp, sl=config.sl, hold=config.hold,
        fee=config.fee, slippage=config.slippage, sizing=config.sizing,
        position=config.position, capital=config.capital, cash=config.cash,
        open=np.asarray(columns["open"], dtype=float)[first:],
        entry_open=config.entry == "open", through=config.through,
    )
    tried = trials(trial_key(config.timeframe, start))
    hits = round((stats.hit_rate or 0.0) * stats.signals)
    p_value = binomial_p(hits, stats.signals)
    result = HoldoutResult(
        signals=stats.signals, hit_rate=stats.hit_rate,
        strategy_return=stats.strategy_return, hold_return=stats.hold_return,
        p_value=p_value, adjusted_p=adjusted_p(p_value, tried), trials=tried,
        start=start, end=end, scored_at=time.time(),
    )
    body["holdout"] = result.as_dict()
    info.write_text(json.dumps(body, indent=2) + "\n")
    return result
