"""The strategy builder window: two rails, and a middle column split in two."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from lalala.panels import Card  # noqa: E402
from lalala.strat_builder import COLUMN_SHARES, StrategyBuilderWindow  # noqa: E402
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


def test_the_middle_column_is_two_tiles_not_one_split_tile(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    column = builder.center

    # A tile is a card. The middle column is a splitter holding two of them,
    # each with its own chrome — the column itself is not a card.
    assert isinstance(column, Card) is False
    assert column.count() == 2
    assert column.orientation() == Qt.Orientation.Vertical
    assert column.handleWidth() == CARD_GAP
    assert column.childrenCollapsible() is False
    assert column.widget(0) is builder.name_tile
    assert column.widget(1) is builder.timeframe_tile
    assert isinstance(builder.name_tile, Card)
    assert isinstance(builder.timeframe_tile, Card)
    # Each keeps its own surface, rather than being a well cut into the other.
    assert builder.name_tile.objectName() == "venuePanel"
    assert builder.timeframe_tile.objectName() == "venuePanel"

    top, bottom = column.sizes()
    assert top == pytest.approx(bottom, abs=2)
    assert builder.name_tile.width() == builder.timeframe_tile.width()

    gap = (
        builder.timeframe_tile.geometry().top()
        - builder.name_tile.geometry().bottom()
        - 1
    )
    assert gap == pytest.approx(CARD_GAP, abs=1)


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

        top, bottom = builder.center.sizes()
        assert top == pytest.approx(bottom, abs=2)


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
    top = builder.name_tile
    bottom = builder.timeframe_tile
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


def test_every_tile_is_empty(builder: StrategyBuilderWindow) -> None:
    for tile in (
        builder.left,
        builder.name_tile,
        builder.timeframe_tile,
        builder.right,
    ):
        # Nothing has been decided about the shape of a strategy yet.
        assert tile.findChildren(QLabel) == []
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
