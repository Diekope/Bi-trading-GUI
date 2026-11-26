"""The model spec: layer shapes, the validator, parameter counts, the code view."""

from __future__ import annotations

import pytest

from bi_trading.ml.spec import (
    ARCHITECTURE_PRESETS,
    KINDS,
    ModelSpec,
    check_layers,
    default_layer,
    default_training,
    kind_params,
    layer_stack_code,
    parameter_count,
    shape_trace,
)


def errors(layers, training=None, **kwargs):
    issues = check_layers(layers, training or default_training(), kwargs.pop("features", 8), **kwargs)
    return [item.text for item in issues if item.level == "error"]


def test_every_preset_is_valid() -> None:
    for name, layers in ARCHITECTURE_PRESETS.items():
        assert errors(layers) == [], name


def test_the_mock_stack_is_valid_and_warns_about_capacity() -> None:
    layers = [
        {**default_layer("LSTM"), "units": 64},
        {**default_layer("Dropout"), "rate": 0.2},
        {**default_layer("Dense"), "units": 32},
    ]
    issues = check_layers(layers, default_training(), 8, samples=1_100_000)
    levels = [item.level for item in issues]
    assert "error" not in levels
    assert issues[0].text.startswith("Shapes line up: (30, 8) → LSTM 64 → Dropout 0.2 → Dense 32 → 1")
    assert any("1.1M training samples" in item.text for item in issues)
    assert any(item.level == "warn" and "Capacity" in item.text for item in issues)


def test_dense_before_a_sequence_layer_is_an_error() -> None:
    found = errors([default_layer("Dense"), default_layer("LSTM")])
    assert any("LSTM must come before any Dense" in text for text in found)


def test_dropout_of_one_or_more_is_an_error() -> None:
    assert any("Dropout" in text for text in errors([{**default_layer("Dropout"), "rate": 1.0}]))


def test_attention_needs_channels_that_split_into_heads() -> None:
    layer = {**default_layer("Attention"), "heads": 3}
    assert any("heads" in text for text in errors([layer], features=8))
    assert errors([{**default_layer("Attention"), "heads": 2}], features=8) == []


def test_bad_training_settings_are_errors() -> None:
    training = {**default_training(), "lr": 0, "epochs": 0, "batch": 0}
    found = errors([default_layer("Dense")], training)
    assert len(found) == 3


def test_an_unknown_layer_is_an_error() -> None:
    assert any("Unknown layer" in text for text in errors([{"kind": "Transformer"}]))


def test_no_features_is_an_error() -> None:
    assert any("No features" in text for text in errors([], features=0))


def test_a_sequence_layer_that_follows_another_keeps_its_bars() -> None:
    trace = shape_trace([default_layer("LSTM"), default_layer("LSTM")], 8)
    assert [shape.text() for _, shape, _ in trace if shape] == ["(30, 8)", "(30, 64)", "(64)", "(1)"]


def test_the_output_is_sized_for_the_target() -> None:
    assert shape_trace([], 8, classes=3)[-1][1].text() == "(3)"
    assert shape_trace([], 8, classes=2)[-1][1].text() == "(1)"


def test_parameter_counts_agree_with_torch() -> None:
    torch = pytest.importorskip("torch")
    from bi_trading.ml.nets import _build

    del torch
    for name in ("Neural net (MLP)", "LSTM", "Conv1D"):
        layers = ARCHITECTURE_PRESETS[name]
        spec = ModelSpec("x", "custom", {}, layers)
        net = _build(spec, 8, 2, 30)
        real = sum(parameter.numel() for parameter in net.parameters())
        assert parameter_count(layers, 8) == real, name


def test_attention_and_gru_counts_agree_with_torch() -> None:
    pytest.importorskip("torch")
    from bi_trading.ml.nets import _build

    layers = [
        {**default_layer("Attention"), "heads": 2},
        {**default_layer("GRU"), "units": 16},
        {**default_layer("BatchNorm")},
        {**default_layer("Dense"), "units": 8},
    ]
    net = _build(ModelSpec("x", "custom", {}, layers), 8, 3, 30)
    assert parameter_count(layers, 8, classes=3) == sum(p.numel() for p in net.parameters())


def test_the_code_view_reads_like_the_network() -> None:
    code = layer_stack_code(ARCHITECTURE_PRESETS["LSTM"], 8)
    assert "nn.LSTM(8, 64, batch_first=True)" in code
    assert "x = x[:, -1]" in code
    assert "torch.sigmoid" in code
    compile(code, "<net>", "exec")


def test_the_code_view_compiles_for_every_preset() -> None:
    for layers in ARCHITECTURE_PRESETS.values():
        compile(layer_stack_code(layers, 8), "<net>", "exec")


def test_builtin_settings_clamp_and_default() -> None:
    spec = ModelSpec("g", "gbm", {"trees": 999_999, "depth": 0})
    resolved = spec.resolved()
    assert resolved["trees"] == 2000 and resolved["depth"] == 1
    assert resolved["lr"] == 0.05


def test_a_spec_round_trips_through_a_dict() -> None:
    spec = ModelSpec("m", "custom", {}, [default_layer("Dense")], {**default_training(), "epochs": 5})
    again = ModelSpec.from_dict(spec.as_dict())
    assert again.layers == spec.layers and again.training["epochs"] == 5


def test_each_builtin_kind_has_settings() -> None:
    for kind in KINDS:
        assert kind_params(kind)
