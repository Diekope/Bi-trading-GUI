"""The locked hold-out: never fitted on, scored once, and the variants counted."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from bi_trading.ml import holdout, store  # noqa: E402
from bi_trading.ml.features import default_features  # noqa: E402
from bi_trading.ml.spec import ModelSpec  # noqa: E402
from bi_trading.ml.train import MLError, TrainConfig, train  # noqa: E402


@pytest.fixture(autouse=True)
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_MODELS", str(tmp_path / "models"))


def market(count: int = 6_000):
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, count)))
    open_ = np.r_[close[0], close[:-1]]
    columns = {
        "open": open_, "high": np.maximum(open_, close) * 1.001,
        "low": np.minimum(open_, close) * 0.999, "close": close,
        "volume": rng.uniform(1, 2, count),
    }
    return columns, np.arange(count, dtype=np.int64) * 60_000


def config(**kwargs) -> TrainConfig:
    return TrainConfig(
        spec=ModelSpec("t", "logistic", {}), features=default_features(), horizon=1,
        min_move=0.0, max_samples=8_000, tp=1.0, sl=1.0, hold=5, fee=0.0,
        slippage=0.0, up=0.52, down=0.48, **kwargs,
    )


def test_the_holdout_is_the_last_slice_and_nothing_is_fitted_on_it() -> None:
    columns, stamps = market()
    model = train(columns, stamps, config(holdout=0.2), "a")
    assert model.holdout_start > model.test_end
    assert model.holdout_end <= int(stamps[-1])
    share = model.samples["holdout"] / sum(model.samples.values())
    assert share == pytest.approx(0.2, abs=0.02)
    # The rule's bars stop where the hold-out starts: the screen never trades it.
    assert model.test_p is not None
    assert len(model.test_close) == int((model.holdout_start - model.test_start) // 60_000)


def test_no_holdout_leaves_the_split_as_it_was() -> None:
    columns, stamps = market()
    model = train(columns, stamps, config(holdout=0.0), "a")
    assert model.holdout_start == 0 and "holdout" not in model.samples
    assert model.trials == 0


def test_each_training_counts_as_a_variant_tried() -> None:
    columns, stamps = market()
    first = train(columns, stamps, config(holdout=0.2), "a")
    second = train(columns, stamps, config(holdout=0.2), "b")
    assert (first.trials, second.trials) == (1, 2)
    assert holdout.trials(holdout.trial_key("1m", second.holdout_start)) == 2


def test_the_holdout_is_scored_once_and_the_answer_kept() -> None:
    columns, stamps = market()
    model = train(columns, stamps, config(holdout=0.2), "a")
    store.save_model(model, "a")
    first = holdout.score_holdout("a", columns, stamps)
    assert not first.again and first.start == model.holdout_start
    assert first.signals > 0
    assert first.adjusted_p is not None and first.adjusted_p >= first.p_value
    # Asking again never recomputes, even with different data behind it.
    columns2, _ = market(6_000)
    columns2["close"] = columns2["close"][::-1].copy()
    again = holdout.score_holdout("a", columns2, stamps)
    assert again.again
    assert (again.signals, again.strategy_return) == (first.signals, first.strategy_return)
    # And it survives a reload from disk.
    assert store.load_model("a").holdout_start == model.holdout_start


def test_a_model_trained_without_a_holdout_cannot_be_scored_on_one() -> None:
    columns, stamps = market()
    store.save_model(train(columns, stamps, config(holdout=0.0), "a"), "a")
    with pytest.raises(MLError):
        holdout.score_holdout("a", columns, stamps)


def test_the_p_value_is_corrected_for_the_variants_tried() -> None:
    p = holdout.binomial_p(60, 100)
    assert p == pytest.approx(0.0287, abs=0.003)
    assert holdout.binomial_p(50, 100) > 0.4
    assert holdout.binomial_p(0, 0) is None
    assert holdout.adjusted_p(p, 10) == pytest.approx(min(1.0, p * 10))
    assert holdout.adjusted_p(0.4, 10) == 1.0
    assert holdout.adjusted_p(None, 3) is None
