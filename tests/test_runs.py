"""Saved backtest runs: what a run keeps, and reading it back."""

from __future__ import annotations


import pytest

from lalala.state import runs


# in stamp, in index, in price, out stamp, out index, out price, result, size,
# pnl, reason, fees, price path, side
TRADE = [1000, 3, 100.0, 5000, 9, 98.0, 0.019, 200.0, 3.8, "tp", 0.24,
         [100.0, 99.0, 98.0], "short"]


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
            trades=[TRADE],
            strategy_curve=[10_000.0, 10_050.0, 10_020.0],
            random_curve=[10_000.0, 9_990.0, 10_010.0],
            side="short",
            strategy="Dip",
        )
    )
    found = runs.get("dip")
    assert found is not None
    assert found.years == [2019, 2020]
    assert found.rule == "saved"
    assert found.params == {"tp": 2.0, "sl": 1.0}
    assert found.trades == [TRADE]
    assert found.strategy_curve == [10_000.0, 10_050.0, 10_020.0]
    assert found.random_curve == [10_000.0, 9_990.0, 10_010.0]
    assert found.side == "short"
    assert found.strategy == "Dip"


def test_saving_under_a_name_replaces(tmp_path) -> None:
    runs.save(runs.SavedRun(name="a", years=[2020]))
    runs.save(runs.SavedRun(name="a", years=[2021]))
    kept = runs.load()
    assert len(kept) == 1
    assert kept[0].years == [2021]


def test_the_index_holds_no_trades_and_the_trades_are_parquet(tmp_path) -> None:
    import json

    runs.save(runs.SavedRun(name="dip", trades=[TRADE, TRADE]))
    index = json.loads((tmp_path / "runs.json").read_text())
    assert "trades" not in index[0]
    assert index[0]["trade_count"] == 2
    assert runs.trades_file("dip").suffix == ".parquet"
    assert runs.trades_file("dip").exists()
    # Listing is light: counts, not rows.
    assert runs.load()[0].trade_count == 2
    assert runs.load()[0].trades == []


def test_removing_a_run_deletes_its_files() -> None:
    runs.save(
        runs.SavedRun(
            name="dip", trades=[TRADE], strategy_curve=[1.0], random_curve=[1.0]
        )
    )
    assert runs.curves_file("dip").exists()
    runs.remove("dip")
    assert runs.get("dip") is None
    assert not runs.trades_file("dip").exists()
    assert not runs.curves_file("dip").exists()


def test_names_that_clean_up_alike_keep_separate_files() -> None:
    assert runs.trades_file("a/b") != runs.trades_file("a b")


def test_an_older_index_with_inline_trades_is_migrated(tmp_path) -> None:
    import json

    legacy = [
        {
            "name": "old",
            "years": [2020],
            "trades": [[1000, 3, 100.0, 5000, 9, 98.0, 0.019, 200.0, 3.8, "tp", 0.24]],
        }
    ]
    (tmp_path / "runs.json").write_text(json.dumps(legacy))

    found = runs.get("old")
    assert found is not None
    assert len(found.trades) == 1
    assert found.trades[0][12] == "long"  # no side then: a long
    assert found.trade_count == 1
    # The index no longer carries them, and the old file is kept.
    assert "trades" not in json.loads((tmp_path / "runs.json").read_text())[0]
    assert (tmp_path / "runs.json.bak").exists()
