"""The saved-strategies rail: the kept drafts, with what they returned."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.candles import append_rows, candle_file  # noqa: E402
from lalala.strategies import SavedStrategy  # noqa: E402
from lalala.strat_saved import (  # noqa: E402
    DRAFT_BADGE,
    StrategyListTile,
    StrategyRow,
    strategy_pnl,
    strategy_stats,
)
from lalala.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))
    from lalala import candles

    candles._ROW_CACHE.clear()
    strategy_stats.cache_clear()
    yield


def _write_year(year: int, count: int) -> None:
    rows = []
    for index in range(count):
        price = 100.0 + (index % 20)
        rows.append((index * 60_000, price, price + 1, price - 1, price, 1.0))
    append_rows(candle_file(year), rows)


# -- the return, cached ------------------------------------------------------


def test_a_strategy_returns_a_return_or_nothing() -> None:
    _write_year(2021, 600)

    pnl = strategy_pnl("close < sma(close, 5)", "pnl >= tp", "1m")
    assert isinstance(pnl, float)

    # Nothing to read, or a rule that will not parse, is None, not a guess.
    assert strategy_pnl("", "pnl >= tp", "1m") is None
    assert strategy_pnl("close < clsoe", "pnl >= tp", "1m") is None


# -- the list ----------------------------------------------------------------


def test_an_empty_list_says_so(app: QApplication) -> None:
    tile = StrategyListTile()
    tile.resize(240, 400)
    tile.show()
    app.processEvents()

    assert tile.rows == []
    assert tile.empty.isVisible() is True
    assert tile.empty.text() == "no saved strategies yet"
    assert tile.create_button.text() == "Create a strategy"
    tile.close()


def test_saved_strategies_are_listed_most_recent_first(
    app: QApplication,
) -> None:
    _write_year(2021, 600)
    saved = [
        SavedStrategy("Dip", "1m", "close < sma(close, 5)", "pnl >= tp"),
        SavedStrategy("Pop", "1m", "close > sma(close, 5)", "pnl <= 0 - sl"),
    ]

    tile = StrategyListTile()
    tile.resize(240, 400)
    tile.show()
    tile.set_strategies(saved, None)
    app.processEvents()

    assert [row.name for row in tile.rows] == ["Pop", "Dip"]
    assert tile.empty.isVisible() is False
    for row in tile.rows:
        assert isinstance(row, StrategyRow)
        assert row.badge.text().endswith("%")
        assert row.time_label.text() == "1m"
    tile.close()


def test_the_draft_shows_among_the_saved_and_is_lit(
    app: QApplication,
) -> None:
    _write_year(2021, 600)
    saved = [SavedStrategy("Dip", "1m", "close < sma(close, 5)", "pnl >= tp")]

    tile = StrategyListTile()
    tile.resize(240, 400)
    tile.show()

    # A named draft that is not saved yet sits at the top, badged "draft".
    draft = SavedStrategy("Fresh", "5m", "close > sma(close, 5)", "")
    tile.set_strategies(saved, draft)
    app.processEvents()
    assert [row.name for row in tile.rows] == ["Fresh", "Dip"]
    assert tile.rows[0].badge.text() == DRAFT_BADGE
    assert tile.rows[0].time_label.text() == "5m"
    assert tile.rows[0].property("selected") is True
    assert tile.rows[1].property("selected") is False

    # A draft that matches a saved one lights that row instead, and no extra
    # row is shown.
    tile.set_strategies(saved, saved[0])
    app.processEvents()
    assert [row.name for row in tile.rows] == ["Dip"]
    assert tile.rows[0].property("selected") is True

    # No name at all: nothing is a draft.
    tile.set_strategies(saved, SavedStrategy("", "1m", "", ""))
    app.processEvents()
    assert [row.name for row in tile.rows] == ["Dip"]
    assert tile.rows[0].property("selected") is False

    # A draft sharing a saved name but with other rules: the draft row is lit,
    # the saved row of the same name is not.
    tile.set_strategies(
        saved, SavedStrategy("Dip", "1m", "close > sma(close, 5)", "")
    )
    app.processEvents()
    assert [row.name for row in tile.rows] == ["Dip", "Dip"]
    assert tile.rows[0].badge.text() == DRAFT_BADGE
    assert tile.rows[0].property("selected") is True
    assert tile.rows[1].property("selected") is False
    tile.close()


def test_clicking_a_row_says_which_name(app: QApplication) -> None:
    saved = [SavedStrategy("Dip", "1m", "close < sma(close, 5)", "pnl >= tp")]
    tile = StrategyListTile()
    tile.resize(240, 400)
    tile.show()
    tile.set_strategies(saved, None)
    app.processEvents()

    picked: list[str] = []
    tile.chosen.connect(picked.append)
    tile.rows[0].clicked.emit("Dip")
    app.processEvents()
    assert picked == ["Dip"]
    tile.close()


def test_a_row_carries_its_bar_and_its_record(app: QApplication) -> None:
    _write_year(2021, 600)
    saved = [SavedStrategy("Dip", "1m", "close < sma(close, 5)", "pnl >= tp")]
    tile = StrategyListTile()
    tile.resize(240, 400)
    tile.show()
    tile.set_strategies(saved, None)
    app.processEvents()

    row = tile.rows[0]
    assert row.time_label.text() == "1m"
    # Under the return: the trades it took and how many of them won.
    assert row.badge.text().endswith("%")
    assert " tr · " in row.stats.text()
    assert row.stats.text().endswith("%")
    tile.close()


def test_a_row_can_be_archived_or_deleted(app: QApplication) -> None:
    saved = [SavedStrategy("Dip", "1m", "close < sma(close, 5)", "pnl >= tp")]
    tile = StrategyListTile()
    tile.resize(240, 400)
    tile.show()
    tile.set_strategies(saved, None)
    app.processEvents()

    archived: list[str] = []
    deleted: list[str] = []
    tile.archived.connect(archived.append)
    tile.deleted.connect(deleted.append)

    row = tile.rows[0]
    assert row.archive_action is not None
    assert row.delete_action is not None
    row.archive_action.trigger()
    row.delete_action.trigger()
    app.processEvents()
    assert archived == ["Dip"]
    assert deleted == ["Dip"]
    tile.close()


def test_archived_strategies_hide_until_shown(app: QApplication) -> None:
    saved = [
        SavedStrategy("Dip", "1m", "close < sma(close, 5)", "pnl >= tp"),
        SavedStrategy("Old", "1m", "close < 10", "", archived=True),
    ]
    tile = StrategyListTile()
    tile.resize(240, 400)
    tile.show()
    tile.set_strategies(saved, None)
    app.processEvents()

    # The archived one is kept but out of the list, and the toggle says so.
    assert [row.name for row in tile.rows] == ["Dip"]
    assert tile.archive_toggle.isVisible() is True
    assert "1" in tile.archive_toggle.text()

    tile.archive_toggle.click()
    app.processEvents()
    assert [row.name for row in tile.rows] == ["Dip", "Old"]
    assert tile.rows[1].property("archived") is True
    # An archived row offers Restore, not Archive.
    assert tile.rows[1].restore_action is not None
    assert tile.rows[1].archive_action is None

    restored: list[str] = []
    tile.restored.connect(restored.append)
    tile.rows[1].restore_action.trigger()
    app.processEvents()
    assert restored == ["Old"]
    tile.close()

