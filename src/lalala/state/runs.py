"""Saved backtest runs: what was run, how, and what it traded.

A run remembers the span, the resolution, the parameters, the strategy (a
built-in key, or a saved strategy's entry rule, exit rule and side) and what
the walk produced: every trade and the equity curves. It can be re-opened and
its trades listed and marked on the chart.

The small things live in an index, the large ones in Parquet beside it:

    ~/.config/lalala/runs.json              the index (LALALA_RUNS overrides it)
    ~/.config/lalala/runs_data/<run>.trades.parquet   one row per trade
    ~/.config/lalala/runs_data/<run>.curves.parquet   one row per bar

so listing the runs reads a few kilobytes however many trades they made, and a
run's curves (millions of bars for a decade of minutes) are stored compressed
and in columns rather than as a JSON array.

An index written before this layout, with the trades inline, is migrated the
first time it is read.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["SavedRun", "get", "load", "path", "remove", "save"]

DEFAULT_PATH = "~/.config/lalala/runs.json"

# One closed trade, as the playback logs it:
# (in stamp, in index, in price, out stamp, out index, out price, result,
#  size, pnl, reason, fees, price path, side)
TRADE_COLUMNS = (
    "in_stamp", "in_index", "in_price", "out_stamp", "out_index", "out_price",
    "result", "size", "pnl", "reason", "fees", "path", "side",
)


@dataclass
class SavedRun:
    name: str
    years: list[int] = field(default_factory=list)
    resolution: str = "1m"
    rule: str = "bollinger"
    strategy: str = ""        # the saved strategy's name, when one was applied
    entry: str = ""
    exit: str = ""
    side: str = "long"
    short_entry: str = ""
    params: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)
    strategy_curve: list = field(default_factory=list)
    random_curve: list = field(default_factory=list)
    trade_count: int = 0

    def as_dict(self) -> dict:
        """The index entry: everything but the trades and the curves."""
        return {
            "name": self.name,
            "years": list(self.years),
            "resolution": self.resolution,
            "rule": self.rule,
            "strategy": self.strategy,
            "entry": self.entry,
            "exit": self.exit,
            "side": self.side,
            "short_entry": self.short_entry,
            "params": dict(self.params),
            "trade_count": self.trade_count or len(self.trades),
        }


def path() -> Path:
    return Path(os.environ.get("LALALA_RUNS", DEFAULT_PATH)).expanduser()


def data_dir() -> Path:
    """Where the Parquet files go: beside the index."""
    target = path()
    return target.with_name(f"{target.stem}_data")


def _stem(name: str) -> str:
    """A file name for a run: readable, and unique even if two names clean up
    to the same text."""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")[:40] or "run"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{clean}-{digest}"


def trades_file(name: str) -> Path:
    return data_dir() / f"{_stem(name)}.trades.parquet"


def curves_file(name: str) -> Path:
    return data_dir() / f"{_stem(name)}.curves.parquet"


# -- reading -----------------------------------------------------------------


def _from_index(item: dict) -> SavedRun | None:
    name = str(item.get("name", "")).strip()
    if not name:
        return None
    years = item.get("years", [])
    side = item.get("side") if item.get("side") in ("short", "both") else "long"
    inline = list(item.get("trades", []) or [])
    return SavedRun(
        name=name,
        years=[int(y) for y in years] if isinstance(years, list) else [],
        resolution=str(item.get("resolution", "1m")),
        rule=str(item.get("rule", "bollinger")),
        strategy=str(item.get("strategy", "")),
        entry=str(item.get("entry", "")),
        exit=str(item.get("exit", "")),
        side=side,
        short_entry=str(item.get("short_entry", "")),
        params=dict(item.get("params", {}) or {}),
        trades=inline,
        trade_count=int(item.get("trade_count", len(inline)) or 0),
    )


def _read_index() -> list[dict]:
    try:
        raw = json.loads(path().read_text())
    except (OSError, ValueError):
        return []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def load() -> list[SavedRun]:
    """Every saved run, oldest first, without its trades or curves.

    Cheap to call: it reads the index only. `get` brings one run back whole.
    """
    items = _read_index()
    if any(item.get("trades") for item in items):
        items = _migrate(items)
    runs = [_from_index(item) for item in items]
    return [run for run in runs if run is not None]


def get(name: str) -> SavedRun | None:
    """One run with its trades and curves, or None."""
    for item in load():
        if item.name == name:
            item.trades = read_trades(name)
            item.strategy_curve, item.random_curve = read_curves(name)
            return item
    return None


def read_trades(name: str) -> list:
    """The trades of a run, as the records the playback logs."""
    import pyarrow.parquet as pq

    try:
        table = pq.read_table(trades_file(name))
    except (OSError, ValueError):
        return []
    columns = [table.column(key).to_pylist() for key in TRADE_COLUMNS]
    return [list(row) for row in zip(*columns, strict=True)]


def read_curves(name: str) -> tuple[list, list]:
    """The strategy and random-buy equity curves of a run."""
    import pyarrow.parquet as pq

    try:
        table = pq.read_table(curves_file(name))
    except (OSError, ValueError):
        return [], []
    return (
        table.column("strategy").to_pylist(),
        table.column("random").to_pylist(),
    )


# -- writing -----------------------------------------------------------------


def save(run: SavedRun) -> list[SavedRun]:
    """Keep a run under its name, replacing one with the same name."""
    name = run.name.strip()
    if not name:
        raise ValueError("a run needs a name")
    run.name = name
    run.trade_count = len(run.trades)
    write_trades(name, run.trades)
    write_curves(name, run.strategy_curve, run.random_curve)
    kept = [item for item in _read_index() if item.get("name") != name]
    kept.append(run.as_dict())
    _write(kept)
    return load()


def write_trades(name: str, trades: list) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = [_pad(record) for record in trades]
    columns = list(zip(*rows, strict=True)) if rows else [()] * len(TRADE_COLUMNS)
    types = (
        pa.int64(), pa.int64(), pa.float64(), pa.int64(), pa.int64(),
        pa.float64(), pa.float64(), pa.float64(), pa.float64(), pa.string(),
        pa.float64(), pa.list_(pa.float64()), pa.string(),
    )
    table = pa.table(
        {
            key: pa.array(list(values), type=kind)
            for key, values, kind in zip(TRADE_COLUMNS, columns, types, strict=True)
        }
    )
    target = trades_file(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target, compression="zstd")


def write_curves(name: str, strategy, random) -> None:
    """The two equity curves, a row per bar (the shorter one padded with its
    last value, so the columns line up)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    target = curves_file(name)
    if not len(strategy) and not len(random):
        target.unlink(missing_ok=True)
        return
    size = max(len(strategy), len(random))

    def padded(curve):
        values = [float(value) for value in curve]
        if values and len(values) < size:
            values += [values[-1]] * (size - len(values))
        return values or [0.0] * size

    table = pa.table(
        {
            "strategy": pa.array(padded(strategy), type=pa.float64()),
            "random": pa.array(padded(random), type=pa.float64()),
        }
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target, compression="zstd")


def _pad(record) -> tuple:
    """A trade record at full width: an older one lacks the path and the side."""
    row = list(record)
    row += [None] * (len(TRADE_COLUMNS) - len(row))
    if row[11] is None:
        row[11] = []
    if row[12] not in ("long", "short"):
        row[12] = "long"
    return tuple(row[: len(TRADE_COLUMNS)])


def remove(name: str) -> list[SavedRun]:
    """Forget a run and delete its Parquet files."""
    kept = [item for item in _read_index() if item.get("name") != name]
    _write(kept)
    trades_file(name).unlink(missing_ok=True)
    curves_file(name).unlink(missing_ok=True)
    return load()


def _migrate(items: list[dict]) -> list[dict]:
    """Move trades kept inline in the index into Parquet files."""
    # Keep the old file once, in case the layout needs to be walked back.
    backup = path().with_suffix(".json.bak")
    if not backup.exists():
        try:
            backup.write_bytes(path().read_bytes())
        except OSError:
            pass
    out = []
    for item in items:
        inline = item.get("trades") or []
        name = str(item.get("name", "")).strip()
        if inline and name:
            write_trades(name, inline)
            item = {key: value for key, value in item.items() if key != "trades"}
            item["trade_count"] = len(inline)
        out.append(item)
    _write(out)
    return out


def _write(items: list[dict]) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(items, indent=2) + "\n")
