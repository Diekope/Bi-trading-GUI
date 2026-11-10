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
os.environ["LALALA_RUNS"] = os.path.join(_CONFIG, "runs.json")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from lalala.ui.strat.strat_builder import StrategyBuilderWindow  # noqa: E402
from lalala.ui.strat.strat_window import StratWindow  # noqa: E402
from lalala.ui.theme import apply_dark_theme  # noqa: E402

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
    from lalala.ui.main_window import MainWindow

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
    window.resize(1180, 940)
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
    window.left._refresh_progress()
    window.left.player.update()
    window.results.refresh()
    _settle(app)

    _save(window, "backtest.png")
    _save(window.results, "part-results.png")

    # And the trades part, with a trade picked.
    window.results.set_part(1)
    _settle(app)
    _save(window.results, "part-trades.png")
    window.close()


def builder(app: QApplication) -> None:
    """The three builder tabs, and the pieces the Formula/Code tabs are made of."""
    from lalala import strategies
    from lalala.state.strategies import SavedStrategy

    # A few kept drafts, so the saved-strategies rail looks like the mock.
    for item in (
        SavedStrategy(
            "Bollinger reversion", "1m",
            "band = bollinger_lower(close, 20, 2)\nclose < band",
            "pnl >= tp or pnl <= 0 - sl or bars >= 90",
        ),
        SavedStrategy("Late favorite", "5m", "close > sma(close, 50)", "pnl >= tp"),
        SavedStrategy("Edge vs model", "1m", "close < ema(close, 30)", "pnl <= 0 - sl"),
    ):
        strategies.save(item)

    window = StrategyBuilderWindow()
    window.resize(1280, 900)
    window.show()
    _settle(app)

    window.name_edit.setText("Volume spike")
    window.entry.set_text(
        "band = bollinger_lower(close, 20, 2)\nclose < band and volume > 0"
    )
    window.exit.set_text("pnl >= tp or pnl <= 0 - sl or bars >= 90")

    # The saved-strategies rail.
    _settle(app)
    _save(window.left_column, "part-saved-rail.png")

    # Results: the three subwindows. Overview first, then Compare.
    window.report.set_view("overview")
    _settle(app)
    _save(window.report, "part-report.png")
    window.report.set_view("compare")
    _settle(app)
    window.report.compare.add_strategy(
        next(
            item for item in strategies.load()
            if item.name == "Late favorite"
        )
    )
    _settle(app)
    _save(window.report, "part-report-compare.png")
    window.report.set_view("overview")
    _settle(app)

    # Rules: the grouped condition editor, first of the three tabs.
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

    # The code tab's right rail.
    window.entry_tile.set_mode("code")
    _settle(app)
    window.entry._select_variable("close")
    _settle(app)
    _save(window, "builder-code.png")
    rail = window.entry.vocab_card.parentWidget()
    _save(rail, "part-code-rail.png")

    # Delete: a saved strategy on show arms the footer button, and the prompt.
    from lalala.ui.strat.strat_builder import ConfirmDialog

    window.name_edit.setText("Bollinger reversion")
    window.entry.set_text("band = bollinger_lower(close, 20, 2)\nclose < band")
    window.exit.set_text("pnl >= tp or pnl <= 0 - sl or bars >= 90")
    _settle(app)
    _save(window, "builder-delete.png")
    dialog = ConfirmDialog("Bollinger reversion", window)
    dialog.show()
    _settle(app)
    _save(dialog, "part-delete-prompt.png")
    dialog.close()
    window.close()


def main() -> None:
    import sys

    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)
    # Optionally name which ones to rebuild: `... builder` skips the terminal
    # and the backtest. No names means all of them.
    wanted = set(sys.argv[1:])
    for name, build in (
        ("terminal", terminal),
        ("backtest", backtest),
        ("builder", builder),
    ):
        if not wanted or name in wanted:
            build(app)


if __name__ == "__main__":
    main()
