"""Regenerate the images in `docs/images/`.

Run headless, offscreen, into a throwaway config so nothing touches a real
settings or strategy file:

    uv run python tools/screenshots.py

The terminal shot waits for live venue data; the rest are built from the
candles on disk in `data/candles/`, so the backtest walk has something real to
read.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# A throwaway config: opening the windows must not write drafts or settings
# into a developer's own files.
_CONFIG = tempfile.mkdtemp(prefix="lalala-shots-")
os.environ["LALALA_SETTINGS"] = os.path.join(_CONFIG, "settings.json")
os.environ["LALALA_STRATEGIES"] = os.path.join(_CONFIG, "strategies.json")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from lalala.strat_builder import StrategyBuilderWindow  # noqa: E402
from lalala.strat_window import StratWindow  # noqa: E402
from lalala.theme import apply_dark_theme  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"


def _settle(app: QApplication, rounds: int = 12) -> None:
    for _ in range(rounds):
        app.processEvents()


def _save(widget: QWidget, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    widget.grab().toImage().save(str(path))
    print(f"wrote {path.relative_to(OUT.parent.parent)}")


def terminal(app: QApplication) -> None:
    """The live terminal. Needs network for the venues to fill it."""
    from lalala.main_window import MainWindow

    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    # Give the feeds a few seconds to land a universe, some candles and a
    # five-minute market.
    end = time.time() + 22
    while time.time() < end:
        app.processEvents()
        time.sleep(0.03)
    _save(window, "terminal.png")
    window.close()


def backtest(app: QApplication) -> None:
    """The backtest window, run over a year of real candles."""
    window = StratWindow()
    window.resize(1180, 780)
    window.show()
    _settle(app)

    # One year keeps the walk short enough to finish while we watch.
    window.left.set_source([2017], "1m")
    window.left.restart()
    session = window.left.session
    assert session is not None
    while not session.strategy.done:
        session.advance()
    window.left._refresh_metrics()
    window.left.player.update()
    window.results.refresh()
    _settle(app)

    _save(window, "backtest.png")
    _save(window.results, "part-results.png")
    window.close()


def builder(app: QApplication) -> None:
    """The three builder tabs, and the pieces the Formula/Code tabs are made of."""
    window = StrategyBuilderWindow()
    window.resize(1280, 900)
    window.show()
    _settle(app)

    window.name_edit.setText("Bollinger reversion")
    window.entry.set_text(
        "band = bollinger_lower(close, 20, 2)\nclose < band and volume > 0"
    )

    # Rules: the presets gallery, first of the three tabs.
    window.entry_tile.set_mode("rules")
    _settle(app)
    _save(window, "builder-rules.png")

    # Formula: the three columns and the LET / BUY WHEN sections.
    window.entry_tile.set_mode("formula")
    _settle(app)
    formula = window.entry.formula
    _save(window, "builder-formula.png")
    _save(formula.blocks_card, "part-blocks.png")
    _save(formula.formula_card, "part-formula-card.png")
    _save(formula.selected_card, "part-selected-block.png")

    # Code: the code and the right rail, with a variable picked.
    window.entry_tile.set_mode("code")
    _settle(app)
    window.entry._select_variable("close")
    _settle(app)
    _save(window, "builder-code.png")
    rail = window.entry.vocab_card.parentWidget()
    _save(rail, "part-code-rail.png")
    window.close()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)
    terminal(app)
    backtest(app)
    builder(app)


if __name__ == "__main__":
    main()
