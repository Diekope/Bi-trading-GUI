"""The model builder: design a custom network, check it, and save it for the ML builder.

Layers on the left are clicked (or dragged) into a stack in the middle; the
right shows a guide to the layer picked and a validator that says what would
fail before anything is trained. Errors disable Save. A saved model appears in
the ML strategy builder's model list; what is saved is the architecture, and it
is trained there, on the features and target picked there.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bi_trading.ml import store
from bi_trading.ml.features import default_features
from bi_trading.ml.spec import (
    ACTIVATION_LAYERS,
    ACTIVATIONS,
    ARCHITECTURE_PRESETS,
    INPUT_BARS,
    LAYER_GUIDE,
    LAYER_KINDS,
    LOSSES,
    OPTIMIZERS,
    Issue,
    ModelSpec,
    check_layers,
    default_layer,
    default_training,
    layer_stack_code,
    parameter_count,
)
from bi_trading.ui.ml.ml_style import (
    ML_QSS,
    SegmentedChoice,
    button,
    clear,
    field,
    label,
    panel,
)
from bi_trading.ui.palette import AMBER_DOT, DOWN_SOFT, UP

__all__ = ["ModelBuilderView"]

FEATURES = len(default_features())


class FixedRow(QFrame):
    """The Input and Output rows: a name and a line of detail; clicking shows its guide."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.detail: QLabel = QLabel()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


class Grip(QLabel):
    """The ⋮⋮ handle: dragging it moves the layer."""

    def __init__(self, owner: LayerRow) -> None:
        super().__init__("⋮⋮")
        self.owner = owner
        self.setStyleSheet("color: #6b6d75; letter-spacing: -2px;")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not event.buttons() & Qt.MouseButton.LeftButton:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.owner.index))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class LayerRow(QFrame):
    """One layer of the stack: grip, name, its settings, a remove button."""

    changed = Signal()
    removed = Signal(int)
    picked = Signal(int)

    def __init__(self, index: int, layer: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.layer = layer
        self.setObjectName("mlLayerRow")
        self.setProperty("selected", False)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)
        row.addWidget(Grip(self))
        name = label(str(layer["kind"]), "mlLayerName")
        name.setFixedWidth(84)
        row.addWidget(name)
        settings = QHBoxLayout()
        settings.setSpacing(14)
        self.edits: dict[str, object] = {}
        for param in LAYER_KINDS[layer["kind"]][1]:
            cell = QHBoxLayout()
            cell.setSpacing(6)
            cell.addWidget(label(param.label))
            edit = field(f"{layer.get(param.key, param.default):g}", width=70)
            edit.editingFinished.connect(lambda p=param, e=edit: self._edited(p, e))
            cell.addWidget(edit)
            settings.addLayout(cell)
            self.edits[param.key] = edit
        if layer["kind"] in ACTIVATION_LAYERS:
            combo = QComboBox()
            combo.setObjectName("mlCombo")
            combo.addItems(ACTIVATIONS)
            combo.setCurrentText(str(layer.get("activation", "ReLU")))
            combo.currentTextChanged.connect(self._activation)
            combo.setFixedWidth(96)
            settings.addWidget(combo)
        settings.addStretch(1)
        row.addLayout(settings, 1)
        remove = button("×", "mlMini")
        remove.setToolTip(f"Remove {layer['kind']}")
        remove.clicked.connect(lambda: self.removed.emit(self.index))
        row.addWidget(remove)

    def _edited(self, param, edit) -> None:
        text = edit.text().strip().replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            edit.setProperty("invalid", True)
            edit.style().unpolish(edit)
            edit.style().polish(edit)
            return
        edit.setProperty("invalid", False)
        edit.style().unpolish(edit)
        edit.style().polish(edit)
        self.layer[param.key] = int(value) if param.integer and value == int(value) else value
        self.changed.emit()

    def _activation(self, text: str) -> None:
        self.layer["activation"] = text
        self.changed.emit()

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.picked.emit(self.index)
        super().mousePressEvent(event)


class Stack(QWidget):
    """The input row, the layers and the output row, with drag-to-reorder."""

    layers_changed = Signal()
    layer_picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.layers: list[dict] = []
        self.rows: list[LayerRow] = []
        self.selected = -1
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(4)
        self.input_text = ""
        self.output_text = ""

    # -- building --------------------------------------------------------------

    def set_layers(self, layers: list[dict]) -> None:
        self.layers = layers
        self.rebuild()

    def rebuild(self) -> None:
        clear(self.column)
        self.rows = []
        self.column.addWidget(self._fixed("Input", self.input_text))
        for index, layer in enumerate(self.layers):
            self.column.addWidget(self._arrow())
            row = LayerRow(index, layer)
            row.changed.connect(self.layers_changed)
            row.removed.connect(self.remove)
            row.picked.connect(self._pick)
            self.rows.append(row)
            self.column.addWidget(row)
        self.column.addWidget(self._arrow())
        self.output_row = self._fixed("Output", self.output_text)
        self.column.addWidget(self.output_row)
        self.selected = min(self.selected, len(self.layers) - 1)
        if 0 <= self.selected < len(self.rows):
            self.rows[self.selected].set_selected(True)

    def _fixed(self, name: str, text: str) -> FixedRow:
        frame = FixedRow()
        frame.setObjectName("mlFixedRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)
        title = label(name, "mlMono")
        title.setStyleSheet("font-weight: 600; color: #8b8d95;")
        title.setFixedWidth(84)
        row.addWidget(title)
        detail = label(text, "mlMonoMuted")
        detail.setObjectName("mlMonoMuted")
        row.addWidget(detail, 1)
        frame.detail = detail
        frame.clicked.connect(partial(self.layer_picked.emit, name))
        return frame

    @staticmethod
    def _arrow() -> QLabel:
        arrow = QLabel("▼")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet("color: #4a4b52; font-size: 10px;")
        arrow.setFixedHeight(10)
        return arrow

    def set_ends(self, input_text: str, output_text: str) -> None:
        self.input_text, self.output_text = input_text, output_text
        item = self.column.itemAt(0)
        first = item.widget() if item is not None else None
        if isinstance(first, FixedRow):
            first.detail.setText(input_text)
        self.output_row.detail.setText(output_text)

    # -- editing -----------------------------------------------------------------

    def add(self, kind: str) -> None:
        self.layers.append(default_layer(kind))
        self.selected = len(self.layers) - 1
        self.rebuild()
        self.layers_changed.emit()
        self.layer_picked.emit(kind)

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.layers):
            del self.layers[index]
            self.selected = min(self.selected, len(self.layers) - 1)
            self.rebuild()
            self.layers_changed.emit()

    def _pick(self, index: int) -> None:
        for row in self.rows:
            row.set_selected(row.index == index)
        self.selected = index
        self.layer_picked.emit(str(self.layers[index]["kind"]))

    def move_layer(self, source: int, target: int) -> None:
        if source == target or not (0 <= source < len(self.layers)):
            return
        layer = self.layers.pop(source)
        self.layers.insert(max(0, min(target, len(self.layers))), layer)
        self.selected = target
        self.rebuild()
        self.layers_changed.emit()

    # -- dragging ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        try:
            source = int(event.mimeData().text())
        except ValueError:
            return
        y = event.position().y()
        target = len(self.rows) - 1
        for row in self.rows:
            if y < row.geometry().center().y():
                target = row.index if row.index <= source else row.index - 1
                break
        self.move_layer(source, target)
        event.acceptProposedAction()


class ModelBuilderView(QWidget):
    """The model builder page."""

    closed = Signal()
    saved = Signal(str)
    use_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mlRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(ML_QSS)
        self.layers: list[dict] = [dict(layer) for layer in ARCHITECTURE_PRESETS["Neural net (MLP)"]]
        self.training = default_training()
        self.features = FEATURES
        self.samples: int | None = self._estimate_samples()
        self._issues: list[Issue] = []
        self._guide_key = "Input"

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

        body.addLayout(self._top())
        columns = QGridLayout()
        columns.setSpacing(8)
        columns.addWidget(self._palette(), 0, 0)
        columns.addWidget(self._architecture(), 0, 1)
        columns.addLayout(self._right(), 0, 2)
        columns.setColumnMinimumWidth(0, 230)
        columns.setColumnStretch(1, 1)
        columns.setColumnMinimumWidth(2, 340)
        body.addLayout(columns, 1)
        body.addLayout(self._bottom())

        self.stack.set_layers(self.layers)
        self._refresh()

    @staticmethod
    def _estimate_samples() -> int | None:
        try:
            from bi_trading.ui.ml.workers import available_years
            from bi_trading.ui.strat.playback_data import count_bars

            years = available_years()
            total = count_bars(years, "5m") if years else 0
            return int(total * 0.6) or None
        except Exception:  # an estimate for a hint line; never worth failing the view
            return None

    # -- layout ---------------------------------------------------------------------

    def _top(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        name_col = QVBoxLayout()
        name_col.setSpacing(5)
        name_col.addWidget(label("Model name"))
        self.name = field("My model", mono=False, width=260)
        self.name.textChanged.connect(self._refresh)
        name_col.addWidget(self.name)
        row.addLayout(name_col)
        start_col = QVBoxLayout()
        start_col.setSpacing(5)
        start_col.addWidget(label("Start from"))
        self.start = QComboBox()
        self.start.setObjectName("mlCombo")
        self.start.setFixedWidth(200)
        self.start.addItems(list(ARCHITECTURE_PRESETS))
        self.start.currentTextChanged.connect(self._start_from)
        start_col.addWidget(self.start)
        row.addLayout(start_col)
        row.addStretch(1)
        modes = SegmentedChoice((("visual", "Visual"), ("code", "Code")), "visual")
        modes.picked.connect(self._page_picked)
        row.addWidget(modes, 0, Qt.AlignmentFlag.AlignBottom)
        return row

    def _palette(self) -> QFrame:
        frame, layout = panel("Layers")
        groups: dict[str, list[str]] = {}
        for kind, (group, _) in LAYER_KINDS.items():
            groups.setdefault(group, []).append(kind)
        for group, kinds in groups.items():
            layout.addWidget(label(group.upper(), "mlGroup"))
            wrap = QGridLayout()
            wrap.setSpacing(6)
            for index, kind in enumerate(kinds):
                chip = button(kind, "mlLayerChip")
                chip.clicked.connect(lambda _=False, k=kind: self.stack.add(k))
                wrap.addWidget(chip, index // 2, index % 2)
            layout.addLayout(wrap)
            layout.addSpacing(10)
        layout.addWidget(label("Click a layer to add it to the stack, or drag it by its handle to move it.", "mlCaption", wrap=True))
        layout.addStretch(1)
        return frame

    def _architecture(self) -> QFrame:
        frame, layout = panel()
        head = QHBoxLayout()
        head.addWidget(label("ARCHITECTURE", "mlH2"))
        head.addStretch(1)
        self.count_label = label("", "mlMonoMuted")
        head.addWidget(self.count_label)
        layout.addLayout(head)

        self.pages = QStackedWidget()
        self.stack = Stack()
        self.stack.layers_changed.connect(self._refresh)
        self.stack.layer_picked.connect(self._guide)
        visual = QWidget()
        visual_layout = QVBoxLayout(visual)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        visual_layout.addWidget(self.stack)
        add = button("+ Add layer", "mlSoft")
        add.clicked.connect(self._add_menu)
        visual_layout.addWidget(add)
        self.pages.addWidget(visual)
        self.code = QPlainTextEdit()
        self.code.setObjectName("mlCode")
        self.code.setReadOnly(True)
        self.code.setMinimumHeight(240)
        self.pages.addWidget(self.code)
        layout.addWidget(self.pages)

        layout.addWidget(label("TRAINING", "mlGroup"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.loss = QComboBox()
        self.loss.setObjectName("mlCombo")
        self.loss.addItems(LOSSES)
        self.optimizer = QComboBox()
        self.optimizer.setObjectName("mlCombo")
        self.optimizer.addItems(OPTIMIZERS)
        self.lr = field("0.001")
        self.epochs = field("30")
        self.batch = field("256")
        from PySide6.QtWidgets import QCheckBox

        self.early = QCheckBox("Early stopping")
        self.early.setObjectName("mlCheck")
        self.early.setChecked(True)
        grid.addWidget(label("Loss"), 0, 0, 1, 2)
        grid.addWidget(self.loss, 1, 0, 1, 2)
        grid.addWidget(label("Optimizer"), 0, 2)
        grid.addWidget(self.optimizer, 1, 2)
        for column, (caption, widget) in enumerate(
            (("Learning rate", self.lr), ("Epochs", self.epochs), ("Batch size", self.batch))
        ):
            grid.addWidget(label(caption), 2, column)
            grid.addWidget(widget, 3, column)
        grid.addWidget(self.early, 4, 0, 1, 3)
        for widget in (self.lr, self.epochs, self.batch):
            widget.editingFinished.connect(self._training_edited)
        self.loss.currentTextChanged.connect(self._training_edited)
        self.optimizer.currentTextChanged.connect(self._training_edited)
        self.early.toggled.connect(self._training_edited)
        layout.addLayout(grid)
        layout.addStretch(1)
        return frame

    def _right(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        guide, layout = panel("Layer guide")
        self.guide_tabs = QHBoxLayout()
        self.guide_tabs.setSpacing(4)
        layout.addLayout(self.guide_tabs)
        title = QHBoxLayout()
        self.guide_name = label("", "mlLayerName")
        self.guide_name.setStyleSheet("font-size: 14px;")
        self.guide_tag = label("", "mlTag")
        title.addWidget(self.guide_name)
        title.addWidget(self.guide_tag)
        title.addStretch(1)
        layout.addLayout(title)
        self.guide_text: list[QLabel] = []
        for caption in ("What it does", "Main setting", "Watch out"):
            layout.addWidget(label(caption.upper(), "mlGroup"))
            text = label("", "mlBody", wrap=True)
            layout.addWidget(text)
            self.guide_text.append(text)
        layout.addStretch(1)
        column.addWidget(guide, 1)

        validator, layout = panel("Validator")
        self.verdict = QFrame()
        verdict_row = QHBoxLayout(self.verdict)
        verdict_row.setContentsMargins(10, 8, 10, 8)
        self.verdict_text = label("", "mlBody")
        self.verdict_count = label("", "mlCaption")
        verdict_row.addWidget(self.verdict_text)
        verdict_row.addStretch(1)
        verdict_row.addWidget(self.verdict_count)
        layout.addWidget(self.verdict)
        self.issue_box = QVBoxLayout()
        self.issue_box.setSpacing(6)
        layout.addLayout(self.issue_box)
        layout.addWidget(
            label(
                "Errors (✕) disable Save and Use in strategy. It catches, for example, Dense "
                "before LSTM, dropout of 1 or more, or an attention that does not split its channels.",
                "mlCaption", wrap=True,
            )
        )
        column.addWidget(validator, 1)
        return column

    def _bottom(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.summary = label("", "mlCaption")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.summary, 1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.closed)
        self.save_button = button("Save to my models")
        self.save_button.clicked.connect(self.save)
        self.use_button = button("Use in strategy", "mlPrimary")
        self.use_button.clicked.connect(self._use)
        for widget in (cancel, self.save_button, self.use_button):
            row.addWidget(widget)
        return row

    # -- state ------------------------------------------------------------------------

    def spec(self) -> ModelSpec:
        return ModelSpec(
            self.name.text().strip(), "custom", {}, [dict(layer) for layer in self.layers], dict(self.training)
        )

    def load(self, name: str) -> bool:
        """Open a saved custom model for editing."""
        found = next((item for item in store.architectures() if item.name == name), None)
        if found is None:
            return False
        self.name.setText(found.name)
        self.layers = [dict(layer) for layer in found.layers]
        self.training = {**default_training(), **found.training}
        self.stack.set_layers(self.layers)
        self.loss.setCurrentText(str(self.training["loss"]))
        self.optimizer.setCurrentText(str(self.training["optimizer"]))
        self.lr.setText(f"{self.training['lr']:g}")
        self.epochs.setText(f"{self.training['epochs']:g}")
        self.batch.setText(f"{self.training['batch']:g}")
        self.early.setChecked(bool(self.training.get("early_stopping", True)))
        self._refresh()
        return True

    def set_context(self, features: int, samples: int | None = None) -> None:
        self.features = max(1, features)
        self.samples = samples
        self._refresh()

    def _page_picked(self, key: str) -> None:
        self.pages.setCurrentIndex(0 if key == "visual" else 1)

    def _start_from(self, text: str) -> None:
        self.layers = [dict(layer) for layer in ARCHITECTURE_PRESETS.get(text, [])]
        self.stack.selected = -1
        self.stack.set_layers(self.layers)
        self._refresh()

    def _training_edited(self, *_args) -> None:
        self.training["loss"] = self.loss.currentText()
        self.training["optimizer"] = self.optimizer.currentText()
        self.training["early_stopping"] = self.early.isChecked()
        for key, edit in (("lr", self.lr), ("epochs", self.epochs), ("batch", self.batch)):
            try:
                value = float(edit.text().strip().replace(",", "."))
            except ValueError:
                continue
            self.training[key] = value if key == "lr" else int(value)
        self._refresh()

    def _add_menu(self) -> None:
        menu = QMenu(self)
        for kind in LAYER_KINDS:
            menu.addAction(kind, partial(self.stack.add, kind))
        menu.exec(self.cursor().pos())

    # -- the validator, the guide, the summary ---------------------------------------------

    def _refresh(self, *_args) -> None:
        self._issues = check_layers(self.layers, self.training, self.features, self.samples)
        errors = [item for item in self._issues if item.level == "error"]
        warnings = [item for item in self._issues if item.level == "warn"]
        total = 0 if errors else parameter_count(self.layers, self.features)
        self.count_label.setText(f"{total:,} parameters" if not errors else "")
        self.stack.set_ends(
            f"{INPUT_BARS} bars × {self.features} features",
            "Dense 1 · sigmoid → model_p = P(up)",
        )
        self.code.setPlainText(
            layer_stack_code(self.layers, self.features)
            if not errors
            else "# fix the errors in the validator to see the code"
        )
        # The verdict box.
        ok = not errors and bool(self.name.text().strip())
        colour, edge, fill = (UP, "#1f4a33", "#13211a") if not errors else (DOWN_SOFT, "#5a2a2a", "#2c1a1a")
        self.verdict.setStyleSheet(f"QFrame {{ border: 1px solid {edge}; background: {fill}; border-radius: 8px; }}")
        self.verdict_text.setStyleSheet(f"color: {colour}; font-weight: 600; font-size: 13px; border: none;")
        self.verdict_text.setText("✓ Model is valid" if not errors else "✕ Model has errors")
        self.verdict_count.setStyleSheet("border: none;")
        self.verdict_count.setText(f"{len(errors)} error{'s' if len(errors) != 1 else ''} · {len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
        clear(self.issue_box)
        glyphs = {"ok": ("✓", UP), "warn": ("●", AMBER_DOT), "error": ("✕", DOWN_SOFT)}
        for issue in sorted(self._issues, key=lambda item: item.level == "warn"):
            glyph, tint = glyphs[issue.level]
            row = QHBoxLayout()
            row.setSpacing(8)
            mark = QLabel(glyph)
            mark.setStyleSheet(f"color: {tint}; font-weight: 700;")
            mark.setFixedWidth(12)
            mark.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(mark)
            row.addWidget(label(issue.text, "mlBody", wrap=True), 1)
            holder = QWidget()
            holder.setLayout(row)
            self.issue_box.addWidget(holder)
        self.save_button.setEnabled(ok)
        self.use_button.setEnabled(ok)
        if errors:
            self.summary.setText(f'<span style="color:{DOWN_SOFT}">✕</span> {len(errors)} error(s): fix them to save')
        else:
            extra = f" · {len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
            self.summary.setText(
                f'<span style="color:{UP}">✓</span> Valid{extra} · saved models appear in the ML strategy builder'
            )
        self._rebuild_guide_tabs()
        self._guide(self._guide_key if self._guide_key in self._guide_keys() else "Input")

    def _guide_keys(self) -> list[str]:
        kinds = []
        for layer in self.layers:
            if layer["kind"] not in kinds:
                kinds.append(str(layer["kind"]))
        return ["Input", *kinds, "Output"]

    def _rebuild_guide_tabs(self) -> None:
        clear(self.guide_tabs)
        self._tab_buttons = {}
        for key in self._guide_keys():
            tab = button(key, "mlSeg")
            tab.setCheckable(True)
            tab.clicked.connect(lambda _=False, k=key: self._guide(k))
            self.guide_tabs.addWidget(tab)
            self._tab_buttons[key] = tab
        self.guide_tabs.addStretch(1)

    def _guide(self, key: str) -> None:
        if key not in LAYER_GUIDE:
            return
        self._guide_key = key
        for name, tab in getattr(self, "_tab_buttons", {}).items():
            tab.setChecked(name == key)
        tag, what, setting, watch = LAYER_GUIDE[key]
        self.guide_name.setText(key)
        self.guide_tag.setText(tag)
        for widget, text in zip(self.guide_text, (what, setting, watch), strict=True):
            widget.setText(text)

    # -- saving ----------------------------------------------------------------------------------

    def save(self) -> str | None:
        spec = self.spec()
        if not spec.name or any(item.level == "error" for item in self._issues):
            return None
        store.save_architecture(spec)
        self.summary.setText(f'<span style="color:{UP}">✓</span> Saved “{spec.name}” to my models')
        self.saved.emit(spec.name)
        return spec.name

    def _use(self) -> None:
        name = self.save()
        if name:
            self.use_requested.emit(name)

