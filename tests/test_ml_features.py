"""Features and targets: causal inputs, honest labels, time-ordered splits."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy")  # the smoothed features (EMA, RSI) use it; part of the ml extra

from bi_trading.ml.features import (  # noqa: E402
    FEATURES,
    class_balance,
    default_features,
    feature_label,
    feature_matrix,
    forward_return,
    make_target,
    time_split,
)
from tests.ml_data import make_market  # noqa: E402


def test_every_feature_is_causal() -> None:
    """Changing the future must not change a past feature value."""
    columns, _ = make_market(800)
    keys = [feature.key for feature in FEATURES]
    before = feature_matrix(columns, keys)
    altered = {name: series.copy() for name, series in columns.items()}
    for name in ("open", "high", "low", "close", "volume"):
        altered[name][500:] *= 1.37
    after = feature_matrix(altered, keys)
    assert np.allclose(before[:500], after[:500], equal_nan=True)
    assert not np.allclose(before[500:], after[500:], equal_nan=True)


def test_the_warm_up_is_unknown_not_zero() -> None:
    columns, _ = make_market(300)
    matrix = feature_matrix(columns, ["ret15", "zscore20", "ema_ratio"])
    assert np.isnan(matrix[0]).all()
    assert np.isnan(matrix[10, 0]) and not np.isnan(matrix[20, 0])
    assert not np.isnan(matrix[60]).any()


def test_return_and_zscore_match_their_definitions() -> None:
    columns, _ = make_market(200)
    close = columns["close"]
    matrix = feature_matrix(columns, ["ret5", "zscore20"])
    assert matrix[50, 0] == pytest.approx(close[50] / close[45] - 1)
    window = close[31:51]
    assert matrix[50, 1] == pytest.approx((close[50] - window.mean()) / window.std())


def test_the_rolling_std_blocks_agree_with_a_plain_pass() -> None:
    from bi_trading.ml.features import _rolling_std

    values = np.random.default_rng(1).normal(size=450_000)
    got = _rolling_std(values, 20)
    for index in (19, 199_999, 200_018, 449_999):
        assert got[index] == pytest.approx(values[index - 19 : index + 1].std())
    assert np.isnan(got[18])


def test_ema_and_rsi_are_smoothed_in_one_pass() -> None:
    columns, _ = make_market(400)
    matrix = feature_matrix(columns, ["rsi14", "ema_ratio"])
    rsi = matrix[:, 0][~np.isnan(matrix[:, 0])]
    assert ((rsi >= 0) & (rsi <= 100)).all()
    assert not np.isnan(matrix[60, 1])


def test_a_custom_feature_is_a_formula() -> None:
    columns, _ = make_market(200)
    matrix = feature_matrix(
        columns, ["custom:range"], {"custom:range": "(high - low) / close"}
    )
    expected = (columns["high"] - columns["low"]) / columns["close"]
    assert np.allclose(matrix[:, 0], expected)
    assert feature_label("custom:range") == "range"


def test_an_unknown_feature_is_refused() -> None:
    columns, _ = make_market(50)
    with pytest.raises(KeyError):
        feature_matrix(columns, ["nope"])


def test_the_defaults_are_eight_of_ten() -> None:
    assert len(FEATURES) == 10
    assert len(default_features()) == 8
    assert "atr14" not in default_features() and "rsi14" not in default_features()


def test_the_target_looks_forward_and_drops_the_tail() -> None:
    close = np.array([100.0, 101.0, 100.0, 103.0, 102.0, 102.05])
    moves = forward_return(close, 2)
    assert moves[0] == pytest.approx(0.0)
    assert np.isnan(moves[-2:]).all()
    labels = make_target(close, 1, 0.0)
    assert list(labels) == [1, 0, 1, 0, 1, -1]


def test_a_move_inside_the_band_is_unlabelled_for_up_down() -> None:
    close = np.array([100.0, 100.05, 101.0, 99.0])
    labels = make_target(close, 1, 0.10)
    assert list(labels) == [-1, 1, 0, -1]


def test_three_classes_keep_the_flat_ones() -> None:
    close = np.array([100.0, 100.05, 101.0, 99.0])
    labels = make_target(close, 1, 0.10, "ternary")
    assert list(labels) == [1, 2, 0, -1]


def test_class_balance_counts_labelled_bars_only() -> None:
    labels = np.array([1, 1, 0, -1, -1], dtype=np.int8)
    balance = class_balance(labels)
    assert balance["up"] == pytest.approx(2 / 3)
    assert balance["down"] == pytest.approx(1 / 3)


def test_the_split_is_by_time_and_never_shuffled() -> None:
    train, valid, test = time_split(np.arange(1000))
    assert (len(train), len(valid), len(test)) == (600, 200, 200)
    assert train[-1] < valid[0] and valid[-1] < test[0]
