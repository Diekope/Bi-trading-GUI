"""Custom models: a layer stack from the model builder, built and trained in torch.

torch is imported inside the functions, so the rest of the app (and the model
builder's validator) never pays for it. A network reads the last `bars` bars of
the standardised features and ends in a head sized for the target: one sigmoid
unit for up / down, three softmax units for up / flat / down.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from bi_trading.ml.spec import INPUT_BARS, SEQUENCE_LAYERS, ModelSpec, shape_trace

__all__ = ["MissingBackend", "NetModel", "fit_net", "torch_available"]


class MissingBackend(RuntimeError):
    """torch (or scikit-learn) is not installed: `uv sync --extra ml`."""


def torch_available() -> bool:
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def _torch():
    try:
        import torch
    except ImportError as exc:
        raise MissingBackend(
            "torch is not installed: run `uv sync --extra ml` to train a custom model"
        ) from exc
    return torch


def _build(spec: ModelSpec, features: int, classes: int, bars: int):
    """The `nn.Module` for a stack, in the same order the code view prints."""
    _torch()  # raises MissingBackend, with the install hint, when torch is absent
    import torch
    from torch import nn

    trace = shape_trace(spec.layers, features, bars, classes)

    class _Activation(nn.Module):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.fn = {"ReLU": torch.relu, "Tanh": torch.tanh}.get(name)

        def forward(self, x):
            return self.fn(x) if self.fn is not None else x

    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.steps = nn.ModuleList()
            self.plan: list[tuple] = []
            shape = trace[0][1]
            assert shape is not None
            for position, layer in enumerate(spec.layers):
                kind = layer["kind"]
                after = trace[position + 1][1]
                size = shape.size
                flat = shape.bars * shape.size if shape.is_sequence else size
                activation = str(layer.get("activation", "None"))
                module: nn.Module
                if kind == "Dense":
                    module = nn.Linear(flat, int(layer["units"]))
                    self.plan.append(("dense", shape.is_sequence, activation))
                elif kind == "Dropout":
                    module = nn.Dropout(float(layer["rate"]))
                    self.plan.append(("plain",))
                elif kind == "BatchNorm":
                    module = nn.BatchNorm1d(size)
                    self.plan.append(("norm", shape.is_sequence))
                elif kind == "Activation":
                    module = _Activation(activation)
                    self.plan.append(("plain",))
                elif kind in ("LSTM", "GRU"):
                    module = getattr(nn, kind)(size, int(layer["units"]), batch_first=True)
                    self.plan.append(("recurrent", after is not None and not after.is_sequence))
                elif kind == "Conv1D":
                    module = nn.Conv1d(
                        size, int(layer["filters"]), int(layer["kernel"]), padding="same"
                    )
                    self.plan.append(("conv", activation))
                else:  # Attention
                    module = nn.MultiheadAttention(size, int(layer["heads"]), batch_first=True)
                    self.plan.append(("attention",))
                self.steps.append(module)
                assert after is not None
                shape = after
            self.sequence_out = shape.is_sequence
            self.head = nn.Linear(shape.size, 1 if classes == 2 else classes)
            self.classes = classes

        def forward(self, x):
            for module, plan in zip(self.steps, self.plan, strict=True):
                kind = plan[0]
                if kind == "dense":
                    x = module(x.flatten(1) if plan[1] else x)
                    x = _apply(x, plan[2])
                elif kind == "norm":
                    x = module(x.transpose(1, 2)).transpose(1, 2) if plan[1] else module(x)
                elif kind == "recurrent":
                    x, _ = module(x)
                    if plan[1]:
                        x = x[:, -1]
                elif kind == "conv":
                    x = _apply(module(x.transpose(1, 2)).transpose(1, 2), plan[1])
                elif kind == "attention":
                    x, _ = module(x, x, x)
                else:
                    x = module(x)
            if self.sequence_out:
                x = x.mean(1)
            return self.head(x)  # logits

    def _apply(x, name: str):
        if name == "ReLU":
            return torch.relu(x)
        if name == "Tanh":
            return torch.tanh(x)
        return x

    return Net()


class NetModel:
    """A trained network with the standardisation it was trained under."""

    def __init__(
        self, spec: ModelSpec, features: int, classes: int, bars: int = INPUT_BARS
    ) -> None:
        self.spec = spec
        self.features = features
        self.classes = classes
        self.bars = bars
        self.mean = np.zeros(features)
        self.scale = np.ones(features)
        self.net = _build(spec, features, classes, bars)

    # -- inputs ------------------------------------------------------------

    def _windows(self, matrix: np.ndarray, rows: np.ndarray):
        """A batch of (bars × features) windows ending at each row, standardised."""
        torch = _torch()
        offsets = np.arange(-self.bars + 1, 1)
        block = (matrix[rows[:, None] + offsets] - self.mean) / self.scale
        return torch.from_numpy(np.nan_to_num(block, nan=0.0).astype(np.float32))

    def first_row(self) -> int:
        """The earliest bar whose whole window can exist."""
        return self.bars - 1

    # -- predicting --------------------------------------------------------

    def predict_up(self, matrix: np.ndarray, rows: np.ndarray, chunk: int = 8192) -> np.ndarray:
        """P(up) for each row, in batches so a decade does not sit in memory."""
        torch = _torch()
        self.net.eval()
        out = np.empty(len(rows))
        with torch.no_grad():
            for start in range(0, len(rows), chunk):
                batch = rows[start : start + chunk]
                logits = self.net(self._windows(matrix, batch))
                if self.classes == 2:
                    probability = torch.sigmoid(logits).squeeze(-1)
                else:
                    probability = torch.softmax(logits, dim=-1)[:, -1]
                out[start : start + chunk] = probability.numpy()
        return out

    def predict_proba(self, matrix: np.ndarray, rows: np.ndarray) -> np.ndarray:
        """(rows × classes) probabilities."""
        up = self.predict_up(matrix, rows) if self.classes == 2 else None
        if up is not None:
            return np.column_stack([1.0 - up, up])
        torch = _torch()
        self.net.eval()
        parts = []
        with torch.no_grad():
            for start in range(0, len(rows), 8192):
                batch = rows[start : start + 8192]
                parts.append(torch.softmax(self.net(self._windows(matrix, batch)), dim=-1).numpy())
        return np.concatenate(parts) if parts else np.empty((0, self.classes))

    # -- saving ------------------------------------------------------------

    def state(self) -> dict:
        torch = _torch()
        buffer = {key: value.cpu() for key, value in self.net.state_dict().items()}
        return {
            "spec": self.spec.as_dict(),
            "features": self.features,
            "classes": self.classes,
            "bars": self.bars,
            "mean": self.mean,
            "scale": self.scale,
            "weights": buffer,
            "torch": torch.__version__,
        }

    @classmethod
    def from_state(cls, state: dict) -> NetModel:
        model = cls(
            ModelSpec.from_dict(state["spec"]),
            int(state["features"]),
            int(state["classes"]),
            int(state["bars"]),
        )
        model.mean, model.scale = state["mean"], state["scale"]
        model.net.load_state_dict(state["weights"])
        model.net.eval()
        return model


class Stopped(Exception):
    """Training was cancelled from the screen."""


def fit_net(
    spec: ModelSpec,
    matrix: np.ndarray,
    labels: np.ndarray,
    train_rows: np.ndarray,
    valid_rows: np.ndarray,
    classes: int,
    progress: Callable[[float, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    bars: int = INPUT_BARS,
) -> NetModel:
    """Train a network on `train_rows`, watching `valid_rows` for early stopping.

    `matrix` is the whole span's feature matrix; a row is a sample once all
    `bars` rows before it exist and are finite, which the caller guarantees.
    """
    torch = _torch()
    nn = torch.nn
    training = spec.training
    model = NetModel(spec, matrix.shape[1], classes, bars)

    train_block = matrix[train_rows]
    model.mean = np.nanmean(train_block, axis=0)
    model.scale = np.nanstd(train_block, axis=0)
    model.scale[~(model.scale > 0)] = 1.0

    torch.manual_seed(0)
    net = model.net
    lr = float(training["lr"])
    optimizer = {"SGD": torch.optim.SGD, "AdamW": torch.optim.AdamW}.get(
        str(training["optimizer"]), torch.optim.Adam
    )(net.parameters(), lr=lr)
    use_mse = str(training["loss"]) == "MSE"

    def loss_of(logits, target):
        if classes == 2:
            if use_mse:
                return nn.functional.mse_loss(torch.sigmoid(logits).squeeze(-1), target.float())
            return nn.functional.binary_cross_entropy_with_logits(logits.squeeze(-1), target.float())
        if use_mse:
            hot = nn.functional.one_hot(target.long(), classes).float()
            return nn.functional.mse_loss(torch.softmax(logits, dim=-1), hot)
        return nn.functional.cross_entropy(logits, target.long())

    epochs = int(training["epochs"])
    batch = int(training["batch"])
    rng = np.random.default_rng(0)
    best, best_state, stale = float("inf"), None, 0

    for epoch in range(epochs):
        net.train()
        order = rng.permutation(len(train_rows))
        for start in range(0, len(order), batch):
            if cancelled is not None and cancelled():
                raise Stopped()
            rows = train_rows[order[start : start + batch]]
            optimizer.zero_grad()
            loss = loss_of(net(model._windows(matrix, rows)), torch.from_numpy(labels[rows]))
            loss.backward()
            optimizer.step()
        validation = _validation_loss(model, matrix, labels, valid_rows, loss_of)
        if progress is not None:
            progress((epoch + 1) / epochs, f"epoch {epoch + 1}/{epochs} · valid loss {validation:.4f}")
        if validation < best - 1e-5:
            best, stale = validation, 0
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            stale += 1
            if training.get("early_stopping", True) and stale >= 3:
                break
    if best_state is not None and training.get("early_stopping", True):
        net.load_state_dict(best_state)
    net.eval()
    return model


def _validation_loss(model, matrix, labels, rows, loss_of) -> float:
    if not len(rows):
        return 0.0
    torch = _torch()
    model.net.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for start in range(0, len(rows), 8192):
            batch = rows[start : start + 8192]
            loss = loss_of(model.net(model._windows(matrix, batch)), torch.from_numpy(labels[batch]))
            total += float(loss) * len(batch)
            count += len(batch)
    return total / max(1, count)


__all__ += ["Stopped", "SEQUENCE_LAYERS"]
