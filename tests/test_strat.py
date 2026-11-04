"""The blank backtest/strategy window starts empty, on the shared theme."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.panels import Card  # noqa: E402
from lalala.strat_window import StratWindow  # noqa: E402
from lalala.theme import CANVAS, apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_the_window_splits_in_two_empty_halves(
    app: QApplication,
) -> None:
    window = StratWindow()
    window.show()
    app.processEvents()

    assert window.windowTitle() == "lalala · backtest + strategy"
    # Two equal floating cards, side by side, both still empty.
    assert window.splitter.count() == 2
    assert window.splitter.orientation() == Qt.Orientation.Horizontal
    assert window.left.findChildren(Card) == []
    assert window.right.findChildren(Card) == []
    left, right = window.splitter.sizes()
    assert abs(left - right) <= 1
    # It paints, and paints the shell's canvas colour through the gap.
    image = window.grab().toImage()
    assert not image.isNull()
    handle = window.splitter.handle(1)
    gap = handle.mapTo(window, handle.rect().center())
    assert image.pixelColor(gap).name() == CANVAS
    window.close()
