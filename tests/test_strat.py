"""The strategy window: the run and its inputs on top, results across the bottom."""

from __future__ import annotations

import time
import json
import os
from datetime import datetime, UTC

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy  # noqa: E402

from bi_trading.data import candles  # noqa: E402
from bi_trading.data.candles import append_rows, candle_file  # noqa: E402
from bi_trading.ui.panels import Card  # noqa: E402
from bi_trading.ui.strat.strat_builder import StrategyBuilderWindow  # noqa: E402
from bi_trading.ui.strat.strat_params import ParamsTile  # noqa: E402
from bi_trading.ui.strat.strat_tiles import FIRST_YEAR, RESOLUTIONS, DownloadTile  # noqa: E402
from bi_trading.ui.strat.strat_window import StratWindow  # noqa: E402
from bi_trading.ui.theme import CANVAS, CARD_GAP, apply_dark_theme  # noqa: E402

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
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path / "candles"))
    monkeypatch.setattr(
        candles, "expected_rows", lambda year, now=None: TEST_BARS_PER_YEAR
    )
    monkeypatch.setattr(
        "bi_trading.ui.strat.strat_tiles.expected_rows",
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
    assert window.windowTitle() == "bi-trading · backtest + strategy"
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
    assert window.splitter.widget(1) is window.column_scroll
    assert window.column_scroll.widget() is window.right
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
    this_year = datetime.now(tz=UTC).year

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
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(path))

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
    from bi_trading.ui.strat.strat_playback import DEFAULT_STRATEGY, STRATEGIES

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


    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
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
    from bi_trading.state import runs

    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
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
    deadline = time.time() + 10  # the walk may land from its worker thread
    while not window.left.playback.done and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
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
    from bi_trading.ui.strat.strat_playback import SPEEDS

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
    assert set(results.tab_buttons) == {"overview", "trades", "compare"}

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
    from bi_trading.state.settings import Settings

    defaults = Settings.load().backtest
    tile = window.params

    # A Polymarket run bets, a Hyperliquid one holds a position.
    assert tile.findChild(QLabel, "tileTitle").text() == "BET VALUE"
    assert tile.params() == {
        "initial_capital": defaults.initial_capital,
        "sizing": defaults.sizing,
        "position": defaults.position,
        "tp": defaults.tp,
        "sl": defaults.sl,
        "cash": defaults.cash,
        "hold": defaults.hold,
        "warmup": defaults.warmup,
        "slippage": defaults.slippage,
        "fee": defaults.fee,
        "dynamic_tp": defaults.dynamic_tp,
        "dyn_tp_reverse": defaults.dyn_tp_reverse,
        "venue": "Custom",
    }


def test_the_gallery_wraps_by_width(app: QApplication) -> None:
    from bi_trading.ui.strat.strat_params import (
        NARROW_COLUMNS,
        WIDE_AT,
        WIDE_COLUMNS,
    )

    # The wrapping is the tile's own, so test it on a tile of its own — in the
    # window it lives in a narrow column and never reaches its wide layout.
    tile = ParamsTile()
    tile.show()
    assert len(tile._elements) == 12

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

    from bi_trading.ui.strat.strat_params import SIZING_LABELS

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



def test_a_run_keeps_its_exit_rule_and_side(
    app: QApplication, window, monkeypatch, tmp_path
) -> None:
    from bi_trading.state import runs

    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    window.left.set_source([], "1m")
    assert window.left.set_saved_strategy(
        "Fade", "close > sma(close, 5)", None, "pnl >= 0.5 or pnl <= -0.5", "short"
    )
    window.left.restart()
    window.left.finish(wait=True)

    window.save_run.save_requested.emit("fade run")
    app.processEvents()

    saved = runs.get("fade run")
    assert saved.strategy == "Fade"
    assert saved.exit == "pnl >= 0.5 or pnl <= -0.5"
    assert saved.side == "short"
    assert len(saved.trades) == window.left.playback.trades
    assert len(saved.strategy_curve) > 0

    # Loading it points the run at the same strategy again.
    window.left.set_strategy("bollinger")
    window.load_run.load_requested.emit("fade run")
    app.processEvents()
    assert window.left.saved_exit() == "pnl >= 0.5 or pnl <= -0.5"
    assert window.left.side() == "short"
    assert window.left.saved_name() == "Fade"


def test_loading_a_run_shows_its_stored_trades_without_walking(
    app: QApplication, window, monkeypatch, tmp_path
) -> None:
    from bi_trading.engine import core
    from bi_trading.state import runs

    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    window.left.set_source([], "1m")
    window.left.restart()
    window.left.finish(wait=True)
    kept = window.left.playback.trades
    assert kept > 0
    window.save_run.save_requested.emit("stored")
    app.processEvents()

    def no_walk(*args, **kwargs):
        raise AssertionError("a saved run must not be walked again")

    monkeypatch.setattr(core, "walk", no_walk)
    window.load_run.load_requested.emit("stored")
    app.processEvents()

    assert window.left.playback.done is True
    assert window.left.playback.trades == kept
    assert window.left.session.strategy_curve == pytest.approx(
        runs.get("stored").strategy_curve
    )


def test_picking_a_venue_fills_its_costs_and_typing_leaves_custom(
    app: QApplication, window
) -> None:
    tile = window.params
    tile.venue.setCurrentText("Hyperliquid")
    assert tile.fee_field.text() == "0.045"
    assert tile.slippage_field.text() == "0.01"
    assert tile.params()["fee"] == 0.045
    assert tile.params()["venue"] == "Hyperliquid"

    tile.fee_field.setText("0.1")
    assert tile.venue.currentText() == "Custom"

    # A saved run's costs come back as typed, and name the venue they match.
    tile.set_params({"fee": 0.0, "slippage": 0.0})
    assert tile.venue.currentText() == "Polymarket"
    assert tile.fee_field.text() == "0"


# -- overlaying a saved run ---------------------------------------------------


def _saved_run(window, app, monkeypatch, tmp_path, name: str) -> None:
    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    window.left.set_source([], "1m")
    window.left.restart()
    window.left.finish(wait=True)
    window.save_run.save_requested.emit(name)
    app.processEvents()


def test_a_saved_runs_curve_can_be_laid_over_the_current_one(
    app: QApplication, window, monkeypatch, tmp_path
) -> None:
    from bi_trading.state import runs

    _saved_run(window, app, monkeypatch, tmp_path, "first")
    stored = runs.read_curves("first")[0]
    assert window.results.curve.overlay == []
    assert window.results.legend["overlay"].isHidden() is True

    window.load_run.picker.setCurrentText("first")
    window.load_run.overlay_button.setChecked(True)

    overlay = window.results.curve.overlay
    assert len(overlay) == len(stored)
    assert overlay[0] == 0.0                                # a return from its start
    assert overlay[-1] == pytest.approx((stored[-1] / stored[0] - 1.0) * 100.0)
    assert window.results.legend["overlay"].isHidden() is False
    assert "overlay: first" in window.results.legend["overlay"].text()
    assert window.load_run.overlay_button.text() == "Remove overlay"

    window.load_run.overlay_button.setChecked(False)
    assert window.results.curve.overlay == []
    assert window.results.legend["overlay"].isHidden() is True
    assert window.load_run.overlay_button.text() == "Overlay"


def test_picking_another_run_moves_the_overlay(
    app: QApplication, window, monkeypatch, tmp_path
) -> None:
    _saved_run(window, app, monkeypatch, tmp_path, "alpha")
    window.save_run.save_requested.emit("beta")
    app.processEvents()
    window.load_run.picker.setCurrentText("alpha")
    window.load_run.overlay_button.setChecked(True)
    assert "alpha" in window.results.legend["overlay"].text()

    window.load_run.picker.setCurrentText("beta")
    assert "beta" in window.results.legend["overlay"].text()


def test_a_run_with_no_stored_curve_says_so_instead_of_overlaying(
    app: QApplication, window, monkeypatch, tmp_path
) -> None:
    from bi_trading.state import runs

    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    runs.save(runs.SavedRun(name="bare"))                  # no trades, no curves
    window.load_run.refresh()
    window.load_run.picker.setCurrentText("bare")

    window.load_run.overlay_button.setChecked(True)
    assert window.results.curve.overlay == []
    assert "no stored curve" in window.load_run.note.text()


def test_the_overlay_widens_the_scale_and_is_resampled() -> None:
    from bi_trading.ui.strat.strat_results import _resample

    assert _resample([1.0, 2.0, 3.0], 10) == [1.0, 2.0, 3.0]    # short: untouched
    long = [float(i) for i in range(1_000)]
    cut = _resample(long, 100)
    assert len(cut) == 100 and cut[0] == 0.0 and cut[-1] == 999.0


# -- keyboard shortcuts -------------------------------------------------------


def _press(window, key) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    window.keyPressEvent(event)


def test_space_runs_pauses_and_resumes(app: QApplication, window) -> None:
    window.left.set_source([], "1m")
    assert window.left.playing() is False

    _press(window, Qt.Key.Key_Space)             # the first press starts the walk
    assert window.left.playing() is True
    assert window.left.run_button.text() == "Pause"

    _press(window, Qt.Key.Key_Space)
    assert window.left.playing() is False
    assert window.left.run_button.text() == "Resume"

    _press(window, Qt.Key.Key_Space)
    assert window.left.playing() is True
    window.left.pause()


def test_r_restarts_the_walk(app: QApplication, window) -> None:
    window.left.set_source([], "1m")
    window.left.restart()
    window.left.pause()
    for _ in range(20):
        window.left.session.advance()
    assert window.left.playback.index > 0

    _press(window, Qt.Key.Key_R)
    assert window.left.playback.index < 20       # started over
    window.left.pause()


@pytest.mark.parametrize(("key", "resolution"), [
    (Qt.Key.Key_1, "1m"), (Qt.Key.Key_2, "3m"), (Qt.Key.Key_3, "5m"),
    (Qt.Key.Key_4, "15m"), (Qt.Key.Key_5, "30m"), (Qt.Key.Key_6, "1h"),
])
def test_digits_pick_the_resolution(app: QApplication, window, key, resolution) -> None:
    _press(window, key)
    assert window.download.span()[2] == resolution


def test_a_digit_typed_into_a_field_does_not_change_the_resolution(
    app: QApplication, window
) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    window.show()
    window.params.tp_field.setFocus()
    before = window.download.span()[2]
    # A focused line edit takes the key itself; it never reaches the window.
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_5, Qt.KeyboardModifier.NoModifier, "5")
    window.params.tp_field.keyPressEvent(event)
    assert event.isAccepted()
    assert window.download.span()[2] == before


def test_a_modified_key_is_left_alone(app: QApplication, window) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    before = window.download.span()[2]
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_5, Qt.KeyboardModifier.ControlModifier)
    window.keyPressEvent(event)
    assert window.download.span()[2] == before
    assert window.left.playing() is False


def test_the_buttons_say_their_keys(app: QApplication, window) -> None:
    assert "Space" in window.left.run_button.toolTip()
    assert "(R)" in window.left.restart_button.toolTip()
    assert "1-6" in window.download.resolution.toolTip()


def test_a_short_window_scrolls_the_column_instead_of_squeezing_it(
    app: QApplication, window
) -> None:
    window.resize(1180, 700)
    window.show()
    app.processEvents()
    # The row is shorter than the tiles need, so the column keeps its height…
    assert window.column_scroll.height() < window.right.height()
    assert window.right.height() >= window.right.minimumSizeHint().height()
    # …and no tile is squeezed under what its own contents need.
    for tile in (window.download, window.params, window.strategy):
        assert tile.height() >= tile.minimumSizeHint().height()
    assert window.column_scroll.verticalScrollBar().maximum() > 0


# -- more figures, the CSV, the candle strip and Compare ----------------------


def _finished(app: QApplication, window, years=None):
    window.left.set_source(years or [], "1m")
    window.left.restart(autoplay=False)
    window.left.finish(wait=True)
    window.results.refresh()
    app.processEvents()
    return window.left.session


def test_the_overview_shows_what_a_trade_is_worth(app: QApplication, window) -> None:
    from bi_trading.engine.stats import trade_stats

    session = _finished(app, window)
    assert session.strategy.trades > 0
    stats = trade_stats(session.strategy.trades_log, session.total)
    metrics = window.results.metrics
    assert metrics["expectancy"].text().startswith(f"{stats.expectancy * 100:+,.2f}%")
    assert metrics["hold"].text() == f"{stats.average_hold:,.1f} bars"
    assert metrics["exposure"].text() == f"{stats.exposure * 100:,.0f}%"
    assert metrics["pf"].text() != "—" or stats.profit_factor is None
    assert metrics["expectancy"].toolTip()


def test_the_trades_export_to_a_csv(app: QApplication, window, tmp_path) -> None:
    import csv

    session = _finished(app, window)
    page = window.results.trades_page
    path = tmp_path / "out.csv"

    written = page.export_csv(str(path))

    # Every trade of the run, not only the newest the table shows.
    assert written == session.strategy.trades > 0
    with open(path, newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "entry_time" and len(rows) == written + 1
    assert "written" in page.count.text()


def test_there_is_nothing_to_export_before_a_run(app: QApplication, window, tmp_path) -> None:
    assert window.results.trades_page.export_csv(str(tmp_path / "x.csv")) == 0
    assert not (tmp_path / "x.csv").exists()


def test_a_picked_trade_shows_its_real_candles(app: QApplication, window) -> None:
    import random as dice

    rng = dice.Random(3)
    price, rows = 100.0, []
    for index in range(600):
        price *= 1.0 + rng.uniform(-0.01, 0.01)
        rows.append((index * 60_000, price, price * 1.004, price * 0.996, price, 1.0))
    append_rows(candle_file(2021), rows)
    # (the 2021 file's own stamps are in January 1970: read by year of the stamp)
    window.left.set_source([1970], "1m")
    append_rows(candle_file(1970), rows)
    window.left.restart(autoplay=False)
    window.left.finish(wait=True)
    window.results.refresh()
    window.results.set_part(1)
    app.processEvents()

    page = window.results.trades_page
    assert page.trades, "the run made no trades"
    page._show_detail()
    assert len(page.spark._bars) >= 2           # candles, not just a line
    trade = page.spark._trade
    assert page.spark._bars[0].stamp <= trade["in_stamp"]
    assert page.spark._bars[-1].stamp >= trade["out_stamp"]
    assert not page.spark.grab().toImage().isNull()


def test_a_sample_run_falls_back_to_the_line(app: QApplication, window) -> None:
    _finished(app, window)                      # nothing on disk: the sample run
    window.results.set_part(1)
    app.processEvents()
    page = window.results.trades_page
    page._show_detail()
    assert page.spark._bars == []
    assert not page.spark.grab().toImage().isNull()


def test_compare_gets_the_rule_and_the_last_bars(app: QApplication, window) -> None:
    window.left.set_strategy("bollinger")
    session = _finished(app, window)
    window.results.set_part(2)
    app.processEvents()

    compare = window.results.compare
    assert window.results.part() == "compare"
    assert compare.entry is not None and compare.report is not None
    assert 0 < len(compare.bars) <= window.COMPARE_BARS
    assert len(compare.bars) == min(window.COMPARE_BARS, session.total)
    assert window.results.compare_hint.isHidden()


def test_compare_says_so_without_an_entry_rule(app: QApplication, window) -> None:
    window.left.set_strategy("random")
    _finished(app, window)
    window.results.set_part(2)
    app.processEvents()
    assert window.results.compare.entry is None
    assert not window.results.compare_hint.isHidden()


# -- renaming a run, editing a rule, the Create button -------------------------


def test_a_run_is_renamed_from_its_tile(app: QApplication, window, tmp_path, monkeypatch) -> None:
    from bi_trading.state import runs

    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    runs.save(runs.SavedRun(name="first", years=[2020]))
    runs.save(runs.SavedRun(name="second", years=[2020]))
    tile = window.load_run
    tile.refresh()
    tile.picker.setCurrentText("first")
    seen: list[tuple[str, str]] = []
    tile.renamed.connect(lambda old, new: seen.append((old, new)))

    assert tile.rename_to("  renamed ") is True
    assert seen == [("first", "renamed")]
    assert tile.picker.currentText() == "renamed"
    assert [item.name for item in runs.load()] == ["second", "renamed"]

    assert tile.rename_to("second") is False                 # taken: the tile says so
    assert "already a run" in tile.note.text()
    assert tile.picker.currentText() == "renamed"


def test_the_save_tile_follows_a_renamed_run(app: QApplication, window, tmp_path, monkeypatch) -> None:
    from bi_trading.state import runs

    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    runs.save(runs.SavedRun(name="mine", years=[2020]))
    window.save_run.set_saved("mine")
    window.load_run.refresh()
    window.load_run.picker.setCurrentText("mine")
    window.load_run.rename_to("yours")
    assert window.save_run.name.text() == "yours"


def _saved_strategy(tmp_path, monkeypatch):
    from bi_trading.state import strategies

    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    strategies.save(strategies.SavedStrategy(
        "Dip", "1m", "close < sma(close, 20)", "pnl >= tp",
    ))


def test_a_saved_strategys_rules_are_edited_in_the_backtest_window(
    app: QApplication, window, tmp_path, monkeypatch
) -> None:
    from bi_trading.state import strategies

    _saved_strategy(tmp_path, monkeypatch)
    tile = window.strategy
    tile.refresh_saved()
    assert tile.edit_button.isEnabled() is False             # a built-in is on show
    tile.picker.setCurrentText("Dip")
    assert tile.edit_button.isEnabled() is True
    picked: list = []
    tile.saved_picked.connect(picked.append)

    updated = tile.save_rules("close < sma(close, 50)", "pnl >= tp or bars >= 9")

    assert updated.entry == "close < sma(close, 50)"
    (kept,) = strategies.load()
    assert (kept.name, kept.entry, kept.exit) == ("Dip", "close < sma(close, 50)", "pnl >= tp or bars >= 9")
    assert picked and picked[-1].entry == "close < sma(close, 50)"   # the run points at it
    assert tile.picker.currentText() == "Dip"


def test_the_rule_dialog_names_a_typo_and_will_not_save_it(app: QApplication) -> None:
    from bi_trading.ui.strat.rule_edit import RuleEditDialog

    dialog = RuleEditDialog("Dip", "close < sma(close, 20)", "pnl >= tp")
    assert dialog.save_button.isEnabled() and "valid" in dialog.entry_status.text()
    dialog.entry_edit.setPlainText("clsoe < 1")
    assert not dialog.save_button.isEnabled()
    assert "unknown name 'clsoe'" in dialog.entry_status.text()
    dialog.entry_edit.setPlainText("close < 1")
    dialog.exit_edit.setPlainText("pnl >= nope")
    assert not dialog.save_button.isEnabled()
    dialog.exit_edit.setPlainText("")                         # no exit rule is allowed
    assert dialog.save_button.isEnabled()
    dialog.entry_edit.setPlainText("")                        # an entry rule is not optional
    assert not dialog.save_button.isEnabled()
    assert dialog.entry() == ""


def test_the_create_button_opens_the_builder(app: QApplication, window, monkeypatch) -> None:
    opened: list[bool] = []
    monkeypatch.setattr(type(window), "open_builder", lambda self: opened.append(True))
    window.strategy.create_button.click()
    assert opened == [True]


def test_the_hub_sends_create_to_its_own_builder_view(app: QApplication, monkeypatch, tmp_path) -> None:
    from bi_trading.ui.hub.main_hub import MainHubWindow

    from bi_trading.state import venue as venue_state

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(venue_state, "current", lambda: venue_state.HL)
    hub = MainHubWindow(autostart=False)
    hub._venue = venue_state.HL
    hub._open("backtest")
    app.processEvents()
    assert hub._key == "backtest"
    hub._view.strategy.create_button.click()
    app.processEvents()
    assert hub._key == "builder"                 # the hub's Builder view, not a second window
    hub.close()


# -- a strip of candles on every row of the trades table -----------------------


def _walk_on_disk(years: list[int], per_year: int = 700) -> None:
    import random as dice

    rng = dice.Random(17)
    price = 100.0
    for year in years:
        rows = []
        for index in range(per_year):
            price *= 1.0 + rng.uniform(-0.01, 0.01)
            stamp = int(datetime(year, 1, 1, tzinfo=UTC).timestamp() * 1000) + index * 60_000
            rows.append((stamp, price, price * 1.004, price * 0.996, price, 1.0))
        append_rows(candle_file(year), rows)


def test_trade_strips_are_the_trades_own_bars() -> None:
    from bi_trading.ui.strat.playback_data import trade_strips

    _walk_on_disk([2021])
    start = int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000)
    bars = candles.arrays(candle_file(2021))
    entry, exit_ = start + 100 * 60_000, start + 105 * 60_000

    (strip,) = trade_strips([2021], "1m", [(entry, exit_)], margin=2)

    assert len(strip) == 5 + 1 + 4               # bars 98..107 (the trade and two either side)
    first = 98
    assert strip[0] == (bars[1][first], bars[2][first], bars[3][first], bars[4][first])
    assert strip[-1][3] == bars[4][first + len(strip) - 1]


def test_a_long_trade_is_squeezed_to_the_limit_and_a_missing_one_is_none() -> None:
    from bi_trading.ui.strat.playback_data import trade_strips

    _walk_on_disk([2021])
    start = int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000)
    bars = candles.arrays(candle_file(2021))

    strips = trade_strips(
        [2021], "1m",
        [(start + 10 * 60_000, start + 300 * 60_000),       # 290 bars
         (start + 5 * 60_000, start + 5 * 60_000),          # a single bar
         (int(datetime(2020, 6, 1, tzinfo=UTC).timestamp() * 1000), 1)],   # a year not on disk
        limit=32,
    )
    long_strip = strips[0]
    assert long_strip is not None and len(long_strip) <= 32
    # Squeezed bars keep the first open, the extremes and the last close.
    assert long_strip[0][0] == bars[1][8]
    assert max(bar[1] for bar in long_strip) == pytest.approx(bars[2][8:304].max())
    assert min(bar[2] for bar in long_strip) == pytest.approx(bars[3][8:304].min())
    assert strips[1] is not None and len(strips[1]) >= 2     # the margin gives it neighbours
    assert strips[2] is None


def test_a_year_is_read_once_for_all_the_trades_in_it(monkeypatch) -> None:
    from bi_trading.ui.strat import playback_data

    _walk_on_disk([2021])
    playback_data._YEAR_CACHE.clear()
    reads: list[object] = []
    original = candles.arrays
    monkeypatch.setattr(candles, "arrays", lambda path: reads.append(path) or original(path))
    start = int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000)
    spans = [(start + i * 60_000, start + (i + 4) * 60_000) for i in range(0, 600, 10)]

    strips = playback_data.trade_strips([2021], "1m", spans)
    playback_data.bars_between([2021], "1m", spans[0][0], spans[0][1])

    assert all(strips) and len(reads) == 1          # sixty trades, and a picked one: one read
    _walk_on_disk([2021], 20)                         # the file changed: it is read again
    playback_data.trade_strips([2021], "1m", spans[:1])
    assert len(reads) == 2


def test_every_row_of_the_trades_table_carries_its_candles(app: QApplication, window) -> None:
    _walk_on_disk([2021], 900)
    window.left.set_source([2021], "1m")
    window.left.restart(autoplay=False)
    window.left.finish(wait=True)
    window.results.refresh()
    window.results.set_part(1)
    app.processEvents()

    page = window.results.trades_page
    assert page.table.rowCount() > 5
    from bi_trading.ui.strat.strat_results import STRIP_ROLE

    strips = [page.table.item(row, 3).data(STRIP_ROLE) for row in range(page.table.rowCount())]
    assert all(strip and len(strip) >= 2 for strip in strips)
    assert all(len(bar) == 4 for bar in strips[0])
    # A filter does not read the store again: the strips are kept.
    before = dict(page._strips)
    page.outcome.setCurrentText("win")
    app.processEvents()
    assert page._strips == before
    assert not page.table.grab().toImage().isNull()


def test_a_sample_run_has_no_strips_and_still_draws(app: QApplication, window) -> None:
    from bi_trading.ui.strat.strat_results import STRIP_ROLE

    _finished(app, window)                       # nothing on disk
    window.results.set_part(1)
    app.processEvents()
    page = window.results.trades_page
    assert page.table.rowCount() > 0
    assert page.table.item(0, 3).data(STRIP_ROLE) is None
    assert not page.table.grab().toImage().isNull()
