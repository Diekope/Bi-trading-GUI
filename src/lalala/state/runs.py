"""Saved backtest runs: a name, how the walk was set, and what it traded.

A run remembers the span, the resolution, the parameters, the strategy (a
built-in key or a saved strategy's entry rule) and every trade it made, so it
can be re-opened and its trades listed and marked on the chart.

    ~/.config/lalala/runs.json      (LALALA_RUNS overrides it)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["SavedRun", "load", "path", "remove", "save"]

DEFAULT_PATH = "~/.config/lalala/runs.json"


@dataclass
class SavedRun:
    name: str
    years: list[int] = field(default_factory=list)
    resolution: str = "1m"
    rule: str = "bollinger"
    entry: str = ""
    exit: str = ""
    params: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "years": list(self.years),
            "resolution": self.resolution,
            "rule": self.rule,
            "entry": self.entry,
            "exit": self.exit,
            "params": dict(self.params),
            "trades": list(self.trades),
        }


def path() -> Path:
    return Path(os.environ.get("LALALA_RUNS", DEFAULT_PATH)).expanduser()


def load() -> list[SavedRun]:
    target = path()
    try:
        raw = json.loads(target.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[SavedRun] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        years = item.get("years", [])
        out.append(
            SavedRun(
                name=name,
                years=[int(y) for y in years] if isinstance(years, list) else [],
                resolution=str(item.get("resolution", "1m")),
                rule=str(item.get("rule", "bollinger")),
                entry=str(item.get("entry", "")),
                exit=str(item.get("exit", "")),
                params=dict(item.get("params", {}) or {}),
                trades=list(item.get("trades", []) or []),
            )
        )
    return out


def save(run: SavedRun) -> list[SavedRun]:
    name = run.name.strip()
    if not name:
        raise ValueError("a run needs a name")
    run.name = name
    kept = [item for item in load() if item.name != name]
    kept.append(run)
    _write(kept)
    return kept


def get(name: str) -> SavedRun | None:
    for item in load():
        if item.name == name:
            return item
    return None


def remove(name: str) -> list[SavedRun]:
    kept = [item for item in load() if item.name != name]
    _write(kept)
    return kept


def _write(runs: list[SavedRun]) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([item.as_dict() for item in runs], indent=2) + "\n"
    )
