"""The ML strategy builder and the model builder screens, and their place in the hub."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.ml import store  # noqa: E402
from bi_trading.ml.spec import default_layer  # noqa: E402
from bi_trading.state import strategies  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402
from tests.ml_data import make_market  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def pump(app: QApplication, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Saved strategies, models and runs live in a folder of the test's own."""
    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    monkeypatch.setenv("BI_TRADING_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("BI_TRADING_ARCHITECTURES", str(tmp_path / "architectures.json"))
    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))


@pytest.fixture
def no_candles(monkeypatch):
    monkeypatch.setattr("bi_trading.ui.ml.ml_builder.available_years", lambda: [])


@pytest.fixture
def market(monkeypatch):
    """A synthetic span in place of the candle store."""
    columns, stamps = make_market(6000)
    monkeypatch.setattr("bi_trading.ui.ml.ml_builder.available_years", lambda: [2021])
    monkeypatch.setattr(
        "bi_trading.ui.ml.workers.load_columns", lambda years, timeframe: (columns, stamps)
    )


def view(app):
    from bi_trading.ui.ml.ml_builder import MLBuilderView

    widget = MLBuilderView()
    widget.resize(1280, 900)
    widget.show()
    pump(app)
    return widget


def train_it(app, widget, kind: str = "logistic") -> None:
    pytest.importorskip("sklearn")
    widget._select_kind(kind)
    widget.horizon.setText("1")
    widget.min_move.setText("0")
    widget.start_training()
    widget.wait_for_training()
    pump(app)
    assert widget._trained is not None, widget.status.text()


# -- the ML strategy builder -----------------------------------------------------


def test_without_candles_the_data_step_is_current_and_training_says_why(app, no_candles) -> None:
    widget = view(app)
    try:
        widget.start_training()
        assert "no candles" in widget.status.text()
        assert widget._worker is None
    finally:
        widget.close()


def test_saving_before_training_says_to_train_first(app, no_candles) -> None:
    widget = view(app)
    try:
        assert widget.save() is None
        assert "train a model first" in widget.status.text()
    finally:
        widget.close()


def test_the_defaults_are_eight_of_ten_features_and_gradient_boosting(app, no_candles) -> None:
    widget = view(app)
    try:
        assert widget.features_count.text() == "8 of 10 selected"
        assert widget._kind == "gbm"
        assert widget.name_edit.text() == "BTC direction · gradient boosting"
        assert [label.text() for label in widget.param_labels] == ["Trees", "Max depth", "Learning rate"]
    finally:
        widget.close()


def test_unticking_a_feature_updates_the_count_and_a_model_change_the_name(app, no_candles) -> None:
    widget = view(app)
    try:
        widget._features["ret1"].setChecked(False)
        assert widget.features_count.text() == "7 of 10 selected"
        widget._select_kind("forest")
        assert widget.name_edit.text() == "BTC direction · random forest"
        assert not widget.param_labels[2].isHidden() and widget.param_labels[2].text() == "Min leaf"
        widget._select_kind("logistic")
        assert widget.param_labels[2].isHidden()
    finally:
        widget.close()


def test_a_name_typed_by_hand_is_kept(app, no_candles) -> None:
    widget = view(app)
    try:
        widget.name_edit.setText("mine")
        widget.name_edit.textEdited.emit("mine")
        widget._select_kind("forest")
        assert widget.name_edit.text() == "mine"
    finally:
        widget.close()


def test_a_custom_feature_is_added_and_ticked(app, no_candles, monkeypatch) -> None:
    from bi_trading.ui.ml import ml_builder

    class Fake(ml_builder.CustomFeatureDialog):
        def exec(self) -> int:
            self.name.setText("range")
            self.formula.setPlainText("(high - low) / close")
            return 1

    monkeypatch.setattr(ml_builder, "CustomFeatureDialog", Fake)
    widget = view(app)
    try:
        widget._add_custom_feature()
        assert widget._features["custom:range"].isChecked()
        assert widget.features_count.text() == "9 of 11 selected"
        assert widget._config().custom == {"custom:range": "(high - low) / close"}
    finally:
        widget.close()


def test_the_custom_feature_dialog_checks_the_formula(app) -> None:
    from bi_trading.ui.ml.ml_builder import CustomFeatureDialog

    dialog = CustomFeatureDialog()
    assert not dialog.add.isEnabled()
    dialog.name.setText("x")
    dialog.formula.setPlainText("clsoe + 1")
    assert not dialog.add.isEnabled() and "unknown name" in dialog.status.text()
    dialog.formula.setPlainText("close + 1")
    assert dialog.add.isEnabled() and dialog.status.text() == "✓ valid"


def test_training_fills_the_results(app, market) -> None:
    widget = view(app)
    try:
        train_it(app, widget)
        assert widget.table.item(0, 3).text().endswith("%")
        assert widget.importance.items and widget.importance.items[0][1] == 100.0
        assert widget.signals_value.text() != "—"
        assert "Class balance" in widget.balance.text() and "up" in widget.balance.text()
        assert widget.curve.strategy
        assert widget.ml_legend.text().startswith("ML ")
        assert widget.train_button.isEnabled() and not widget.stop_button.isEnabled()
    finally:
        widget.close()


def test_save_writes_the_model_and_a_strategy_that_reads_model_p(app, market) -> None:
    widget = view(app)
    try:
        train_it(app, widget)
        widget.up.setText("0.58")
        widget.down.setText("0.42")
        names = []
        widget.saved.connect(names.append)
        name = widget.save()
        assert name == "BTC direction · logistic regression" and names == [name]
        item = next(s for s in strategies.load() if s.name == name)
        assert (item.entry, item.short_entry, item.side) == ("model_p >= 0.58", "model_p <= 0.42", "both")
        assert item.model == name and item.timeframe == "5m"
        assert name in store.model_names()
    finally:
        widget.close()


def test_moving_a_threshold_retrades_the_test_part_without_retraining(app, market) -> None:
    widget = view(app)
    try:
        train_it(app, widget)
        before = widget._trained.stats.signals
        widget.up.setText("0.90")
        widget.down.setText("0.10")
        widget._thresholds_changed()
        assert widget._trained.stats.signals < before
        assert widget.signals_value.text() == f"{widget._trained.stats.signals:,}"
    finally:
        widget.close()


def test_the_exit_rule_goes_into_the_saved_strategy(app, market) -> None:
    widget = view(app)
    try:
        train_it(app, widget)
        widget._exit = "pnl >= tp"
        name = widget.save()
        assert next(s for s in strategies.load() if s.name == name).exit == "pnl >= tp"
    finally:
        widget.close()


def test_a_saved_model_opens_again_with_its_settings(app, market) -> None:
    widget = view(app)
    try:
        train_it(app, widget)
        widget.up.setText("0.57")
        name = widget.save()
    finally:
        widget.close()
    again = view(app)
    try:
        again.load_saved(name)
        assert again.features_count.text() == widget.features_count.text()
        assert again.name_edit.text() == name
        assert again._kind == "logistic"
        assert again.up.text() == "0.57"
        assert again.horizon.text() == "1"
        assert again.table.item(0, 3).text().endswith("%")
    finally:
        again.close()


def test_stop_cancels_a_run_and_says_so(app, market) -> None:
    pytest.importorskip("sklearn")
    widget = view(app)
    try:
        widget._select_kind("forest")
        widget.param_edits[0].setText("500")
        widget.start_training()
        widget._stop()
        widget.wait_for_training()
        pump(app)
        assert widget._trained is None
    finally:
        widget.close()


def test_a_custom_model_with_errors_will_not_start(app, market) -> None:
    store.save_architecture(
        store.ModelSpec("bad", "custom", {}, [default_layer("Dense"), default_layer("LSTM")])
    )
    widget = view(app)
    try:
        widget.refresh_architectures()
        widget._select_kind("custom:bad")
        widget.start_training()
        assert "LSTM must come before" in widget.status.text()
        assert widget._worker is None
        assert "open Edit and fix it" in widget.custom_note.text()
    finally:
        widget.close()


# -- the model builder ------------------------------------------------------------------


def builder(app):
    from bi_trading.ui.ml.model_builder import ModelBuilderView

    widget = ModelBuilderView()
    widget.resize(1200, 800)
    widget.show()
    pump(app)
    return widget


def test_the_model_builder_starts_as_a_valid_mlp(app) -> None:
    widget = builder(app)
    try:
        assert [layer["kind"] for layer in widget.layers] == ["Dense", "Dropout", "Dense"]
        assert widget.verdict_text.text() == "✓ Model is valid"
        assert widget.save_button.isEnabled()
        assert widget.count_label.text().endswith("parameters")
        assert "30 bars × 8 features" in widget.stack.input_text
    finally:
        widget.close()


def test_adding_and_removing_layers_changes_the_stack_and_the_count(app) -> None:
    widget = builder(app)
    try:
        before = widget.count_label.text()
        widget.stack.add("Dense")
        assert len(widget.layers) == 4 and widget.count_label.text() != before
        widget.stack.remove(3)
        assert len(widget.layers) == 3 and widget.count_label.text() == before
    finally:
        widget.close()


def test_dense_before_lstm_is_an_error_that_disables_saving(app) -> None:
    widget = builder(app)
    try:
        widget.stack.add("LSTM")
        assert widget.verdict_text.text() == "✕ Model has errors"
        assert not widget.save_button.isEnabled() and not widget.use_button.isEnabled()
        assert widget.save() is None
        widget.stack.move_layer(3, 0)
        assert widget.verdict_text.text() == "✓ Model is valid"
        assert widget.save_button.isEnabled()
    finally:
        widget.close()


def test_a_value_typed_into_a_layer_is_validated(app) -> None:
    widget = builder(app)
    try:
        dropout = widget.stack.rows[1]
        edit = dropout.edits["rate"]
        edit.setText("1.5")
        edit.editingFinished.emit()
        assert widget.verdict_text.text() == "✕ Model has errors"
        edit.setText("0.3")
        edit.editingFinished.emit()
        assert widget.verdict_text.text() == "✓ Model is valid"
        assert widget.layers[1]["rate"] == 0.3
    finally:
        widget.close()


def test_training_settings_are_read_and_checked(app) -> None:
    widget = builder(app)
    try:
        widget.lr.setText("0")
        widget.lr.editingFinished.emit()
        assert widget.verdict_text.text() == "✕ Model has errors"
        widget.lr.setText("0.002")
        widget.lr.editingFinished.emit()
        widget.epochs.setText("12")
        widget.epochs.editingFinished.emit()
        assert widget.training["lr"] == 0.002 and widget.training["epochs"] == 12
    finally:
        widget.close()


def test_start_from_replaces_the_stack(app) -> None:
    widget = builder(app)
    try:
        widget.start.setCurrentText("LSTM")
        assert widget.layers[0]["kind"] == "LSTM"
        widget.start.setCurrentText("Blank")
        assert widget.layers == []
        assert widget.verdict_text.text() == "✓ Model is valid"
    finally:
        widget.close()


def test_the_code_page_shows_the_network(app) -> None:
    widget = builder(app)
    try:
        widget.start.setCurrentText("LSTM")
        assert "nn.LSTM(8, 64, batch_first=True)" in widget.code.toPlainText()
        widget.stack.add("Dense")
        widget.stack.move_layer(widget.stack.selected, 0)
        assert "fix the errors" in widget.code.toPlainText()
    finally:
        widget.close()


def test_the_guide_follows_the_layer_picked(app) -> None:
    widget = builder(app)
    try:
        widget.stack.add("LSTM")
        assert widget.guide_name.text() == "LSTM"
        assert "short-term memory" in widget.guide_text[0].text()
        assert "Input" in widget._tab_buttons and "Output" in widget._tab_buttons
    finally:
        widget.close()


def test_saving_makes_the_model_appear_in_the_ml_builder(app, no_candles) -> None:
    widget = builder(app)
    try:
        widget.name.setText("My LSTM v2")
        widget.start.setCurrentText("LSTM")
        used = []
        widget.use_requested.connect(used.append)
        widget._use()
        assert used == ["My LSTM v2"]
    finally:
        widget.close()
    ml = view(app)
    try:
        assert "custom:My LSTM v2" in ml._model_rows
        ml.use_architecture("My LSTM v2")
        assert ml._kind == "custom:My LSTM v2"
        assert "LSTM → Dropout → Dense" in ml.custom_note.text()
        assert ml.walk_forward.isEnabled() is False
    finally:
        ml.close()
    reopened = builder(app)
    try:
        assert reopened.load("My LSTM v2")
        assert reopened.layers[0]["kind"] == "LSTM"
    finally:
        reopened.close()


def test_dragging_a_layer_to_the_top_moves_it(app) -> None:
    widget = builder(app)
    try:
        last = widget.layers[2]
        widget.stack.move_layer(2, 0)
        assert widget.layers[0] is last
    finally:
        widget.close()


# -- in the hub --------------------------------------------------------------------------------


def hub(app, monkeypatch, tmp_path):
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    from bi_trading.ui.hub.main_hub import MainHubWindow

    window = MainHubWindow(autostart=False)
    window.show()
    pump(app)
    return window


def test_the_rail_has_an_ml_section_and_it_opens_the_builder(app, monkeypatch, tmp_path, no_candles) -> None:
    window = hub(app, monkeypatch, tmp_path)
    try:
        assert "ml" in window._nav_buttons
        window._open("ml")
        assert type(window._view).__name__ == "MLBuilderView"
        assert window._nav_buttons["ml"][0].property("active") == "true"
    finally:
        window.close()


def test_the_model_builder_opens_under_ml_and_comes_back_with_the_saved_model(
    app, monkeypatch, tmp_path, no_candles
) -> None:
    window = hub(app, monkeypatch, tmp_path)
    try:
        window._open("ml")
        window._view.open_model_builder.emit("")
        pump(app)
        assert type(window._view).__name__ == "ModelBuilderView"
        assert window._nav_buttons["ml"][0].property("active") == "true"
        window._view.name.setText("Hub Net")
        window._view._use()
        pump(app)
        assert type(window._view).__name__ == "MLBuilderView"
        assert window._view._kind == "custom:Hub Net"
    finally:
        window.close()


def test_run_full_backtest_opens_the_backtest_on_the_strategy(app, monkeypatch, tmp_path, market) -> None:
    from bi_trading.state import venue as venue_state

    monkeypatch.setattr(venue_state, "current", lambda: venue_state.HL)
    window = hub(app, monkeypatch, tmp_path)
    try:
        window._open("ml")
        train_it(app, window._view)
        window._view._run_backtest()
        pump(app)
        assert window._key == "backtest"
        tile = window._view.left
        assert tile.saved_name() == "BTC direction · logistic regression"
        assert tile.saved_model() == "BTC direction · logistic regression"
    finally:
        window.close()


def test_the_builder_keeps_the_model_link_when_the_strategy_is_resaved(app) -> None:
    from bi_trading.ui.strat.strat_builder import StrategyBuilderWindow

    strategies.save(strategies.SavedStrategy("ml", "1m", "model_p >= 0.6", "", "long", "", "linked"))
    window = StrategyBuilderWindow()
    try:
        window.load_strategy("ml")
        assert window.draft_strategy().model == "linked"
        window.entry.set_text("close > open")
        assert window.draft_strategy().model == ""
    finally:
        window.close()


def test_every_training_setting_comes_back_with_a_saved_model(app, market) -> None:
    pytest.importorskip("sklearn")
    widget = view(app)
    try:
        widget._select_kind("forest")
        widget.param_edits[0].setText("33")
        widget.param_edits[1].setText("5")
        widget.param_edits[2].setText("77")
        widget._features["atr14"].setChecked(True)
        widget._features["ret1"].setChecked(False)
        widget.horizon.setText("2")
        widget.min_move.setText("0.05")
        widget.timeframe.setCurrentText("15m")
        widget.retrain.setText("3")
        widget.walk_forward.setChecked(True)
        widget.start_training()
        widget.wait_for_training()
        pump(app)
        name = widget.save()
        assert name
    finally:
        widget.close()
    again = view(app)
    try:
        again.load_saved(name)
        assert again._kind == "forest"
        assert [e.text() for e in again.param_edits] == ["33", "5", "77"]
        assert again._features["atr14"].isChecked() and not again._features["ret1"].isChecked()
        assert (again.horizon.text(), again.min_move.text()) == ("2", "0.05")
        assert again.timeframe.currentText() == "15m"
        assert again.retrain.text() == "3" and again.walk_forward.isChecked()
    finally:
        again.close()


def test_the_builder_says_how_far_ahead_the_model_looks(app, no_candles) -> None:
    widget = view(app)
    try:
        widget.timeframe.setCurrentText("5m")
        widget.horizon.setText("1")
        widget.horizon.editingFinished.emit()
        assert "5 min ahead" in widget.horizon_note.text() and "can use it" in widget.horizon_note.text()
        widget.timeframe.setCurrentText("1m")
        widget.horizon.setText("5")
        widget.horizon.editingFinished.emit()
        assert "can use it" in widget.horizon_note.text()
        widget.timeframe.setCurrentText("15m")
        assert "75 min ahead" in widget.horizon_note.text() and "backtests only" in widget.horizon_note.text()
    finally:
        widget.close()


def test_the_holdout_is_locked_until_saved_and_scores_only_once(app, market) -> None:
    import time

    widget = view(app)
    try:
        train_it(app, widget)
        assert "locked" in widget.holdout_value.text()
        assert widget.trials_value.text() == "1"
        assert not widget.holdout_button.isEnabled()       # it is scored by name: save first
        widget.save()
        assert widget.holdout_button.isEnabled()
        widget._score_holdout()
        end = time.time() + 30
        while widget._hold_worker is not None and time.time() < end:
            pump(app)
            time.sleep(0.01)
        pump(app)
        assert "scored once" in widget.holdout_value.text()
        assert not widget.holdout_button.isEnabled()       # not offered a second time
    finally:
        widget.close()
