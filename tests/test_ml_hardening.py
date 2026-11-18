"""The ML layer against the rest of the project: bad data, name clashes, stale models."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.data import candles  # noqa: E402
from bi_trading.state import runs, strategies  # noqa: E402
from bi_trading.state.strategies import SavedStrategy  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402
from tests.ml_data import make_market  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path / "candles"))
    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    monkeypatch.setenv("BI_TRADING_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    candles._ROW_CACHE.clear()


# -- the candle store ------------------------------------------------------------------


def test_repair_cuts_stray_rows_and_keeps_the_rest() -> None:
    path = candles.candle_file(2021)
    start = candles._stamp(2021, 1, 1)
    good = [(start + i * 60_000, 1.0, 2.0, 0.5, 1.5, 1.0) for i in range(50)]
    stray = [(i * 60_000, 117.0, 118.0, 116.0, 117.5, 1.0) for i in range(10)]
    candles.append_rows(path, good)
    candles.append_rows(path, stray)                  # stamps in 1970
    candles.append_rows(path, good[:5])               # a block written twice
    assert candles.repair(path) == 15
    stamps = candles.arrays(path)[0]
    assert len(stamps) == 50 and (np.diff(stamps) > 0).all()
    assert candles.repair(path) == 0                  # nothing left to cut


def test_repair_of_a_missing_file_is_a_no_op() -> None:
    assert candles.repair(candles.candle_file(1999)) == 0


# -- order and holes ---------------------------------------------------------------------


def test_ordered_mask_drops_what_goes_back_in_time() -> None:
    from bi_trading.ml.features import ordered_mask

    stamps = np.array([10, 20, 0, 60_000, 30, 40])
    assert list(ordered_mask(stamps)) == [True, True, False, True, False, False]


def test_a_hole_marks_the_bars_after_it_and_the_targets_before_it() -> None:
    from bi_trading.ml.features import gap_invalid, horizon_gap

    stamps = np.concatenate([np.arange(10) * 60, 5000 + np.arange(10) * 60])
    assert list(np.nonzero(gap_invalid(stamps, 3))[0]) == [10, 11, 12]
    assert list(np.nonzero(horizon_gap(stamps, 2))[0]) == [8, 9]


def test_loading_columns_drops_out_of_order_rows(monkeypatch) -> None:
    pytest.importorskip("scipy")
    from bi_trading.ui.ml import workers
    from bi_trading.ui.strat import playback_data

    columns, stamps = make_market(300)
    bad = stamps.copy()
    bad[100] = 0
    span = playback_data.ColumnSpan.from_arrays(
        (bad, columns["open"], columns["high"], columns["low"], columns["close"], columns["volume"])
    )
    monkeypatch.setattr(playback_data, "load_span", lambda years, tf: span)
    kept_columns, kept = workers.load_columns([2021], "1m")
    assert len(kept) == 299 and (np.diff(kept) > 0).all()
    assert len(kept_columns["close"]) == 299


def test_training_and_scoring_leave_the_bars_after_a_hole_unknown() -> None:
    pytest.importorskip("sklearn")
    pytest.importorskip("scipy")
    from bi_trading.ml.features import default_features
    from bi_trading.ml.spec import ModelSpec
    from bi_trading.ml.train import TrainConfig, predict_series, train

    columns, stamps = make_market(6000)
    stamps = stamps.copy()
    stamps[4900:] += 10_000 * 60_000                  # a hole before bar 4900
    model = train(
        columns, stamps,
        TrainConfig(
            spec=ModelSpec("t", "logistic"), features=default_features(),
            horizon=1, min_move=0.0, max_samples=5000,
        ),
    )
    p = predict_series(model, columns, stamps, "1m", in_sample=True)
    assert np.isnan(p[4900:4900 + 61]).all()
    assert np.isfinite(p[4900 + 62:]).all()


def test_the_parts_leave_out_the_bars_whose_label_reaches_the_next_part() -> None:
    pytest.importorskip("sklearn")
    pytest.importorskip("scipy")
    from bi_trading.ml.features import default_features
    from bi_trading.ml.spec import ModelSpec
    from bi_trading.ml.train import TrainConfig, train

    columns, stamps = make_market(6000)
    base = dict(spec=ModelSpec("t", "logistic"), features=default_features(), min_move=0.0, max_samples=5000)
    short = train(columns, stamps, TrainConfig(horizon=1, **base))
    long = train(columns, stamps, TrainConfig(horizon=40, **base))
    assert short.samples["train"] - long.samples["train"] >= 39
    assert short.samples["valid"] - long.samples["valid"] >= 39


# -- the model store ---------------------------------------------------------------------------


def trained_model(name_hint: str = "t"):
    pytest.importorskip("sklearn")
    pytest.importorskip("scipy")
    from bi_trading.ml.features import default_features
    from bi_trading.ml.spec import ModelSpec
    from bi_trading.ml.train import TrainConfig, train

    columns, stamps = make_market(3000)
    return train(
        columns, stamps,
        TrainConfig(spec=ModelSpec(name_hint, "logistic"), features=default_features(), horizon=1, min_move=0.0),
    ), columns, stamps


def test_names_that_read_alike_keep_separate_models() -> None:
    from bi_trading.ml import store

    first, _, _ = trained_model()
    second, _, _ = trained_model()
    second.test_start = 12345
    store.save_model(first, "A b")
    store.save_model(second, "a-b")
    assert store.load_model("A b").test_start != store.load_model("a-b").test_start
    assert sorted(store.model_names()) == ["A b", "a-b"]


def test_changed_weights_are_refused_before_they_are_read() -> None:
    from bi_trading.ml import store
    from bi_trading.ml.train import MLError

    model, _, _ = trained_model()
    store.save_model(model, "tamper")
    weights = store._paths("tamper")[1]
    weights.write_bytes(weights.read_bytes() + b"x")
    store._CACHE.clear()
    with pytest.raises(MLError, match="do not match"):
        store.load_model("tamper")


def test_a_summary_reads_without_the_weights() -> None:
    from bi_trading.ml import store

    model, _, _ = trained_model()
    store.save_model(model, "sum")
    store._paths("sum")[1].unlink()
    summary = store.model_summary("sum")
    assert summary["timeframe"] == "1m" and summary["trained_at"] > 0
    assert store.model_summary("nothing") is None


def test_scoring_a_span_twice_reads_the_cache_and_retraining_empties_it() -> None:
    from bi_trading.ml import store

    model, columns, stamps = trained_model()
    store.save_model(model, "cache")
    a = store.scored("cache", columns, stamps, "1m")
    assert store.scored("cache", columns, stamps, "1m") is a
    store.save_model(model, "cache")                  # saved again: new files, new key
    assert store.scored("cache", columns, stamps, "1m") is not a


# -- strategies, runs and the screens ---------------------------------------------------------


def test_deleting_an_ml_strategy_deletes_its_model(app) -> None:
    from bi_trading.ml import store
    from bi_trading.ui.strat import strat_builder

    model, _, _ = trained_model()
    store.save_model(model, "gone")
    strategies.save(SavedStrategy("gone", "1m", "model_p >= 0.6", "", "long", "", "gone"))
    window = strat_builder.StrategyBuilderWindow()
    try:
        window.left.selected_name = "gone"

        class Dialog:
            choice = "delete"

            def __init__(self, *a): ...
            def exec(self): ...

        original = strat_builder.ConfirmDialog
        strat_builder.ConfirmDialog = Dialog
        try:
            window.delete_draft()
        finally:
            strat_builder.ConfirmDialog = original
    finally:
        window.close()
    assert "gone" not in store.model_names()
    assert strategies.load() == []


def test_a_model_shared_by_two_strategies_survives_one_delete(app) -> None:
    from bi_trading.ml import store
    from bi_trading.ui.strat import strat_builder

    model, _, _ = trained_model()
    store.save_model(model, "shared")
    for name in ("one", "two"):
        strategies.save(SavedStrategy(name, "1m", "model_p >= 0.6", "", "long", "", "shared"))
    window = strat_builder.StrategyBuilderWindow()
    try:
        window.left.selected_name = "one"

        class Dialog:
            choice = "delete"

            def __init__(self, *a): ...
            def exec(self): ...

        original = strat_builder.ConfirmDialog
        strat_builder.ConfirmDialog = Dialog
        try:
            window.delete_draft()
        finally:
            strat_builder.ConfirmDialog = original
    finally:
        window.close()
    assert "shared" in store.model_names()


def test_saving_will_not_replace_a_strategy_that_is_not_the_models(app, monkeypatch) -> None:
    pytest.importorskip("sklearn")
    from bi_trading.ui.ml.ml_builder import MLBuilderView

    monkeypatch.setattr("bi_trading.ui.ml.ml_builder.available_years", lambda: [])
    strategies.save(SavedStrategy("taken", "1m", "close > open", "pnl >= tp"))
    model, _, _ = trained_model()
    widget = MLBuilderView()
    try:
        widget._trained = model
        widget.name_edit.setText("taken")
        assert widget.save() is None
        assert "already exists" in widget.status.text()
        assert strategies.load()[0].entry == "close > open"
    finally:
        widget.close()


def test_the_home_badge_of_an_ml_strategy_is_its_models_test_return(app) -> None:
    from bi_trading.ml import store
    from bi_trading.ui.hub.hub_widgets import _pnl_badge

    model, _, _ = trained_model()
    model.stats.strategy_return = 3.456
    store.save_model(model, "badge")
    badge, tone = _pnl_badge("model_p >= 0.6", "", "1m", "long", "", "badge")
    assert "ML +3.46%" in badge
    assert "ML" in _pnl_badge("model_p >= 0.6", "", "1m", "long", "", "missing")[0]


def test_the_saved_list_marks_an_ml_strategy(app) -> None:
    from bi_trading.ml import store
    from bi_trading.ui.strat.strat_saved import StrategyListTile

    model, _, _ = trained_model()
    model.stats.strategy_return = -2.0
    store.save_model(model, "listed")
    text, _ = StrategyListTile._model_badge("listed")
    assert text.startswith("ML ") and "2.00" in text
    assert StrategyListTile._model_badge("nope") == ("ML", "muted")


def test_the_compare_page_says_a_model_strategy_needs_the_backtest(app) -> None:
    from bi_trading.data.candles import append_rows, candle_file
    from bi_trading.engine.formula import ENTRY_FIELDS, EXIT_FIELDS, EXIT_FUNCTIONS, FUNCTIONS, parse
    from bi_trading.engine.formula_eval import backtest
    from bi_trading.ui.strat.strat_compare import ComparePage
    from bi_trading.ui.strat.strat_saved import load_bars

    append_rows(candle_file(2021), [
        (i * 60_000, 100 + (i % 7), 101 + (i % 7), 99 + (i % 7), 100 + (i % 5), 1.0)
        for i in range(600)
    ])
    bars, _ = load_bars("1m")
    entry = parse("close < sma(close, 5)", ENTRY_FIELDS, FUNCTIONS)
    exit_ = parse("pnl >= tp", EXIT_FIELDS, EXIT_FUNCTIONS)
    page = ComparePage()
    page.configure(bars, entry, exit_, backtest(bars, entry, exit_, tp=2.0, sl=1.0), 2.0, 1.0)
    before = len(page.runs)
    page.add_strategy(SavedStrategy("ml", "1m", "model_p >= 0.6", "", "both", "model_p <= 0.4", "m"))
    assert len(page.runs) == before
    assert "needs its model" in page.sweep_hint.text()
    page.close()


def test_ml_is_a_valid_start_page(app, monkeypatch, tmp_path) -> None:
    import json

    from bi_trading.state.settings import Settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"general": {"start_page": "ml"}}))
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(path))
    assert Settings.load().general.start_page == "ml"
    from bi_trading.ui.hub.main_hub import MainHubWindow

    window = MainHubWindow(autostart=False)
    try:
        assert window._key == "ml"
    finally:
        window.close()


def test_a_run_remembers_which_model_it_used() -> None:
    runs.save(runs.SavedRun(name="r", model="m", model_stamp=123.5, rule="saved", entry="model_p > 0.5"))
    assert runs.get("r").model_stamp == 123.5


def test_closing_the_view_mid_training_does_not_wait_for_the_worker(app, monkeypatch) -> None:
    import time

    from bi_trading.ui.ml import ml_builder
    from bi_trading.ui.ml.ml_builder import MLBuilderView

    class Slow(ml_builder.TrainWorker):
        def run(self) -> None:
            for _ in range(100):
                if self._stop:
                    return
                time.sleep(0.02)

    monkeypatch.setattr(ml_builder, "TrainWorker", Slow)
    monkeypatch.setattr(ml_builder, "available_years", lambda: [2021])
    widget = MLBuilderView()
    widget.show()
    widget.start_training()
    worker = widget._worker
    began = time.time()
    widget.close()
    assert time.time() - began < 0.5
    assert worker in ml_builder._DETACHED
    worker.wait(5000)
    for _ in range(10):
        app.processEvents()
    assert worker not in ml_builder._DETACHED


def test_the_score_worker_warms_the_cache(app, monkeypatch) -> None:
    from bi_trading.ml import store
    from bi_trading.ui.ml import workers

    model, columns, stamps = trained_model()
    store.save_model(model, "warm")
    monkeypatch.setattr(workers, "load_columns", lambda years, tf: (columns, stamps))
    worker = workers.ScoreWorker("warm", [2021], "1m")
    worker.start()
    worker.wait(30_000)
    app.processEvents()
    assert any(key[0] == "warm" for key in store._SCORES)


def test_home_lists_the_ml_strategies_and_opens_one(app, monkeypatch, tmp_path) -> None:
    from bi_trading.ml import store
    from bi_trading.ui.hub.main_hub import MainHubWindow

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    model, _, _ = trained_model()
    store.save_model(model, "home ml")
    strategies.save(SavedStrategy("home ml", "1m", "model_p >= 0.6", "", "both", "model_p <= 0.4", "home ml"))
    strategies.save(SavedStrategy("plain", "1m", "close > open", ""))
    window = MainHubWindow(autostart=False)
    try:
        names = [
            window._model_box.itemAt(i).widget().name
            for i in range(window._model_box.count())
            if hasattr(window._model_box.itemAt(i).widget(), "name")
        ]
        assert names == ["home ml"]
        window._open("ml", strategy="home ml")
        assert type(window._view).__name__ == "MLBuilderView"
        assert window._view.name_edit.text() == "home ml"
    finally:
        window.close()
