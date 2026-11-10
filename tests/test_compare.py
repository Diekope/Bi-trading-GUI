"""The compare subwindow: the run against its stand-ins, and the sweep."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.data.candles import append_rows, candle_file  # noqa: E402
from lalala.engine.formula import EXIT_FIELDS, EXIT_FUNCTIONS, parse  # noqa: E402
from lalala.engine.formula_eval import backtest  # noqa: E402
from lalala.ui.strat.strat_compare import (  # noqa: E402
    SWEEP_SLS,
    SWEEP_TPS,
    ComparePage,
    sweep_returns,
    walk_forward,
)
from lalala.ui.strat.strat_report import load_bars  # noqa: E402
from lalala.state.strategies import SavedStrategy  # noqa: E402
from lalala.ui.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    from lalala.data import candles

    candles._ROW_CACHE.clear()
    yield


def _write_year(year: int, count: int) -> None:
    rows = []
    for index in range(count):
        price = 100.0 + (index % 20)
        rows.append((index * 60_000, price, price + 1, price - 1, price, 1.0))
    append_rows(candle_file(year), rows)


def _rules():
    entry = parse("close < sma(close, 5)")
    exit_ = parse(
        "pnl >= tp or pnl <= 0 - sl or bars >= 3", EXIT_FIELDS, EXIT_FUNCTIONS
    )
    return entry, exit_


# -- the sums ----------------------------------------------------------------


def test_a_walk_forward_gives_one_return_per_fold() -> None:
    _write_year(2021, 400)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()

    returns = walk_forward(bars, entry, exit_, 2.0, 1.0, folds=4)

    assert len(returns) == 4
    assert all(isinstance(value, float) for value in returns)


def test_the_sweep_is_a_grid_of_tp_and_sl() -> None:
    _write_year(2021, 400)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()

    grid = sweep_returns(bars, entry, exit_)

    assert len(grid) == len(SWEEP_SLS)
    assert all(len(row) == len(SWEEP_TPS) for row in grid)


# -- the page ----------------------------------------------------------------


def test_the_page_shows_the_runs_the_table_and_the_sweep(
    app: QApplication,
) -> None:
    _write_year(2021, 600)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()
    report = backtest(bars, entry, exit_, tp=2.0, sl=1.0)

    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    app.processEvents()

    assert [chip.name() for chip in page.tags + [page.add_chip]] == [
        "Strategy", "Random buy", "Buy & hold", "+ Add",
    ]
    # The table has a figure for each run; Hold has no win rate.
    assert page._cells[(1, 1)].text().endswith("%")  # PnL strategy
    assert page._cells[(4, 3)].text() == "—"  # hold win rate
    # The sweep and the folds are filled, and the key is under the grid.
    assert len(page.heatmap.values) == len(SWEEP_SLS)
    assert "/" in page.folds_row.text()
    assert page.legend.isVisibleTo(page)
    page.close()


def test_adding_a_saved_strategy_puts_it_in_the_compare(
    app: QApplication,
) -> None:
    _write_year(2021, 600)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()
    report = backtest(bars, entry, exit_, tp=2.0, sl=1.0)
    saved = SavedStrategy(
        "Older draft", "1m", "close > sma(close, 10)", "pnl >= tp"
    )

    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    app.processEvents()

    page.add_strategy(saved)
    app.processEvents()

    assert len(page.runs) == 1
    assert page.runs[0]["label"] == "Older draft"
    assert [chip.name() for chip in page.extra_chips] == ["Older draft"]
    # The table grew a column and the chart knows the extra curve.
    assert (1, 4) in page._cells
    assert page._cells[(1, 4)].text().endswith("%")
    assert page.chart.extra == [
        (page.runs[0]["colour"], page.runs[0]["report"].strategy)
    ]

    # The same strategy twice is not added again.
    page.add_strategy(saved)
    assert len(page.runs) == 1

    # Clicking its chip takes it back out.
    page.remove_run(page.extra_chips[0])
    app.processEvents()
    assert page.runs == []
    assert page.extra_chips == []
    assert (1, 4) not in page._cells
    assert page.chart.extra == []
    page.close()


def test_a_strategy_that_does_not_parse_is_ignored(app: QApplication) -> None:
    _write_year(2021, 600)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()
    report = backtest(bars, entry, exit_, tp=2.0, sl=1.0)

    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    page.add_strategy(SavedStrategy("Broken", "1m", "clsoe < 1", "pnl >= tp"))
    app.processEvents()

    assert page.runs == []
    assert page.extra_chips == []
    page.close()


def test_a_new_rule_clears_the_added_strategies(app: QApplication) -> None:
    _write_year(2021, 600)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()
    report = backtest(bars, entry, exit_, tp=2.0, sl=1.0)
    saved = SavedStrategy(
        "Older draft", "1m", "close > sma(close, 10)", "pnl >= tp"
    )

    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    page.add_strategy(saved)
    app.processEvents()
    assert len(page.runs) == 1

    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    app.processEvents()

    assert page.runs == []
    assert page.extra_chips == []
    assert (1, 4) not in page._cells
    page.close()


def test_the_add_menu_lists_saved_strategies(
    app: QApplication, tmp_path, monkeypatch
) -> None:
    _write_year(2021, 600)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()
    report = backtest(bars, entry, exit_, tp=2.0, sl=1.0)

    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "saved.json"))
    from lalala.state import strategies

    strategies.save(
        SavedStrategy("Keep", "5m", "close > sma(close, 10)", "pnl >= tp")
    )
    strategies.save(
        SavedStrategy("Broken", "1m", "clsoe < 1", "pnl >= tp")
    )

    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    app.processEvents()

    menu = page._build_add_menu()
    actions = {action.text(): action for action in menu.actions()}
    assert "Keep · 5m" in actions
    assert actions["Keep · 5m"].isEnabled()
    assert "Broken · invalid rule" in actions
    assert not actions["Broken · invalid rule"].isEnabled()

    actions["Keep · 5m"].trigger()
    app.processEvents()
    assert [run["label"] for run in page.runs] == ["Keep"]

    # Once added, the entry is shown greyed out.
    menu = page._build_add_menu()
    texts = [action.text() for action in menu.actions()]
    assert "Keep · added" in texts
    page.close()


def test_the_strategy_on_show_is_not_offered_again(
    app: QApplication, tmp_path, monkeypatch
) -> None:
    _write_year(2021, 600)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()
    report = backtest(bars, entry, exit_, tp=2.0, sl=1.0)

    monkeypatch.setenv("LALALA_STRATEGIES", str(tmp_path / "saved.json"))
    from lalala.state import strategies

    current = SavedStrategy(
        "On show", "1m", "close > sma(close, 10)", "pnl >= tp"
    )
    other = SavedStrategy(
        "Another", "1m", "close < sma(close, 20)", "pnl >= tp"
    )
    strategies.save(current)
    strategies.save(other)

    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    page.set_selected("On show")
    app.processEvents()

    menu = page._build_add_menu()
    texts = [action.text() for action in menu.actions()]
    assert "Another · 1m" in texts
    assert not any(text.startswith("On show") for text in texts)

    # Even asked directly, the run on show is not added twice.
    page.add_strategy(current)
    assert page.runs == []
    page.close()


def test_an_empty_rule_leaves_the_table_dashed(app: QApplication) -> None:
    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure([], None, None, None, 2.0, 1.0)
    app.processEvents()

    assert all(cell.text() == "—" for cell in page._cells.values())
    assert page.heatmap.values == []
    page.close()
