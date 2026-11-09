"""The strategy window: the run and its inputs on top, results across the bottom."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy  # noqa: E402

from lalala import candles  # noqa: E402
from lalala.candles import append_rows, candle_file  # noqa: E402
from lalala.panels import Card  # noqa: E402
from lalala.strat_builder import StrategyBuilderWindow  # noqa: E402
from lalala.strat_params import ParamsTile  # noqa: E402
from lalala.strat_tiles import FIRST_YEAR, RESOLUTIONS, DownloadTile  # noqa: E402
from lalala.strat_window import StratWindow  # noqa: E402
from lalala.theme import CANVAS, CARD_GAP, apply_dark_theme  # noqa: E402

# A year holds this many bars in the tests, so faking one stays cheap.
TEST_BARS_PER_YEAR = 10


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def small_year(monkeypatch, tmp_path):
    # No real candle directory, and a year that fits in a handful of rows.
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    monkeypatch.setattr(
        candles, "expected_rows", lambda year, now=None: TEST_BARS_PER_YEAR
    )
    monkeypatch.setattr(
        "lalala.strat_tiles.expected_rows",
        lambda year, now=None: TEST_BARS_PER_YEAR,
    )
    candles._ROW_CACHE.clear()


@pytest.fixture
def window(app: QApplication) -> StratWindow:
    win = StratWindow()
    win.show()
    app.processEvents()
    yield win
    win.close()


def _write(year: int, rows: int) -> None:
    append_rows(
        candle_file(year),
        [(i * 60_000, 1.0, 2.0, 0.5, 1.5, 10.0) for i in range(rows)],
    )


def _pick(tile: DownloadTile, start: int, end: int, resolution: str) -> None:
    tile.start_year.setCurrentText(str(start))
    tile.end_year.setCurrentText(str(end))
    tile.resolution.group.button(RESOLUTIONS.index(resolution)).click()


def test_the_results_span_the_bottom(app: QApplication, window) -> None:
    assert window.windowTitle() == "lalala · backtest + strategy"
    # The whole window is a vertical splitter: the run on top, results below.
    assert window.outer.orientation() == Qt.Orientation.Vertical
    assert window.outer.count() == 2
    assert window.outer.widget(0) is window.splitter
    assert window.outer.widget(1) is window.results

    # The results are as wide as the window's content area.
    app.processEvents()
    canvas = window.centralWidget()
    assert window.results.width() == pytest.approx(
        canvas.width() - 2 * CARD_GAP, abs=2
    )

    image = window.grab().toImage()
    assert not image.isNull()
    handle = window.outer.handle(1)
    gap = handle.mapTo(window, handle.rect().center())
    assert image.pixelColor(gap).name() == CANVAS


def test_the_top_row_is_the_run_and_its_inputs(app: QApplication, window) -> None:
    # The run on the left, a narrow input column on the right.
    assert window.splitter.count() == 2
    assert window.splitter.orientation() == Qt.Orientation.Horizontal
    assert window.splitter.widget(0) is window.left
    assert window.splitter.widget(1) is window.right
    app.processEvents()
    left, right = window.splitter.sizes()
    assert left > right  # the run takes the slack; the column stays narrow


def test_the_right_column_stacks_five_tiles(app: QApplication, window) -> None:
    column = window.right.layout()
    assert column.itemAt(0).widget() is window.download
    assert column.itemAt(1).widget() is window.params
    assert column.itemAt(2).widget() is window.strategy
    # Save and Load share one row.
    runs_row = column.itemAt(3).widget()
    runs = [runs_row.layout().itemAt(i).widget() for i in range(2)]
    assert runs == [window.save_run, window.load_run]
    for tile in (window.download, window.params, window.strategy, window.results):
        assert isinstance(tile, Card)


def test_the_tiles_fill_the_column_without_scrolling(
    app: QApplication, window
) -> None:
    app.processEvents()
    # The tiles share the whole column, so nothing is left over to scroll.
    tiles = (window.download, window.params, window.strategy, window.save_run)
    total = sum(tile.height() for tile in tiles) + 3 * CARD_GAP
    assert total == pytest.approx(window.right.height(), abs=12)
    assert window.results.height() > window.params.height()


def test_the_span_picker_covers_2017_to_now(app: QApplication, window) -> None:
    tile = window.download
    this_year = datetime.now(tz=timezone.utc).year

    years = [tile.start_year.itemText(i) for i in range(tile.start_year.count())]
    assert years[0] == str(FIRST_YEAR)
    assert years[-1] == str(this_year)
    assert tile.start_year.currentText() == str(FIRST_YEAR)
    assert tile.end_year.currentText() == str(this_year)
    assert tile.span() == (FIRST_YEAR, this_year, "1m")


def test_the_history_tile_starts_from_the_saved_defaults(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "backtest": {
                    "timeframe": "1h",
                    "start_year": 2021,
                    "end_year": 2022,
                }
            }
        )
    )
    monkeypatch.setenv("LALALA_SETTINGS", str(path))

    tile = DownloadTile()
    tile.show()
    app.processEvents()
    try:
        assert tile.span() == (2021, 2022, "1h")
    finally:
        tile.close()


def test_the_resolution_picker_is_exclusive(app: QApplication, window) -> None:
    picker = window.download.resolution

    assert picker.current() == "1m"
    order = [
        picker.group.button(i).text()
        for i in range(len(picker.group.buttons()))
    ]
    assert order == list(RESOLUTIONS)

    picker.group.button(RESOLUTIONS.index("1h")).click()
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
    assert tile.download_button.isEnabled() is True
    assert tile.download_button.property("attention") is True


def test_a_short_year_reads_as_partial_in_amber(window) -> None:
    tile = window.download
    _pick(tile, 2017, 2017, "1m")
    _write(2017, 4)
    tile.refresh()

    missing, partial = tile.coverage()
    assert missing == []
    assert partial == [2017]
    assert tile.status.text() == "partial 2017"
    assert tile.status.property("state") == "partial"
    assert tile.download_button.isEnabled() is True


def test_a_complete_span_grays_download_out(window) -> None:
    tile = window.download
    _pick(tile, 2017, 2017, "1h")
    _write(2017, TEST_BARS_PER_YEAR)
    tile.refresh()

    assert tile.coverage() == ([], [])
    assert tile.has_data() is True
    assert tile.status.isVisible() is False
    # Coverage is a property of the 1m store, not the picked resolution.
    assert tile.download_button.isVisible() is False


def test_the_action_row_is_start_left_download_right(
    app: QApplication, window
) -> None:
    tile = window.download
    assert tile.start_button.text() == "Start backtest"

    row = tile.body.itemAt(tile.body.count() - 1).layout()
    assert row.itemAt(0).widget() is tile.start_button
    assert row.itemAt(1).widget() is tile.download_button
    assert row.itemAt(2).widget() is tile.status
    for index in range(3):
        assert row.stretch(index) == 1


def test_only_the_relevant_button_is_shown(app: QApplication, window) -> None:
    tile = window.download

    assert tile.download_button.isVisible() is True
    assert tile.start_button.isVisible() is False

    _pick(tile, 2017, 2017, "1m")
    _write(2017, TEST_BARS_PER_YEAR)
    tile.refresh()
    app.processEvents()

    assert tile.start_button.isVisible() is True
    assert tile.download_button.isVisible() is False
    assert tile.status.isVisible() is False
    assert tile.start_button.width() > tile.width() * 0.8


def test_the_note_shares_the_row_with_download(app: QApplication, window) -> None:
    tile = window.download
    assert tile.status.isVisible() is True  # missing years in the empty store
    assert tile.start_button.isVisible() is False
    assert tile.download_button.width() == pytest.approx(
        tile.status.width(), abs=8
    )


def test_containers_do_not_show_the_canvas(app: QApplication, window) -> None:
    """A plain child widget must not paint the dark canvas over the card."""
    tile = window.download
    image = window.grab().toImage()
    widget = tile.resolution
    y = widget.mapTo(window, widget.rect().center()).y()
    seen = {
        image.pixelColor(
            widget.mapTo(window, widget.rect().topLeft()).x() + dx, y
        ).name()
        for dx in range(4, widget.width() - 4, 7)
    }
    assert CANVAS not in seen


def test_the_actionable_button_is_the_one_that_pulses(window) -> None:
    tile = window.download

    assert tile.download_button.graphicsEffect() is tile._glow_download
    assert tile._pulse_download.loopCount() == -1
    assert tile._pulse_download.state() == tile._pulse_download.State.Running
    assert tile._pulse_start.state() == tile._pulse_start.State.Stopped

    _pick(tile, 2017, 2017, "1m")
    _write(2017, TEST_BARS_PER_YEAR)
    tile.refresh()

    assert tile._pulse_download.state() == tile._pulse_download.State.Stopped
    assert tile._glow_download.opacity() == pytest.approx(1.0)
    assert tile._pulse_start.state() == tile._pulse_start.State.Running


def test_a_reversed_range_is_flipped_back(app: QApplication, window) -> None:
    tile = window.download

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


# -- downloading -----------------------------------------------------------

def test_download_asks_only_for_the_years_that_are_short(
    app: QApplication, window, monkeypatch
) -> None:
    tile = window.download
    asked: list[list[int]] = []
    monkeypatch.setattr(
        tile.downloader, "start", lambda years: asked.append(years) or True
    )

    _pick(tile, 2017, 2018, "1m")
    _write(2017, TEST_BARS_PER_YEAR)  # complete; only 2018 is needed
    tile.refresh()
    tile.download_button.click()
    app.processEvents()

    assert asked == [[2018]]
    assert "downloading 2018" in tile.status.text()
    assert tile.download_button.isEnabled() is False


def test_progress_reads_as_a_percentage(app: QApplication, window, monkeypatch) -> None:
    tile = window.download
    monkeypatch.setattr(tile.downloader, "start", lambda years: True)

    tile.download_button.click()
    tile._on_progress(2017, TEST_BARS_PER_YEAR // 2)
    assert tile.status.text() == "downloading 2017… 50%"


def test_finishing_swaps_the_button_to_start(
    app: QApplication, window, monkeypatch
) -> None:
    tile = window.download
    monkeypatch.setattr(tile.downloader, "start", lambda years: True)

    tile.download_button.click()
    _write(2017, TEST_BARS_PER_YEAR)
    tile._on_finished()
    app.processEvents()

    assert tile.has_data() is False  # the default span still misses years
    # Narrow the span to the one that is complete; Start takes over.
    _pick(tile, 2017, 2017, "1m")
    assert tile.start_button.isVisible() is True


def test_the_strategy_picker_lists_the_rules(app: QApplication, window) -> None:
    from lalala.strat_playback import DEFAULT_STRATEGY, STRATEGIES

    tile = window.strategy
    labels = [tile.picker.itemText(i) for i in range(tile.picker.count())]

    assert labels == [label for _, label, _ in STRATEGIES]
    assert tile.rule() == DEFAULT_STRATEGY

    tile.set_rule("random")
    app.processEvents()
    assert tile.rule() == "random"
    assert "coin flip" in tile.note.text()


def test_the_strategy_tile_lists_saved_strategies(
    app: QApplication, window, monkeypatch, tmp_path
) -> None:
    import json


    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))
    (tmp_path / "strategies.json").write_text(
        json.dumps(
            [
                {
                    "name": "Edge",
                    "timeframe": "1m",
                    "entry": "close < sma(close, 5)",
                    "exit": "pnl >= tp",
                }
            ]
        )
    )
    tile = window.strategy
    tile.refresh_saved()
    assert tile.picker.findText("Edge") >= 0

    # Picking it points the run at its entry rule.
    tile.picker.setCurrentText("Edge")
    app.processEvents()
    assert window.left.rule_key() == "saved"
    assert window.left.saved_entry() == "close < sma(close, 5)"


def test_a_run_saves_and_reloads(app: QApplication, window, monkeypatch, tmp_path) -> None:
    from lalala import runs

    monkeypatch.setenv("LALALA_RUNS", str(tmp_path / "runs.json"))
    window.left.set_source([], "1m")
    window.left.restart()
    window.left.pause()
    session = window.left.session
    while not session.strategy.done:
        session.advance()
    window.left._refresh_metrics()

    window.save_run.name.setText("my run")
    window.save_run.save_requested.emit("my run")
    app.processEvents()
    assert runs.get("my run") is not None
    assert window.load_run.picker.findText("my run") >= 0

    window.load_run.load_requested.emit("my run")
    app.processEvents()
    assert window.left.session is not None
    # A loaded run is shown whole: walked to the end, results and all.
    assert window.left.playback.done is True
    assert window.left.playing() is False
    assert window.left.session.strategy.trades > 0


def test_the_create_strategy_button_is_a_placeholder(
    app: QApplication, window
) -> None:
    tile = window.strategy

    assert tile.create_button.text() == "Create a strategy"
    assert tile.create_button.isEnabled() is True
    # Tall enough to read as the tile's main action, and inert on purpose.
    assert tile.create_button.minimumHeight() >= 30

    before = tile.rule()
    tile.create_button.click()
    app.processEvents()
    # Nothing opens, and the run is untouched: the builder is not connected.
    assert tile.rule() == before
    assert not any(
        child.isWindow() and child.isVisible()
        for child in window.findChildren(StrategyBuilderWindow)
    )


def test_a_strategy_change_waits_for_the_button(
    app: QApplication, window
) -> None:
    playback = window.left
    playback.run_button.click()
    app.processEvents()
    for _ in range(5):
        playback.playback.advance()
    index = playback.playback.index

    window.strategy.set_rule("random")
    app.processEvents()
    # Remembered, not applied.
    assert playback.playback.index == index
    assert playback.playback.rule != "random"

    window.left.restart_button.click()
    app.processEvents()
    assert playback.playback.index == 0
    assert playback.playback.rule == "random"


def test_opening_the_window_starts_no_run(app: QApplication, window) -> None:
    assert window.left.playing() is False
    assert window.left.playback.recent() == []
    assert window.left.playback.total == 0
    assert "idle" in window.left.note.text()
    assert window.left.run_button.text() == "Run"


def test_starting_a_run_and_restarting_it(app: QApplication, window) -> None:
    """Only a button press restarts the walk: the span cannot do it."""
    playback = window.left

    playback.run_button.click()
    app.processEvents()
    assert playback.playing() is True
    assert playback.run_button.text() == "Pause"
    for _ in range(6):
        playback.playback.advance()
    assert playback.playback.index == 6

    _pick(window.download, 2017, 2017, "1m")
    app.processEvents()
    # A span change alone leaves the walk exactly where it is…
    assert playback.playback.index == 6

    # …and either button starts it over.
    window.download.start_button.click()
    app.processEvents()
    assert playback.playback.index == 0


def test_run_becomes_pause_and_resume(app: QApplication, window) -> None:
    playback = window.left

    playback.run_button.click()
    app.processEvents()
    assert playback.playing() is True
    assert playback.run_button.text() == "Pause"

    playback.run_button.click()  # pause
    app.processEvents()
    assert playback.playing() is False
    assert playback.run_button.text() == "Resume"

    playback.run_button.click()  # resume
    app.processEvents()
    assert playback.playing() is True
    assert playback.run_button.text() == "Pause"


def test_the_header_has_restart_speed_and_a_progress_bar(
    app: QApplication, window
) -> None:
    from lalala.strat_playback import SPEEDS

    playback = window.left
    assert playback.restart_button.text() == "Restart"
    assert [
        playback.speed.itemText(i) for i in range(playback.speed.count())
    ] == list(SPEEDS)
    assert playback.speed.currentText() == SPEEDS[0]
    assert playback.progress_label.text() == "—"

    playback.run_button.click()
    app.processEvents()
    assert playback.progress.value() >= 0
    assert "candles" in playback.progress_label.text()


def test_a_failed_download_says_so(app: QApplication, window, monkeypatch) -> None:
    tile = window.download
    monkeypatch.setattr(tile.downloader, "start", lambda years: True)

    tile.download_button.click()
    tile._on_failed("HTTPStatusError: 500")

    assert "download failed" in tile.status.text()
    assert tile.download_button.isEnabled() is True


def test_the_results_switch_between_overview_and_trades(
    app: QApplication, window
) -> None:
    results = window.results
    assert results.part() == "overview"
    assert results.stack.currentIndex() == 0
    assert set(results.tab_buttons) == {"overview", "trades"}

    window.left.set_source([], "1m")
    window.left.restart()
    window.left.pause()
    session = window.left.session
    assert session is not None
    while not session.strategy.done:
        session.advance()
    window.left._refresh_metrics()
    results.refresh()

    assert session.strategy.trades > 0
    results.set_part(1)
    app.processEvents()
    assert results.stack.currentIndex() == 1
    page = results.trades_page
    assert page.table.rowCount() == min(page.SHOWN, session.strategy.trades)
    # Newest first, a Long, with a coloured PnL and an exit reason.
    assert page.table.item(0, 2).text() == "Long"
    assert page.table.item(0, 6).text() in ("TP", "SL", "Time")
    assert page.table.item(0, 5).text().startswith(("+", "−", "-"))
    # A trade is picked, so the detail panel shows it…
    assert page.detail_title.text().startswith("Trade #")
    # …and the candle chart is told which trade to bring out, and the run
    # itself does not move.
    index_before = window.left.playback.index
    page.table.selectRow(0)
    app.processEvents()
    assert window.left.player.trade is not None
    assert window.left.playback.index == index_before

    # The exit filter narrows the list.
    page.exit.setCurrentText("SL")
    app.processEvents()
    assert all(
        page.table.item(row, 6).text() == "SL"
        for row in range(page.table.rowCount())
    )


# -- backtest parameters ---------------------------------------------------


def test_the_parameters_start_from_the_settings_file(app: QApplication, window) -> None:
    from lalala.settings import Settings

    defaults = Settings.load().backtest
    tile = window.params

    assert tile.findChild(QLabel, "tileTitle").text() == "BACKTEST VALUE"
    assert tile.params() == {
        "initial_capital": defaults.initial_capital,
        "sizing": defaults.sizing,
        "position": defaults.position,
        "tp": defaults.tp,
        "sl": defaults.sl,
        "cash": defaults.cash,
        "fee": defaults.fee,
        "dynamic_tp": defaults.dynamic_tp,
        "dyn_tp_reverse": defaults.dyn_tp_reverse,
    }


def test_the_gallery_wraps_by_width(app: QApplication) -> None:
    from lalala.strat_params import (
        NARROW_COLUMNS,
        WIDE_AT,
        WIDE_COLUMNS,
    )

    # The wrapping is the tile's own, so test it on a tile of its own — in the
    # window it lives in a narrow column and never reaches its wide layout.
    tile = ParamsTile()
    tile.show()
    assert len(tile._elements) == 9

    tile.resize(WIDE_AT + 40, tile.height())
    app.processEvents()
    assert tile._columns == WIDE_COLUMNS
    assert tile._grid.getItemPosition(0)[1] == 0
    assert tile._grid.getItemPosition(4)[1] == 0  # fifth element starts row 2

    tile.resize(WIDE_AT - 40, tile.height())
    app.processEvents()
    assert tile._columns == NARROW_COLUMNS
    assert tile._grid.getItemPosition(3)[1] == 0  # fourth element starts row 2
    tile.close()


def test_the_sizing_mode_changes_what_position_means(
    app: QApplication, window
) -> None:
    from PySide6.QtGui import QValidator

    from lalala.strat_params import SIZING_LABELS

    tile = window.params
    assert tile.sizing_mode() == "balance"
    assert tile.position_element.caption.text() == "Position %"

    # Fixed dollars: the caption follows, and the cap is no longer 100.
    tile.sizing.setCurrentText(SIZING_LABELS["fixed"])
    app.processEvents()
    assert tile.sizing_mode() == "fixed"
    assert tile.position_element.caption.text() == "Position $"
    tile.position.setText("5000")
    assert tile.position.validator().validate("5000", 0)[0] == QValidator.State.Acceptable
    assert tile.params()["position"] == 5000.0

    # Back to a share of the book: 5000 is impossible, so it is clamped.
    tile.sizing.setCurrentText(SIZING_LABELS["balance"])
    app.processEvents()
    assert tile.params()["position"] == 100.0


def test_the_fields_only_take_numbers(window) -> None:
    from PySide6.QtGui import QValidator

    tile = window.params

    assert tile.cash_field.validator().validate("12.5", 0)[0] == QValidator.State.Acceptable
    # Letters never become a number.
    assert tile.cash_field.validator().validate("abc", 0)[0] != QValidator.State.Acceptable
    # A percentage cannot exceed the whole book; cash is an amount, so it can.
    assert tile.sl_field.validator().validate("120", 0)[0] != QValidator.State.Acceptable
    assert tile.cash_field.validator().validate("120", 0)[0] == QValidator.State.Acceptable


def test_the_dynamic_switch_is_clickable_anywhere_in_its_cell(window) -> None:
    tile = window.params
    checkbox = tile.dynamic_tp

    # A wide hit area, so the caption above can name it and the box is obvious.
    assert checkbox.text() == "Enabled"
    assert checkbox.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding

    # Clicking the middle of the cell toggles it, not just the little box.
    from PySide6.QtTest import QTest

    QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=checkbox.rect().center())
    assert checkbox.isChecked() is True
    assert tile.reverse_element.isEnabled() is True


def test_the_reverse_field_follows_the_dynamic_switch(window) -> None:
    tile = window.params

    assert tile.dynamic_tp.isChecked() is False
    assert tile.reverse_element.isEnabled() is False

    tile.dynamic_tp.setChecked(True)
    assert tile.reverse_element.isEnabled() is True
    assert tile.params()["dynamic_tp"] is True
    assert tile.params()["dyn_tp_reverse"] == 0.5


def test_every_input_marks_the_tile_changed(window) -> None:
    # The run reads the tile's values only when `changed` fires; a field that
    # stays silent leaves the run pointed at a stale value.
    tile = window.params
    seen = []
    tile.changed.connect(lambda: seen.append(1))

    tile.fee_field.setText("0.5")
    assert len(seen) == 1

    tile.reverse_field.setText("3")
    assert len(seen) == 2

    tile.dynamic_tp.setChecked(True)
    assert len(seen) == 3

