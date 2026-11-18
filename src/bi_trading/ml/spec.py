"""What a model is, before any of it is trained: kinds, settings and layers.

Two families live here:

* the **built-in kinds** (gradient boosting, random forest, logistic regression
  and an MLP), each a handful of settings, trained with scikit-learn;
* a **custom model**, a stack of layers the model builder edits and torch runs.

`ModelSpec` is the saved description of either; `check_layers` is the
validator the model builder shows, and `layer_stack_code` the code view. Nothing
here imports scikit-learn or torch, so the screens can open without them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ARCHITECTURE_PRESETS",
    "ACTIVATIONS",
    "KINDS",
    "LAYER_GUIDE",
    "LAYER_KINDS",
    "LOSSES",
    "ModelSpec",
    "OPTIMIZERS",
    "Param",
    "Issue",
    "check_layers",
    "default_layer",
    "default_training",
    "kind_params",
    "layer_stack_code",
    "parameter_count",
    "shape_trace",
]

INPUT_BARS = 30  # how many bars a sequence model reads


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float
    low: float
    high: float
    integer: bool = False

    def clamp(self, value: float) -> float:
        value = min(self.high, max(self.low, float(value)))
        return int(round(value)) if self.integer else value


# kind -> (label, tag, settings). `custom` has no settings of its own here.
KINDS: dict[str, tuple[str, str, tuple[Param, ...]]] = {
    "gbm": (
        "Gradient boosting",
        "Recommended",
        (
            Param("trees", "Trees", 300, 10, 2000, True),
            Param("depth", "Max depth", 4, 1, 16, True),
            Param("lr", "Learning rate", 0.05, 0.001, 1.0),
        ),
    ),
    "forest": (
        "Random forest",
        "Tabular",
        (
            Param("trees", "Trees", 200, 10, 1000, True),
            Param("depth", "Max depth", 8, 1, 32, True),
            Param("leaf", "Min leaf", 50, 1, 5000, True),
        ),
    ),
    "logistic": (
        "Logistic regression",
        "Baseline",
        (
            Param("c", "Regularisation C", 1.0, 0.0001, 1000.0),
            Param("iters", "Max iterations", 200, 10, 5000, True),
        ),
    ),
    "mlp": (
        "Neural net (MLP)",
        "Deep",
        (
            Param("units", "Units", 64, 4, 512, True),
            Param("layers", "Hidden layers", 2, 1, 6, True),
            Param("lr", "Learning rate", 0.001, 0.00001, 0.5),
        ),
    ),
}

BUILTIN_KINDS = tuple(KINDS)


def kind_params(kind: str) -> tuple[Param, ...]:
    return KINDS[kind][2] if kind in KINDS else ()


# -- layers -------------------------------------------------------------------

ACTIVATIONS = ("ReLU", "Tanh", "None")
LOSSES = ("Binary cross-entropy", "MSE")
OPTIMIZERS = ("Adam", "SGD", "AdamW")

# layer -> (group, the settings it has)
LAYER_KINDS: dict[str, tuple[str, tuple[Param, ...]]] = {
    "Dense": ("Core", (Param("units", "units", 32, 1, 4096, True),)),
    "Dropout": ("Core", (Param("rate", "rate", 0.2, 0.0, 1.0),)),
    "BatchNorm": ("Core", ()),
    "Activation": ("Core", ()),
    "LSTM": ("Sequence", (Param("units", "units", 64, 1, 1024, True),)),
    "GRU": ("Sequence", (Param("units", "units", 64, 1, 1024, True),)),
    "Conv1D": (
        "Sequence",
        (
            Param("filters", "filters", 32, 1, 1024, True),
            Param("kernel", "kernel", 3, 1, 15, True),
        ),
    ),
    "Attention": ("Sequence", (Param("heads", "heads", 2, 1, 16, True),)),
}

SEQUENCE_LAYERS = ("LSTM", "GRU", "Conv1D", "Attention")
# Layers that carry a choice of activation next to their numbers.
ACTIVATION_LAYERS = ("Dense", "Activation", "Conv1D")


def default_layer(kind: str) -> dict:
    layer: dict[str, Any] = {"kind": kind}
    for param in LAYER_KINDS[kind][1]:
        layer[param.key] = param.default if not param.integer else int(param.default)
    if kind in ACTIVATION_LAYERS:
        layer["activation"] = "ReLU"
    return layer


def default_training() -> dict:
    return {
        "loss": LOSSES[0],
        "optimizer": OPTIMIZERS[0],
        "lr": 0.001,
        "epochs": 30,
        "batch": 256,
        "early_stopping": True,
    }


# "Start from" in the model builder: name -> its layer stack.
ARCHITECTURE_PRESETS: dict[str, list[dict]] = {
    "Neural net (MLP)": [
        {**default_layer("Dense"), "units": 64},
        {**default_layer("Dropout")},
        {**default_layer("Dense"), "units": 32},
    ],
    "LSTM": [
        {**default_layer("LSTM"), "units": 64},
        {**default_layer("Dropout")},
        {**default_layer("Dense"), "units": 32},
    ],
    "Conv1D": [
        {**default_layer("Conv1D")},
        {**default_layer("Dropout")},
        {**default_layer("Dense"), "units": 32},
    ],
    "Blank": [],
}


@dataclass
class ModelSpec:
    """A model to train: a kind and its settings, or a custom layer stack."""

    name: str = ""
    kind: str = "gbm"
    params: dict = field(default_factory=dict)
    layers: list[dict] = field(default_factory=list)
    training: dict = field(default_factory=default_training)

    def resolved(self) -> dict:
        """The built-in kind's settings, each filled with its default."""
        out = {}
        for param in kind_params(self.kind):
            out[param.key] = param.clamp(self.params.get(param.key, param.default))
        return out

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "params": dict(self.params),
            "layers": [dict(layer) for layer in self.layers],
            "training": dict(self.training),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> ModelSpec:
        training = default_training()
        if isinstance(raw.get("training"), dict):
            training.update(raw["training"])
        return cls(
            name=str(raw.get("name", "")),
            kind=str(raw.get("kind", "gbm")),
            params=dict(raw.get("params") or {}),
            layers=[dict(item) for item in raw.get("layers") or [] if isinstance(item, dict)],
            training=training,
        )

    @property
    def is_custom(self) -> bool:
        return self.kind == "custom"

    @property
    def label(self) -> str:
        if self.is_custom:
            return self.name or "Custom model"
        return KINDS[self.kind][0] if self.kind in KINDS else self.kind


# -- shapes, parameters, validation -------------------------------------------


@dataclass(frozen=True)
class Shape:
    """Either a sequence (bars × channels) or a flat vector."""

    bars: int  # 0 for a vector
    size: int

    @property
    def is_sequence(self) -> bool:
        return self.bars > 0

    def text(self) -> str:
        return f"({self.bars}, {self.size})" if self.is_sequence else f"({self.size})"


@dataclass(frozen=True)
class Issue:
    level: str  # "ok", "warn" or "error"
    text: str


def _layer_name(layer: dict) -> str:
    return str(layer.get("kind", "?"))


def _step(layer: dict, shape: Shape, more_sequence_after: bool) -> tuple[Shape | None, int]:
    """The shape after `layer` and the parameters it holds; None if it cannot run."""
    kind = _layer_name(layer)
    if kind == "Dense":
        features = shape.bars * shape.size if shape.is_sequence else shape.size
        units = int(layer.get("units", 0))
        return Shape(0, units), features * units + units
    if kind in ("Dropout", "Activation"):
        return shape, 0
    if kind == "BatchNorm":
        return shape, 2 * shape.size
    if kind in ("LSTM", "GRU"):
        if not shape.is_sequence:
            return None, 0
        units = int(layer.get("units", 0))
        gates = 4 if kind == "LSTM" else 3
        params = gates * (shape.size * units + units * units + 2 * units)
        out = Shape(shape.bars, units) if more_sequence_after else Shape(0, units)
        return out, params
    if kind == "Conv1D":
        if not shape.is_sequence:
            return None, 0
        filters, kernel = int(layer.get("filters", 0)), int(layer.get("kernel", 0))
        return Shape(shape.bars, filters), kernel * shape.size * filters + filters
    if kind == "Attention":
        if not shape.is_sequence:
            return None, 0
        size = shape.size
        return shape, 4 * size * size + 4 * size
    return None, 0


def shape_trace(
    layers: list[dict], features: int, bars: int = INPUT_BARS, classes: int = 2
) -> list[tuple[str, Shape | None, int]]:
    """(label, shape after it, parameters) for the input, each layer and the output."""
    shape: Shape | None = Shape(bars, features)
    trace: list[tuple[str, Shape | None, int]] = [("Input", shape, 0)]
    for position, layer in enumerate(layers):
        if shape is None:
            trace.append((_layer_name(layer), None, 0))
            continue
        later = any(_layer_name(item) in SEQUENCE_LAYERS for item in layers[position + 1 :])
        shape, params = _step(layer, shape, later)
        trace.append((_layer_name(layer), shape, params))
    if shape is not None:
        if shape.is_sequence:
            shape = Shape(0, shape.size)  # averaged over the bars
        out_units = 1 if classes == 2 else classes
        trace.append(("Output", Shape(0, out_units), shape.size * out_units + out_units))
    else:
        trace.append(("Output", None, 0))
    return trace


def parameter_count(
    layers: list[dict], features: int, bars: int = INPUT_BARS, classes: int = 2
) -> int:
    return sum(params for _, _, params in shape_trace(layers, features, bars, classes))


def check_layers(
    layers: list[dict],
    training: dict,
    features: int,
    samples: int | None = None,
    bars: int = INPUT_BARS,
    classes: int = 2,
) -> list[Issue]:
    """What the validator lists: errors stop saving, warnings do not."""
    issues: list[Issue] = []
    if features < 1:
        issues.append(Issue("error", "No features: pick at least one in the ML builder"))
    seen_dense = False
    broken = False
    shape: Shape = Shape(bars, max(1, features))
    for position, layer in enumerate(layers):
        kind = _layer_name(layer)
        if kind not in LAYER_KINDS:
            issues.append(Issue("error", f"Unknown layer {kind!r}"))
            broken = True
            continue
        for param in LAYER_KINDS[kind][1]:
            value = layer.get(param.key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                issues.append(Issue("error", f"{kind}: {param.label} must be a number"))
                broken = True
            elif kind == "Dropout" and not 0.0 <= value < 1.0:
                issues.append(Issue("error", f"Dropout rate {value} must be below 1"))
                broken = True
            elif value < param.low or value > param.high:
                issues.append(
                    Issue("error", f"{kind}: {param.label} {value:g} is outside {param.low:g} to {param.high:g}")
                )
                broken = True
        if broken:
            continue
        if kind in SEQUENCE_LAYERS and seen_dense:
            issues.append(
                Issue("error", f"Layer order: {kind} must come before any Dense (it needs the bars in order)")
            )
            broken = True
            continue
        if kind == "Dense":
            seen_dense = True
        if kind == "Attention" and shape.is_sequence and shape.size % int(layer["heads"]):
            issues.append(
                Issue("error", f"Attention: {shape.size} channels do not split into {int(layer['heads'])} heads")
            )
            broken = True
            continue
        later = any(_layer_name(item) in SEQUENCE_LAYERS for item in layers[position + 1 :])
        after, _ = _step(layer, shape, later)
        if after is None:
            issues.append(Issue("error", f"{kind} needs sequence input ({bars} bars × features)"))
            broken = True
            continue
        if kind == "Dense" and shape.is_sequence:
            issues.append(
                Issue("warn", f"Dense flattens the {bars} bars × {shape.size} features into one vector")
            )
        shape = after

    lr = training.get("lr")
    if not isinstance(lr, (int, float)) or not 0 < lr <= 1:
        issues.append(Issue("error", f"Learning rate {lr} must be above 0 and at most 1"))
    if int(training.get("epochs", 0) or 0) < 1:
        issues.append(Issue("error", "Epochs must be at least 1"))
    if int(training.get("batch", 0) or 0) < 1:
        issues.append(Issue("error", "Batch size must be at least 1"))
    if broken or any(item.level == "error" for item in issues):
        return issues

    trace = shape_trace(layers, features, bars, classes)
    steps = [trace[0][1].text()]  # type: ignore[union-attr]
    for layer in layers:
        steps.append(f"{_layer_name(layer)} {_main_number(layer)}".strip())
    steps.append("1" if classes == 2 else str(classes))
    issues.insert(0, Issue("ok", "Shapes line up: " + " → ".join(steps)))
    issues.insert(
        1,
        Issue(
            "ok",
            "Output: 1 unit + sigmoid matches “up / down”"
            if classes == 2
            else f"Output: {classes} units + softmax matches “up / flat / down”",
        ),
    )
    if layers:
        issues.append(Issue("ok", "Layer order: sequence layers come before Dense"))
    issues.append(
        Issue(
            "ok",
            f"Values in range: learning rate {lr:g}"
            + "".join(
                f", dropout {layer['rate']:g}" for layer in layers if layer.get("kind") == "Dropout"
            ),
        )
    )
    if samples:
        batch = int(training["batch"])
        issues.append(Issue("ok", f"Data: {_short(samples)} training samples, batch size {batch}"))
    total = parameter_count(layers, features, bars, classes)
    if total > 1000 * max(1, features):
        issues.append(
            Issue("warn", f"Capacity: {total:,} parameters for {features} features. Fewer units may overfit less.")
        )
    return issues


def _main_number(layer: dict) -> str:
    for key in ("units", "filters", "heads", "rate"):
        if key in layer:
            value = layer[key]
            return f"{value:g}" if isinstance(value, float) else str(value)
    return ""


def _short(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}k"
    return str(count)


# -- the layer guide (right-hand panel of the model builder) -------------------

# layer -> (group tag, what it does, main setting, watch out)
LAYER_GUIDE: dict[str, tuple[str, str, str, str]] = {
    "Input": (
        "Data",
        "Hands the model the last 30 bars, each described by the features you picked.",
        "The number of features comes from the ML builder, the 30 bars are fixed.",
        "Features are standardised on the training period only, so nothing leaks from the future.",
    ),
    "LSTM": (
        "Sequence",
        "Reads the last 30 bars in order and keeps a short-term memory, so it can pick up trends and reversals.",
        "Units is the size of that memory. More units give more power but more overfitting. 32 to 64 is a good start.",
        "Needs sequence input (30 bars × features) and must come before any Dense layer.",
    ),
    "GRU": (
        "Sequence",
        "Like an LSTM with fewer moving parts: it reads the bars in order and keeps a memory.",
        "Units is the size of the memory. 32 to 64 is a good start.",
        "Needs sequence input and must come before any Dense layer.",
    ),
    "Conv1D": (
        "Sequence",
        "Slides small filters along the bars to spot short patterns, such as a three-bar run.",
        "Filters is how many patterns it looks for, kernel how many bars each spans.",
        "Needs sequence input and must come before any Dense layer.",
    ),
    "Attention": (
        "Sequence",
        "Lets every bar weigh every other bar, to find which earlier bars matter now.",
        "Heads splits the channels into groups that each attend on their own.",
        "The number of channels must divide by the heads. Needs sequence input.",
    ),
    "Dense": (
        "Core",
        "Mixes everything it receives into a new, smaller set of numbers.",
        "Units is how many numbers it produces. 16 to 64 is a good start.",
        "After a sequence it flattens the bars into one long vector, which is many parameters.",
    ),
    "Dropout": (
        "Core",
        "Switches off a random share of its inputs while training, so the model cannot lean on any one.",
        "Rate is the share switched off. 0.1 to 0.3 is typical.",
        "A rate of 1 or more is invalid. It does nothing when predicting.",
    ),
    "BatchNorm": (
        "Core",
        "Rescales what passes through each batch, which often makes training steadier.",
        "No settings.",
        "With very small batches its estimates get noisy.",
    ),
    "Activation": (
        "Core",
        "Applies a curve (ReLU or Tanh) so the layers can learn more than a straight line.",
        "Pick ReLU unless you have a reason for Tanh.",
        "Without one between two Dense layers, they collapse into a single layer.",
    ),
    "Output": (
        "Output",
        "One unit with a sigmoid gives the probability the market goes up: model_p = P(up).",
        "Sized for you from the target: 1 unit for up / down, 3 for up / flat / down.",
        "It is added automatically; you do not add it.",
    ),
}


# -- the code view ------------------------------------------------------------


def layer_stack_code(
    layers: list[dict], features: int, bars: int = INPUT_BARS, classes: int = 2
) -> str:
    """The torch module the stack stands for, as text to read."""
    trace = shape_trace(layers, features, bars, classes)
    init = [f"        # input: ({bars} bars, {features} features)"]
    forward = ["        # x: (batch, bars, features)"]
    shape = trace[0][1]
    for position, layer in enumerate(layers):
        kind = _layer_name(layer)
        after = trace[position + 1][1]
        if shape is None:
            init.append(f"        # {kind}: the shapes before it do not line up")
            continue
        name, size = f"layer{position + 1}", shape.size
        flat = shape.bars * shape.size if shape.is_sequence else shape.size
        act = {"ReLU": "nn.ReLU()", "Tanh": "nn.Tanh()"}.get(str(layer.get("activation", "")))
        if kind == "Dense":
            init.append(f"        self.{name} = nn.Linear({flat}, {layer.get('units')})")
            if shape.is_sequence:
                forward.append("        x = x.flatten(1)")
            forward.append(f"        x = self.{name}(x)")
            if act:
                forward.append(f"        x = {act.replace('nn.', 'torch.').lower().replace('()', '')}(x)")
        elif kind == "Dropout":
            init.append(f"        self.{name} = nn.Dropout({layer.get('rate')})")
            forward.append(f"        x = self.{name}(x)")
        elif kind == "BatchNorm":
            init.append(f"        self.{name} = nn.BatchNorm1d({size})")
            forward.append(
                f"        x = self.{name}(x.transpose(1, 2)).transpose(1, 2)"
                if shape.is_sequence else f"        x = self.{name}(x)"
            )
        elif kind == "Activation":
            fn = {"ReLU": "torch.relu", "Tanh": "torch.tanh"}.get(str(layer.get("activation", "")))
            forward.append(f"        x = {fn}(x)" if fn else "        # no activation")
        elif kind in ("LSTM", "GRU"):
            init.append(
                f"        self.{name} = nn.{kind}({size}, {layer.get('units')}, batch_first=True)"
            )
            forward.append(f"        x, _ = self.{name}(x)")
            if after is not None and not after.is_sequence:
                forward.append("        x = x[:, -1]  # the last step's memory")
        elif kind == "Conv1D":
            init.append(
                f"        self.{name} = nn.Conv1d({size}, {layer.get('filters')}, "
                f"{layer.get('kernel')}, padding='same')"
            )
            forward.append(f"        x = self.{name}(x.transpose(1, 2)).transpose(1, 2)")
            if act:
                forward.append(f"        x = {act.replace('nn.', 'torch.').lower().replace('()', '')}(x)")
        elif kind == "Attention":
            init.append(
                f"        self.{name} = nn.MultiheadAttention({size}, {layer.get('heads')}, batch_first=True)"
            )
            forward.append(f"        x, _ = self.{name}(x, x, x)")
        shape = after
    tail = trace[-1][1]
    if shape is not None and tail is not None:
        init.append(f"        self.head = nn.Linear({shape.size if not shape.is_sequence else shape.size}, {tail.size})")
        if shape.is_sequence:
            forward.append("        x = x.mean(1)  # average over the bars")
        forward.append("        x = self.head(x)")
        forward.append(
            "        return torch.sigmoid(x).squeeze(-1)  # model_p = P(up)"
            if classes == 2
            else "        return torch.softmax(x, dim=-1)  # P(down), P(flat), P(up)"
        )
    return "\n".join(
        ["import torch", "from torch import nn", "", "", "class Net(nn.Module):",
         "    def __init__(self):", "        super().__init__()", *init, "",
         "    def forward(self, x):", *forward, ""]
    )
