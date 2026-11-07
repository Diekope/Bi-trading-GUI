"""The strategy builder window: two rails, a compact STRATEGY tile, one below."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
)

from lalala.panels import Card  # noqa: E402
from lalala.strat_builder import (  # noqa: E402
    COLUMN_SHARES,
    TIMEFRAMES,
    LockedHandle,
    StrategyBuilderWindow,
)
from lalala.strat_rules import RULES_MODES as ENTRY_MODES  # noqa: E402
from lalala.theme import CANVAS, CARD_GAP, apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


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


def test_the_window_holds_three_columns(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    splitter = builder.splitter

    assert splitter.count() == 3
    # A vertical split: the handles run top to bottom, the columns sit side by
    # side and share the height.
    assert splitter.orientation() == Qt.Orientation.Horizontal
    assert splitter.handleWidth() == CARD_GAP
    assert splitter.childrenCollapsible() is False
    assert splitter.widget(0) is builder.left
    assert splitter.widget(1) is builder.center
    assert splitter.widget(2) is builder.right
    assert isinstance(builder.left, Card)
    assert isinstance(builder.right, Card)


def test_the_middle_column_is_three_tiles_stacked(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    column = builder.center

    # The column itself is not a card: it holds three of them.
    assert isinstance(column, Card) is False
    assert column.count() == 3
    assert column.orientation() == Qt.Orientation.Vertical
    assert column.handleWidth() == CARD_GAP
    assert column.childrenCollapsible() is False
    assert column.widget(0) is builder.strategy_tile
    assert column.widget(1) is builder.entry_tile
    assert column.widget(2) is builder.exit_tile
    for tile in (builder.strategy_tile, builder.entry_tile, builder.exit_tile):
        assert isinstance(tile, Card)

    for upper, lower in (
        (builder.strategy_tile, builder.entry_tile),
        (builder.entry_tile, builder.exit_tile),
    ):
        gap = lower.geometry().top() - upper.geometry().bottom() - 1
        assert gap == pytest.approx(CARD_GAP, abs=1)


def test_the_entry_and_exit_tiles_are_titled(
    builder: StrategyBuilderWindow
) -> None:
    entry_title = builder.entry_tile.findChildren(QLabel)[0]
    exit_title = builder.exit_tile.findChildren(QLabel)[0]
    assert entry_title.text() == "ENTRY RULES"
    assert exit_title.text() == "EXIT RULES"
    for title in (entry_title, exit_title):
        assert title.objectName() == "tileTitle"
        assert title.geometry().top() < 20  # at the top, not centred

    # The entry tile has its header row, the presets row and the pages; the
    # exit tile is the same.
    assert builder.entry_tile.body.count() == 3
    assert builder.exit_tile.body.count() == 3


def test_the_strategy_tile_is_titled_and_compact(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    tile = builder.strategy_tile

    assert [label.text() for label in tile.findChildren(QLabel)] == ["STRATEGY"]
    title = tile.findChildren(QLabel)[0]
    assert title.objectName() == "tileTitle"

    # Only the height its title and row need, not a share of the column.
    top, entry, exit_ = builder.center.sizes()
    assert top == pytest.approx(tile.sizeHint().height(), abs=2)
    # The two rules tiles split the rest of the column evenly.
    assert entry == pytest.approx(exit_, abs=2)


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
    assert edit.width() > picker.width() * 3

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


def test_the_columns_are_split_21_47_32(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.splitter.setSizes(builder.column_sizes())
    app.processEvents()

    shares = _shares(builder)
    assert shares[0] == pytest.approx(COLUMN_SHARES[0], abs=0.01)
    assert shares[1] == pytest.approx(COLUMN_SHARES[1], abs=0.01)
    assert shares[2] == pytest.approx(COLUMN_SHARES[2], abs=0.01)

    left, middle, right = builder.splitter.sizes()
    assert left < middle and right < middle
    assert left < right


def test_the_entry_tile_has_two_ways_to_write_a_rule(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    labels = [label for key, label in ENTRY_MODES]
    assert labels == ["Formulas", "Code"]

    buttons = builder.mode_buttons
    assert list(buttons) == [key for key, _ in ENTRY_MODES]
    assert [button.text() for button in buttons.values()] == labels
    for button in buttons.values():
        assert button.isCheckable() is True
        assert builder.entry_tile.isAncestorOf(button)

    # One at a time, and the tiles are the default.
    assert builder.entry_modes.exclusive() is True
    assert builder.entry_mode() == "formulas"
    assert buttons["formulas"].isChecked() is True

    picked: list[str] = []
    builder.entry_mode_changed.connect(picked.append)
    buttons["code"].click()
    app.processEvents()

    assert builder.entry_mode() == "code"
    assert buttons["code"].isChecked() is True
    assert buttons["formulas"].isChecked() is False
    assert picked == ["code"]
    # Switching the mode changes nothing else yet.
    assert builder.name_edit.text() == ""


def test_the_formulas_page_builds_and_checks_a_formula(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # The tiles are the page on show.
    builder.mode_buttons["formulas"].click()
    app.processEvents()

    assert builder.entry_pages.currentIndex() == 0
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

    builder.mode_buttons["formulas"].click()
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
    builder.mode_buttons["formulas"].click()
    app.processEvents()
    # Build something with the tiles.
    builder.set_entry_formula("mid = sma(close, 20)\nclose < mid")
    app.processEvents()

    builder.mode_buttons["code"].click()
    app.processEvents()
    assert builder.entry_pages.currentIndex() == 1
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
    for key in ("formulas", "code"):
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
    assert exit_groups == ["Trade", "Logic & Maths"]
    assert list(builder.exit.formula.blocks) == exit_groups

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


def test_each_tile_offers_presets_before_the_formulas(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    from lalala.strat_rules import ENTRY_PRESETS, EXIT_PRESETS

    labels = [button.text() for button in builder.entry.preset_buttons]
    assert labels == [preset.label for preset in ENTRY_PRESETS]
    assert labels == [
        "Bollinger", "SMA above", "Breakout", "RSI dip", "Volume", "Dip + volume",
    ]
    assert [b.text() for b in builder.exit.preset_buttons] == [
        preset.label for preset in EXIT_PRESETS
    ]

    # The presets sit above the builder, above the tabs' pages.
    body = builder.entry_tile.body
    header = body.itemAt(0).layout()
    presets = body.itemAt(1).layout()
    pages = body.itemAt(2).widget()
    assert header.indexOf(builder.entry.title) != -1
    assert presets.indexOf(builder.entry.preset_holder) != -1
    assert builder.entry.preset_holder.isAncestorOf(
        builder.entry.preset_buttons[0]
    )
    assert isinstance(pages, type(builder.entry_pages))


def test_clicking_a_preset_fills_the_tile(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.entry.preset_buttons[0].click()  # Bollinger
    app.processEvents()
    assert builder.entry_formula() == "close < bollinger_lower(close, 20, 2)"
    assert builder.entry_formula_error() == ""
    assert builder.entry_formula_parsed() is not None

    # The multi-line preset comes through whole.
    builder.entry.preset_buttons[5].click()  # Dip + volume
    app.processEvents()
    assert builder.entry_formula().startswith("band = bollinger_lower")
    assert builder.entry_formula_error() == ""

    # The exit tile has its own presets, in the trade's words.
    builder.exit.preset_buttons[2].click()  # TP or SL
    app.processEvents()
    assert builder.exit_formula() == "pnl >= tp or pnl <= 0 - sl"
    assert builder.exit_formula_error() == ""
    # The entry formula is untouched.
    assert builder.entry_formula().startswith("band = bollinger_lower")


def test_the_exit_tile_has_the_same_tabs_as_the_entry(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # Same widget, same two tabs, its own formula.
    assert builder.exit_tile is not builder.entry_tile
    assert list(builder.exit_tile.mode_buttons) == ["formulas", "code"]
    assert builder.exit_mode() == "formulas"

    builder.exit.set_mode("code")
    app.processEvents()
    assert builder.exit_mode() == "code"
    assert builder.exit_tile.pages.currentIndex() == 1
    assert builder.entry_mode() == "formulas"  # entry untouched

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


def test_the_gaps_stay_exactly_the_card_gap(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    for width in (960, 1280, 1600):
        builder.resize(width, 720)
        app.processEvents()
        left, middle, right = builder.left, builder.center, builder.right
        first = middle.geometry().left() - left.geometry().right() - 1
        second = right.geometry().left() - middle.geometry().right() - 1
        assert first == pytest.approx(CARD_GAP, abs=0.5)
        assert second == pytest.approx(CARD_GAP, abs=0.5)


def test_the_split_scales_with_the_window(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    for width in (960, 1600):
        builder.resize(width, 720)
        app.processEvents()
        shares = _shares(builder)
        assert shares[0] == pytest.approx(COLUMN_SHARES[0], abs=0.01)
        assert shares[1] == pytest.approx(COLUMN_SHARES[1], abs=0.01)
        assert shares[2] == pytest.approx(COLUMN_SHARES[2], abs=0.01)

        # The strategy tile stays compact; the two rules tiles share the rest
        # of the column evenly.
        top, entry, exit_ = builder.center.sizes()
        assert top == pytest.approx(
            builder.strategy_tile.sizeHint().height(), abs=4
        )
        assert entry == pytest.approx(exit_, abs=3)
        assert entry > 0


def test_the_left_rail_does_not_get_clamped_to_the_card_floor() -> None:
    # 21% of the default window is below the Card default of 220 px; the tiles
    # lower their own floor so the proportions win.
    window = StrategyBuilderWindow()
    assert window.left.minimumWidth() < 220
    window.close()


def test_the_middle_tiles_fill_their_column(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.splitter.setSizes(builder.column_sizes())
    app.processEvents()

    column = builder.center
    tiles = (builder.strategy_tile, builder.entry_tile, builder.exit_tile)
    # Every card spans the column, less the transparent splitter handle.
    for tile in tiles:
        assert tile.width() == pytest.approx(column.width() - 2, abs=2)
    assert sum(tile.height() for tile in tiles) + 2 * CARD_GAP == pytest.approx(
        column.height(), abs=2
    )


def test_both_gaps_show_the_canvas(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.splitter.setSizes(builder.column_sizes())
    app.processEvents()

    left, middle, right = builder.left, builder.center, builder.right
    first = middle.geometry().left() - left.geometry().right() - 1
    second = right.geometry().left() - middle.geometry().right() - 1
    assert first == pytest.approx(CARD_GAP, abs=1)
    assert second == pytest.approx(CARD_GAP, abs=1)


def test_the_side_rails_stay_empty(builder: StrategyBuilderWindow) -> None:
    for tile in (builder.left, builder.right):
        assert tile.findChildren(QLabel) == []
        assert tile.findChildren(QLineEdit) == []
        assert tile.findChildren(QComboBox) == []
        assert tile.body.count() == 0


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
