"""The strategy builder window: three vertical tiles, 21 / 47 / 32."""

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


def test_it_splits_into_three_vertical_tiles(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    splitter = builder.splitter

    assert splitter.count() == 3
    # A vertical split: the handles run top to bottom, the tiles sit side by
    # side and share the height.
    assert splitter.orientation() == Qt.Orientation.Horizontal
    assert splitter.handleWidth() == CARD_GAP
    assert splitter.childrenCollapsible() is False
    assert splitter.widget(0) is builder.left
    assert splitter.widget(1) is builder.center
    assert splitter.widget(2) is builder.right
    for tile in (builder.left, builder.center, builder.right):
        assert isinstance(tile, Card)
        assert tile.height() == builder.left.height()


def test_the_width_is_split_21_47_32(
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


def test_the_left_rail_does_not_get_clamped_to_the_card_floor() -> None:
    # 21% of the default window is below the Card default of 220 px; the tiles
    # lower their own floor so the proportions win.
    window = StrategyBuilderWindow()
    assert window.left.minimumWidth() < 220
    window.close()


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


def test_all_three_tiles_are_empty(builder: StrategyBuilderWindow) -> None:
    for tile in (builder.left, builder.center, builder.right):
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
