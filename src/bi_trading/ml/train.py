"""Train a model on a span, judge it on bars it never saw, and score a span.

The order of a run:

1. build the feature matrix and the target for the whole span;
2. split the labelled bars **by time** (train, then valid, then test, no
   shuffling) and fit on the first part, tuning on the second if asked;
3. measure accuracy, AUC and log loss on each part, rank the features by how
   much shuffling each one hurts the validation score, and trade the model's
   calls over the test part;
4. optionally redo the test part **walk-forward**: retrain every N days on what
   came before and predict only the next N days, as live trading would.

The test part is only looked at in step 3, after the model is chosen.

`predict_series` is what a backtest calls: the model's P(up) for every bar of a
span, unknown (NaN) wherever the model had a look at the bar in training.

Pure NumPy plus scikit-learn / torch; no Qt.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from bi_trading.ml.features import (
    class_balance,
    feature_label,
    feature_matrix,
    gap_invalid,
    horizon_gap,
    make_target,
    time_split,
)
from bi_trading.ml.models import SklearnModel, auto_tune_grid, finite_rows, fit_sklearn
from bi_trading.ml.nets import INPUT_BARS, MissingBackend, NetModel, Stopped, fit_net
from bi_trading.ml.spec import ModelSpec

__all__ = [
    "MLError",
    "RuleStats",
    "Stopped",
    "TrainConfig",
    "TrainedModel",
    "predict_series",
    "trade_test",
    "rule_stats",
    "train",
]

Progress = Callable[[float, str], None]

# The longest look-back of any feature (the 50-bar EMA), with a little to spare.
LOOKBACK = 60

TIMEFRAME_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


class MLError(RuntimeError):
    """A model cannot be trained or used, with the reason in words."""


@dataclass
class TrainConfig:
    spec: ModelSpec
    features: list[str]
    custom: dict[str, str] = field(default_factory=dict)  # custom feature -> formula
    target: str = "binary"
    horizon: int = 5
    min_move: float = 0.10
    split: tuple[float, float] = (0.6, 0.2)  # train, valid; the rest is test
    timeframe: str = "1m"
    auto_tune: bool = False
    walk_forward: bool = False
    retrain_days: int = 7
    up: float = 0.60
    down: float = 0.40
    # How far the model's P(up) must sit from the market's price before a live
    # Polymarket bet is worth it. Kept with the model; backtests have no market
    # price to compare with, so they do not use it.
    min_edge: float = 0.05
    # How the test bars are traded, as a backtest would: the Settings values.
    tp: float = 2.0           # take profit, percent
    sl: float = 1.0           # stop loss, percent
    hold: int = 7             # bars a trade may run; 0 = no limit
    fee: float = 0.06         # per side, percent
    slippage: float = 0.01    # per side, percent
    size: float = 1.0         # share of the cash a trade stakes
    capital: float = 10_000.0  # the book the test starts with, dollars
    cash: float = float("inf")  # most cash the book may trade with, dollars
    max_samples: int = 300_000  # most bars fitted on; the rest are strided out

    @property
    def classes(self) -> int:
        return 3 if self.target == "ternary" else 2

    def as_dict(self) -> dict:
        return {
            "spec": self.spec.as_dict(),
            "features": list(self.features),
            "custom": dict(self.custom),
            "target": self.target,
            "horizon": self.horizon,
            "min_move": self.min_move,
            "split": list(self.split),
            "timeframe": self.timeframe,
            "auto_tune": self.auto_tune,
            "walk_forward": self.walk_forward,
            "retrain_days": self.retrain_days,
            "up": self.up,
            "down": self.down,
            "min_edge": self.min_edge,
            "tp": self.tp,
            "sl": self.sl,
            "hold": self.hold,
            "fee": self.fee,
            "slippage": self.slippage,
            "size": self.size,
            "capital": self.capital,
            "cash": None if self.cash == float("inf") else self.cash,
            "max_samples": self.max_samples,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> TrainConfig:
        split = raw.get("split") or (0.6, 0.2)
        return cls(
            spec=ModelSpec.from_dict(raw.get("spec") or {}),
            features=list(raw.get("features") or []),
            custom=dict(raw.get("custom") or {}),
            target=str(raw.get("target", "binary")),
            horizon=int(raw.get("horizon", 5)),
            min_move=float(raw.get("min_move", 0.1)),
            split=(float(split[0]), float(split[1])),
            timeframe=str(raw.get("timeframe", "1m")),
            auto_tune=bool(raw.get("auto_tune", False)),
            walk_forward=bool(raw.get("walk_forward", False)),
            retrain_days=int(raw.get("retrain_days", 7)),
            up=float(raw.get("up", 0.6)),
            down=float(raw.get("down", 0.4)),
            min_edge=float(raw.get("min_edge", 0.05)),
            tp=float(raw.get("tp", 2.0)),
            sl=float(raw.get("sl", 1.0)),
            hold=int(raw.get("hold", 7)),
            fee=float(raw.get("fee", 0.06)),
            slippage=float(raw.get("slippage", 0.01)),
            size=float(raw.get("size", 1.0)),
            capital=float(raw.get("capital", 10_000.0)),
            cash=float("inf") if raw.get("cash") is None else float(raw["cash"]),
            max_samples=int(raw.get("max_samples", 300_000)),
        )


@dataclass
class RuleStats:
    """What trading the model's calls over the test bars would have done."""

    signals: int = 0
    hit_rate: float | None = None
    strategy: list[float] = field(default_factory=list)  # return from start, in %
    hold: list[float] = field(default_factory=list)
    strategy_return: float = 0.0
    hold_return: float = 0.0


@dataclass
class TrainedModel:
    name: str
    config: TrainConfig
    predictor: SklearnModel | NetModel | None = None
    metrics: dict[str, dict[str, float | None]] = field(default_factory=dict)
    samples: dict[str, int] = field(default_factory=dict)
    importance: list[tuple[str, float]] = field(default_factory=list)
    balance: dict[str, float] = field(default_factory=dict)
    stats: RuleStats = field(default_factory=RuleStats)
    test_start: int = 0  # the first test bar's stamp (ms); 0 when unknown
    test_end: int = 0
    span_start: int = 0
    seconds: float = 0.0
    trained_at: float = 0.0
    tuned: dict = field(default_factory=dict)
    # Walk-forward predictions over the test part: bar stamps and P(up).
    wf_stamps: np.ndarray | None = None
    wf_p: np.ndarray | None = None
    # Kept in memory after a run so the rule's thresholds can be moved live.
    test_p: np.ndarray | None = None
    test_close: np.ndarray | None = None
    test_high: np.ndarray | None = None
    test_low: np.ndarray | None = None

    @property
    def gap(self) -> float | None:
        """Train accuracy minus test accuracy, in points."""
        train = self.metrics.get("train", {}).get("accuracy")
        test = self.metrics.get("test", {}).get("accuracy")
        if train is None or test is None:
            return None
        return (train - test) * 100.0


# -- one run --------------------------------------------------------------------


def _columns_ok(columns: dict) -> None:
    for name in ("open", "high", "low", "close", "volume"):
        if name not in columns:
            raise MLError(f"no {name} column to train on")


def _stride(rows: np.ndarray, limit: int) -> np.ndarray:
    if len(rows) <= limit:
        return rows
    return rows[:: int(np.ceil(len(rows) / limit))]


def _fit(
    config: TrainConfig,
    matrix: np.ndarray,
    labels: np.ndarray,
    train_rows: np.ndarray,
    valid_rows: np.ndarray,
    progress: Progress | None,
    cancelled: Callable[[], bool] | None,
    spec: ModelSpec | None = None,
):
    spec = spec or config.spec
    classes = config.classes
    if spec.is_custom:
        return fit_net(
            spec, matrix, labels, train_rows, valid_rows, classes,
            progress=progress, cancelled=cancelled, bars=INPUT_BARS,
        )
    return fit_sklearn(spec, matrix[train_rows], labels[train_rows], classes)


def _log_loss(labels: np.ndarray, proba: np.ndarray, classes: int) -> float:
    from sklearn.metrics import log_loss

    return float(log_loss(labels, np.clip(proba, 1e-6, 1 - 1e-6), labels=list(range(classes))))


def _score(
    predictor, matrix: np.ndarray, labels: np.ndarray, rows: np.ndarray, classes: int
) -> dict[str, float | None]:
    """Accuracy, AUC (up against the rest) and log loss over `rows`."""
    if not len(rows):
        return {"accuracy": None, "auc": None, "logloss": None}
    from sklearn.metrics import roc_auc_score

    proba = predictor.predict_proba(matrix, rows)
    truth = labels[rows]
    accuracy = float((proba.argmax(axis=1) == truth).mean())
    up = truth == classes - 1
    auc = float(roc_auc_score(up, proba[:, -1])) if up.any() and not up.all() else None
    return {"accuracy": accuracy, "auc": auc, "logloss": _log_loss(truth, proba, classes)}


def _importance(
    predictor, matrix: np.ndarray, labels: np.ndarray, rows: np.ndarray,
    keys: list[str], classes: int, bars: int,
) -> list[tuple[str, float]]:
    """How much shuffling each feature raises the validation log loss, 0 to 100."""
    if not len(rows):
        return []
    rows = _stride(rows, 4000)
    low = max(0, int(rows.min()) - bars)
    high = int(rows.max()) + 1
    view = matrix[low:high]
    local = rows - low
    truth = labels[rows]
    base = _log_loss(truth, predictor.predict_proba(view, local), classes)
    rng = np.random.default_rng(0)
    raised = []
    for column in range(len(keys)):
        saved = view[:, column].copy()
        try:
            view[:, column] = rng.permutation(saved)
            worse = _log_loss(truth, predictor.predict_proba(view, local), classes)
        finally:
            view[:, column] = saved
        raised.append(max(0.0, worse - base))
    top = max(raised) if raised else 0.0
    scale = 100.0 / top if top > 0 else 0.0
    ranked = sorted(zip(keys, raised, strict=True), key=lambda item: -item[1])
    return [(feature_label(key), round(value * scale, 1)) for key, value in ranked]


# -- the rule's figures ------------------------------------------------------------


def rule_stats(
    p: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    up: float,
    down: float,
    *,
    tp: float,
    sl: float,
    hold: int,
    fee: float,
    slippage: float,
    size: float = 1.0,
    capital: float = 1.0,
    cash: float = float("inf"),
    points: int = 260,
) -> RuleStats:
    """Trade the calls over a stretch of bars the way the backtest does.

    Long at P(up) >= up, short at P(up) <= down; one trade at a time, entered at
    the signal bar's close a little worse by `slippage`. A trade ends at its stop,
    its take profit, or after `hold` bars (0 = no limit) at the close. When one
    bar reaches both the stop and the take profit the stop is booked; the take
    profit is a resting order and fills at its price, every other exit slips
    against the trade. `fee` is charged each side. `size` is the share of the book
    of the cash in each trade, where the cash is the book capped at `cash` dollars
    (the backtest's Max cash); the curve is the book's return from the start, in
    percent.
    """
    count = len(p)
    stats = RuleStats()
    if not count:
        return stats
    with np.errstate(invalid="ignore"):
        wanted = np.nonzero((p >= up) | (p <= down))[0]
    equity = np.zeros(count)
    level, last, free, wins, trades = 1.0, 0, 0, 0, 0
    slip, cost = slippage / 100.0, fee / 100.0
    for position in wanted:
        index = int(position)
        if index < free or index >= count - 1:
            continue
        long = bool(p[index] >= up)
        entry = close[index] * (1.0 + slip if long else 1.0 - slip)
        stop = entry * (1.0 - sl / 100.0 if long else 1.0 + sl / 100.0)
        target = entry * (1.0 + tp / 100.0 if long else 1.0 - tp / 100.0)
        end = count - 1 if hold <= 0 else min(count - 1, index + hold)
        exit_index, exit_price = end, None
        for bar in range(index + 1, end + 1):
            hit_stop = low[bar] <= stop if long else high[bar] >= stop
            hit_target = high[bar] >= target if long else low[bar] <= target
            if hit_stop:
                exit_index, exit_price = bar, stop * (1.0 - slip if long else 1.0 + slip)
                break
            if hit_target:
                exit_index, exit_price = bar, target
                break
        if exit_price is None:
            exit_price = close[exit_index] * (1.0 - slip if long else 1.0 + slip)
        move = exit_price / entry - 1.0 if long else 1.0 - exit_price / entry
        book = level * capital
        stake = size * min(cash, book)
        outcome = stake * (move - 2.0 * cost) / book
        equity[last : exit_index] = level
        level *= 1.0 + outcome
        last = exit_index
        trades += 1
        wins += 1 if outcome > 0 else 0
        free = exit_index + 1
    equity[last:] = level
    stats.signals = trades
    stats.hit_rate = wins / trades if trades else None
    picks = np.linspace(0, count - 1, min(points, count)).astype(int)
    stats.strategy = [float((equity[i] - 1.0) * 100.0) for i in picks]
    held = close / close[0] - 1.0
    stats.hold = [float(held[i] * 100.0) for i in picks]
    stats.strategy_return = float((level - 1.0) * 100.0)
    stats.hold_return = float(held[-1] * 100.0)
    return stats


def trade_test(trained: TrainedModel, config: TrainConfig) -> RuleStats:
    """The rule's figures over the kept test bars, with the config's thresholds."""
    assert trained.test_p is not None and trained.test_close is not None
    assert trained.test_high is not None and trained.test_low is not None
    return rule_stats(
        trained.test_p, trained.test_close, trained.test_high, trained.test_low,
        config.up, config.down, tp=config.tp, sl=config.sl, hold=config.hold,
        fee=config.fee, slippage=config.slippage, size=config.size,
        capital=config.capital, cash=config.cash,
    )


# -- walk-forward -------------------------------------------------------------------


def _walk_forward(
    config: TrainConfig,
    matrix: np.ndarray,
    labels: np.ndarray,
    usable: np.ndarray,
    test_rows: np.ndarray,
    progress: Progress | None,
    cancelled: Callable[[], bool] | None,
    spec: ModelSpec,
) -> np.ndarray:
    """P(up) over the test bars from models that only ever saw the past.

    Every `retrain_days` the model is refitted on all labelled bars before the
    next stretch (the last `horizon` of them are left out: their label would
    have needed bars from the stretch itself) and scores that stretch alone.
    """
    minutes = TIMEFRAME_MINUTES.get(config.timeframe, 1)
    step = max(1, int(config.retrain_days * 1440 / minutes))
    out = np.full(len(matrix), np.nan)
    starts = list(range(int(test_rows[0]), int(test_rows[-1]) + 1, step))
    for done, start in enumerate(starts):
        if cancelled is not None and cancelled():
            raise Stopped()
        stop = start + step
        past = usable[usable < start - max(1, config.horizon)]
        fitting = _stride(past, max(10_000, config.max_samples // 3))
        model = _fit(config, matrix, labels, fitting, fitting[-1000:], None, cancelled, spec)
        rows = test_rows[(test_rows >= start) & (test_rows < stop)]
        if len(rows):
            out[rows] = model.predict_up(matrix, rows)
        if progress is not None:
            progress((done + 1) / len(starts), f"walk-forward {done + 1}/{len(starts)}")
    return out


# -- the whole run -----------------------------------------------------------------------


def train(
    columns: dict,
    stamps: np.ndarray,
    config: TrainConfig,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> TrainedModel:
    """Fit, judge and trade one model over a span. Raises `MLError` with a reason."""
    started = time.time()
    _columns_ok(columns)
    if not config.features:
        raise MLError("pick at least one feature")
    close = np.asarray(columns["close"], dtype=float)
    total = len(close)
    if total < 500:
        raise MLError(f"only {total} bars on disk: download more history first")

    def say(fraction: float, text: str) -> None:
        if progress is not None:
            progress(fraction, text)

    def check() -> None:
        if cancelled is not None and cancelled():
            raise Stopped()

    try:
        say(0.02, "features")
        matrix = feature_matrix(columns, config.features, config.custom)
    except (KeyError, ValueError) as exc:
        raise MLError(f"a feature could not be built: {exc}") from exc
    check()
    labels = make_target(close, config.horizon, config.min_move, config.target)
    window = INPUT_BARS if config.spec.is_custom else 1
    # No feature, window or target may reach across a hole in the data.
    stamps = np.asarray(stamps)
    matrix[gap_invalid(stamps, LOOKBACK + window)] = np.nan
    labels[horizon_gap(stamps, config.horizon)] = -1
    finite = np.isfinite(matrix).all(axis=1)
    first = int(np.argmax(finite)) if finite.any() else total
    usable = finite_rows(matrix, first + window - 1)
    usable = usable[labels[usable] >= 0]
    if len(usable) < 300:
        raise MLError(
            f"only {len(usable)} bars can be labelled: lower the horizon or the minimum move"
        )
    train_all, valid_all, test_all = time_split(usable, config.split[0], config.split[1])
    # Purge: a label looks `horizon` bars ahead, so the last labels of a part would
    # read closes from the next one. Leave them out and the parts share no price.
    if len(valid_all) and len(test_all):
        train_all = train_all[train_all + config.horizon < valid_all[0]]
        valid_all = valid_all[valid_all + config.horizon < test_all[0]]
    if not (len(train_all) and len(valid_all) and len(test_all)):
        raise MLError("the split leaves a part empty")
    classes = config.classes
    trained = TrainedModel(name=name or config.spec.name, config=config)
    trained.balance = class_balance(labels[usable], config.target)
    trained.span_start = int(stamps[0]) if len(stamps) else 0
    trained.test_start = int(stamps[test_all[0]]) if len(stamps) else 0
    trained.test_end = int(stamps[test_all[-1]]) if len(stamps) else 0

    train_rows = _stride(train_all, config.max_samples)
    valid_rows = _stride(valid_all, config.max_samples // 3)
    spec = config.spec
    check()

    if config.auto_tune and not spec.is_custom:
        grid = auto_tune_grid(spec.kind)
        best_loss, best_spec = float("inf"), spec
        small = _stride(train_rows, max(20_000, config.max_samples // 3))
        for number, params in enumerate(grid):
            check()
            say(0.05 + 0.4 * number / len(grid), f"auto-tune {number + 1}/{len(grid)}")
            candidate = ModelSpec(spec.name, spec.kind, params, [], spec.training)
            fitted = _fit(config, matrix, labels, small, valid_rows, None, cancelled, candidate)
            loss = _log_loss(labels[valid_rows], fitted.predict_proba(matrix, valid_rows), classes)
            if loss < best_loss:
                best_loss, best_spec = loss, candidate
        spec = ModelSpec(spec.name, spec.kind, best_spec.params, [], spec.training)
        trained.tuned = dict(best_spec.params)

    say(0.5, "fitting")

    def fit_progress(fraction: float, text: str) -> None:
        say(0.5 + 0.3 * fraction, text)

    model = _fit(config, matrix, labels, train_rows, valid_rows, fit_progress, cancelled, spec)
    trained.predictor = model
    check()

    say(0.82, "scoring")
    trained.samples = {
        "train": len(train_all), "valid": len(valid_all), "test": len(test_all)
    }
    trained.metrics["train"] = _score(model, matrix, labels, _stride(train_all, 100_000), classes)
    trained.metrics["valid"] = _score(model, matrix, labels, _stride(valid_all, 100_000), classes)
    check()

    # The test bars the rule can trade: every bar with a known move, not only the
    # ones the label kept (a small move is no label but still a trade's outcome).
    span = np.arange(int(test_all[0]), int(test_all[-1]) + 1)
    span = span[np.isfinite(matrix[span]).all(axis=1)] if len(span) else span
    if spec.is_custom:
        span = span[span >= first + window - 1]
    if config.walk_forward and not spec.is_custom:
        say(0.86, "walk-forward")
        p_full = _walk_forward(
            config, matrix, labels, usable, span,
            lambda f, t: say(0.86 + 0.12 * f, t), cancelled, spec,
        )
        p_span = p_full[span]
        keep = np.isfinite(p_span)
        trained.wf_stamps = np.asarray(stamps)[span[keep]]
        trained.wf_p = p_span[keep]
        scored = span[keep][labels[span[keep]] >= 0]
        if classes == 2 and len(scored):
            trained.metrics["test"] = _wf_score(p_full[scored], labels[scored])
        else:
            trained.metrics["test"] = _score(model, matrix, labels, _stride(test_all, 100_000), classes)
    else:
        p_span = model.predict_up(matrix, span)
        p_full = None
        trained.metrics["test"] = _score(model, matrix, labels, _stride(test_all, 200_000), classes)
    say(0.98, "ranking features")
    trained.importance = _importance(
        model, matrix, labels, valid_all, config.features, classes,
        INPUT_BARS if spec.is_custom else 1,
    )
    trained.test_p = p_span
    trained.test_close = close[span]
    trained.test_high = np.asarray(columns["high"], dtype=float)[span]
    trained.test_low = np.asarray(columns["low"], dtype=float)[span]
    trained.stats = trade_test(trained, config)
    trained.config = TrainConfig.from_dict({**config.as_dict(), "spec": spec.as_dict()})
    trained.seconds = time.time() - started
    trained.trained_at = time.time()
    say(1.0, "done")
    return trained


def _wf_score(p: np.ndarray, truth: np.ndarray) -> dict[str, float | None]:
    from sklearn.metrics import roc_auc_score

    up = truth == 1
    return {
        "accuracy": float(((p >= 0.5) == up).mean()),
        "auc": float(roc_auc_score(up, p)) if up.any() and not up.all() else None,
        "logloss": _log_loss(truth, np.column_stack([1.0 - p, p]), 2),
    }


# -- scoring a span (what a backtest calls) -----------------------------------------------


def predict_series(
    trained: TrainedModel,
    columns: dict,
    stamps: np.ndarray,
    resolution: str,
    in_sample: bool = False,
    chunk: int = 1_000_000,
) -> np.ndarray:
    """The model's P(up) for every bar of a span; NaN where there is no honest call.

    A bar the model could have learned from (before its test part began) is NaN
    unless `in_sample`, so a backtest cannot flatter the model. A span whose
    bars are not the model's timeframe is refused rather than scored wrongly.
    Where walk-forward predictions exist they replace the single model's.
    """
    config = trained.config
    if resolution != config.timeframe:
        raise MLError(
            f"model trained on {config.timeframe} bars, the backtest runs {resolution}"
        )
    if trained.predictor is None:
        raise MLError("the model has no weights")
    _columns_ok(columns)
    stamps = np.asarray(stamps)
    matrix = feature_matrix(columns, config.features, config.custom)
    window = INPUT_BARS if config.spec.is_custom else 1
    matrix[gap_invalid(stamps, LOOKBACK + window)] = np.nan
    ok = np.isfinite(matrix).all(axis=1)
    if not ok.any():
        return np.full(len(matrix), np.nan)
    first = int(np.argmax(ok))
    rows = finite_rows(matrix, first + window - 1)
    if not in_sample and trained.test_start:
        rows = rows[stamps[rows] >= trained.test_start]
    out = np.full(len(matrix), np.nan)
    for start in range(0, len(rows), chunk):
        part = rows[start : start + chunk]
        out[part] = trained.predictor.predict_up(matrix, part)
    if trained.wf_stamps is not None and trained.wf_p is not None and len(trained.wf_stamps):
        where = np.searchsorted(stamps, trained.wf_stamps)
        where = where[where < len(stamps)]
        hit = stamps[where] == trained.wf_stamps[: len(where)]
        out[where[hit]] = trained.wf_p[: len(where)][hit]
        # Inside walk-forward's coverage only its own calls count.
        lo, hi = int(trained.wf_stamps[0]), int(trained.wf_stamps[-1])
        inside = (stamps >= lo) & (stamps <= hi)
        covered = np.zeros(len(stamps), dtype=bool)
        covered[where[hit]] = True
        out[inside & ~covered] = np.nan
    return out


__all__ += ["MissingBackend"]
