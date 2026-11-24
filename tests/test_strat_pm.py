from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.data import candles, polymarket_history as ph  # noqa: E402
from bi_trading.state.strategies import SavedStrategy  # noqa: E402
from bi_trading.ui.strat.strat_pm import PolymarketBacktestWindow, load_candles  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402

W = ph.HISTORY_START_MS


@pytest.fixture(scope="module")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_DATA", str(tmp_path))
    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    candles._ROW_CACHE.clear()
    rows = [(W + i * 60_000, 100.0, 101.0, 99.0, 100.0 + (i % 3), 1.0) for i in range(50)]
    candles.append_rows(candles.candle_file(2026), rows)
    ph.append_rows(ph.history_file(2026), [
        ph.WindowRow(W + i * 300_000, i % 2, 1.0, (10, 70, 130, 190, 250), (0.5,) * 5)
        for i in range(10)
    ])
    win = PolymarketBacktestWindow()
    yield win
    win.close()


def test_the_window_reports_what_is_on_disk(window) -> None:
    assert "10 markets" in window.coverage_label.text()
    assert "Binance 1m candles" in window.coverage_label.text()


def test_load_candles_cuts_to_the_span(window) -> None:
    got = load_candles(W + 5 * 60_000, W + 9 * 60_000)
    assert len(got["timestamp"]) == 5 and got["timestamp"][0] == W + 5 * 60_000


def test_a_strategy_runs_and_the_result_is_shown(window, app) -> None:
    from bi_trading.state import strategies

    strategies.save(SavedStrategy("pm-test", "1m", "minute == 1 and up_price < 0.6", "pnl >= 10"))
    window.refresh_strategies()
    window.span.setCurrentIndex(0)
    window._run()
    window._worker.wait(10_000)
    for _ in range(5):
        app.processEvents()
    text = window.figures.text()
    assert "bets" in text and "Always UP" in text and "Always DOWN" in text
    assert window.table.rowCount() > 0
    assert window.run_button.isEnabled()


def test_a_rule_that_does_not_parse_is_explained(window) -> None:
    from bi_trading.state import strategies

    strategies.save(SavedStrategy("bad", "1m", "model_p > 0.5 and nonsense > 1", ""))
    window.refresh_strategies()
    window._run()
    assert "does not read" in window.strategy_note.text()
    assert window._worker is None


def test_the_hub_opens_the_polymarket_backtest_on_the_polymarket_venue(app, monkeypatch, tmp_path) -> None:
    from bi_trading.ui.hub.main_hub import MainHubWindow

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    hub = MainHubWindow(autostart=False)
    hub._venue = "pm"
    hub._open("backtest")
    app.processEvents()
    assert isinstance(hub._view, PolymarketBacktestWindow)
    hub._view.open_builder()
    app.processEvents()
    assert hub._key == "builder"
    hub.close()


def test_a_strategy_with_a_down_rule_bets_both_sides(window, app) -> None:
    from bi_trading.state import strategies

    strategies.save(SavedStrategy(
        "both-sides", "1m", "minute == 2 and close >= 101", "", side="both",
        short_entry="minute == 2 and close < 101",
    ))
    window.refresh_strategies()
    window.strategy.setCurrentText("both-sides")
    window._run()
    window._worker.wait(10_000)
    for _ in range(5):
        app.processEvents()
    assert "bet DOWN when" in window.strategy_note.text()
    sides = {window.table.item(r, 1).text() for r in range(window.table.rowCount())}
    assert sides == {"UP", "DOWN"}
