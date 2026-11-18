"""The built-in models, trained with scikit-learn, behind one small interface.

Every trained model, built-in or a torch network, answers the same two calls:

    predict_proba(matrix, rows) -> (rows × classes) probabilities
    predict_up(matrix, rows)    -> P(up) for each row

`matrix` is a whole span's feature matrix and `rows` the bars to score, so the
caller never copies the span. A bar whose features are not all known (the
warm-up at the start) must not be passed in; `finite_rows` finds the ones that
can be.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from bi_trading.ml.nets import MissingBackend
from bi_trading.ml.spec import ModelSpec

__all__ = [
    "SklearnModel",
    "auto_tune_grid",
    "finite_rows",
    "fit_sklearn",
]


def _sklearn():
    try:
        import sklearn  # noqa: F401
    except ImportError as exc:
        raise MissingBackend(
            "scikit-learn is not installed: run `uv sync --extra ml`"
        ) from exc


def finite_rows(matrix: np.ndarray, first: int = 0) -> np.ndarray:
    """Indices of the bars (from `first` on) whose every feature is a number."""
    ok = np.isfinite(matrix).all(axis=1)
    ok[:first] = False
    return np.nonzero(ok)[0]


class SklearnModel:
    """A fitted scikit-learn estimator, with the class count it was fitted for."""

    def __init__(self, spec: ModelSpec, estimator: Any, classes: int) -> None:
        self.spec = spec
        self.estimator = estimator
        self.classes = classes

    def predict_proba(self, matrix: np.ndarray, rows: np.ndarray) -> np.ndarray:
        if not len(rows):
            return np.empty((0, self.classes))
        raw = self.estimator.predict_proba(matrix[rows])
        seen = list(self.estimator.classes_)
        if len(seen) == self.classes:
            return raw
        # A class that never occurred in training gets zero, so the columns still
        # line up with down / (flat) / up.
        full = np.zeros((len(rows), self.classes))
        for column, label in enumerate(seen):
            full[:, int(label)] = raw[:, column]
        return full

    def predict_up(self, matrix: np.ndarray, rows: np.ndarray) -> np.ndarray:
        return self.predict_proba(matrix, rows)[:, -1]


def _estimator(spec: ModelSpec, classes: int):
    _sklearn()
    settings = spec.resolved()
    if spec.kind == "gbm":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            max_iter=settings["trees"],
            max_depth=settings["depth"],
            learning_rate=settings["lr"],
            early_stopping=False,
            random_state=0,
        )
    if spec.kind == "forest":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(
            n_estimators=settings["trees"],
            max_depth=settings["depth"],
            min_samples_leaf=settings["leaf"],
            n_jobs=-1,
            random_state=0,
        )
    if spec.kind == "logistic":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        return make_pipeline(
            StandardScaler(),
            LogisticRegression(C=settings["c"], max_iter=settings["iters"]),
        )
    if spec.kind == "mlp":
        from sklearn.neural_network import MLPClassifier
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        return make_pipeline(
            StandardScaler(),
            MLPClassifier(
                hidden_layer_sizes=(settings["units"],) * settings["layers"],
                learning_rate_init=settings["lr"],
                early_stopping=True,
                max_iter=200,
                random_state=0,
            ),
        )
    raise KeyError(f"no built-in model called {spec.kind!r}")


def fit_sklearn(
    spec: ModelSpec, features: np.ndarray, labels: np.ndarray, classes: int
) -> SklearnModel:
    """Fit a built-in model on already-selected rows."""
    estimator = _estimator(spec, classes)
    estimator.fit(features, labels)
    return SklearnModel(spec, estimator, classes)


def auto_tune_grid(kind: str) -> list[dict]:
    """A few settings worth trying for a kind: the search Auto-tune runs."""
    if kind == "gbm":
        return [
            {"trees": trees, "depth": depth, "lr": lr}
            for trees, depth, lr in (
                (150, 3, 0.05), (300, 4, 0.05), (300, 3, 0.03),
                (200, 6, 0.05), (500, 3, 0.02), (150, 2, 0.1),
            )
        ]
    if kind == "forest":
        return [
            {"trees": 200, "depth": depth, "leaf": leaf}
            for depth, leaf in ((4, 100), (8, 50), (12, 200), (6, 500))
        ]
    if kind == "logistic":
        return [{"c": c, "iters": 300} for c in (0.01, 0.1, 1.0, 10.0)]
    if kind == "mlp":
        return [
            {"units": units, "layers": layers, "lr": lr}
            for units, layers, lr in ((32, 1, 0.001), (64, 2, 0.001), (32, 2, 0.003), (128, 2, 0.0005))
        ]
    return []

