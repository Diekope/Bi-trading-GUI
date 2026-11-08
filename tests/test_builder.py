"""The strategy builder window: two rails, a compact STRATEGY tile, one below."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QWidget,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
)

from lalala.strat_builder import (  # noqa: E402
    COLUMN_SHARES,
    TIMEFRAMES,
    LockedHandle,
    StrategyBuilderWindow,
)
from lalala.strat_rules import RULES_MODES as ENTRY_MODES  # noqa: E402
from lalala.strat_saved import StrategyListTile  # noqa: E402
from lalala.strategies import SavedStrategy  # noqa: E402
from lalala.theme import CANVAS, CARD_GAP, apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """An empty candle store, so no test reads a developer's real history."""
    from lalala import candles

    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()


def _write_candles(year: int, count: int) -> None:
    """A little history for the report to read."""
    from lalala import candles
    from lalala.candles import append_rows, candle_file

    rows = []
    for index in range(count):
        price = 100.0 + (index % 20)
        rows.append((index * 60_000, price, price + 1, price - 1, price, 1.0))
    append_rows(candle_file(year), rows)
    candles._ROW_CACHE.clear()


@pytest.fixture
def builder(app: QApplication) -> StrategyBuilderWindow:
    window = StrategyBuilderWindow()
    window.show()
    # Two passes: the first lays the columns out, the second settles the
    # middle column now that the entry tile knows how tall it wants to be.
    for _ in range(3):
        app.processEvents()
    yield window
    window.close()


def _shares(window: StrategyBuilderWindow) -> list[float]:
    left, middle, right = window.splitter.sizes()
    total = left + middle + right
    return [left / total, middle / total, right / total]


def test_it_is_a_window_of_its_own(builder: StrategyBuilderWindow) -> None:
    assert builder.windowTitle() == "lalala · create a strategy"
    assert builder.isWindow() is True
    assert builder.isVisible() is True
    # Wide enough for three columns without the 21% rail collapsing.
    assert builder.minimumWidth() >= 560
    assert builder.minimumHeight() >= 380


def test_the_window_holds_the_rail_and_the_rest(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    splitter = builder.splitter

    # A narrow rail on the left, everything else on the right.
    assert splitter.count() == 2
    assert splitter.orientation() == Qt.Orientation.Horizontal
    assert splitter.handleWidth() == CARD_GAP
    assert splitter.childrenCollapsible() is False
    assert splitter.widget(0) is builder.left_column
    assert splitter.widget(1) is builder.right_column


def test_the_naming_tile_sits_on_the_rail_over_the_saved_list(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    rail = builder.left_column

    assert rail.count() == 2
    assert rail.orientation() == Qt.Orientation.Vertical
    assert rail.widget(0) is builder.strategy_tile
    assert rail.widget(1) is builder.left
    assert isinstance(builder.left, StrategyListTile)
    assert (
        builder.left.geometry().top()
        - builder.strategy_tile.geometry().bottom()
        - 1
    ) == pytest.approx(CARD_GAP, abs=1)


def test_the_rules_got_the_upper_part_and_the_report_the_rest(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    column = builder.right_column

    # One rules tile on top, the report under it.
    assert column.count() == 2
    assert column.orientation() == Qt.Orientation.Vertical
    assert column.widget(0) is builder.rules
    assert column.widget(1) is builder.report

    # The switcher holds both rules but shows one at a time.
    assert builder.rules.stack.count() == 2
    assert builder.rules.stack.widget(0) is builder.entry_tile
    assert builder.rules.stack.widget(1) is builder.exit_tile
    assert builder.rules.stack.currentWidget() is builder.entry_tile

    # The report is under the rules, not beside them.
    assert builder.report.geometry().top() > builder.rules.geometry().bottom()
    assert (
        builder.report.geometry().top()
        - builder.rules.geometry().bottom()
        - 1
    ) == pytest.approx(CARD_GAP, abs=1)


def test_the_rule_titles_switch_between_the_two_tiles(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    assert [button.text() for button in builder.rules.side_buttons.values()] == [
        "ENTRY RULES",
        "EXIT RULES",
    ]
    for button in builder.rules.side_buttons.values():
        assert button.objectName() == "sideButton"
        assert button.isCheckable() is True
    assert builder.rules.side_buttons["entry"].isChecked() is True

    # The inner tiles keep their titles, but do not draw them: the switch is
    # the title now.
    assert builder.entry_tile.title.text() == "ENTRY RULES"
    assert builder.exit_tile.title.text() == "EXIT RULES"
    assert builder.entry_tile.title.isHidden() is True
    assert builder.exit_tile.title.isHidden() is True

    # Choosing the exit title shows that tile, and the pills follow its mode.
    builder.exit_tile.set_mode("code")
    builder.rules.side_buttons["exit"].click()
    app.processEvents()
    assert builder.rules.stack.currentWidget() is builder.exit_tile
    assert builder.rules.mode_buttons["code"].isChecked() is True

    builder.rules.side_buttons["entry"].click()
    app.processEvents()
    assert builder.rules.stack.currentWidget() is builder.entry_tile
    assert builder.rules.mode_buttons["rules"].isChecked() is True


def test_the_naming_tile_is_small_on_the_rail(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    tile = builder.strategy_tile

    assert [label.text() for label in tile.findChildren(QLabel)] == ["STRATEGY"]
    assert tile.findChildren(QLabel)[0].objectName() == "tileTitle"

    # Only as tall as its title and row, and it spans the rail's width.
    top, below = builder.left_column.sizes()
    assert top == pytest.approx(tile.sizeHint().height(), abs=2)
    assert below > 0
    assert tile.width() == pytest.approx(builder.left_column.width() - 2, abs=2)


def test_the_name_and_the_timeframe_share_the_strategy_tile(
    builder: StrategyBuilderWindow
) -> None:
    tile = builder.strategy_tile
    edit = builder.name_edit
    picker = builder.timeframe

    assert tile.isAncestorOf(edit)
    assert tile.isAncestorOf(picker)
    # One row: the name takes the slack, the timeframe keeps its own width,
    # and they sit at the same height.
    assert edit.geometry().top() == pytest.approx(picker.geometry().top(), abs=2)
    assert edit.geometry().left() < picker.geometry().left()
    # The name takes the slack; on the narrow rail that is still the wider one.
    assert edit.width() > picker.width()

    # Scoped to this tile: the name and the timeframe are here and nowhere
    # else, on either of the rules tiles.
    for tile in (builder.entry_tile, builder.exit_tile):
        assert tile.findChild(QLineEdit, "strategyName") is None
        assert tile.findChild(QComboBox, "strategyTimeframe") is None


def test_the_name_is_a_text_field(builder: StrategyBuilderWindow) -> None:
    edit = builder.name_edit

    assert edit.placeholderText() == "name"
    assert edit.text() == ""

    edit.setText("lower band dip")
    assert edit.text() == "lower band dip"


def test_the_timeframe_is_a_dropdown(builder: StrategyBuilderWindow) -> None:
    picker = builder.timeframe

    assert [picker.itemText(index) for index in range(picker.count())] == list(
        TIMEFRAMES
    )
    assert picker.currentText() == "1m"

    picker.setCurrentText("1h")
    assert picker.currentText() == "1h"


def test_the_rail_and_the_rest_split_the_width(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.splitter.setSizes(builder.column_sizes())
    app.processEvents()

    rail, rest = builder.splitter.sizes()
    total = rail + rest
    assert rail / total == pytest.approx(COLUMN_SHARES[0], abs=0.02)
    assert rest / total == pytest.approx(COLUMN_SHARES[1], abs=0.02)
    assert rest > rail


def test_the_one_rule_takes_the_whole_width(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    for width in (1100, 1500):
        builder.resize(width, 900)
        app.processEvents()
        # The visible rule fills the switcher's width; the stack does too.
        assert builder.rules.stack.width() == pytest.approx(
            builder.rules.width() - 24, abs=2
        )
        assert builder.entry_tile.width() > 0


def test_the_entry_tile_has_three_ways_to_write_a_rule(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    labels = [label for key, label in ENTRY_MODES]
    assert labels == ["Rules", "Formula", "Code"]

    buttons = builder.mode_buttons
    assert list(buttons) == [key for key, _ in ENTRY_MODES]
    assert [button.text() for button in buttons.values()] == labels
    for button in buttons.values():
        assert button.isCheckable() is True
        assert builder.entry_tile.isAncestorOf(button)

    # One at a time, and the rules page is the default.
    assert builder.entry_modes.exclusive() is True
    assert builder.entry_mode() == "rules"
    assert buttons["rules"].isChecked() is True

    picked: list[str] = []
    builder.entry_mode_changed.connect(picked.append)
    buttons["code"].click()
    app.processEvents()

    assert builder.entry_mode() == "code"
    assert buttons["code"].isChecked() is True
    assert buttons["formula"].isChecked() is False
    assert picked == ["code"]
    # Switching the mode changes nothing else yet.
    assert builder.name_edit.text() == ""


def test_the_formulas_page_builds_and_checks_a_formula(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # The tiles are the page on show.
    builder.mode_buttons["formula"].click()
    app.processEvents()

    assert builder.entry_pages.currentIndex() == 1
    assert builder.entry_tile.isAncestorOf(builder.formula)
    # Empty is not an error; there is simply no formula yet.
    assert builder.entry_formula() == ""
    assert builder.entry_formula_error() == ""
    assert builder.entry_formula_parsed() is None

    # A complete formula parses and clears the error line.
    builder.set_entry_formula("mid = sma(close, 20)\nclose < mid")
    app.processEvents()
    assert builder.entry_formula() == "mid = sma(close, 20)\nclose < mid"
    assert builder.entry_formula_error() == ""
    parsed = builder.entry_formula_parsed()
    assert parsed is not None and parsed.series_names == ("mid",)

    # A typo is reported with its place.
    builder.set_entry_formula("close < clsoe")
    app.processEvents()
    assert builder.entry_formula_error() == (
        "line 1, column 9: unknown name 'clsoe'"
    )
    assert builder.entry_formula_parsed() is None

    # Correcting it clears the error again.
    builder.set_entry_formula("close < 10")
    app.processEvents()
    assert builder.entry_formula_error() == ""
    assert builder.entry_formula_parsed() is not None


def test_building_a_formula_from_the_palette(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    from lalala.formula_builder import PALETTES

    builder.mode_buttons["formula"].click()
    app.processEvents()
    formula = builder.formula

    def item(group: str, label: str):
        for title, items in PALETTES:
            if title == group:
                for entry in items:
                    if entry.label == label:
                        return entry
        raise AssertionError(f"no palette item {group}/{label}")

    strip = formula.strips[0]
    # An indicator drops as a single tile, its numbers inside it.
    spec = item("Indicators", "SMA").call
    formula.drop_tokens(
        {
            "tokens": [],
            "call": {
                "func": spec[0],
                "series": spec[1],
                "params": list(spec[2]),
                "label": spec[3],
            },
            "from": None,
        },
        strip,
        0,
    )
    app.processEvents()

    # One chip, valid straight away, and the tile's field holds the period.
    assert len(strip.chips()) == 1
    assert [field.text() for field in strip.chips()[0].fields] == ["20"]
    assert formula.formula_text() == "sma(close, 20)"
    assert formula.error() == ""
    assert formula.parsed() is not None

    # Editing the number in the tile rewrites the formula.
    strip.chips()[0].fields[0].setText("50")
    app.processEvents()
    assert formula.formula_text() == "sma(close, 50)"


def test_the_code_page_shows_the_tiles_as_editable_code(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.mode_buttons["formula"].click()
    app.processEvents()
    # Build something with the tiles.
    builder.set_entry_formula("mid = sma(close, 20)\nclose < mid")
    app.processEvents()

    builder.mode_buttons["code"].click()
    app.processEvents()
    assert builder.entry_pages.currentIndex() == 2
    assert builder.entry_tile.isAncestorOf(builder.code_edit)
    # The code is what the tiles stand for, and it checks out.
    assert builder.code_edit.toPlainText() == "mid = sma(close, 20)\nclose < mid"
    assert builder.code_error.text() == ""

    # Typing code changes the formula, and the tiles follow.
    builder.code_edit.setPlainText("close < bollinger_lower(close, 20, 2)")
    app.processEvents()
    assert builder.entry_formula() == "close < bollinger_lower(close, 20, 2)"
    assert builder.code_error.text() == ""
    assert builder.entry_formula_parsed() is not None


def test_the_code_page_respects_the_variables(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.mode_buttons["code"].click()
    app.processEvents()

    # A name that was never defined is flagged, with its place.
    builder.code_edit.setPlainText("close < clsoe")
    app.processEvents()
    assert builder.code_error.text() == (
        "line 1, column 9: unknown name 'clsoe'"
    )
    assert builder.entry_formula_parsed() is None

    # Defining it above makes it valid; the tiles see it too.
    builder.code_edit.setPlainText("clsoe = close * 2\nclose < clsoe")
    app.processEvents()
    assert builder.code_error.text() == ""
    parsed = builder.entry_formula_parsed()
    assert parsed is not None and parsed.series_names == ("clsoe",)


def test_only_one_entry_page_shows_at_a_time(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    for key in ("rules", "formula", "code"):
        builder.mode_buttons[key].click()
        app.processEvents()
        visible = [
            index
            for index in range(builder.entry_pages.count())
            if builder.entry_pages.widget(index).isVisible()
        ]
        assert visible == [builder.entry_pages.currentIndex()]


def test_the_exit_tile_reads_the_trade_and_takes_no_indicators(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    from lalala.formula_builder import EXIT_PALETTES, PALETTES

    # Different palettes: the trade's own words, and no indicators.
    entry_groups = [title for title, _ in PALETTES]
    exit_groups = [title for title, _ in EXIT_PALETTES]
    assert "Indicators" in entry_groups
    assert "Indicators" not in exit_groups
    assert exit_groups == ["Trade", "Maths", "Logic"]
    assert list(builder.exit.formula.blocks) == ["Variables"] + exit_groups

    labels = [block.item.label for block in builder.exit.formula.blocks["Trade"]]
    assert labels == ["price", "entry", "PNL", "TP", "SL", "bars"]

    # An exit rule about the trade parses.
    builder.set_exit_formula("pnl >= tp or pnl <= 0 - sl")
    app.processEvents()
    assert builder.exit_formula_error() == ""
    parsed = builder.exit_formula_parsed()
    assert parsed is not None
    assert parsed.fields == ("price", "entry", "tp", "sl", "pnl", "bars")


def test_an_indicator_is_refused_in_the_exit_tile(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # `close` is not a word the exit rule knows.
    builder.set_exit_formula("close < 10")
    app.processEvents()
    assert "unknown name 'close'" in builder.exit_formula_error()
    assert builder.exit.parsed() is None

    # An indicator call is refused, and says why.
    builder.set_exit_formula("price < sma(price, 20)")
    app.processEvents()
    assert "not here, this rule takes no indicators" in (
        builder.exit_formula_error()
    )

    # Plain maths is still allowed.
    builder.set_exit_formula("pnl >= tp or bars > max(10, 5)")
    app.processEvents()
    assert builder.exit_formula_error() == ""
    assert builder.exit.parsed() is not None


def test_the_entry_tile_still_reads_the_bar(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # The two vocabularies do not leak into each other.
    builder.set_entry_formula("close < bollinger_lower(close, 20, 2)")
    app.processEvents()
    assert builder.entry_formula_error() == ""

    builder.set_entry_formula("pnl >= tp")
    app.processEvents()
    assert "unknown name 'pnl'" in builder.entry_formula_error()


def test_each_rule_tab_starts_with_conditions(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # The first page of both rules is the grouped condition editor.
    assert builder.entry_pages.count() == 3
    assert builder.entry_pages.widget(0) is builder.entry.conditions
    assert builder.exit.pages.widget(0) is builder.exit.conditions

    for tile in (builder.entry, builder.exit):
        page = tile.conditions
        assert len(page.groups) == 1
        assert page.groups[0].caption.text() == "GROUP 1"
        # A fresh rule holds one cell, ready to fill.
        assert len(page.groups[0].rows) == 1
        assert not page.groups[0].add_cell_button.isHidden()
        # The variables rail offers what the rule can use.
        assert page.variable_buttons

    assert "close" in builder.entry.conditions.variable_buttons
    assert "sma(close, 20)" in builder.entry.conditions.variable_buttons
    # The exit rule reads the trade, not the bar.
    assert "pnl" in builder.exit.conditions.variable_buttons
    assert "close" not in builder.exit.conditions.variable_buttons


def test_the_condition_rows_fill_the_rule(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    page = builder.entry.conditions
    row = page.groups[0].rows[0]
    row.left.setCurrentText("close")
    row.op.setCurrentText("<")
    row.right.setCurrentText("bollinger_lower(close, 20, 2)")
    app.processEvents()

    assert builder.entry_formula() == "close < bollinger_lower(close, 20, 2)"
    assert builder.entry_formula_error() == ""
    assert builder.entry_formula_parsed() is not None

    # A second group joins with AND, and its rows can be OR.
    group = page.add_group(logic="or")
    group_row = group.rows[0]
    group_row.left.setCurrentText("volume")
    group_row.op.setCurrentText(">")
    group_row.right.setCurrentText("0")
    app.processEvents()
    assert builder.entry_formula() == (
        "close < bollinger_lower(close, 20, 2) and volume > 0"
    )

    # The exit tile has its own conditions, in the trade's words.
    exit_row = builder.exit.conditions.groups[0].rows[0]
    exit_row.left.setCurrentText("pnl")
    exit_row.op.setCurrentText(">=")
    exit_row.right.setCurrentText("tp")
    app.processEvents()
    assert builder.exit_formula() == "pnl >= tp"
    assert builder.exit_formula_error() == ""
    # The entry formula is untouched.
    assert builder.entry_formula().startswith("close < bollinger_lower")


def test_typing_the_code_reaches_the_rules_and_the_report(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    calls: list[int] = []
    original = builder._sync_report
    builder._sync_report = lambda: (calls.append(1), original())[1]

    builder.entry.set_mode("code")
    builder.entry.code_edit.setPlainText("band = sma(close, 5)\nclose < band")
    app.processEvents()

    # The rows follow the code…
    assert builder.entry_formula() == "band = sma(close, 5)\nclose < band"
    page = builder.entry.conditions
    assert [row.line() for row in page.assignment_rows] == [
        "band = sma(close, 5)"
    ]
    assert page.groups[0].rows[0].right.currentText() == "band"
    # …and the window was told, so the report re-ran.
    assert calls


def test_the_report_follows_the_rules(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    from lalala import candles
    from lalala.candles import append_rows, candle_file

    # A little history for the report to read.
    rows = []
    for index in range(600):
        price = 100.0 + (index % 20)
        rows.append((index * 60_000, price, price + 1, price - 1, price, 1.0))
    append_rows(candle_file(2021), rows)
    candles._ROW_CACHE.clear()

    builder.set_entry_formula("close < sma(close, 5)")
    builder.set_exit_formula("pnl >= tp or pnl <= 0 - sl or bars >= 3")
    builder._sync_report()
    app.processEvents()

    assert builder.report.chart.report is not None
    assert "2021" in builder.report.note.text()
    assert builder.report.legend["strategy"].text().startswith("strategy ")

    # A different bar re-reads and re-runs it.
    builder.timeframe.setCurrentText("1h")
    app.processEvents()
    assert "· 1h ·" in builder.report.note.text()

    # And an empty rule clears the numbers rather than leaving them behind.
    builder.set_entry_formula("")
    app.processEvents()
    assert builder.report.chart.report is None
    assert "no entry rule yet" in builder.report.note.text()


def test_the_footer_resets_the_draft(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.name_edit.setText("Dip")
    builder.set_entry_formula("close < sma(close, 5)")
    builder.set_exit_formula("pnl >= tp")
    builder._describe_draft()
    app.processEvents()
    assert builder.draft.text() == "Dip · unsaved"

    builder.reset_button.click()
    app.processEvents()

    assert builder.name_edit.text() == ""
    assert builder.entry_formula() == ""
    assert builder.exit_formula() == ""
    assert builder.entry_mode() == "rules"
    assert builder.draft.text() == "untitled · unsaved"


def test_the_footer_saves_the_draft(
    app: QApplication,
    builder: StrategyBuilderWindow,
    tmp_path,
    monkeypatch,
) -> None:
    from lalala import strategies

    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))

    builder.name_edit.setText("Bollinger reversion")
    builder.timeframe.setCurrentText("1h")
    builder.set_entry_formula("close < bollinger_lower(close, 20, 2)")
    builder.set_exit_formula("pnl >= tp or pnl <= 0 - sl")
    app.processEvents()

    builder.save_button.click()
    app.processEvents()

    kept = strategies.load()
    assert len(kept) == 1
    assert kept[0].name == "Bollinger reversion"
    assert kept[0].timeframe == "1h"
    assert kept[0].entry == "close < bollinger_lower(close, 20, 2)"
    assert kept[0].exit == "pnl >= tp or pnl <= 0 - sl"
    assert "saved" in builder.draft.text()


def test_saving_needs_a_name_and_a_sound_rule(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.save_button.click()
    app.processEvents()
    assert "name" in builder.draft.text()

    builder.name_edit.setText("Dip")
    builder.set_entry_formula("close < clsoe")  # a name that means nothing
    app.processEvents()
    builder.save_button.click()
    app.processEvents()
    assert "fix the rules" in builder.draft.text()


def test_saving_lists_it_in_the_rail(
    app: QApplication, builder: StrategyBuilderWindow, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))
    builder.name_edit.setText("Dip")
    builder.set_entry_formula("close < sma(close, 5)")
    app.processEvents()
    assert [row.name for row in builder.left.rows] == ["Dip"]  # the draft

    builder.save_button.click()
    app.processEvents()

    # Once saved it is a kept row, still lit, and no longer a draft.
    assert [row.name for row in builder.left.rows] == ["Dip"]
    assert builder.left.rows[0].badge.text() != "draft"
    assert builder.left.rows[0].property("selected") is True


def test_clicking_a_saved_strategy_loads_it(
    app: QApplication, builder: StrategyBuilderWindow, tmp_path, monkeypatch
) -> None:
    from lalala import strategies

    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))
    strategies.save(
        SavedStrategy("Dip", "1h", "close < sma(close, 5)", "pnl >= tp")
    )
    builder._refresh_saved()
    app.processEvents()

    picked: list[str] = []
    builder.left.chosen.connect(picked.append)
    builder.left.rows[0].clicked.emit("Dip")
    app.processEvents()

    assert picked == ["Dip"]
    assert builder.name_edit.text() == "Dip"
    assert builder.timeframe.currentText() == "1h"
    assert builder.entry_formula() == "close < sma(close, 5)"
    assert builder.exit_formula() == "pnl >= tp"
    # The strategy on show is not offered again under "+ Add".
    assert builder.report.compare.selected_name == "Dip"


def test_create_a_strategy_starts_a_fresh_draft(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.name_edit.setText("Dip")
    builder.set_entry_formula("close < sma(close, 5)")
    app.processEvents()

    builder.left.create_button.click()
    app.processEvents()

    assert builder.name_edit.text() == ""
    assert builder.entry_formula() == ""
    assert builder.exit_formula() == ""


def test_a_saved_strategy_can_be_deleted_after_a_prompt(
    app: QApplication, builder: StrategyBuilderWindow, tmp_path, monkeypatch
) -> None:
    from lalala import strategies

    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))
    builder.name_edit.setText("Dip")
    builder.set_entry_formula("close < sma(close, 5)")
    app.processEvents()
    builder.save_button.click()
    app.processEvents()

    # With a saved strategy on show, the delete button is armed (red).
    assert builder.left.selected_name == "Dip"
    assert builder.delete_button.property("armed") is True

    # A cancelled prompt leaves everything as it was.
    def cancel(_dialog):
        return None

    monkeypatch.setattr(
        "lalala.strat_builder.ConfirmDialog.exec", cancel
    )
    builder.delete_button.click()
    app.processEvents()
    assert [item.name for item in strategies.load()] == ["Dip"]

    # Confirming deletes it, and the editor is cleared.
    def confirm(dialog):
        dialog.choice = "delete"
        return 1

    monkeypatch.setattr(
        "lalala.strat_builder.ConfirmDialog.exec", confirm
    )
    builder.delete_button.click()
    app.processEvents()
    assert strategies.load() == []
    assert builder.name_edit.text() == ""
    assert builder.left.selected_name is None
    assert builder.delete_button.property("armed") is False


def test_the_delete_prompt_offers_reset_or_delete(
    app: QApplication, builder: StrategyBuilderWindow, tmp_path, monkeypatch
) -> None:
    from lalala import strategies

    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "strategies.json"))
    builder.name_edit.setText("Dip")
    builder.set_entry_formula("close < sma(close, 5)")
    app.processEvents()
    builder.save_button.click()
    app.processEvents()

    # Choosing Reset clears the draft but keeps the saved strategy.
    def reset(dialog):
        dialog.choice = "reset"
        return 1

    monkeypatch.setattr("lalala.strat_builder.ConfirmDialog.exec", reset)
    builder.delete_button.click()
    app.processEvents()
    assert [item.name for item in strategies.load()] == ["Dip"]
    assert builder.name_edit.text() == ""


def test_the_code_page_has_the_vocabulary_and_the_values(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.mode_buttons["code"].click()
    app.processEvents()

    # The vocabulary names every word the rule may use.
    texts = [
        label.text()
        for label in builder.entry_tile.findChildren(QLabel)
    ]
    assert "VARIABLES" in texts and "VALUES" in texts
    assert "close" in texts and "model_p" in texts
    assert "sma()" in texts and "zscore()" in texts

    # The values beside it are the newest bar's, with the rule's verdict.
    _write_candles(2021, 200)
    builder.set_entry_formula("z = zscore(close, 20)\nz < 0 - 2 and close > 0")
    builder._sync_report()
    app.processEvents()
    values = {
        label.text()
        for label in builder.entry.code_values.findChildren(QLabel)
    }
    assert "close" in values and "z" in values
    assert "result" in values


def test_the_code_lists_scroll_in_place(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.mode_buttons["code"].click()
    app.processEvents()

    page = builder.entry.pages.currentWidget()
    lists = [
        scroll
        for scroll in page.findChildren(QScrollArea)
        if scroll.objectName() == "listScroll"
    ]
    # One scroll area for VARIABLES, one for VALUES, both inside the page.
    assert len(lists) == 2
    # The vocabulary hides its bar; the width goes to the names.
    assert (
        lists[0].verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    # They are stacked in the right rail: the vocabulary on top, the values
    # under it, both to the right of the code.
    vocab_card = lists[0].parentWidget()
    values_card = lists[1].parentWidget()
    vocab = vocab_card.geometry().translated(
        vocab_card.mapTo(page, vocab_card.rect().topLeft())
    )
    values = values_card.geometry().translated(
        values_card.mapTo(page, values_card.rect().topLeft())
    )
    assert vocab.left() == values.left()
    assert vocab.top() < values.top()
    code = builder.entry.code_edit.parentWidget()
    code_rect = code.geometry().translated(code.mapTo(page, code.rect().topLeft()))
    assert vocab.left() > code_rect.right()
    assert min(vocab.left(), values.left()) >= 0
    # The page itself no longer scrolls: the lists do, so the code stays put.
    assert page.findChild(QScrollArea, "pageScroll") is None


def test_clicking_a_variable_describes_it_on_the_right(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.mode_buttons["code"].click()
    app.processEvents()

    row = builder.entry.vocab_rows["close"]
    row.clicked.emit("close")
    app.processEvents()

    assert builder.entry.selected_variable == "close"
    assert row.property("selected") is True
    texts = [
        label.text()
        for label in builder.entry.values_card.findChildren(QLabel)
    ]
    assert "close" in texts
    assert "the bar's closing price" in texts

    # Clicking another word moves the description; clicking it again clears.
    sma = builder.entry.vocab_rows["sma()"]
    sma.clicked.emit("sma()")
    app.processEvents()
    assert builder.entry.selected_variable == "sma()"
    assert row.property("selected") is False
    texts = [
        label.text()
        for label in builder.entry.values_card.findChildren(QLabel)
    ]
    assert "simple moving average of a series over N bars" in texts
    sma.clicked.emit("sma()")
    app.processEvents()
    assert builder.entry.selected_variable is None


def test_the_live_values_reach_both_panels(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    _write_candles(2021, 200)
    builder.set_entry_formula("close > 0")
    builder._sync_report()
    app.processEvents()

    values, result = builder.report.watch
    assert values.get("close") is not None
    # The panel beside the editor has them, and so does the code tab.
    assert builder.entry.formula.values.get("close") == values["close"]
    assert builder.entry.formula.result is result


def test_the_formula_panel_scrolls_rather_than_growing_the_tile(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.resize(1000, 800)
    app.processEvents()
    builder.timeframe.setCurrentText("1h")
    builder.set_entry_formula("band = bollinger_lower(close, 20, 2)\nclose < band")
    app.processEvents()

    formula = builder.entry.formula
    # It sits in a scroll area, so the tile keeps whatever width the window
    # gives it and the panel moves under the cursor when it does not fit.
    assert formula.parentWidget().objectName() == "qt_scrollarea_viewport"
    # And it is modest enough that the tile fits the window's own minimum.
    assert formula.minimumSizeHint().width() < 620
    assert builder.minimumWidth() >= formula.minimumSizeHint().width()


def test_the_value_rows_are_not_a_different_colour(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # The rows in the vocabulary list and the values list are plain containers
    # on the card. Without a rule of their own they would paint the canvas
    # colour over it, which is what made them read darker.
    from lalala.theme import STYLESHEET

    assert "#valueRow" in STYLESHEET
    block = STYLESHEET.split("#valueRow")[1].split("}")[0]
    assert "transparent" in block

    builder.mode_buttons["code"].click()
    builder.set_entry_formula("close > 0")
    app.processEvents()
    rows = builder.entry_tile.findChildren(QWidget, "valueRow")
    assert rows, "the code page lists something"


def test_the_exit_tile_has_the_same_tabs_as_the_entry(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # Same widget, same three tabs, its own formula.
    assert builder.exit_tile is not builder.entry_tile
    assert list(builder.exit_tile.mode_buttons) == ["rules", "formula", "code"]
    assert builder.exit_mode() == "rules"

    builder.exit.set_mode("code")
    app.processEvents()
    assert builder.exit_mode() == "code"
    assert builder.exit_tile.pages.currentIndex() == 2
    assert builder.entry_mode() == "rules"  # entry untouched

    # The two formulas are independent.
    builder.set_entry_formula("close < sma(close, 20)")
    builder.set_exit_formula("pnl <= 0 - sl")
    app.processEvents()
    assert builder.entry_formula() == "close < sma(close, 20)"
    assert builder.exit_formula() == "pnl <= 0 - sl"


def test_the_columns_cannot_be_dragged(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    builder.splitter.setSizes(builder.column_sizes())
    app.processEvents()
    before = builder.splitter.sizes()

    handle = builder.splitter.handle(1)
    # The handle is the swallowing kind; Qt only starts a splitter drag on an
    # accepted press, and this one accepts nothing.
    assert isinstance(handle, LockedHandle)
    start = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(handle, start + QPoint(120, 0))
    QTest.mouseRelease(
        handle, Qt.MouseButton.LeftButton, pos=start + QPoint(120, 0)
    )

    assert builder.splitter.sizes() == before


def test_the_lateral_gaps_are_the_card_gap(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    for width in (1300, 1600):
        builder.resize(width, 940)
        app.processEvents()
        assert (
            builder.right_column.geometry().left()
            - builder.left_column.geometry().right()
            - 1
        ) == pytest.approx(CARD_GAP, abs=1)


def test_the_split_scales_with_the_window(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    for width in (1300, 1600):
        builder.resize(width, 940)
        app.processEvents()

        rail, rest = builder.splitter.sizes()
        total = rail + rest
        assert rail / total == pytest.approx(COLUMN_SHARES[0], abs=0.02)
        assert rest / total == pytest.approx(COLUMN_SHARES[1], abs=0.02)

        # The naming tile keeps its own height on the rail.
        top, below = builder.left_column.sizes()
        assert top == pytest.approx(
            builder.strategy_tile.sizeHint().height(), abs=4
        )
        assert below > 0

        # The one rule fills the width above the report.
        assert builder.rules.width() == pytest.approx(
            builder.right_column.width() - 2, abs=4
        )


def test_the_rules_fill_their_part(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.splitter.setSizes(builder.column_sizes())
    app.processEvents()

    assert builder.strategy_tile.width() == pytest.approx(
        builder.left_column.width() - 2, abs=2
    )
    for tile in (builder.entry_tile, builder.exit_tile):
        assert tile.width() > 0
        assert tile.height() > 0
    assert builder.report.width() == pytest.approx(builder.rules.width(), abs=6)
    assert (
        builder.right_column.height()
        - builder.rules.height()
        - builder.report.height()
        - CARD_GAP
    ) == pytest.approx(0, abs=4)


def test_the_report_is_not_a_rules_tile(
    builder: StrategyBuilderWindow
) -> None:
    assert builder.right is builder.right_column
    assert builder.report is not builder.entry_tile
    assert builder.report is not builder.exit_tile


def test_it_uses_the_same_desk_as_the_other_windows(
    builder: StrategyBuilderWindow
) -> None:
    canvas = builder.centralWidget()
    assert canvas.objectName() == "builderCanvas"
    # The canvas is the darkest surface, painted, not left to the default.
    assert CANVAS in canvas.styleSheet()

    layout = canvas.layout()
    assert layout.contentsMargins().left() == CARD_GAP
    assert layout.contentsMargins().top() == CARD_GAP
    assert not builder.grab().toImage().isNull()


def test_it_does_not_run_anything(builder: StrategyBuilderWindow) -> None:
    # Nothing in it starts a walk or touches the candle store.
    assert not hasattr(builder, "playback")
    assert not hasattr(builder, "session")
