"""Saved strategies: the drafts worth keeping, in one JSON file.

A strategy is a name, the bar it reads, which way it trades (long, short or
both) and its rules as text — the same text
the tiles stand for. Keeping it as text rather than as chips means it can be
read and checked with the same parser as anything typed by hand, and it does
not care how it was written.

    ~/.config/lalala/strategies.json      (LALALA_STRATEGIES overrides it)

Saving under a name that is already there replaces it, so re-saving a draft
does not pile up copies.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_PATH",
    "SavedStrategy",
    "load",
    "path",
    "remove",
    "save",
]

DEFAULT_PATH = "~/.config/lalala/strategies.json"


@dataclass(frozen=True)
class SavedStrategy:
    """One saved draft: a name, a bar, and both rules as text."""

    name: str
    timeframe: str
    entry: str
    exit: str
    side: str = "long"
    # The condition that opens a short, for a strategy that goes both ways;
    # then `entry` opens the longs. Empty for a long or a short strategy.
    short_entry: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "timeframe": self.timeframe,
            "entry": self.entry,
            "exit": self.exit,
            "side": self.side,
            "short_entry": self.short_entry,
        }


def path() -> Path:
    """Where the drafts live, honouring LALALA_STRATEGIES."""
    return Path(os.environ.get("LALALA_STRATEGIES", DEFAULT_PATH)).expanduser()


def load() -> list[SavedStrategy]:
    """Every saved strategy, oldest first. A missing or broken file is empty."""
    target = path()
    try:
        raw = json.loads(target.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[SavedStrategy] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        out.append(
            SavedStrategy(
                name=name,
                timeframe=str(item.get("timeframe", "1m")),
                entry=str(item.get("entry", "")),
                exit=str(item.get("exit", "")),
                side=_side(item.get("side")),
                short_entry=str(item.get("short_entry", "")),
            )
        )
    return out


def save(strategy: SavedStrategy) -> list[SavedStrategy]:
    """Add a strategy, or replace the one with the same name."""
    name = strategy.name.strip()
    if not name:
        raise ValueError("a strategy needs a name")
    kept = [item for item in load() if item.name != name]
    kept.append(
        SavedStrategy(
            name=name,
            timeframe=strategy.timeframe,
            entry=strategy.entry,
            exit=strategy.exit,
            side=_side(strategy.side),
            short_entry=strategy.short_entry,
        )
    )
    _write(kept)
    return kept


def _side(value: object) -> str:
    """`short`, `both` or `long`; anything else, including a file from before
    shorting, is a long."""
    return value if value in ("short", "both") else "long"


def remove(name: str) -> list[SavedStrategy]:
    kept = [item for item in load() if item.name != name]
    _write(kept)
    return kept


def _write(strategies: list[SavedStrategy]) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([item.as_dict() for item in strategies], indent=2) + "\n"
    )
