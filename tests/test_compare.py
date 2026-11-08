"""The compare subwindow: the run against its stand-ins, and the sweep."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.candles import append_rows, candle_file  # noqa: E402
from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS, parse  # noqa: E402
from lalala.formula_eval import backtest  # noqa: E402
from lalala.strat_compare import (  # noqa: E402
    SWEEP_SLS,
    SWEEP_TPS,
    ComparePage,
    sweep_returns,
    walk_forward,
)
from lalala.strat_report import load_bars  # noqa: E402
from lalala.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    from lalala import candles

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


def test_adding_a_sweep_cell_puts_it_in_the_compare(
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

    # A cell does nothing until "+ Add" arms the sweep.
    page._cell_clicked(1, 2)
    assert page.runs == []

    page.toggle_pick_mode()
    assert page.pick_mode is True
    assert "Click a cell" in page.sweep_hint.text()

    page._cell_clicked(1, 2)  # SL 1.0, TP 2.0
    app.processEvents()

    assert page.pick_mode is False
    assert len(page.runs) == 1
    assert page.runs[0]["label"] == "TP 2 / SL 1"
    assert [chip.name() for chip in page.extra_chips] == ["TP 2 / SL 1"]
    # The table grew a column and the chart knows the extra curve.
    assert (1, 4) in page._cells
    assert page._cells[(1, 4)].text().endswith("%")
    assert page.chart.extra == [
        (page.runs[0]["colour"], page.runs[0]["report"].strategy)
    ]

    # The same cell twice is not added again.
    page.toggle_pick_mode()
    page._cell_clicked(1, 2)
    assert len(page.runs) == 1

    # Clicking its chip takes it back out.
    page.remove_run(page.extra_chips[0])
    app.processEvents()
    assert page.runs == []
    assert page.extra_chips == []
    assert (1, 4) not in page._cells
    assert page.chart.extra == []
    page.close()


def test_a_new_rule_clears_the_added_runs(app: QApplication) -> None:
    _write_year(2021, 600)
    bars, _ = load_bars("1m")
    entry, exit_ = _rules()
    report = backtest(bars, entry, exit_, tp=2.0, sl=1.0)

    page = ComparePage()
    page.resize(820, 320)
    page.show()
    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    page.toggle_pick_mode()
    page._cell_clicked(0, 0)
    app.processEvents()
    assert len(page.runs) == 1

    page.configure(bars, entry, exit_, report, 2.0, 1.0)
    app.processEvents()

    assert page.runs == []
    assert page.extra_chips == []
    assert (1, 4) not in page._cells
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
