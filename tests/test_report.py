"""The right rail: the rule's numbers and its curve against two others."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.candles import append_rows, candle_file  # noqa: E402
from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS, parse  # noqa: E402
from lalala.strat_report import (  # noqa: E402
    Bar,
    CurveChart,
    ReportTile,
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
    """A saw-tooth, so a rule has something to trade."""
    rows = []
    for index in range(count):
        price = 100.0 + (index % 20)
        rows.append((index * 60_000, price, price + 1, price - 1, price, 1.0))
    append_rows(candle_file(year), rows)


# -- loading ----------------------------------------------------------------


def test_compacting_keeps_first_open_and_last_close() -> None:
    bars = [
        Bar(0, 10.0, 12.0, 9.0, 11.0, 1.0),
        Bar(1, 11.0, 15.0, 10.0, 14.0, 2.0),
        Bar(2, 14.0, 14.5, 8.0, 9.0, 3.0),
    ]

    two = compact(bars, 2)

    assert two[0] == Bar(0, 10.0, 15.0, 9.0, 14.0, 3.0)
    assert two[1].close == 9.0
    assert compact(bars, 1) == bars


def test_the_newest_year_on_disk_is_the_one_read() -> None:
    assert latest_year() is None  # an empty store
    _write_year(2019, 50)
    _write_year(2021, 50)

    assert latest_year() == 2021
    bars, year = load_bars("1m")
    assert year == 2021
    assert bars[-1].close == 100.0 + (49 % 20)


def test_the_tail_is_compacted_to_the_resolution() -> None:
    _write_year(2020, 600)
    minute, _ = load_bars("1m")
    hour, _ = load_bars("1h")
    assert len(minute) > len(hour)
    assert hour[0].open == pytest.approx(minute[0].open)


def test_an_empty_store_loads_nothing() -> None:
    assert load_bars("1h") == ([], None)


# -- the tile ---------------------------------------------------------------


def test_the_tile_says_when_there_is_nothing_to_run(app: QApplication) -> None:
    tile = ReportTile()
    tile.resize(300, 420)
    tile.show()
    app.processEvents()

    assert "no candles on disk" in tile.note.text()
    assert not tile.chart.grab().toImage().isNull()
    tile.close()


def test_the_tile_says_when_there_is_no_rule(app: QApplication) -> None:
    _write_year(2021, 200)
    tile = ReportTile()
    tile.resize(300, 420)
    tile.show()
    app.processEvents()

    assert "no entry rule yet" in tile.note.text()
    assert [value.text() for _, value in tile._metrics] == ["—"] * 5
    tile.close()


def test_the_tile_reports_the_run_in_two_rows(app: QApplication) -> None:
    _write_year(2021, 600)
    entry = parse("close < sma(close, 5)")
    exit_ = parse(
        "pnl >= tp or pnl <= 0 - sl or bars >= 3", EXIT_FIELDS, EXIT_FUNCTIONS
    )

    tile = ReportTile()
    tile.resize(320, 460)
    tile.show()
    tile.configure(entry, exit_, "1m")
    app.processEvents()

    captions = [caption.text() for caption, _ in tile._metrics]
    assert captions == ["PnL", "Sharpe", "Max DD", "Trades", "Win rate"]
    values = {caption.text(): value.text() for caption, value in tile._metrics}
    assert values["PnL"].endswith("%")
    assert values["Max DD"].endswith("%")
    assert values["Trades"].isdigit()
    assert values["Win rate"].endswith("%")

    # The three curves are drawn, and named in the legend with their totals.
    assert tile.chart.report is not None
    assert tile.chart.report.strategy
    assert tile.legend["strategy"].text().startswith("strategy ")
    assert tile.legend["random"].text().startswith("random buy ")
    assert tile.legend["hold"].text().startswith("buy & hold ")
    assert "2021" in tile.note.text()
    assert not tile.grab().toImage().isNull()
    tile.close()


def test_an_empty_rule_clears_the_numbers_and_the_curve(
    app: QApplication,
) -> None:
    _write_year(2021, 400)
    tile = ReportTile()
    tile.resize(320, 460)
    tile.show()
    tile.configure(parse("close < sma(close, 5)"), None, "1m")
    app.processEvents()
    assert tile.chart.report is not None

    tile.configure(parse(""), None, "1m")
    app.processEvents()
    assert tile.chart.report is None
    assert [value.text() for _, value in tile._metrics] == ["—"] * 5
    assert tile.legend["strategy"].text() == "strategy"
    tile.close()


def test_the_curve_chart_paints_before_any_run(app: QApplication) -> None:
    chart = CurveChart()
    chart.resize(300, 200)
    chart.show()
    app.processEvents()

    assert not chart.grab().toImage().isNull()
    chart.close()
