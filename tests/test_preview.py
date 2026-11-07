"""The preview tile: the rule run over the candles on disk."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.candles import HEADER, append_rows, candle_file  # noqa: E402
from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS, parse  # noqa: E402
from lalala.strat_preview import (  # noqa: E402
    VISIBLE,
    PreviewBar,
    PreviewTile,
    compact,
    latest_year,
    load_bars,
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
    from lalala import candles

    candles._ROW_CACHE.clear()
    yield


def _write_year(year: int, count: int) -> None:
    """A saw-tooth so there is something to enter on."""
    rows = []
    price = 100.0
    for index in range(count):
        price = 100.0 + (index % 20)
        rows.append((index * 60_000, price, price + 1, price - 1, price, 1.0))
    append_rows(candle_file(year), rows)


# -- loading ----------------------------------------------------------------


def test_compacting_keeps_first_open_and_last_close() -> None:
    bars = [
        PreviewBar(0, 10.0, 12.0, 9.0, 11.0, 1.0),
        PreviewBar(1, 11.0, 15.0, 10.0, 14.0, 2.0),
        PreviewBar(2, 14.0, 14.5, 8.0, 9.0, 3.0),
    ]

    two = compact(bars, 2)

    assert two[0] == PreviewBar(0, 10.0, 15.0, 9.0, 14.0, 3.0)
    assert two[1].close == 9.0
    assert two[1].volume == 3.0
    assert compact(bars, 1) == bars


def test_the_newest_year_on_disk_is_the_one_shown() -> None:
    assert latest_year() is None  # an empty store
    _write_year(2019, 50)
    _write_year(2021, 50)

    assert latest_year() == 2021
    bars, year = load_bars("1m")
    assert year == 2021
    assert bars
    # The bars are the newest year's, not the older file's.
    assert bars[-1].close == 100.0 + (49 % 20)


def test_the_tail_is_compacted_to_the_resolution() -> None:
    _write_year(2020, 600)

    minute, _ = load_bars("1m")
    hour, _ = load_bars("1h")

    # A minute series is longer than an hourly one over the same span.
    assert len(minute) > len(hour)
    assert hour[0].open == pytest.approx(minute[0].open)


def test_an_empty_store_loads_nothing() -> None:
    assert load_bars("1h") == ([], None)


# -- the tile ---------------------------------------------------------------


def test_the_tile_says_when_there_is_nothing_to_run(app: QApplication) -> None:
    tile = PreviewTile()
    tile.resize(300, 400)
    tile.show()
    app.processEvents()

    assert "no candles on disk" in tile.note.text()
    tile.close()


def test_the_tile_says_when_there_is_no_rule(app: QApplication) -> None:
    _write_year(2021, 200)
    tile = PreviewTile()
    tile.resize(300, 400)
    tile.show()
    app.processEvents()

    assert "no entry rule yet" in tile.note.text()
    tile.close()


def test_the_tile_marks_where_the_rule_fires(app: QApplication) -> None:
    _write_year(2021, 600)
    entry = parse("close < sma(close, 5)")
    exit_ = parse(
        "pnl >= tp or pnl <= 0 - sl or bars >= 3", EXIT_FIELDS, EXIT_FUNCTIONS
    )

    tile = PreviewTile()
    tile.resize(300, 400)
    tile.show()
    tile.configure(entry, exit_, "1m")
    app.processEvents()

    assert tile.chart.entries, "the rule should fire on a saw-tooth"
    assert tile.chart.exits
    assert "2021" in tile.note.text()
    assert "entries in view" in tile.note.text()
    # The markers are the bars the walk says they are.
    entries, exits = tile.chart.entries, tile.chart.exits
    assert all(0 <= index < len(tile.chart.bars) for index in entries)
    assert all(entries[i] < exits[i] for i in range(len(exits)))
    assert not tile.grab().toImage().isNull()
    tile.close()


def test_the_tile_shows_the_last_bars_only(app: QApplication) -> None:
    _write_year(2021, VISIBLE + 200)
    tile = PreviewTile()
    tile.resize(300, 400)
    tile.show()
    tile.configure(parse("close > 0"), None, "1m")
    app.processEvents()

    # Every bar is kept, but only the tail is drawn.
    assert len(tile.chart.bars) > VISIBLE
    assert not tile.chart.grab().toImage().isNull()
    tile.close()


def test_the_note_names_the_defaults_the_preview_used(app: QApplication) -> None:
    _write_year(2021, 300)
    tile = PreviewTile()
    tile.show()
    tile.configure(parse("close > 0"), None, "1m")
    app.processEvents()

    assert "tp 2 / sl 1" in tile.note.text()
    tile.close()
