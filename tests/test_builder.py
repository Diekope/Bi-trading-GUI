"""The strategy builder window, split into two vertical tiles."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from lalala.panels import Card  # noqa: E402
from lalala.strat_builder import StrategyBuilderWindow  # noqa: E402
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


def test_it_is_a_window_of_its_own(builder: StrategyBuilderWindow) -> None:
    assert builder.windowTitle() == "lalala · create a strategy"
    assert builder.isWindow() is True
    assert builder.isVisible() is True
    # Big enough for two tiles, small enough to sit beside the other windows.
    assert builder.minimumWidth() >= 480
    assert builder.minimumHeight() >= 380


def test_it_splits_into_two_vertical_tiles(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    splitter = builder.splitter

    assert splitter.count() == 2
    # A vertical split: the handle runs top to bottom, the tiles sit side by
    # side and share the height.
    assert splitter.orientation() == Qt.Orientation.Horizontal
    assert splitter.handleWidth() == CARD_GAP
    assert splitter.childrenCollapsible() is False
    assert splitter.widget(0) is builder.left
    assert splitter.widget(1) is builder.right
    assert isinstance(builder.left, Card)
    assert isinstance(builder.right, Card)

    left, right = splitter.sizes()
    assert left == pytest.approx(right, abs=2)
    assert builder.left.height() == builder.right.height()


def test_both_tiles_are_empty(builder: StrategyBuilderWindow) -> None:
    for tile in (builder.left, builder.right):
        # Nothing has been decided about the shape of a strategy yet.
        assert tile.findChildren(QLabel) == []
        assert tile.body.count() == 0


def test_the_gap_separates_the_tiles(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    left, right = builder.left, builder.right
    gap = right.geometry().left() - left.geometry().right() - 1

    # The canvas shows through between them, the same gap as the other windows.
    assert gap == pytest.approx(CARD_GAP, abs=1)


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
