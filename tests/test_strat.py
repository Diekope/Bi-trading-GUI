"""The blank backtest/strategy window starts empty, on the shared theme."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.strat_window import StratWindow  # noqa: E402
from lalala.theme import CANVAS, apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_the_window_is_blank_and_shares_the_shell_theme(
    app: QApplication,
) -> None:
    window = StratWindow()
    window.show()
    app.processEvents()

    assert window.windowTitle() == "lalala · backtest + strategy"
    # Nothing is drawn yet: the canvas is the only widget.
    canvas = window.centralWidget()
    assert canvas is not None
    assert canvas.findChildren(type(canvas)) == []
    # It paints, and paints the shell's canvas colour.
    image = window.grab().toImage()
    assert not image.isNull()
    assert image.pixelColor(window.width() // 2, window.height() // 2).name() == CANVAS
    window.close()
