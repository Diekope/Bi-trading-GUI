"""Training, honest scoring, walk-forward, saving and scoring a span."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("sklearn")

from bi_trading.ml import store  # noqa: E402
from bi_trading.ml.features import default_features  # noqa: E402
from bi_trading.ml.spec import ARCHITECTURE_PRESETS, ModelSpec, default_training  # noqa: E402
from bi_trading.ml.train import (  # noqa: E402
    MLError,
    Stopped,
    TrainConfig,
    predict_series,
    rule_stats,
    train,
)
from tests.ml_data import make_market  # noqa: E402


def config(kind: str = "gbm", **kwargs) -> TrainConfig:
    params = {"trees": 40, "depth": 3} if kind in ("gbm", "forest") else {}
    return TrainConfig(
        spec=ModelSpec("t", kind, params),
        features=default_features(),
        horizon=1,
        min_move=0.0,
        timeframe="1m",
        max_samples=20_000,
        # wide exits and no costs: the trades then just follow the direction called
        **{"tp": 100.0, "sl": 100.0, "hold": 1, "fee": 0.0, "slippage": 0.0, **kwargs},
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("BI_TRADING_ARCHITECTURES", str(tmp_path / "architectures.json"))


@pytest.fixture(scope="module")
def market():
    return make_market(6000)


@pytest.fixture(scope="module")
def trained(market):
    columns, stamps = market
    return train(columns, stamps, config(), "unit")


def test_a_model_finds_the_signal_on_bars_it_never_saw(trained) -> None:
    test = trained.metrics["test"]
    assert test["accuracy"] > 0.57
    assert test["auc"] > 0.60
    assert trained.metrics["train"]["accuracy"] >= test["accuracy"] - 0.05


def test_the_parts_are_in_time_order_and_sized_60_20_20(trained, market) -> None:
    _, stamps = market
    assert sum(trained.samples.values()) <= len(stamps)
    ratios = [trained.samples[part] / sum(trained.samples.values()) for part in ("train", "valid", "test")]
    assert ratios == pytest.approx([0.6, 0.2, 0.2], abs=0.01)
    assert stamps[0] < trained.test_start < trained.test_end <= stamps[-1]


def test_importance_puts_the_informative_feature_first(trained) -> None:
    assert trained.importance[0][0] == "Return 1 bar"
    assert trained.importance[0][1] == 100.0


def test_the_rule_trades_the_test_part(trained) -> None:
    assert trained.stats.signals > 0
    assert trained.stats.hit_rate > 0.55
    assert len(trained.stats.strategy) == len(trained.stats.hold) <= 260


def test_the_calls_are_unknown_where_the_model_could_have_learned(trained, market) -> None:
    columns, stamps = market
    p = predict_series(trained, columns, stamps, "1m")
    before = stamps < trained.test_start
    assert np.isnan(p[before]).all()
    assert np.isfinite(p[~before]).mean() > 0.99
    assert ((p[np.isfinite(p)] >= 0) & (p[np.isfinite(p)] <= 1)).all()


def test_in_sample_calls_are_available_on_request(trained, market) -> None:
    columns, stamps = market
    p = predict_series(trained, columns, stamps, "1m", in_sample=True)
    assert np.isfinite(p[stamps < trained.test_start][100:]).all()


def test_a_span_at_another_timeframe_is_refused(trained, market) -> None:
    columns, stamps = market
    with pytest.raises(MLError, match="trained on 1m"):
        predict_series(trained, columns, stamps, "5m")


def test_too_little_data_says_so() -> None:
    columns, stamps = make_market(200)
    with pytest.raises(MLError, match="download more history"):
        train(columns, stamps, config())


def test_no_features_says_so(market) -> None:
    columns, stamps = market
    bad = config()
    bad.features = []
    with pytest.raises(MLError, match="at least one feature"):
        train(columns, stamps, bad)


def test_stop_ends_the_run(market) -> None:
    columns, stamps = market
    with pytest.raises(Stopped):
        train(columns, stamps, config(), cancelled=lambda: True)


def test_progress_reaches_the_end(market) -> None:
    columns, stamps = market
    seen: list[float] = []
    train(columns, stamps, config("logistic"), progress=lambda f, _t: seen.append(f))
    assert seen[0] < 0.1 and seen[-1] == 1.0 and seen == sorted(seen)


@pytest.mark.parametrize("kind", ["forest", "logistic", "mlp"])
def test_every_builtin_kind_trains(market, kind) -> None:
    columns, stamps = market
    model = train(columns, stamps, config(kind))
    assert model.metrics["test"]["accuracy"] > 0.5


def test_auto_tune_records_what_it_chose(market) -> None:
    columns, stamps = market
    model = train(columns, stamps, config("logistic", auto_tune=True))
    assert set(model.tuned) == {"c", "iters"}


def test_three_classes_train_and_give_p_up(market) -> None:
    columns, stamps = market
    three = config(target="ternary")
    three.min_move = 0.1
    model = train(columns, stamps, three)
    p = predict_series(model, columns, stamps, "1m")
    assert model.predictor.classes == 3
    assert 0.0 <= np.nanmin(p) and np.nanmax(p) <= 1.0
    assert set(model.balance) == {"down", "flat", "up"}


def test_walk_forward_replaces_the_single_models_test_calls(market) -> None:
    columns, stamps = market
    walking = config(walk_forward=True, retrain_days=1)
    model = train(columns, stamps, walking)
    assert model.wf_p is not None and len(model.wf_p) == len(model.wf_stamps)
    assert model.wf_stamps[0] >= model.test_start
    p = predict_series(model, columns, stamps, "1m")
    where = np.searchsorted(stamps, model.wf_stamps)
    assert np.allclose(p[where], model.wf_p)


def test_custom_network_trains_saves_and_reloads(market) -> None:
    pytest.importorskip("torch")
    columns, stamps = market
    spec = ModelSpec(
        "tiny", "custom", {}, [dict(layer) for layer in ARCHITECTURE_PRESETS["Neural net (MLP)"]],
        {**default_training(), "epochs": 2, "batch": 128},
    )
    model = train(columns, stamps, TrainConfig(
        spec=spec, features=default_features(), horizon=1, min_move=0.0, max_samples=3000
    ))
    assert model.metrics["test"]["accuracy"] is not None
    store.save_model(model, "tiny net")
    again = store.load_model("tiny net")
    a = predict_series(model, columns, stamps, "1m")
    b = predict_series(again, columns, stamps, "1m")
    assert np.allclose(a, b, equal_nan=True)


# -- the rule's figures, by hand ---------------------------------------------------


def trade(p, close, high, low, **kwargs):
    base = {"tp": 2.0, "sl": 1.0, "hold": 3, "fee": 0.0, "slippage": 0.0}
    return rule_stats(
        np.array(p, float), np.array(close, float), np.array(high, float),
        np.array(low, float), 0.6, 0.4, **{**base, **kwargs},
    )


def test_a_long_takes_its_profit_at_the_target_price() -> None:
    stats = trade([0.7, 0.5, 0.5], [100, 101, 99], [100, 103, 99], [100, 100, 98])
    assert stats.signals == 1 and stats.hit_rate == 1.0
    assert stats.strategy_return == pytest.approx(2.0)  # filled at 102, not at the high


def test_a_bar_that_reaches_both_books_the_stop() -> None:
    stats = trade([0.7, 0.5, 0.5], [100, 100, 100], [100, 103, 100], [100, 98.9, 100])
    assert stats.strategy_return == pytest.approx(-1.0) and stats.hit_rate == 0.0


def test_a_trade_ends_at_the_close_after_the_hold_limit() -> None:
    stats = trade(
        [0.7, 0.5, 0.5, 0.5], [100, 100.2, 100.4, 100.6], [100, 100.3, 100.5, 100.7],
        [100, 100.1, 100.3, 100.5], hold=2,
    )
    assert stats.strategy_return == pytest.approx(0.4)


def test_a_short_gains_when_price_falls_and_its_stop_is_above() -> None:
    won = trade([0.3, 0.5, 0.5], [100, 99, 98], [100, 99.5, 98.5], [100, 97, 97.5])
    assert won.strategy_return == pytest.approx(2.0)  # target 98, a resting order
    lost = trade([0.3, 0.5, 0.5], [100, 101, 101], [100, 101.5, 101], [100, 100, 100])
    assert lost.strategy_return == pytest.approx(-1.0)


def test_fees_and_slippage_come_off_each_side() -> None:
    stats = trade(
        [0.7, 0.5, 0.5], [100, 100, 100], [100, 100, 100], [100, 100, 100],
        hold=1, fee=0.1, slippage=0.1,
    )
    # in at 100.1, out at 99.9: -0.2 percent from slippage, 0.2 from the two fees
    assert stats.strategy_return == pytest.approx(
        ((99.9 / 100.1 - 1) - 0.002) * 100, rel=1e-6
    )


def test_only_one_trade_runs_at_a_time_and_size_scales_the_book() -> None:
    stats = trade(
        [0.7, 0.7, 0.7, 0.5, 0.5], [100, 100, 100, 100, 100],
        [100, 103, 103, 103, 100], [100, 100, 100, 100, 100], size=0.5,
    )
    assert stats.signals == 2  # bars 0 and 2; bar 1 is inside the first trade
    assert stats.strategy_return == pytest.approx((1.01 * 1.01 - 1) * 100)


def test_the_curve_and_the_buy_and_hold_line_are_returns_from_the_start() -> None:
    stats = trade([0.5, 0.5, 0.5], [100, 110, 121], [100, 110, 121], [100, 110, 121])
    assert stats.signals == 0 and stats.hit_rate is None
    assert stats.hold_return == pytest.approx(21.0) and stats.strategy == [0.0, 0.0, 0.0]


# -- saving ------------------------------------------------------------------------


def test_a_saved_model_scores_the_same(trained, market) -> None:
    columns, stamps = market
    store.save_model(trained, "Round Trip")
    assert "Round Trip" in store.model_names()
    again = store.load_model("Round Trip")
    assert np.allclose(
        predict_series(trained, columns, stamps, "1m"),
        predict_series(again, columns, stamps, "1m"),
        equal_nan=True,
    )
    assert again.metrics == trained.metrics
    assert again.test_start == trained.test_start
    assert again.importance[0] == trained.importance[0]


def test_loading_a_model_that_is_not_there_says_so() -> None:
    with pytest.raises(MLError, match="no saved model"):
        store.load_model("never saved")


def test_removing_a_model_removes_its_files() -> None:
    columns, stamps = make_market(2500)
    model = train(columns, stamps, config("logistic"))
    store.save_model(model, "Gone")
    store.remove_model("Gone")
    assert "Gone" not in store.model_names()


def test_architectures_are_saved_by_name_and_replaced() -> None:
    spec = ModelSpec("My LSTM", "custom", {}, [dict(layer) for layer in ARCHITECTURE_PRESETS["LSTM"]])
    store.save_architecture(spec)
    spec.layers = []
    store.save_architecture(spec)
    kept = [item for item in store.architectures() if item.name == "My LSTM"]
    assert len(kept) == 1 and kept[0].layers == [] and kept[0].kind == "custom"
    store.remove_architecture("My LSTM")
    assert all(item.name != "My LSTM" for item in store.architectures())


def test_the_cash_cap_limits_what_a_trade_stakes() -> None:
    # 10 percent of a 2,000 cap on a 10,000 book is 200 dollars: a 2 percent win is +4
    stats = trade(
        [0.7, 0.5, 0.5], [100, 101, 99], [100, 103, 99], [100, 100, 98],
        size=0.10, capital=10_000.0, cash=2_000.0,
    )
    assert stats.strategy_return == pytest.approx(0.04)
