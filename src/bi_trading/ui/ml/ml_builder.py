"""The ML strategy builder: train a model to predict the market, then trade it.

Six steps, as the mockup lays them out: Data, Features, Target, Model,
Validation and Trading rule. Three columns hold the inputs (data and features,
target and model, the rule on the model's probability) and a results panel
underneath reports what the model did on bars it never saw.

Training runs on a worker thread (`workers.TrainWorker`). Saving writes the
trained model (`ml.store`) and a saved strategy whose rules read `model_p`, the
model's P(up), so the backtest, the builder and the compare page need nothing
new to use it.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bi_trading.ml import store
from bi_trading.ml.features import (
    FEATURES,
    TARGETS,
    custom_feature,
    default_features,
)
from bi_trading.ml.nets import torch_available
from bi_trading.ml.spec import (
    KINDS,
    ModelSpec,
    check_layers,
    kind_params,
    parameter_count,
)
from bi_trading.ml.train import TrainConfig, TrainedModel, trade_test
from bi_trading.state import strategies
from bi_trading.state.strategies import SavedStrategy
from bi_trading.ui.ml.ml_style import (
    ML_QSS,
    CurveChart,
    ImportanceBars,
    SplitBar,
    button,
    clear,
    field,
    label,
    panel,
    read_number,
    rule,
)
from bi_trading.ui.ml.workers import TrainWorker, available_years
from bi_trading.ui.palette import AMBER_DOT, DOWN_SOFT, UP

log = logging.getLogger(__name__)

__all__ = ["MLBuilderView"]

TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h")
BUILTIN = tuple(KINDS)

# Workers whose view was closed mid-run: kept alive until they end.
_DETACHED: list = []  # gbm, forest, logistic, mlp


def _day(stamp: int) -> str:
    if not stamp:
        return "?"
    return datetime.fromtimestamp(stamp / 1000, tz=UTC).strftime("%Y-%m-%d")


def _percent(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _decimal(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


class CustomFeatureDialog(QDialog):
    """A name and a formula over the bar's columns, checked as it is typed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QPlainTextEdit, QPushButton

        self.setWindowTitle("Custom feature")
        self.setModal(True)
        self.setStyleSheet(ML_QSS)
        self.resize(460, 280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(label("Name"))
        self.name = field("", mono=False)
        self.name.setPlaceholderText("range_pct")
        layout.addWidget(self.name)
        layout.addWidget(
            label(
                "Formula: the bar's own columns and the indicators, as in a rule. "
                "The last line is the value, one number per bar.",
                wrap=True,
            )
        )
        self.formula = QPlainTextEdit()
        self.formula.setObjectName("mlCode")
        self.formula.setPlaceholderText("(high - low) / close")
        layout.addWidget(self.formula, 1)
        self.status = label("", "mlCaption")
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("mlGhost")
        cancel.clicked.connect(self.reject)
        self.add = QPushButton("Add feature")
        self.add.setObjectName("mlPrimary")
        self.add.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.add)
        layout.addLayout(row)
        self.name.textChanged.connect(self._check)
        self.formula.textChanged.connect(self._check)
        self._check()

    def _check(self) -> None:
        from bi_trading.engine.formula import FIELDS, FUNCTIONS, FormulaError, parse

        name = self.name.text().strip()
        text = self.formula.toPlainText().strip()
        problem = ""
        if not name:
            problem = "give it a name"
        elif not text:
            problem = "write the formula"
        else:
            try:
                parse(text, FIELDS, FUNCTIONS)
            except FormulaError as exc:
                problem = str(exc)
        self.status.setText(problem or "✓ valid")
        self.add.setEnabled(not problem)

    def values(self) -> tuple[str, str]:
        return self.name.text().strip(), self.formula.toPlainText().strip()


class ModelRow(QFrame):
    """One model in the list: a radio, its name, a tag and sometimes Edit."""

    chosen = Signal(str)
    edit_requested = Signal(str)

    def __init__(self, key: str, name: str, tag: str, editable: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("mlModelRow")
        self.setProperty("selected", False)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 5, 9, 5)
        row.setSpacing(8)
        self.radio = QRadioButton(name)
        self.radio.setObjectName("mlRadio")
        self.radio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.radio.toggled.connect(self._toggled)
        row.addWidget(self.radio, 1)
        row.addWidget(label(tag, "mlTag"))
        if editable:
            edit = button("Edit", "mlMini")
            edit.clicked.connect(lambda: self.edit_requested.emit(self.key))
            row.addWidget(edit)

    def _toggled(self, on: bool) -> None:
        if on:
            self.chosen.emit(self.key)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.radio.blockSignals(True)
        self.radio.setChecked(on)
        self.radio.blockSignals(False)
        self.style().unpolish(self)
        self.style().polish(self)


class MLBuilderView(QWidget):
    """The ML strategy builder page."""

    open_builder = Signal(str)  # a saved strategy's name, or "" for a blank builder
    open_backtest = Signal(str)  # the saved strategy to run
    open_model_builder = Signal(str)  # a custom model's name, or "" for a new one
    saved = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mlRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(ML_QSS)

        self._trained: TrainedModel | None = None
        self._worker: TrainWorker | None = None
        self._saved_name = ""
        self._name_touched = False
        self._exit = ""
        self._kind = "gbm"
        self._features: dict[str, QCheckBox] = {}
        self._custom: dict[str, str] = {}
        self._model_rows: dict[str, ModelRow] = {}
        self._years = available_years()
        self._architectures = {spec.name: spec for spec in store.architectures()}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        page = QWidget()
        page.setObjectName("mlRoot")
        scroll.setWidget(page)
        body = QVBoxLayout(page)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)

        columns = QGridLayout()
        columns.setSpacing(8)
        columns.addWidget(self._data_column(), 0, 0)
        columns.addWidget(self._model_column(), 0, 1)
        columns.addWidget(self._rule_column(), 0, 2)
        for column in range(3):
            columns.setColumnStretch(column, 1)
        body.addLayout(columns, 1)
        body.addWidget(self._results())

        self._features_changed()
        self._select_kind("gbm")

    # -- layout ----------------------------------------------------------------

    def _data_column(self) -> QFrame:
        frame, layout = panel("Data & features")
        for caption, value in (("Market", "BTC"),):
            layout.addLayout(self._row(caption, label(value, "mlMono")))
        self.timeframe = QComboBox()
        self.timeframe.setObjectName("mlCombo")
        self.timeframe.addItems(TIMEFRAMES)
        self.timeframe.setCurrentText("5m" if "5m" in TIMEFRAMES else "1m")
        self.timeframe.currentTextChanged.connect(self._invalidate)
        span = (
            f"{self._years[0]} → {self._years[-1]}" if self._years else "no candles on disk"
        )
        self.span_label = label(span, "mlMono")
        candles = QHBoxLayout()
        candles.setSpacing(8)
        candles.addWidget(self.timeframe)
        candles.addWidget(self.span_label)
        layout.addLayout(self._row("Candles", candles))
        layout.addLayout(self._row("Source", label("Local store (Binance)", "mlMono")))

        layout.addSpacing(4)
        layout.addWidget(label("Split by time (no shuffling)"))
        layout.addWidget(SplitBar((("Train 60%", 0.6), ("Valid 20%", 0.2), ("Test 20%", 0.2))))
        layout.addWidget(label("The test set stays untouched until the final run."))

        head = QHBoxLayout()
        head.addWidget(label("FEATURES", "mlGroup"))
        head.addStretch(1)
        self.features_count = label("", "mlCaption")
        head.addWidget(self.features_count)
        layout.addSpacing(6)
        layout.addLayout(head)
        self.feature_grid = QGridLayout()
        self.feature_grid.setHorizontalSpacing(12)
        self.feature_grid.setVerticalSpacing(7)
        wanted = set(default_features())
        for feature in FEATURES:
            self._add_feature(feature.key, feature.label, feature.key in wanted)
        layout.addLayout(self.feature_grid)
        layout.addStretch(1)
        custom = button("+ Custom feature (formula)", "mlSoft")
        custom.clicked.connect(self._add_custom_feature)
        layout.addWidget(custom, 0, Qt.AlignmentFlag.AlignLeft)
        return frame

    def _add_feature(self, key: str, text: str, checked: bool) -> None:
        box = QCheckBox(text)
        box.setObjectName("mlCheck")
        box.setChecked(checked)
        box.toggled.connect(self._features_changed)
        position = len(self._features)
        self.feature_grid.addWidget(box, position // 2, position % 2)
        self._features[key] = box

    def _model_column(self) -> QFrame:
        frame, layout = panel("Target & model")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.target = QComboBox()
        self.target.setObjectName("mlCombo")
        for key, (text, _) in TARGETS.items():
            self.target.addItem(text, key)
        self.target.currentIndexChanged.connect(self._invalidate)
        self.horizon = field("5")
        self.min_move = field("0.10")
        for edit in (self.horizon, self.min_move):
            edit.editingFinished.connect(self._invalidate)
        grid.addWidget(label("Predict"), 0, 0, 1, 2)
        grid.addWidget(self.target, 1, 0, 1, 2)
        grid.addWidget(label("Horizon (bars)"), 2, 0)
        grid.addWidget(self.horizon, 3, 0)
        grid.addWidget(label("Min move %"), 2, 1)
        grid.addWidget(self.min_move, 3, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.balance = label("Class balance: shown after training", "mlCaption")
        layout.addWidget(self.balance)

        head = QHBoxLayout()
        head.addWidget(label("MODEL", "mlGroup"))
        head.addStretch(1)
        head.addWidget(label("Pick one, or build your own", "mlCaption"))
        layout.addSpacing(4)
        layout.addLayout(head)
        self.model_list = QVBoxLayout()
        self.model_list.setSpacing(5)
        layout.addLayout(self.model_list)
        self._fill_models()
        build = button("+ Build my own model", "mlSoft")
        build.clicked.connect(lambda: self.open_model_builder.emit(""))
        layout.addWidget(build)

        self.param_grid = QGridLayout()
        self.param_grid.setHorizontalSpacing(10)
        self.param_labels = [label("") for _ in range(3)]
        self.param_edits = [field("") for _ in range(3)]
        for column in range(3):
            self.param_grid.addWidget(self.param_labels[column], 0, column)
            self.param_grid.addWidget(self.param_edits[column], 1, column)
        layout.addLayout(self.param_grid)
        self.custom_note = label("", "mlCaption", wrap=True)
        layout.addWidget(self.custom_note)
        layout.addStretch(1)

        progress = QHBoxLayout()
        progress.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        progress.addWidget(self.progress, 1)
        self.progress_text = label("", "mlMonoMuted")
        progress.addWidget(self.progress_text)
        layout.addLayout(progress)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.auto_tune = QCheckBox("Auto-tune")
        self.auto_tune.setObjectName("mlCheck")
        self.auto_tune.setToolTip("Try a few settings and keep the one with the best validation loss")
        actions.addWidget(self.auto_tune)
        self.train_button = button("Train model", "mlPrimary")
        self.train_button.clicked.connect(self.start_training)
        actions.addWidget(self.train_button, 1)
        self.stop_button = button("Stop", "mlGhost")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)
        return frame

    def _rule_column(self) -> QFrame:
        frame, layout = panel("Trading rule")
        intro = QHBoxLayout()
        intro.setSpacing(6)
        intro.addWidget(label("The model outputs", "mlCaption"))
        intro.addWidget(label("model_p", "mlChip"))
        intro.addWidget(label("= P(up). It also appears as a block in the Formula builder.", "mlCaption"), 1)
        layout.addLayout(intro)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.up = field("0.60")
        self.down = field("0.40")
        self.min_edge = field("0.05")
        self.retrain = field("7")
        self.min_edge.setToolTip(
            "How far P(up) must sit from the market's price for a live Polymarket bet. "
            "Saved with the model; a backtest has no market price, so it is not used there."
        )
        for edit in (self.up, self.down):
            edit.editingFinished.connect(self._thresholds_changed)
        cells = (
            ("Bet UP / Long if P(up) ≥", self.up),
            ("Bet DOWN / Short if P(up) ≤", self.down),
            ("Min edge vs market price", self.min_edge),
            ("Retrain every (days)", self.retrain),
        )
        for index, (caption, edit) in enumerate(cells):
            grid.addWidget(label(caption), (index // 2) * 2, index % 2)
            grid.addWidget(edit, (index // 2) * 2 + 1, index % 2)
        layout.addLayout(grid)
        self.walk_forward = QCheckBox("Walk-forward retraining")
        self.walk_forward.setObjectName("mlCheck")
        self.walk_forward.setToolTip(
            "Score the test part with models retrained every N days on the past only. "
            "Slower; built-in models only."
        )
        layout.addWidget(self.walk_forward)
        layout.addWidget(rule())
        layout.addWidget(label("ON THE TEST SET", "mlGroup"))
        self.signals_value = label("—", "mlMono")
        self.hit_value = label("—", "mlMono")
        self.hit_value.setTextFormat(Qt.TextFormat.RichText)
        layout.addLayout(self._row("Signals", self.signals_value))
        layout.addLayout(self._row("Hit rate", self.hit_value))
        layout.addLayout(self._row("Period", self._period_label()))
        layout.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        edit_exit = button("Edit exit rules")
        edit_exit.clicked.connect(self._edit_exit)
        actions.addWidget(edit_exit, 1)
        formula = button("Open in formula")
        formula.clicked.connect(self._open_in_formula)
        actions.addWidget(formula, 1)
        layout.addLayout(actions)
        return frame

    def _period_label(self) -> QLabel:
        self.period_value = label("—", "mlMono")
        return self.period_value

    def _results(self) -> QFrame:
        frame, layout = panel()
        frame.setMinimumHeight(262)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.results_title = label("RESULTS · TEST SET", "mlH2")
        head.addWidget(self.results_title)
        head.addStretch(1)
        self.name_edit = field("", mono=False, width=260)
        self.name_edit.setPlaceholderText("Strategy name")
        self.name_edit.textEdited.connect(self._on_name_edited)
        head.addWidget(self.name_edit)
        open_saved = button("Open")
        open_saved.setToolTip("Open a saved model: its settings and results come back")
        open_saved.clicked.connect(self._open_menu)
        head.addWidget(open_saved)
        save = button("Save strategy")
        save.clicked.connect(self.save)
        head.addWidget(save)
        self.run_button = button("Run full backtest", "mlPrimary")
        self.run_button.clicked.connect(self._run_backtest)
        head.addWidget(self.run_button)
        layout.addLayout(head)
        self.status = label("", "mlCaption")
        layout.addWidget(self.status)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.table = QTableWidget(3, 4)
        self.table.setObjectName("mlTable")
        self.table.setHorizontalHeaderLabels(["Metric", "Train", "Valid", "Test"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(130)
        for row, name in enumerate(("Accuracy", "AUC", "Log loss")):
            self.table.setItem(row, 0, QTableWidgetItem(name))
        left = QVBoxLayout()
        left.addWidget(self.table)
        self.gap_label = label("", "mlWarn")
        left.addWidget(self.gap_label)
        left.addStretch(1)
        grid.addLayout(left, 0, 0)

        middle = QVBoxLayout()
        middle.addWidget(label("Feature importance"))
        self.importance = ImportanceBars()
        middle.addWidget(self.importance)
        middle.addStretch(1)
        grid.addLayout(middle, 0, 1)

        right = QVBoxLayout()
        right.addWidget(label("Strategy on the test period"))
        self.curve = CurveChart()
        right.addWidget(self.curve, 1)
        legend = QHBoxLayout()
        self.ml_legend = label("", "mlMono")
        self.hold_legend = label("", "mlMono")
        self.ml_legend.setStyleSheet("color: #f2c94c;")
        self.hold_legend.setStyleSheet("color: #c9cad0;")
        legend.addWidget(self.ml_legend)
        legend.addWidget(self.hold_legend)
        legend.addStretch(1)
        right.addLayout(legend)
        grid.addLayout(right, 0, 2)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid, 1)
        self.empty_note = label("Train a model to see how it does on bars it has never seen.", "mlCaption")
        layout.addWidget(self.empty_note)
        return frame

    @staticmethod
    def _row(caption: str, value) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(label(caption))
        row.addStretch(1)
        if isinstance(value, QHBoxLayout):
            row.addLayout(value)
        else:
            row.addWidget(value)
        return row

    # -- models -------------------------------------------------------------------

    def _fill_models(self) -> None:
        clear(self.model_list)
        self._model_rows.clear()
        for key in BUILTIN:
            text, tag, _ = KINDS[key]
            self._add_model_row(key, text, tag)
        for name in self._architectures:
            self._add_model_row(f"custom:{name}", name, "Custom", editable=True)
        row = self._model_rows.get(self._kind)
        if row is not None:
            row.set_selected(True)

    def _add_model_row(self, key: str, name: str, tag: str, editable: bool = False) -> None:
        row = ModelRow(key, name, tag, editable)
        row.chosen.connect(self._select_kind)
        row.edit_requested.connect(lambda k: self.open_model_builder.emit(k.split(":", 1)[1]))
        self.model_list.addWidget(row)
        self._model_rows[key] = row

    def refresh_architectures(self) -> None:
        """Re-read the saved custom models (after the model builder saved one)."""
        self._architectures = {spec.name: spec for spec in store.architectures()}
        self._fill_models()

    def use_architecture(self, name: str) -> None:
        self.refresh_architectures()
        if name in self._architectures:
            self._select_kind(f"custom:{name}")

    def _select_kind(self, key: str) -> None:
        self._kind = key
        for name, row in self._model_rows.items():
            row.set_selected(name == key)
        custom = key.startswith("custom:")
        for edit_label in self.param_labels:
            edit_label.setVisible(not custom)
        for edit in self.param_edits:
            edit.setVisible(not custom)
        self.custom_note.setVisible(custom)
        self.walk_forward.setEnabled(not custom)
        if custom:
            self._describe_custom()
        else:
            params = kind_params(key)
            for slot in range(3):
                shown = slot < len(params)
                self.param_labels[slot].setVisible(shown)
                self.param_edits[slot].setVisible(shown)
                if shown:
                    self.param_labels[slot].setText(params[slot].label)
                    self.param_edits[slot].setText(f"{params[slot].default:g}")
        self._refresh_name()
        self._invalidate()

    def _describe_custom(self) -> None:
        name = self._kind.split(":", 1)[1]
        spec = self._architectures.get(name)
        if spec is None:
            self.custom_note.setText("this custom model is gone")
            return
        features = max(1, len(self._chosen_features()))
        issues = check_layers(spec.layers, spec.training, features)
        errors = [item.text for item in issues if item.level == "error"]
        count = parameter_count(spec.layers, features) if not errors else 0
        stack = " → ".join(str(layer["kind"]) for layer in spec.layers) or "no layers"
        text = f"{stack} · {count:,} parameters"
        if errors:
            text = f"{errors[0]}: open Edit and fix it"
        elif not torch_available():
            text += " · torch is not installed (uv sync --extra ml)"
        self.custom_note.setText(text)

    def _spec(self) -> ModelSpec:
        if self._kind.startswith("custom:"):
            name = self._kind.split(":", 1)[1]
            spec = self._architectures[name]
            return ModelSpec(name, "custom", {}, [dict(x) for x in spec.layers], dict(spec.training))
        params = {}
        for slot, param in enumerate(kind_params(self._kind)):
            params[param.key] = param.clamp(
                read_number(self.param_edits[slot], param.default, param.low, param.high)
            )
        return ModelSpec(KINDS[self._kind][0], self._kind, params)

    # -- reading the controls ----------------------------------------------------------

    def _chosen_features(self) -> list[str]:
        return [key for key, box in self._features.items() if box.isChecked()]

    def _config(self) -> TrainConfig:
        from bi_trading.state.settings import Settings

        backtest = Settings.load().backtest
        horizon = int(read_number(self.horizon, 5, 1, 500))
        min_move = read_number(self.min_move, 0.10, 0.0, 10.0)
        chosen = self._chosen_features()
        return TrainConfig(
            spec=self._spec(),
            features=chosen,
            custom={key: text for key, text in self._custom.items() if key in chosen},
            target=str(self.target.currentData()),
            horizon=horizon,
            min_move=min_move,
            timeframe=self.timeframe.currentText(),
            auto_tune=self.auto_tune.isChecked(),
            walk_forward=self.walk_forward.isChecked() and self.walk_forward.isEnabled(),
            retrain_days=int(read_number(self.retrain, 7, 1, 365)),
            up=read_number(self.up, 0.60, 0.5, 0.99),
            down=read_number(self.down, 0.40, 0.01, 0.5),
            min_edge=read_number(self.min_edge, 0.05, 0.0, 0.5),
            tp=backtest.tp,
            sl=backtest.sl,
            hold=backtest.hold,
            fee=backtest.fee,
            slippage=backtest.slippage,
            sizing=backtest.sizing,
            position=backtest.position,
            capital=backtest.initial_capital,
            cash=min(backtest.cash, backtest.initial_capital),
        )

    # -- events ----------------------------------------------------------------------------

    def _features_changed(self) -> None:
        chosen = len(self._chosen_features())
        self.features_count.setText(f"{chosen} of {len(self._features)} selected")
        if self._kind.startswith("custom:"):
            self._describe_custom()
        self._invalidate()

    def _add_custom_feature(self) -> None:
        dialog = CustomFeatureDialog(self)
        if not dialog.exec():
            return
        name, text = dialog.values()
        key = custom_feature(name)
        if key in self._features:
            self._custom[key] = text
            self._features[key].setChecked(True)
            return
        self._custom[key] = text
        self._add_feature(key, name, True)
        self._features_changed()

    def _invalidate(self, *_args) -> None:
        """An input changed: the shown results no longer describe the controls."""
        self._refresh_name()

    def _on_name_edited(self, _text: str) -> None:
        self._name_touched = True

    def _refresh_name(self) -> None:
        if self._name_touched:
            return
        spec_label = (
            self._kind.split(":", 1)[1] if self._kind.startswith("custom:") else KINDS[self._kind][0]
        )
        self.name_edit.setText(f"BTC direction · {spec_label.lower()}")

    def _open_menu(self) -> None:
        names = store.model_names()
        menu = QMenu(self)
        if not names:
            menu.addAction("No saved models yet").setEnabled(False)
        for name in names:
            menu.addAction(name, partial(self.load_saved, name))
        menu.exec(self.cursor().pos())

    # -- training -------------------------------------------------------------------------------

    def start_training(self) -> None:
        if self._worker is not None:
            return
        if not self._years:
            self._say("no candles on disk: download history in the Backtest view", error=True)
            return
        config = self._config()
        if not config.features:
            self._say("pick at least one feature", error=True)
            return
        if config.spec.is_custom:
            issues = check_layers(config.spec.layers, config.spec.training, len(config.features))
            errors = [item.text for item in issues if item.level == "error"]
            if errors:
                self._say(errors[0], error=True)
                return
        self._say("")
        self.train_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress.setValue(0)
        self._worker = TrainWorker(config, self._years, self.name_edit.text().strip(), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.trained.connect(self._on_trained)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._worker_done)
        self._worker.start()

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.progress_text.setText("stopping…")

    def _on_progress(self, fraction: float, text: str) -> None:
        self.progress.setValue(int(fraction * 1000))
        self.progress_text.setText(text)

    def _on_failed(self, reason: str) -> None:
        if reason != "stopped":
            self._log("warn", "TRAIN", f"Training failed: {reason}")
        self.progress.setValue(0)
        self.progress_text.setText("")
        self._say(reason if reason != "stopped" else "stopped", error=reason != "stopped")

    def _on_trained(self, trained: TrainedModel) -> None:
        self._trained = trained
        self._saved_name = ""
        test = trained.metrics.get("test", {}).get("accuracy")
        self._log(
            "info", "TRAIN",
            f"Trained {trained.config.spec.label} in {self._duration(trained.seconds)}"
            + (f": test accuracy {test * 100:.1f}%" if test is not None else ""),
        )
        self.progress.setValue(1000)
        self.progress_text.setText(f"done · {self._duration(trained.seconds)}")
        self._show(trained)

    def _worker_done(self) -> None:
        worker, self._worker = self._worker, None
        self.train_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if worker is not None:
            worker.deleteLater()

    @staticmethod
    def _duration(seconds: float) -> str:
        minutes, rest = divmod(int(round(seconds)), 60)
        return f"{minutes}m {rest:02d}s" if minutes else f"{rest}s"

    def wait_for_training(self, timeout_ms: int = 600_000) -> None:
        """Block until a running training ends (tests, and closing the view)."""
        if self._worker is not None:
            self._worker.wait(timeout_ms)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Leave without waiting: the worker is told to stop and left to finish.

        A single model fit cannot be interrupted, so waiting here would freeze the
        window for as long as it takes. The worker is detached from this view,
        kept alive until it ends, and its result is dropped.
        """
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
            for signal in (worker.progress, worker.trained, worker.failed):
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect()
            worker.setParent(None)
            _DETACHED.append(worker)
            worker.finished.connect(lambda w=worker: _DETACHED.remove(w) if w in _DETACHED else None)
        super().closeEvent(event)

    # -- showing a result ---------------------------------------------------------------------------

    def _show(self, trained: TrainedModel) -> None:
        self.empty_note.setVisible(False)
        for column, part in enumerate(("train", "valid", "test"), start=1):
            metrics = trained.metrics.get(part, {})
            for row, (key, text) in enumerate(
                (
                    ("accuracy", _percent(metrics.get("accuracy"))),
                    ("auc", _decimal(metrics.get("auc"))),
                    ("logloss", _decimal(metrics.get("logloss"))),
                )
            ):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        gap = trained.gap
        if gap is None:
            self.gap_label.setText("")
        elif gap > 5.0:
            self.gap_label.setText(f"● Train − test gap {gap:.1f} pts: watch overfitting")
            self.gap_label.setStyleSheet(f"color: {AMBER_DOT};")
        else:
            self.gap_label.setText(f"✓ Train − test gap {gap:.1f} pts")
            self.gap_label.setStyleSheet(f"color: {UP};")
        self.importance.set_items(trained.importance)
        if trained.balance:
            self.balance.setText(
                "Class balance: " + " · ".join(f"{name} {share * 100:.0f}%" for name, share in sorted(
                    trained.balance.items(), key=lambda item: ("down", "flat", "up").index(item[0])
                ))
            )
        self.period_value.setText(f"{_day(trained.test_start)} → {_day(trained.test_end)}")
        walk = trained.config.walk_forward
        self.results_title.setText("RESULTS · TEST SET" + (" · WALK-FORWARD" if walk else ""))
        self._show_stats(trained)
        if trained.tuned:
            self.progress_text.setText(
                self.progress_text.text() + " · tuned " + ", ".join(f"{k} {v:g}" for k, v in trained.tuned.items())
            )

    def _show_stats(self, trained: TrainedModel) -> None:
        stats = trained.stats
        self.signals_value.setText(f"{stats.signals:,}")
        hit = stats.hit_rate
        if hit is None:
            self.hit_value.setText("—")
        else:
            colour = UP if hit >= 0.58 else AMBER_DOT if hit >= 0.52 else DOWN_SOFT
            self.hit_value.setText(
                f'<span style="color:{colour};font-size:9px;margin-right:5px">●</span>{hit * 100:.0f}%'
            )
        self.curve.set_curves(stats.strategy, stats.hold)
        self.ml_legend.setText(f"ML {stats.strategy_return:+.1f}%".replace("-", "−"))
        self.hold_legend.setText(f"buy & hold {stats.hold_return:+.1f}%".replace("-", "−"))

    def _thresholds_changed(self) -> None:
        """Moving a threshold re-trades the test bars; nothing is retrained."""
        config = self._config()
        trained = self._trained
        if trained is None or trained.test_p is None:
            return
        trained.config.up, trained.config.down = config.up, config.down
        trained.stats = trade_test(trained, trained.config)
        self._show_stats(trained)

    # -- saving -----------------------------------------------------------------------------------------

    def _log(self, level: str, kind: str, message: str) -> None:
        """Put a line in the trading log, where the Logs view shows it."""
        from bi_trading.state.events import event_log

        event_log().record(
            level, "system", kind, message, origin="ml", strategy=self.name_edit.text().strip()
        )

    def _say(self, text: str, error: bool = False) -> None:
        self.status.setObjectName("mlError" if error else "mlCaption")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)

    def rule_texts(self) -> tuple[str, str]:
        """The entry and short-entry rule the thresholds stand for."""
        up = read_number(self.up, 0.60, 0.5, 0.99)
        down = read_number(self.down, 0.40, 0.01, 0.5)
        return f"model_p >= {up:.2f}", f"model_p <= {down:.2f}"

    def save(self) -> str | None:
        """Save the trained model and a strategy that trades it. Returns the name."""
        name = self.name_edit.text().strip()
        if self._trained is None:
            self._say("train a model first", error=True)
            return None
        if not name:
            self._say("give the strategy a name", error=True)
            return None
        config = self._config()
        trained = self._trained
        trained.config.up, trained.config.down = config.up, config.down
        trained.config.min_edge = config.min_edge
        trained.config.retrain_days = config.retrain_days
        clash = next((s for s in strategies.load() if s.name == name and s.model != name), None)
        if clash is not None:
            # Saving would replace a strategy that is not this model's.
            self._say(
                f"a strategy called “{name}” already exists: pick another name", error=True
            )
            return None
        try:
            store.save_model(trained, name)
        except Exception as exc:  # disk, or a model that cannot be pickled
            log.warning("could not save the model", exc_info=True)
            self._say(f"could not save the model: {exc}", error=True)
            return None
        entry, short = self.rule_texts()
        strategies.save(
            SavedStrategy(
                name=name,
                timeframe=trained.config.timeframe,
                entry=entry,
                exit=self._exit,
                side="both",
                short_entry=short,
                model=name,
            )
        )
        self._saved_name = name
        self._log("info", "ML", f"Saved ML strategy “{name}”")
        self._say(f"saved “{name}”: its rules read model_p; backtest {_day(trained.test_start)} onwards")
        self.saved.emit(name)
        return name

    def _edit_exit(self) -> None:
        from bi_trading.ui.strat.rule_edit import RuleEditDialog

        entry, _ = self.rule_texts()
        dialog = RuleEditDialog(
            self.name_edit.text().strip() or "ML strategy", entry, self._exit, self,
            entry_readonly=True,
        )
        if dialog.exec():
            self._exit = dialog.exit()
            if self._saved_name:
                self.save()

    def _open_in_formula(self) -> None:
        name = self.save()
        if name:
            self.open_builder.emit(name)

    def _run_backtest(self) -> None:
        name = self.save()
        if name:
            self.open_backtest.emit(name)

    def load_saved(self, name: str) -> None:
        """Open a saved model: its settings back in the controls, its results on show."""
        from bi_trading.ml.train import MLError

        try:
            trained = store.load_model(name)
        except MLError as exc:
            self._say(str(exc), error=True)
            return
        config = trained.config
        self._name_touched = True
        self.name_edit.setText(name)
        self.timeframe.setCurrentText(config.timeframe)
        self.target.setCurrentIndex(max(0, self.target.findData(config.target)))
        self.horizon.setText(f"{config.horizon:g}")
        self.min_move.setText(f"{config.min_move:g}")
        self.up.setText(f"{config.up:.2f}")
        self.down.setText(f"{config.down:.2f}")
        self.min_edge.setText(f"{config.min_edge:.2f}")
        self.retrain.setText(str(config.retrain_days))
        self.walk_forward.setChecked(config.walk_forward)
        self.auto_tune.setChecked(config.auto_tune)
        self._custom = dict(config.custom)
        for key in config.custom:
            if key not in self._features:
                self._add_feature(key, key.split(":", 1)[1], True)
        for key, box in self._features.items():
            box.setChecked(key in config.features)
        spec = config.spec
        kind = f"custom:{spec.name}" if spec.is_custom else spec.kind
        if spec.is_custom and spec.name not in self._architectures:
            self._architectures[spec.name] = spec
            self._fill_models()
        if kind in self._model_rows:
            self._select_kind(kind)
            if not spec.is_custom:
                for slot, param in enumerate(kind_params(spec.kind)):
                    self.param_edits[slot].setText(f"{spec.resolved()[param.key]:g}")
        saved = next((item for item in strategies.load() if item.name == name), None)
        self._exit = saved.exit if saved else ""
        self._trained = trained
        self._saved_name = name if saved else ""
        self.progress.setValue(1000)
        self.progress_text.setText(f"loaded · trained in {self._duration(trained.seconds)}")
        self._show(trained)
