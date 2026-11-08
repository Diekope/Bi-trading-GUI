"""Saved backtest runs: what a run keeps, and reading it back."""

from __future__ import annotations

import json

import pytest

from lalala import runs


@pytest.fixture(autouse=True)
def _tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_RUNS", str(tmp_path / "runs.json"))


def test_a_run_round_trips_through_the_file() -> None:
    runs.save(
        runs.SavedRun(
            name="dip",
            years=[2019, 2020],
            resolution="1h",
            rule="saved",
            entry="close < bollinger_lower(close, 20, 2)",
            exit="pnl >= tp",
            params={"tp": 2.0, "sl": 1.0},
            trades=[[0, 1, 2]],
        )
    )
    found = runs.get("dip")
    assert found is not None
    assert found.years == [2019, 2020]
    assert found.rule == "saved"
    assert found.params == {"tp": 2.0, "sl": 1.0}
    assert found.trades == [[0, 1, 2]]


def test_saving_under_a_name_replaces(tmp_path) -> None:
    runs.save(runs.SavedRun(name="a", years=[2020]))
    runs.save(runs.SavedRun(name="a", years=[2021]))
    kept = runs.load()
    assert len(kept) == 1
    assert kept[0].years == [2021]
