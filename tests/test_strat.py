"""The strategy window: two halves, the right one stacked into two tiles."""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.panels import Card  # noqa: E402
from lalala.strat_tiles import FIRST_YEAR, RESOLUTIONS, DownloadTile  # noqa: E402
from lalala.strat_window import StratWindow  # noqa: E402
from lalala.theme import CANVAS, apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def window(app: QApplication, monkeypatch, tmp_path) -> StratWindow:
    # No real data directory in tests.
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "data"))
    win = StratWindow()
    win.show()
    app.processEvents()
    yield win
    win.close()


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


def test_the_right_side_stacks_two_tiles(
    app: QApplication, window
) -> None:
    column = window.right
    assert column.orientation() == Qt.Orientation.Vertical
    assert column.count() == 2
    assert column.widget(0) is window.download
    assert column.widget(1) is window.blank
    # Both are cards; the lower one is still empty.
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


def test_the_resolution_picker_is_exclusive(
    app: QApplication, window
) -> None:
    picker = window.download.resolution

    assert picker.current() == "1m"
    order = [picker.group.button(i).text() for i in range(len(picker.group.buttons()))]
    assert order == list(RESOLUTIONS)

    picker.group.button(2).click()
    app.processEvents()
    assert picker.current() == "1h"
    # Exclusive: only one pill is checked at a time.
    assert sum(b.isChecked() for b in picker.group.buttons()) == 1


def test_download_grays_out_once_the_span_is_on_disk(window) -> None:
    tile = window.download

    assert tile.download_button.isEnabled() is True

    target = tile.has_data()
    assert target is False
    # Pretend the download ran: the file for that exact span now exists.
    path = os.path.join(
        os.environ["LALALA_DATA"], f"{tile.span_name()}.parquet"
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()

    tile.refresh()
    assert tile.has_data() is True
    assert tile.download_button.isEnabled() is False

    # A different span is still downloadable.
    tile.start_year.setCurrentText(str(FIRST_YEAR + 1))
    assert tile.download_button.isEnabled() is True


def test_start_does_nothing_yet(app: QApplication, window) -> None:
    tile = window.download
    before = (tile.span(), tile.has_data())

    tile.start_button.click()
    app.processEvents()

    assert tile.start_button.isEnabled() is True
    assert (tile.span(), tile.has_data()) == before
