"""Saved strategies: one JSON file, and the drafts in it."""

from __future__ import annotations

import json

import pytest

from lalala.state import strategies
from lalala.state.strategies import SavedStrategy


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))
    yield


def test_the_file_is_where_the_environment_says() -> None:
    assert strategies.path().name == "strategies.json"


def test_an_empty_store_reads_as_nothing() -> None:
    assert strategies.load() == []


def test_saving_a_strategy_keeps_it() -> None:
    strategies.save(SavedStrategy("Dip", "1h", "close < sma(close, 5)", "pnl >= tp"))

    kept = strategies.load()
    assert len(kept) == 1
    assert kept[0] == SavedStrategy("Dip", "1h", "close < sma(close, 5)", "pnl >= tp")
    # It is text on disk, so it can be read back by hand.
    raw = json.loads(strategies.path().read_text())
    assert raw[0]["name"] == "Dip"
    assert raw[0]["entry"] == "close < sma(close, 5)"


def test_saving_the_same_name_replaces_rather_than_piles_up() -> None:
    strategies.save(SavedStrategy("Dip", "1h", "close < 10", ""))
    kept = strategies.save(SavedStrategy("Dip", "5m", "close < 20", "pnl >= tp"))

    assert len(kept) == 1
    assert kept[0].timeframe == "5m"
    assert kept[0].entry == "close < 20"


def test_two_names_live_side_by_side() -> None:
    strategies.save(SavedStrategy("Dip", "1h", "close < 10", ""))
    strategies.save(SavedStrategy("Pop", "5m", "volume > 2", ""))

    assert [item.name for item in strategies.load()] == ["Dip", "Pop"]


def test_removing_one_leaves_the_rest() -> None:
    strategies.save(SavedStrategy("Dip", "1h", "close < 10", ""))
    strategies.save(SavedStrategy("Pop", "5m", "volume > 2", ""))

    left = strategies.remove("Dip")

    assert [item.name for item in left] == ["Pop"]
    assert [item.name for item in strategies.load()] == ["Pop"]


def test_a_strategy_needs_a_name() -> None:
    with pytest.raises(ValueError):
        strategies.save(SavedStrategy("  ", "1h", "close < 10", ""))
    with pytest.raises(ValueError):
        strategies.save(SavedStrategy("", "1h", "close < 10", ""))


def test_a_broken_file_reads_as_nothing_rather_than_raising() -> None:
    strategies.path().parent.mkdir(parents=True, exist_ok=True)
    strategies.path().write_text("{not json")
    assert strategies.load() == []

    strategies.path().write_text('{"name": "one"}')  # an object, not a list
    assert strategies.load() == []


def test_entries_without_a_name_are_dropped() -> None:
    strategies.path().parent.mkdir(parents=True, exist_ok=True)
    strategies.path().write_text(
        json.dumps(
            [
                {"name": "Dip", "timeframe": "1h", "entry": "close < 10"},
                {"name": "   ", "entry": "close < 20"},
                "not a mapping",
            ]
        )
    )

    kept = strategies.load()

    assert [item.name for item in kept] == ["Dip"]
    assert kept[0].exit == ""  # a missing rule is empty, not a failure

