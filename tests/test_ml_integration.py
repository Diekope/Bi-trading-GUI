"""`model_p` in the rest of the app: formulas, saved strategies, the backtest."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from bi_trading.data import candles  # noqa: E402
from bi_trading.data.candles import append_rows, candle_file  # noqa: E402
from bi_trading.engine import formula_eval as fe  # noqa: E402
from bi_trading.engine.formula import ENTRY_FIELDS, FUNCTIONS, parse  # noqa: E402
from bi_trading.state import runs, strategies  # noqa: E402
from bi_trading.state.strategies import SavedStrategy  # noqa: E402
from tests.ml_data import make_market  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path / "candles"))
    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    monkeypatch.setenv("BI_TRADING_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    candles._ROW_CACHE.clear()
    from bi_trading.ui.strat import playback_data, strat_playback

    strat_playback._SPAN_CACHE.clear()
    playback_data._SPAN_ARRAY_CACHE.clear()
    yield


def columns_with_model_p(length: int = 3000, seed: int = 2):
    columns, stamps = make_market(length, seed)
    p = np.random.default_rng(seed).uniform(0, 1, length)
    p[:700] = np.nan  # the model has no call before its test period
    return {**columns, "model_p": p}, stamps


def list_signals(formula, columns, fields):
    length = len(columns["close"])
    bars = [
        {
            name: (None if np.isnan(columns[name][i]) else float(columns[name][i]))
            for name in fields
            if name in columns
        }
        for i in range(length)
    ]
    values = fe.evaluate(formula, fe.bar_context(bars, fields))
    return [i for i, value in enumerate(values) if fe._truth(value)]


@pytest.mark.parametrize(
    "text",
    [
        "model_p >= 0.6",
        "model_p <= 0.4 and close > sma(close, 20)",
        "model_p > 0.5 or close < sma(close, 5)",
        "model_p - 0.5 > 0.1",
        "not (model_p < 0.9)",
    ],
)
def test_model_p_with_gaps_gives_the_same_signals_both_ways(text) -> None:
    columns, _ = columns_with_model_p()
    formula = parse(text, ENTRY_FIELDS, FUNCTIONS)
    fast = fe.entry_signals(formula, columns, ENTRY_FIELDS)
    assert fast == list_signals(formula, columns, ENTRY_FIELDS)
    assert fast, text
    assert min(fast) >= 0


def test_a_rule_on_model_p_is_silent_where_the_model_has_no_call() -> None:
    columns, _ = columns_with_model_p()
    formula = parse("model_p >= 0.0", ENTRY_FIELDS, FUNCTIONS)
    signals = fe.entry_signals(formula, columns, ENTRY_FIELDS)
    assert min(signals) == 700


def test_a_window_over_model_p_falls_back_to_the_list_walk() -> None:
    """A rolling mean over a series with gaps must not poison the bars after it."""
    columns, _ = columns_with_model_p()
    formula = parse("sma(model_p, 3) > 0.5", ENTRY_FIELDS, FUNCTIONS)
    assert not fe._model_p_is_plain(formula)
    assert fe.entry_signals(formula, columns, ENTRY_FIELDS) == list_signals(
        formula, columns, ENTRY_FIELDS
    )


def test_a_line_that_renames_model_p_is_not_plain() -> None:
    formula = parse("p = model_p\nsma(p, 3) > 0.5", ENTRY_FIELDS, FUNCTIONS)
    assert not fe._model_p_is_plain(formula)
    assert fe._model_p_is_plain(parse("model_p > 0.5", ENTRY_FIELDS, FUNCTIONS))


def test_a_field_the_rule_never_reads_need_not_be_in_the_columns() -> None:
    columns, _ = make_market(500)
    formula = parse("close > sma(close, 10)", ENTRY_FIELDS, FUNCTIONS)
    assert fe.entry_signals(formula, columns, ENTRY_FIELDS) == list_signals(
        formula, columns, ENTRY_FIELDS
    )


def test_evaluate_columns_returns_a_number_per_bar() -> None:
    columns, _ = make_market(100)
    formula = parse("(high - low) / close", ENTRY_FIELDS, FUNCTIONS)
    values = fe.evaluate_columns(formula, columns)
    assert np.allclose(values, (columns["high"] - columns["low"]) / columns["close"])


# -- saved strategies and runs carry the model -----------------------------------


def test_a_strategy_remembers_its_model() -> None:
    strategies.save(SavedStrategy("ml", "5m", "model_p >= 0.6", "", "both", "model_p <= 0.4", "my model"))
    kept = strategies.load()[0]
    assert kept.model == "my model" and kept.side == "both"
    strategies.save(SavedStrategy("plain", "5m", "close > open", ""))
    assert strategies.load()[1].model == ""


def test_an_old_strategies_file_without_a_model_still_loads(tmp_path) -> None:
    import json

    strategies.path().write_text(json.dumps([{"name": "old", "timeframe": "1m", "entry": "close > open"}]))
    assert strategies.load()[0].model == ""


def test_a_saved_run_remembers_its_model() -> None:
    runs.save(runs.SavedRun(name="r", model="my model", rule="saved", entry="model_p > 0.5"))
    assert runs.get("r").model == "my model"


# -- the backtest ----------------------------------------------------------------


def _write_candles(year: int, bars: int = 6000):
    columns, stamps = make_market(bars)
    rows = [
        (int(stamps[i]) - int(stamps[0]), columns["open"][i], columns["high"][i],
         columns["low"][i], columns["close"][i], columns["volume"][i])
        for i in range(bars)
    ]
    append_rows(candle_file(year), rows)


_PARAMS = {
    "initial_capital": 10_000.0, "tp": 2.0, "sl": 1.0, "hold": 5, "position": 50.0,
    "sizing": "balance", "cash": 8_000.0, "fee": 0.06, "slippage": 0.01, "warmup": 0,
}


def _train_and_save(name: str, years: list[int]):
    pytest.importorskip("sklearn")
    from bi_trading.ml import store
    from bi_trading.ml.features import default_features
    from bi_trading.ml.spec import ModelSpec
    from bi_trading.ml.train import TrainConfig, train
    from bi_trading.ui.ml.workers import load_columns

    columns, stamps = load_columns(years, "1m")
    model = train(
        columns, stamps,
        TrainConfig(
            spec=ModelSpec("t", "gbm", {"trees": 30, "depth": 3}),
            features=default_features(), horizon=1, min_move=0.0, max_samples=10_000,
        ),
        name,
    )
    store.save_model(model, name)
    return model


def test_a_backtest_trades_a_rule_on_model_p_only_on_unseen_bars() -> None:
    from bi_trading.ui.strat import strat_playback as sp

    _write_candles(2021)
    model = _train_and_save("m", [2021])
    formula = parse("model_p >= 0.55", ENTRY_FIELDS, FUNCTIONS)
    session = sp.build_session(
        [2021], _PARAMS, "saved", "1m", entry_formula=formula, model="m"
    )
    entries = np.nonzero(session.strategy_entries_arr)[0]
    assert len(entries) > 0
    first_test_bar = int(np.searchsorted(session.span.stamps, model.test_start))
    assert entries.min() >= first_test_bar
    assert "scores" in session.model_note
    session.seek(session.total)
    assert session.strategy.trades > 0


def test_a_model_that_cannot_be_used_says_why_and_trades_nothing() -> None:
    from bi_trading.ui.strat import strat_playback as sp

    _write_candles(2021)
    formula = parse("model_p >= 0.55", ENTRY_FIELDS, FUNCTIONS)
    session = sp.build_session(
        [2021], _PARAMS, "saved", "1m", entry_formula=formula, model="not saved"
    )
    assert "no saved model" in session.model_note
    assert not session.strategy_entries_arr.any()


def test_a_backtest_at_another_resolution_is_refused_with_a_reason() -> None:
    from bi_trading.ui.strat import strat_playback as sp

    _write_candles(2021)
    _train_and_save("m", [2021])
    formula = parse("model_p >= 0.55", ENTRY_FIELDS, FUNCTIONS)
    session = sp.build_session(
        [2021], _PARAMS, "saved", "5m", entry_formula=formula, model="m"
    )
    assert "trained on 1m" in session.model_note


def test_the_tile_passes_the_model_on_and_a_new_pick_forgets_it(qtbot=None) -> None:
    from PySide6.QtWidgets import QApplication

    from bi_trading.ui.strat.strat_playback import PlaybackTile

    QApplication.instance() or QApplication([])
    tile = PlaybackTile()
    assert tile.set_saved_strategy("ml", "model_p >= 0.6", ENTRY_FIELDS, "", "long", "", "m")
    assert tile.saved_model() == "m"
    tile.set_strategy("bollinger")
    assert tile.saved_model() == ""
