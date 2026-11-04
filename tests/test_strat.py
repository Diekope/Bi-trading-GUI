"""The strategy window: two halves, the right one stacked into two tiles."""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.panels import Card  # noqa: E402
from lalala.strat_tiles import (  # noqa: E402
    FIRST_YEAR,
    RESOLUTIONS,
    DownloadTile,
    candle_file,
    expected_rows,
)
from lalala.strat_window import StratWindow  # noqa: E402
from lalala.theme import CANVAS, apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def window(app: QApplication, monkeypatch, tmp_path) -> StratWindow:
    # No real candle directory in tests.
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    win = StratWindow()
    win.show()
    app.processEvents()
    yield win
    win.close()


def _write_year(year: int, resolution: str, rows: int) -> None:
    """A minimal OHLCV table with `rows` data lines."""
    path = candle_file(year, resolution)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        handle.write("timestamp,open,high,low,close,volume\n")
        for index in range(rows):
            handle.write(f"{index},1,1,1,1,1\n")


def test_the_window_splits_in_two_halves(app: QApplication, window) -> None:
    assert window.windowTitle() == "lalala · backtest + strategy"
    assert window.splitter.count() == 2
    assert window.splitter.orientation() == Qt.Orientation.Horizontal
    left, right = window.splitter.sizes()
    assert abs(left - right) <= 1

    image = window.grab().toImage()
    assert not image.isNull()
    handle = window.splitter.handle(1)
    gap = handle.mapTo(window, handle.rect().center())
    assert image.pixelColor(gap).name() == CANVAS


def test_the_right_side_stacks_two_tiles(app: QApplication, window) -> None:
    column = window.right
    assert column.orientation() == Qt.Orientation.Vertical
    assert column.count() == 2
    assert column.widget(0) is window.download
    assert column.widget(1) is window.blank
    assert isinstance(window.download, Card)
    assert window.blank.findChildren(Card) == []


def test_the_span_picker_covers_2017_to_now(app: QApplication, window) -> None:
    tile = window.download
    this_year = datetime.now(tz=timezone.utc).year

    years = [tile.start_year.itemText(i) for i in range(tile.start_year.count())]
    assert years[0] == str(FIRST_YEAR)
    assert years[-1] == str(this_year)
    assert tile.start_year.currentText() == str(FIRST_YEAR)
    assert tile.end_year.currentText() == str(this_year)
    assert tile.span() == (FIRST_YEAR, this_year, "1m")


def test_the_resolution_picker_is_exclusive(app: QApplication, window) -> None:
    picker = window.download.resolution

    assert picker.current() == "1m"
    order = [
        picker.group.button(i).text()
        for i in range(len(picker.group.buttons()))
    ]
    assert order == list(RESOLUTIONS)

    picker.group.button(2).click()
    app.processEvents()
    assert picker.current() == "1h"
    assert sum(b.isChecked() for b in picker.group.buttons()) == 1


def test_an_empty_span_is_missing_and_flags_download(window) -> None:
    tile = window.download

    missing, partial = tile.coverage()
    assert missing == list(range(FIRST_YEAR, datetime.now().year + 1))
    assert partial == []
    assert tile.has_data() is False

    assert tile.status.isVisible() is True
    assert tile.status.text() == f"missing {FIRST_YEAR}–{datetime.now().year}"
    assert tile.status.property("state") == "missing"
    # Download is offered, and carries the amber "needs data" edge.
    assert tile.download_button.isEnabled() is True
    assert tile.download_button.property("attention") is True


def test_a_short_year_reads_as_partial_in_amber(window) -> None:
    tile = window.download
    tile.start_year.setCurrentText("2017")
    tile.end_year.setCurrentText("2017")
    tile.resolution.group.button(2).click()  # 1h
    _write_year(2017, "1h", 10)
    tile.refresh()

    missing, partial = tile.coverage()
    assert missing == []
    assert partial == [2017]
    assert tile.status.text() == "partial 2017"
    assert tile.status.property("state") == "partial"
    assert tile.download_button.isEnabled() is True


def test_a_complete_span_grays_the_button_out(window) -> None:
    tile = window.download
    tile.start_year.setCurrentText("2017")
    tile.end_year.setCurrentText("2017")
    tile.resolution.group.button(2).click()  # 1h
    _write_year(2017, "1h", 365 * 24)
    tile.refresh()

    assert tile.coverage() == ([], [])
    assert tile.has_data() is True
    assert tile.status.isVisible() is False
    assert tile.download_button.isEnabled() is False
    assert tile.download_button.property("attention") is False


def test_the_current_year_is_only_expected_up_to_today(window) -> None:
    tile = window.download
    this_year = datetime.now(tz=timezone.utc).year
    tile.start_year.setCurrentText(str(this_year))
    tile.end_year.setCurrentText(str(this_year))
    tile.resolution.group.button(2).click()  # 1h

    now = datetime.now(tz=timezone.utc)
    assert expected_rows(this_year, "1h", now) == max(1, now.timetuple().tm_yday) * 24
    # A full past year is partial today, since this year is not over.
    _write_year(this_year, "1h", expected_rows(this_year, "1h", now))
    assert tile.coverage() == ([], [])


def test_start_does_nothing_yet(app: QApplication, window) -> None:
    tile = window.download
    before = (tile.span(), tile.has_data())

    tile.start_button.click()
    app.processEvents()

    assert tile.start_button.isEnabled() is True
    assert (tile.span(), tile.has_data()) == before


def test_the_action_row_is_start_left_download_right(
    app: QApplication, window
) -> None:
    tile = window.download
    assert tile.start_button.text() == "Start backtest"

    row = tile.body.itemAt(tile.body.count() - 1).layout()
    # Start on the left, Download on the right, the note at the far edge.
    assert row.itemAt(0).widget() is tile.start_button
    assert row.itemAt(1).widget() is tile.download_button
    assert row.itemAt(2).widget() is tile.status
    for index in range(3):
        assert row.stretch(index) == 1


def test_only_the_relevant_button_is_shown(app: QApplication, window) -> None:
    tile = window.download

    # Nothing on disk: Download stands alone, Start is out of the way.
    assert tile.download_button.isVisible() is True
    assert tile.start_button.isVisible() is False

    # Complete span: the big Start backtest takes the row, Download goes.
    tile.start_year.setCurrentText("2017")
    tile.end_year.setCurrentText("2017")
    tile.resolution.group.button(2).click()  # 1h
    _write_year(2017, "1h", 365 * 24)
    tile.refresh()
    app.processEvents()

    assert tile.start_button.isVisible() is True
    assert tile.download_button.isVisible() is False
    assert tile.status.isVisible() is False
    # With the note and Download gone, Start owns the whole row.
    assert tile.start_button.width() > tile.width() * 0.8


def test_the_note_only_squeezes_download(app: QApplication, window) -> None:
    tile = window.download
    assert tile.status.isVisible() is True  # missing years in the empty temp dir
    assert tile.start_button.isVisible() is False

    # Download and the note share the row; the note never touches anything else.
    assert tile.download_button.width() < tile.width()
    assert tile.status.width() > 0
    assert tile.download_button.width() == pytest.approx(
        tile.status.width(), abs=8
    )


def test_a_reversed_range_is_flipped_back(app: QApplication, window) -> None:
    tile = window.download

    # Ask for 2020 → 2018; the picker quietly reorders it.
    tile.start_year.setCurrentText("2020")
    tile.end_year.setCurrentText("2018")
    app.processEvents()

    assert tile.span()[0] <= tile.span()[1]
    assert tile.start_year.currentText() == "2018"
    assert tile.end_year.currentText() == "2020"

    # The other direction works the same way: 2018 → 2017 flips to 2017 → 2018.
    tile.end_year.setCurrentText("2017")
    app.processEvents()
    assert tile.start_year.currentText() == "2017"
    assert tile.end_year.currentText() == "2018"


def test_containers_do_not_show_the_canvas(app: QApplication, window) -> None:
    """A plain child widget must not paint the dark canvas over the card."""
    from lalala.theme import CANVAS

    tile = window.download
    image = window.grab().toImage()
    for widget in (tile.resolution,):
        y = widget.mapTo(window, widget.rect().center()).y()
        seen = {
            image.pixelColor(
                widget.mapTo(window, widget.rect().topLeft()).x() + dx, y
            ).name()
            for dx in range(4, widget.width() - 4, 7)
        }
        assert CANVAS not in seen, widget.objectName()


def test_the_actionable_button_is_the_one_that_pulses(window) -> None:
    tile = window.download

    # Missing data: Download breathes and carries the amber edge, Start does
    # not move.
    assert tile.download_button.graphicsEffect() is tile._glow_download
    assert tile._pulse_download.loopCount() == -1
    assert tile._pulse_download.state() == tile._pulse_download.State.Running
    assert tile._pulse_start.state() == tile._pulse_start.State.Stopped
    assert tile.download_button.property("attention") is True

    # A complete span: the pulse hands over to Start, Download goes quiet.
    tile.start_year.setCurrentText("2017")
    tile.end_year.setCurrentText("2017")
    tile.resolution.group.button(2).click()  # 1h
    _write_year(2017, "1h", 365 * 24)
    tile.refresh()

    assert tile._pulse_download.state() == tile._pulse_download.State.Stopped
    assert tile._glow_download.opacity() == pytest.approx(1.0)
    assert tile._pulse_start.state() == tile._pulse_start.State.Running
    assert tile.download_button.property("attention") is False
