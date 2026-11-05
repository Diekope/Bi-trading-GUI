"""The strategy builder window, launched on its own."""

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
    # Big enough to hold a form later, small enough to sit beside the other.
    assert builder.minimumWidth() >= 480
    assert builder.minimumHeight() >= 380


def test_it_is_blank(builder: StrategyBuilderWindow) -> None:
    # One faint line and no cards: nothing has been decided about the shape of
    # a strategy yet.
    assert builder.centralWidget().findChildren(Card) == []
    lines = builder.centralWidget().findChildren(QLabel)
    assert [line.text() for line in lines] == ["nothing here yet"]


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


def test_it_opens_centred_and_does_not_run_anything(
    app: QApplication, builder: StrategyBuilderWindow
) -> None:
    # Nothing in it starts a walk or touches the candle store.
    assert not hasattr(builder, "playback")
    assert not hasattr(builder, "session")
    assert builder.placeholder.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert not builder.grab().toImage().isNull()
