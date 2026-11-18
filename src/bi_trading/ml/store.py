"""Saved models on disk: custom architectures and trained models.

    ~/.config/bi-trading/architectures.json     layer stacks from the model builder
    ~/.config/bi-trading/models/<slug>.json     a trained model's settings and figures
    ~/.config/bi-trading/models/<slug>.bin      its weights (joblib)

`BI_TRADING_ARCHITECTURES` and `BI_TRADING_MODELS` move them. Saving under a
name that exists replaces it. The figures are readable JSON; only the weights
are binary, and they are loaded only from this folder, which the app writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np

from bi_trading.ml.spec import ModelSpec
from bi_trading.ml.train import MLError, RuleStats, TrainConfig, TrainedModel

__all__ = [
    "architectures",
    "architectures_path",
    "load_model",
    "model_names",
    "model_summary",
    "models_dir",
    "remove_architecture",
    "remove_model",
    "save_architecture",
    "save_model",
    "scored",
    "slug",
]


def architectures_path() -> Path:
    return Path(
        os.environ.get("BI_TRADING_ARCHITECTURES", "~/.config/bi-trading/architectures.json")
    ).expanduser()


def models_dir() -> Path:
    return Path(os.environ.get("BI_TRADING_MODELS", "~/.config/bi-trading/models")).expanduser()


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return text or "model"


# -- custom architectures ---------------------------------------------------------


def architectures() -> list[ModelSpec]:
    """Every saved custom model, oldest first. A missing or broken file is empty."""
    try:
        raw = json.loads(architectures_path().read_text())
    except (OSError, ValueError):
        return []
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and str(item.get("name", "")).strip():
            spec = ModelSpec.from_dict(item)
            spec.kind = "custom"
            out.append(spec)
    return out


def save_architecture(spec: ModelSpec) -> list[ModelSpec]:
    name = spec.name.strip()
    if not name:
        raise ValueError("a model needs a name")
    spec.kind = "custom"
    kept = [item for item in architectures() if item.name != name]
    kept.append(ModelSpec(name, "custom", {}, [dict(x) for x in spec.layers], dict(spec.training)))
    target = architectures_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([item.as_dict() for item in kept], indent=2) + "\n")
    return kept


def remove_architecture(name: str) -> list[ModelSpec]:
    kept = [item for item in architectures() if item.name != name]
    target = architectures_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([item.as_dict() for item in kept], indent=2) + "\n")
    return kept


# -- trained models -----------------------------------------------------------------


def _paths(name: str) -> tuple[Path, Path, Path]:
    # The exact name goes into the file name (as a short digest) so two names that
    # read alike, "A b" and "a-b", never share a file.
    digest = hashlib.sha256(name.strip().encode("utf-8")).hexdigest()[:8]
    base = models_dir() / f"{slug(name)}-{digest}"
    return base.with_suffix(".json"), base.with_suffix(".bin"), base.with_suffix(".wf.npz")


def model_names() -> list[str]:
    folder = models_dir()
    if not folder.is_dir():
        return []
    names = []
    for path in sorted(folder.glob("*.json")):
        try:
            names.append(str(json.loads(path.read_text()).get("name") or path.stem))
        except (OSError, ValueError):
            continue
    return names


def save_model(model: TrainedModel, name: str | None = None) -> str:
    """Write a trained model; returns the name it was saved under."""
    import joblib

    name = (name or model.name).strip()
    if not name:
        raise ValueError("a model needs a name")
    if model.predictor is None:
        raise MLError("nothing trained to save")
    info, weights, forward = _paths(name)
    info.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "name": name,
        "config": model.config.as_dict(),
        "metrics": model.metrics,
        "samples": model.samples,
        "importance": [list(item) for item in model.importance],
        "balance": model.balance,
        "stats": {
            "signals": model.stats.signals,
            "hit_rate": model.stats.hit_rate,
            "strategy": model.stats.strategy,
            "hold": model.stats.hold,
            "strategy_return": model.stats.strategy_return,
            "hold_return": model.stats.hold_return,
        },
        "test_start": model.test_start,
        "test_end": model.test_end,
        "span_start": model.span_start,
        "seconds": model.seconds,
        "trained_at": model.trained_at,
        "tuned": model.tuned,
    }
    predictor = model.predictor
    if hasattr(predictor, "state"):
        payload = {"net": predictor.state()}
    else:
        payload = {"sklearn": predictor}
    joblib.dump(payload, weights)
    body["weights_sha256"] = _digest(weights)
    if model.wf_stamps is not None and model.wf_p is not None:
        np.savez_compressed(forward, stamps=model.wf_stamps, p=model.wf_p)
    elif forward.exists():
        forward.unlink()
    info.write_text(json.dumps(body, indent=2) + "\n")
    return name


def _digest(path: Path) -> str:
    """SHA-256 of a weights file, checked before it is unpickled."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


_CACHE: dict[str, tuple[tuple[float, float], TrainedModel]] = {}


def load_model(name: str) -> TrainedModel:
    """A saved model with its weights, ready to score. Raises `MLError`."""
    info, weights, forward = _paths(name)
    try:
        signature = (info.stat().st_mtime, weights.stat().st_mtime)
    except OSError as exc:
        raise MLError(f"no saved model called {name!r}") from exc
    cached = _CACHE.get(name)
    if cached is not None and cached[0] == signature:
        return cached[1]
    try:
        body = json.loads(info.read_text())
    except (OSError, ValueError) as exc:
        raise MLError(f"the model {name!r} could not be read") from exc
    expected = body.get("weights_sha256")
    if expected and expected != _digest(weights):
        raise MLError(
            f"the weights of {name!r} do not match what was saved: the file was changed"
        )
    try:
        import joblib

        payload = joblib.load(weights)
    except ImportError as exc:
        raise MLError("joblib is not installed: run `uv sync --extra ml`") from exc
    except Exception as exc:  # a damaged or foreign file
        raise MLError(f"the weights of {name!r} could not be read: {exc}") from exc
    if "net" in payload:
        from bi_trading.ml.nets import NetModel

        predictor = NetModel.from_state(payload["net"])
    else:
        predictor = payload["sklearn"]
    stats = body.get("stats") or {}
    model = TrainedModel(
        name=str(body.get("name", name)),
        config=TrainConfig.from_dict(body.get("config") or {}),
        predictor=predictor,
        metrics=body.get("metrics") or {},
        samples=body.get("samples") or {},
        importance=[(str(a), float(b)) for a, b in body.get("importance") or []],
        balance=body.get("balance") or {},
        stats=RuleStats(
            signals=int(stats.get("signals") or 0),
            hit_rate=stats.get("hit_rate"),
            strategy=list(stats.get("strategy") or []),
            hold=list(stats.get("hold") or []),
            strategy_return=float(stats.get("strategy_return") or 0.0),
            hold_return=float(stats.get("hold_return") or 0.0),
        ),
        test_start=int(body.get("test_start") or 0),
        test_end=int(body.get("test_end") or 0),
        span_start=int(body.get("span_start") or 0),
        seconds=float(body.get("seconds") or 0.0),
        trained_at=float(body.get("trained_at") or 0.0),
        tuned=body.get("tuned") or {},
    )
    if forward.exists():
        data = np.load(forward)
        model.wf_stamps, model.wf_p = data["stamps"], data["p"]
    _CACHE[name] = (signature, model)
    return model


def model_summary(name: str) -> dict | None:
    """A saved model's figures without its weights: cheap enough for a list row.

    Keys: `test_return` (the rule's return over the test part, in percent),
    `trained_at`, `test_start`, `timeframe`. None when there is no such model.
    """
    info, _, _ = _paths(name)
    try:
        body = json.loads(info.read_text())
    except (OSError, ValueError):
        return None
    return {
        "test_return": float((body.get("stats") or {}).get("strategy_return") or 0.0),
        "trained_at": float(body.get("trained_at") or 0.0),
        "test_start": int(body.get("test_start") or 0),
        "timeframe": str((body.get("config") or {}).get("timeframe", "1m")),
    }


def remove_model(name: str) -> None:
    for path in _paths(name):
        path.unlink(missing_ok=True)
    _CACHE.pop(name, None)
    for key in [k for k in _SCORES if k[0] == name]:
        del _SCORES[key]


# -- scored spans, kept so a second run does not score the span again ------------------

_SCORES: dict[tuple, Any] = {}


def scored(name: str, columns: dict, stamps, resolution: str):
    """The model's P(up) over a span, from the cache when this span was scored.

    The key is the model's files (so retraining it empties the entry) and the
    span's length, ends and resolution.
    """
    from bi_trading.ml.train import predict_series

    trained = load_model(name)
    info, weights, _ = _paths(name)
    key = (
        name, info.stat().st_mtime_ns, weights.stat().st_mtime_ns, resolution,
        len(stamps), int(stamps[0]) if len(stamps) else 0,
        int(stamps[-1]) if len(stamps) else 0,
    )
    if key not in _SCORES:
        if len(_SCORES) >= 6:
            _SCORES.pop(next(iter(_SCORES)))
        _SCORES[key] = predict_series(trained, columns, stamps, resolution)
    return _SCORES[key]
