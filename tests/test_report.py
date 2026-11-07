"""The right rail: the rule's numbers and its curve against two others."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

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
    assert [value.text() for _, value in tile._metrics] == ["—"] * 6
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
    assert captions == [
        "PnL", "Sharpe", "Max DD", "Trades", "Win rate", "Fees"
    ]
    values = {caption.text(): value.text() for caption, value in tile._metrics}
    assert values["PnL"].endswith("%")
    assert values["Max DD"].endswith("%")
    assert values["Trades"].isdigit()
    assert values["Win rate"].endswith("%")
    assert values["Fees"].startswith("$")

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
    assert [value.text() for _, value in tile._metrics] == ["—"] * 6
    assert tile.legend["strategy"].text() == "strategy"
    tile.close()


def test_the_curve_chart_paints_before_any_run(app: QApplication) -> None:
    chart = CurveChart()
    chart.resize(300, 200)
    chart.show()
    app.processEvents()

    assert not chart.grab().toImage().isNull()
    chart.close()


# -- the two subwindows ------------------------------------------------------


def test_the_tile_has_overview_and_compare(app: QApplication) -> None:
    tile = ReportTile()
    tile.resize(420, 460)
    tile.show()
    app.processEvents()

    # RESULTS keeps its title, and the two views are the pills beside it, the
    # way Rules / Formula / Code sit in the rules tile.
    titles = [
        label.text()
        for label in tile.findChildren(QLabel)
        if label.objectName() == "tileTitle"
    ]
    assert titles == ["RESULTS"]
    assert [button.text() for button in tile.view_buttons.values()] == [
        "Overview",
        "Compare",
    ]
    for button in tile.view_buttons.values():
        assert button.objectName() == "modeButton"
        assert button.isCheckable() is True
    assert tile.view_buttons["overview"].isChecked() is True
    assert tile.pages.count() == 2

    # Overview is the split, and it is the one on show.
    assert tile.view() == "overview"
    page = tile.pages.currentWidget()
    assert page.isAncestorOf(tile.chart)
    assert page.isAncestorOf(tile.reasons)

    # Compare is set aside for now; switching shows it, and the switch goes
    # back.
    picked: list[str] = []
    tile.view_changed.connect(picked.append)
    tile.view_buttons["compare"].click()
    app.processEvents()
    assert tile.view() == "compare"
    assert tile.pages.currentIndex() == 1
    assert tile.compare_message.text() == "put two runs side by side here"
    assert picked == ["compare"]

    tile.set_view("overview")
    assert tile.view() == "overview"
    assert tile.pages.currentIndex() == 0
    assert picked == ["compare", "overview"]
    tile.close()


def test_the_overview_lists_how_the_trades_ended(app: QApplication) -> None:
    _write_year(2021, 600)
    entry = parse("close < sma(close, 5)")
    exit_ = parse(
        "pnl >= tp or pnl <= 0 - sl or bars >= 3", EXIT_FIELDS, EXIT_FUNCTIONS
    )

    tile = ReportTile()
    tile.resize(560, 460)
    tile.show()
    tile.configure(entry, exit_, "1m")
    app.processEvents()

    report = tile.chart.report
    assert report is not None

    # The reasons are the ones the run logged, most appearing first, and their
    # shares add up to the whole.
    rows = tile.reasons.rows
    assert rows, "the walk ended some trades"
    assert [label for label, _, _ in rows] == [
        label for label, _, _ in report.reason_shares
    ]
    shares = [share for _, share, _ in rows]
    assert shares == sorted(shares, reverse=True)
    assert sum(shares) == pytest.approx(1.0)
    # Each reason has a colour of its own.
    assert all(colour for _, _, colour in rows)
    tile.close()


def test_the_fees_and_reasons_follow_the_run(app: QApplication) -> None:
    _write_year(2021, 600)
    entry = parse("close < sma(close, 5)")
    exit_ = parse("pnl <= 0 - sl or pnl >= tp", EXIT_FIELDS, EXIT_FUNCTIONS)

    tile = ReportTile()
    tile.resize(560, 460)
    tile.show()
    tile.configure(entry, exit_, "1m")
    app.processEvents()

    report = tile.chart.report
    values = {caption.text(): value.text() for caption, value in tile._metrics}
    assert values["Fees"] == f"${report.fees:,.0f}"
    assert report.fees > 0
    # Every reason the walk recorded is a known one.
    assert set(report.reasons) <= {
        "Take profit", "Stop loss", "Time", "Rule", "End of data"
    }
    tile.close()
