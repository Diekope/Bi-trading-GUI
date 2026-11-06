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
)

from lalala.panels import Card  # noqa: E402
from lalala.strat_builder import (  # noqa: E402
    COLUMN_SHARES,
    TIMEFRAMES,
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


def test_the_middle_column_is_two_tiles_one_above_the_other(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    column = builder.center

    # The column itself is not a card: it holds two of them.
    assert isinstance(column, Card) is False
    assert column.count() == 2
    assert column.orientation() == Qt.Orientation.Vertical
    assert column.handleWidth() == CARD_GAP
    assert column.childrenCollapsible() is False
    assert column.widget(0) is builder.strategy_tile
    assert column.widget(1) is builder.lower_tile
    assert isinstance(builder.strategy_tile, Card)
    assert isinstance(builder.lower_tile, Card)

    gap = (
        builder.lower_tile.geometry().top()
        - builder.strategy_tile.geometry().bottom()
        - 1
    )
    assert gap == pytest.approx(CARD_GAP, abs=1)


def test_the_strategy_tile_is_titled_and_compact(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    tile = builder.strategy_tile

    assert [label.text() for label in tile.findChildren(QLabel)] == ["STRATEGY"]
    title = tile.findChildren(QLabel)[0]
    assert title.objectName() == "tileTitle"

    # Only the height its title and row need, not half the column.
    top, rest = builder.center.sizes()
    assert top == pytest.approx(tile.sizeHint().height(), abs=2)
    assert rest > top
    assert top < builder.center.height() / 2


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

    # Scoped to this tile, and one empty tile below with neither field.
    assert builder.lower_tile.findChildren(QLineEdit) == []
    assert builder.lower_tile.findChildren(QComboBox) == []


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

        # The strategy tile stays compact; the empty one takes the space.
        top, rest = builder.center.sizes()
        assert top == pytest.approx(builder.strategy_tile.sizeHint().height(), abs=4)
        assert rest > top


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
    top = builder.strategy_tile
    bottom = builder.lower_tile
    # Both cards span the column, less the transparent splitter handle.
    assert top.width() == pytest.approx(column.width() - 2, abs=2)
    assert bottom.width() == pytest.approx(column.width() - 2, abs=2)
    assert top.height() + bottom.height() + CARD_GAP == pytest.approx(
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


def test_the_side_rails_and_the_lower_tile_stay_empty(
    builder: StrategyBuilderWindow
) -> None:
    for tile in (builder.left, builder.lower_tile, builder.right):
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
