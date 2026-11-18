"""Screenshot tests: the two windows, drawn offscreen, against stored pictures.

They catch what a widget test cannot: a tile that collapsed, a column squeezed
under its contents, a colour that went missing. The comparison is deliberately
coarse. Both pictures are shrunk to blocks, and it is the blocks that are
compared, so a font rendering a pixel differently on another system does not
fail a run, while a missing tile or a moved column does.

    pytest tests/test_visual.py                  compare with tests/golden/
    UPDATE_GOLDEN=1 pytest tests/test_visual.py  redraw the goldens, then look at
                                                 them before committing

The pictures are drawn at a fixed size with fixed content (a seeded random walk
on disk), the bundled fonts, and the dark theme.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from bi_trading.data.candles import append_rows, candle_file  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402

GOLDEN = Path(__file__).parent / "golden"
BLOCK = 8                # pixels a side
MEAN_LIMIT = 0.020       # mean block difference, 0..1
WORST_LIMIT = 0.35       # the one most-changed block


@pytest.fixture(scope="module")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def _blocks(image: QImage) -> np.ndarray:
    """The picture as a grid of mean greys: one number per BLOCK x BLOCK square."""
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width, height = gray.width(), gray.height()
    raw = np.frombuffer(gray.constBits(), dtype=np.uint8)
    pixels = raw.reshape(height, gray.bytesPerLine())[:, :width].astype(float) / 255.0
    rows, cols = height // BLOCK, width // BLOCK
    cropped = pixels[: rows * BLOCK, : cols * BLOCK]
    return cropped.reshape(rows, BLOCK, cols, BLOCK).mean(axis=(1, 3))


def check(widget: QWidget, name: str) -> None:
    """Compare the widget's picture with `tests/golden/<name>.png`."""
    image = widget.grab().toImage()
    path = GOLDEN / f"{name}.png"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        image.save(str(path))
        return
    assert path.exists(), f"no golden for {name}: run with UPDATE_GOLDEN=1 and look at it"
    golden = QImage(str(path))
    assert (image.width(), image.height()) == (golden.width(), golden.height()), (
        f"{name}: drawn at {image.width()}x{image.height()}, "
        f"golden is {golden.width()}x{golden.height()}"
    )
    difference = np.abs(_blocks(image) - _blocks(golden))
    if difference.mean() > MEAN_LIMIT or difference.max() > WORST_LIMIT:
        actual = GOLDEN / f"{name}.actual.png"
        image.save(str(actual))
        where = np.unravel_index(int(difference.argmax()), difference.shape)
        raise AssertionError(
            f"{name} differs from its golden: mean {difference.mean():.4f} "
            f"(limit {MEAN_LIMIT}), worst block {difference.max():.2f} at "
            f"row {where[0]}, column {where[1]} (limit {WORST_LIMIT}). "
            f"What was drawn is in {actual.name}."
        )


def _settle(app: QApplication, rounds: int = 15) -> None:
    for _ in range(rounds):
        app.processEvents()


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    """A seeded random walk on disk, so a finished run draws the same every time."""
    from bi_trading.data import candles

    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()
    rng = random.Random(5)
    price, rows = 100.0, []
    for index in range(1500):
        price *= 1.0 + rng.uniform(-0.006, 0.006)
        rows.append((index * 60_000, price, price * 1.003, price * 0.997, price, 1.0))
    append_rows(candle_file(2021), rows)
    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))
    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    yield
    candles._ROW_CACHE.clear()


def _backtest(app: QApplication, height: int = 940):
    from bi_trading.ui.strat.strat_window import StratWindow

    window = StratWindow()
    window.resize(1180, height)
    window.show()
    _settle(app)
    return window


def test_the_backtest_window_idle(app: QApplication) -> None:
    window = _backtest(app)
    check(window, "backtest-idle")
    window.close()


def test_the_backtest_window_after_a_run(app: QApplication) -> None:
    window = _backtest(app)
    window.left.set_source([2021], "1m")
    window.left.restart(autoplay=False)
    window.left.finish(wait=True)
    window.results.refresh()
    _settle(app)
    check(window, "backtest-run")
    window.close()


def test_the_backtest_window_at_a_small_height(app: QApplication) -> None:
    """The column keeps its tiles whole and scrolls (the hub's 820px window)."""
    window = _backtest(app, height=700)
    check(window, "backtest-short")
    window.close()


def test_the_builder_window(app: QApplication) -> None:
    from bi_trading.ui.strat.strat_builder import StrategyBuilderWindow

    window = StrategyBuilderWindow()
    window.resize(1280, 900)
    window.show()
    _settle(app)
    window.name_edit.setText("Volume spike")
    window.entry.set_text("band = bollinger_lower(close, 20, 2)\nclose < band and volume > 0")
    window.exit.set_text("pnl >= tp or pnl <= 0 - sl or bars >= 90")
    _settle(app)
    check(window, "builder")
    window.close()
