"""Chart feel and backtest defaults, editable without touching the source.

Lookup order, lowest priority first:

    built-in defaults
    ~/.config/lalala/settings.json   (written on first launch)
    LALALA_* environment variables

The file exists so the numbers that make the chart move — and the values a
backtest starts from — can be tuned by hand. Restart the app after a change;
nothing reloads at runtime.

Every value is clamped to a sane range, and a broken file never stops the app:
the loader falls back to the defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_PATH = "~/.config/lalala/settings.json"

# Position sizing modes; the tile reads the value as whatever this names.
SIZING_MODES = ("balance", "fixed", "risk")

# A file in this shape is written when none exists. The underscore keys are
# ignored by the loader; they are there for the human who opens the file.
TEMPLATE = {
    "_comment": (
        "lalala chart feel. Edit, then restart. "
        "edge_px_per_s = width * focus_share / (focus_ms / 1000)"
    ),
    "view_ms": 900_000,
    "focus_ms": 130_000,
    "focus_share": 0.85,
    "lag_ms": 1_500,
    "sample_every_ms": 1_000,
    "smooth": 0.30,
    "ease_tip": 0.18,
    "ease_range": 0.08,
    "frame_ms": 33,
    "backtest": {
        "_comment": "Where a new backtest starts. sizing = balance | fixed | risk; cash is in dollars; fee is percent per side",
        "initial_capital": 10_000.0,
        "tp": 2.0,
        "sl": 1.0,
        "position": 10.0,
        "cash": 2_000.0,
        "fee": 0.06,
        "dynamic_tp": False,
        "dyn_tp_reverse": 0.5,
        "sizing": "balance",
    },
}


def settings_path() -> Path:
    """Where the tunable file lives, honouring LALALA_SETTINGS."""
    return Path(os.environ.get("LALALA_SETTINGS", DEFAULT_PATH)).expanduser()


@dataclass(frozen=True)
class BacktestDefaults:
    """The values a fresh backtest form starts from."""

    initial_capital: float = 10_000.0  # book size, in dollars
    tp: float = 2.0                    # take profit, percent
    sl: float = 1.0                    # stop loss, percent
    position: float = 10.0             # read as `sizing` says
    cash: float = 2_000.0              # most that may sit in cash, dollars
    fee: float = 0.06                  # fee per side, percent
    dynamic_tp: bool = False           # let the take profit trail
    dyn_tp_reverse: float = 0.5        # pull-back that closes a trailing TP, %
    sizing: str = "balance"            # balance % | fixed $ | risk %

    @classmethod
    def load(
        cls,
        raw: object,
        environment: dict[str, str] | None = None,
    ) -> "BacktestDefaults":
        environment = os.environ if environment is None else environment
        values = dict(raw) if isinstance(raw, dict) else {}

        for field in fields(cls):
            override = environment.get(f"LALALA_BACKTEST_{field.name.upper()}")
            if override is not None:
                values[field.name] = override

        defaults = cls()
        return cls(
            initial_capital=_clamp(
                _number(values.get("initial_capital"), defaults.initial_capital),
                0.0,
                1e12,
            ),
            tp=_clamp(_number(values.get("tp"), defaults.tp), 0.0, 10_000.0),
            sl=_clamp(_number(values.get("sl"), defaults.sl), 0.0, 100.0),
            position=_clamp(
                _number(values.get("position"), defaults.position), 0.0, 1e9
            ),
            cash=_clamp(_number(values.get("cash"), defaults.cash), 0.0, 1e12),
            fee=_clamp(_number(values.get("fee"), defaults.fee), 0.0, 100.0),
            dynamic_tp=_flag(values.get("dynamic_tp"), defaults.dynamic_tp),
            dyn_tp_reverse=_clamp(
                _number(values.get("dyn_tp_reverse"), defaults.dyn_tp_reverse),
                0.0,
                100.0,
            ),
            sizing=_choice(values.get("sizing"), defaults.sizing),
        )


@dataclass(frozen=True)
class Settings:
    view_ms: int = 900_000           # total span on screen
    focus_ms: int = 130_000          # length of the fast live slice
    focus_share: float = 0.85        # fraction of the plot width it occupies
    lag_ms: int = 1_500             # how far behind live the tip sits
    sample_every_ms: int = 1_000    # resolution of the stored line
    smooth: float = 0.30            # per-sample damping; lower is rounder
    ease_tip: float = 0.18          # per-frame glide toward the target
    ease_range: float = 0.08        # per-frame glide of the y-scale
    frame_ms: int = 33              # repaint interval (~30 fps)
    backtest: BacktestDefaults = BacktestDefaults()

    def edge_px_per_s(self, width_px: float) -> float:
        """How fast the live edge travels, for a given plot width."""
        return width_px * self.focus_share / (self.focus_ms / 1000.0)

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        environ: dict[str, str] | None = None,
    ) -> "Settings":
        target = settings_path() if path is None else Path(path)
        environment = os.environ if environ is None else environ

        values: dict[str, object] = {}
        try:
            loaded = json.loads(target.read_text())
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            values.update(loaded)

        for field in fields(cls):
            if field.name == "backtest":
                continue
            override = environment.get(f"LALALA_{field.name.upper()}")
            if override is not None:
                values[field.name] = override

        defaults = cls()
        numbers: dict[str, float] = {}
        for field in fields(cls):
            if field.name == "backtest":
                continue
            numbers[field.name] = _number(
                values.get(field.name), getattr(defaults, field.name)
            )

        # Dependent bounds, applied after the individual clamps.
        numbers["view_ms"] = _clamp(numbers["view_ms"], 60_000, 3_600_000)
        numbers["sample_every_ms"] = _clamp(
            numbers["sample_every_ms"], 100, 10_000
        )
        numbers["focus_ms"] = _clamp(
            numbers["focus_ms"], 10_000, numbers["view_ms"] * 0.9
        )
        # The tip needs a keyframe ahead of the cursor; a lag at or below the
        # sampling interval makes the painted segment jump backwards.
        numbers["lag_ms"] = _clamp(
            numbers["lag_ms"],
            numbers["sample_every_ms"] * 1.2,
            10_000,
        )
        numbers["focus_share"] = _clamp(numbers["focus_share"], 0.05, 0.9)
        numbers["smooth"] = _clamp(numbers["smooth"], 0.01, 0.95)
        numbers["ease_tip"] = _clamp(numbers["ease_tip"], 0.01, 1.0)
        numbers["ease_range"] = _clamp(numbers["ease_range"], 0.01, 1.0)
        numbers["frame_ms"] = _clamp(numbers["frame_ms"], 16, 250)

        return cls(
            view_ms=int(numbers["view_ms"]),
            focus_ms=int(numbers["focus_ms"]),
            focus_share=numbers["focus_share"],
            lag_ms=int(numbers["lag_ms"]),
            sample_every_ms=int(numbers["sample_every_ms"]),
            smooth=numbers["smooth"],
            ease_tip=numbers["ease_tip"],
            ease_range=numbers["ease_range"],
            frame_ms=int(numbers["frame_ms"]),
            backtest=BacktestDefaults.load(values.get("backtest"), environment),
        )


def ensure_file(path: Path | str | None = None) -> Path:
    """Write the default file once, so there is something to edit."""
    target = settings_path() if path is None else Path(path)
    if target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(TEMPLATE, indent=2) + "\n")
    except OSError:
        pass  # a read-only home is not a reason to refuse to start
    return target


def _number(value: object, fallback: float) -> float:
    if isinstance(value, bool):
        return float(fallback)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(fallback)


def _flag(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def _choice(value: object, fallback: str) -> str:
    return value if value in SIZING_MODES else fallback


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
