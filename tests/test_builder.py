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
    ENTRY_MODES,
    TIMEFRAMES,
    LockedHandle,
    StrategyBuilderWindow,
)
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

    # The entry tile has its header row and the pages; the exit tile only its
    # title and a stretch.
    assert builder.entry_tile.body.count() == 2
    assert builder.exit_tile.body.count() == 2


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
    assert entry > top and exit_ > top
    # The two empty tiles split what is left.
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

    # Scoped to this tile; the rules tiles have neither field.
    for tile in (builder.entry_tile, builder.exit_tile):
        assert tile.findChildren(QLineEdit) == []
        assert tile.findChildren(QComboBox) == []


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


def test_the_entry_tile_has_three_ways_to_write_a_rule(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    labels = [label for key, label in ENTRY_MODES]
    assert labels == ["Rules", "Formulas", "Code"]

    buttons = builder.mode_buttons
    assert list(buttons) == [key for key, _ in ENTRY_MODES]
    assert [button.text() for button in buttons.values()] == labels
    for button in buttons.values():
        assert button.isCheckable() is True
        assert builder.entry_tile.isAncestorOf(button)

    # One at a time, and the first is the default.
    assert builder.entry_modes.exclusive() is True
    assert builder.entry_mode() == "rules"
    assert buttons["rules"].isChecked() is True

    picked: list[str] = []
    builder.entry_mode_changed.connect(picked.append)
    buttons["code"].click()
    app.processEvents()

    assert builder.entry_mode() == "code"
    assert buttons["code"].isChecked() is True
    assert buttons["rules"].isChecked() is False
    assert picked == ["code"]
    # Switching the mode changes nothing else yet.
    assert builder.name_edit.text() == ""


def test_the_formulas_page_edits_and_checks_a_formula(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # The page only exists once Formulas is picked.
    builder.mode_buttons["formulas"].click()
    app.processEvents()

    assert builder.entry_pages.currentIndex() == 1
    edit = builder.formula_edit
    assert builder.entry_tile.isAncestorOf(edit)
    assert edit.placeholderText() == "close < bollinger_lower(close, 20, 2)"
    # Empty is not an error; there is simply no formula yet.
    assert builder.entry_formula_error() == ""
    assert builder.entry_formula_parsed() is None

    # A good formula parses and clears the error line.
    builder.set_entry_formula("mid = sma(close, 20)\nclose < mid")
    app.processEvents()
    assert builder.entry_formula() == "mid = sma(close, 20)\nclose < mid"
    assert builder.entry_formula_error() == ""
    parsed = builder.entry_formula_parsed()
    assert parsed is not None
    assert parsed.series_names == ("mid",)

    # A typo is reported with its place, and there is nothing parsed.
    builder.set_entry_formula("close < clsoe")
    app.processEvents()
    assert builder.entry_formula_error() == (
        "line 1, column 9: unknown name 'clsoe'"
    )
    assert builder.entry_formula_parsed() is None
    assert edit.property("state") == "error"

    # Correcting it clears the error again.
    builder.set_entry_formula("close < 10")
    app.processEvents()
    assert builder.entry_formula_error() == ""
    assert builder.entry_formula_parsed() is not None
    assert edit.property("state") == "ok"


def test_the_rules_and_code_pages_are_placeholders(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    builder.mode_buttons["rules"].click()
    app.processEvents()
    assert builder.entry_pages.currentIndex() == 0

    builder.mode_buttons["code"].click()
    app.processEvents()
    assert builder.entry_pages.currentIndex() == 2

    # Neither is the formula editor, and neither pretends to work: one faint
    # note each, no editor.
    for index in (0, 2):
        page = builder.entry_pages.widget(index)
        notes = [label.text() for label in page.findChildren(QLabel)]
        assert len(notes) == 1
        assert "yet" in notes[0]
        assert page.findChildren(QPlainTextEdit) == []


def test_only_one_entry_page_shows_at_a_time(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    for key in ("rules", "formulas", "code"):
        builder.mode_buttons[key].click()
        app.processEvents()
        visible = [
            index
            for index in range(builder.entry_pages.count())
            if builder.entry_pages.widget(index).isVisible()
        ]
        assert visible == [builder.entry_pages.currentIndex()]


def test_the_exit_tile_has_no_modes(builder: StrategyBuilderWindow) -> None:
    assert builder.exit_tile.findChildren(QPushButton) == []


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

        # The strategy tile stays compact; the two rules tiles share the rest.
        top, entry, exit_ = builder.center.sizes()
        assert top == pytest.approx(
            builder.strategy_tile.sizeHint().height(), abs=4
        )
        assert entry > top and exit_ > top
        assert entry == pytest.approx(exit_, abs=2)


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
