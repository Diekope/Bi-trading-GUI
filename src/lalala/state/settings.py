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
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = "~/.config/lalala/settings.json"

# Position sizing modes; the tile reads the value as whatever this names.
SIZING_MODES = ("balance", "fixed", "risk")

# Resolutions the backtest compactor can produce (1m bars on disk).
TIMEFRAMES: tuple[str, ...] = ("1m", "3m", "5m", "15m", "30m", "1h")

# History starts here: the venues' pre-2017 coverage is thin.
FIRST_YEAR = 2017

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
        "hold": 7,
        "sizing": "balance",
        "timeframe": "1m",
        "start_year": FIRST_YEAR,
        "end_year": datetime.now(tz=timezone.utc).year,
    },
    "accounts": {
        "_comment": "Public addresses only; private keys live in the system keychain (see Settings).",
        "hyperliquid": {"address": "", "testnet": False},
        "polymarket": {"address": "", "signature_type": 0},
    },
    "trading": {
        "_comment": "The trade form's starting values; margin = isolated | cross",
        "leverage": 5,
        "margin_mode": "isolated",
        "size": 3_780.0,
        "polymarket_stake": 20.0,
        "max_stake": 100.0,
        "daily_loss_limit": 200.0,
        "confirm_orders": True,
        "auto_bet": False,
        "live_orders": False,
    },
    "general": {
        "_comment": "start_page = home | live | builder | backtest; an empty data_folder uses data/candles in the repo",
        "start_page": "home",
        "data_folder": "",
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
    hold: int = 7                      # candles a trade may run; 0 = no limit
    sizing: str = "balance"            # balance % | fixed $ | risk %
    timeframe: str = "1m"              # resolution the 1m bars compact to
    start_year: int = FIRST_YEAR       # first year of history
    end_year: int = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).year
    )

    @classmethod
    def load(
        cls,
        raw: object,
        environment: dict[str, str] | None = None,
    ) -> "BacktestDefaults":
        environment = os.environ if environment is None else environment
        values = dict(raw) if isinstance(raw, dict) else {}

        for spec in fields(cls):
            override = environment.get(f"LALALA_BACKTEST_{spec.name.upper()}")
            if override is not None:
                values[spec.name] = override

        defaults = cls()
        latest = datetime.now(tz=timezone.utc).year
        start = int(
            _clamp(
                _number(values.get("start_year"), defaults.start_year),
                FIRST_YEAR,
                latest,
            )
        )
        end = int(
            _clamp(
                _number(values.get("end_year"), defaults.end_year),
                FIRST_YEAR,
                latest,
            )
        )
        if start > end:
            start, end = end, start

        timeframe = values.get("timeframe")
        if timeframe not in TIMEFRAMES:
            timeframe = defaults.timeframe

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
            hold=int(
                _clamp(_number(values.get("hold"), defaults.hold), 0, 1_000_000)
            ),
            sizing=_choice(values.get("sizing"), defaults.sizing),
            timeframe=timeframe,
            start_year=start,
            end_year=end,
        )


@dataclass(frozen=True)
class TradingDefaults:
    """What the trade form opens with. Nothing sends orders yet."""

    leverage: int = 5
    margin_mode: str = "isolated"      # isolated | cross
    size: float = 3_780.0              # default order size, USD
    polymarket_stake: float = 20.0     # dollars per bet
    max_stake: float = 100.0           # most per bet
    daily_loss_limit: float = 200.0    # stop after this much is lost
    confirm_orders: bool = True
    auto_bet: bool = False
    live_orders: bool = False          # off: orders are paper only

    @classmethod
    def load(
        cls,
        raw: object,
        environment: dict[str, str] | None = None,
    ) -> "TradingDefaults":
        environment = os.environ if environment is None else environment
        values = dict(raw) if isinstance(raw, dict) else {}

        for spec in fields(cls):
            override = environment.get(f"LALALA_TRADING_{spec.name.upper()}")
            if override is not None:
                values[spec.name] = override

        defaults = cls()
        return cls(
            leverage=int(
                _clamp(_number(values.get("leverage"), defaults.leverage), 1, 20)
            ),
            margin_mode=_margin(values.get("margin_mode"), defaults.margin_mode),
            size=_clamp(_number(values.get("size"), defaults.size), 0.0, 1e12),
            polymarket_stake=_clamp(
                _number(values.get("polymarket_stake"), defaults.polymarket_stake),
                0.0,
                1e12,
            ),
            max_stake=_clamp(
                _number(values.get("max_stake"), defaults.max_stake), 0.0, 1e12
            ),
            daily_loss_limit=_clamp(
                _number(values.get("daily_loss_limit"), defaults.daily_loss_limit),
                0.0,
                1e12,
            ),
            confirm_orders=_flag(
                values.get("confirm_orders"), defaults.confirm_orders
            ),
            auto_bet=_flag(values.get("auto_bet"), defaults.auto_bet),
            live_orders=_flag(values.get("live_orders"), defaults.live_orders),
        )


@dataclass(frozen=True)
class GeneralSettings:
    """The start page and where the downloaded candles live."""

    start_page: str = "home"           # home | live | builder | backtest
    data_folder: str = ""              # empty = data/candles in the repo

    @classmethod
    def load(
        cls,
        raw: object,
        environment: dict[str, str] | None = None,
    ) -> "GeneralSettings":
        environment = os.environ if environment is None else environment
        values = dict(raw) if isinstance(raw, dict) else {}

        for spec in fields(cls):
            override = environment.get(f"LALALA_GENERAL_{spec.name.upper()}")
            if override is not None:
                values[spec.name] = override

        defaults = cls()
        page = str(values.get("start_page", defaults.start_page)).strip().lower()
        if page not in START_PAGES:
            page = defaults.start_page
        folder = values.get("data_folder", defaults.data_folder)
        return cls(
            start_page=page,
            data_folder=folder.strip() if isinstance(folder, str) else "",
        )


START_PAGES = ("home", "live", "builder", "backtest")

# Sub-sections with their own loader; the top-level numeric pass skips them.
NESTED_SECTIONS = ("backtest", "trading", "general")


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
    trading: TradingDefaults = TradingDefaults()
    general: GeneralSettings = GeneralSettings()

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

        for spec in fields(cls):
            if spec.name in NESTED_SECTIONS:
                continue
            override = environment.get(f"LALALA_{spec.name.upper()}")
            if override is not None:
                values[spec.name] = override

        defaults = cls()
        numbers: dict[str, float] = {}
        for spec in fields(cls):
            if spec.name in NESTED_SECTIONS:
                continue
            numbers[spec.name] = _number(
                values.get(spec.name), getattr(defaults, spec.name)
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
            trading=TradingDefaults.load(values.get("trading"), environment),
            general=GeneralSettings.load(values.get("general"), environment),
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


def load_raw(path: Path | str | None = None) -> dict[str, object]:
    """The settings file as a dictionary; broken files read as empty."""
    target = settings_path() if path is None else Path(path)
    try:
        loaded = json.loads(target.read_text())
    except (OSError, ValueError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def save_raw(raw: dict[str, object], path: Path | str | None = None) -> None:
    """Write the dictionary atomically, creating its folder if needed."""
    target = settings_path() if path is None else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(raw, indent=2) + "\n")
    os.replace(temp, target)


def save_backtest_defaults(
    defaults: BacktestDefaults, path: Path | str | None = None
) -> None:
    """Persist the backtest card, preserving the rest of the file."""
    raw = load_raw(path)
    raw["backtest"] = {
        "initial_capital": defaults.initial_capital,
        "tp": defaults.tp,
        "sl": defaults.sl,
        "position": defaults.position,
        "cash": defaults.cash,
        "fee": defaults.fee,
        "dynamic_tp": defaults.dynamic_tp,
        "dyn_tp_reverse": defaults.dyn_tp_reverse,
        "hold": defaults.hold,
        "sizing": defaults.sizing,
        "timeframe": defaults.timeframe,
        "start_year": defaults.start_year,
        "end_year": defaults.end_year,
    }
    save_raw(raw, path)


def save_trading_defaults(
    defaults: TradingDefaults, path: Path | str | None = None
) -> None:
    """Persist the trading card, preserving the rest of the file."""
    raw = load_raw(path)
    raw["trading"] = {
        "leverage": defaults.leverage,
        "margin_mode": defaults.margin_mode,
        "size": defaults.size,
        "polymarket_stake": defaults.polymarket_stake,
        "max_stake": defaults.max_stake,
        "daily_loss_limit": defaults.daily_loss_limit,
        "confirm_orders": defaults.confirm_orders,
        "auto_bet": defaults.auto_bet,
        "live_orders": defaults.live_orders,
    }
    save_raw(raw, path)


def save_general(general: GeneralSettings, path: Path | str | None = None) -> None:
    """Persist the general card, preserving the rest of the file."""
    raw = load_raw(path)
    raw["general"] = {
        "start_page": general.start_page,
        "data_folder": general.data_folder,
    }
    save_raw(raw, path)


def configured_data_folder() -> str:
    """`general.data_folder`, or an empty string for the built-in location."""
    general = load_raw().get("general")
    if isinstance(general, dict):
        value = general.get("data_folder")
        if isinstance(value, str):
            return value.strip()
    return ""


def load_window_geometry() -> str:
    """The hub window's saved geometry (base64), or an empty string."""
    window = load_raw().get("window")
    if isinstance(window, dict):
        value = window.get("geometry")
        if isinstance(value, str):
            return value
    return ""


def save_window_geometry(geometry: str, path: Path | str | None = None) -> None:
    """Persist the hub window's geometry, preserving the rest of the file."""
    raw = load_raw(path)
    raw["window"] = {"geometry": geometry}
    save_raw(raw, path)


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


def _margin(value: object, fallback: str) -> str:
    return value.lower() if isinstance(value, str) and value.lower() in ("isolated", "cross") else fallback


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
