"""The results tile's sample: deterministic, self-consistent, painted."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from lalala.strat_results import (  # noqa: E402
    CAPITAL,
    EquityCurve,
    ResultsTile,
    sample_run,
)
from lalala.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_the_sample_is_the_same_every_time() -> None:
    first = sample_run()
    second = sample_run()

    assert first == second
    assert first.equity[0] == pytest.approx(CAPITAL)
    assert len(first.equity) == first.days + 1
    assert len(first.benchmark) == first.days + 1


def test_the_metrics_agree_with_the_curve() -> None:
    run = sample_run()

    # One position at a time: equity only moves while a trade is open, and the
    # sample is flat the rest of the time.
    assert 0.0 < run.exposure < 1.0
    assert run.trade_returns and run.trade_holds
    assert sum(run.trade_holds) == pytest.approx(run.exposure * run.days, abs=1)

    # Total return is just the ends of the curve.
    assert run.total_return == pytest.approx(run.equity[-1] / CAPITAL - 1.0)
    drawdown, day = run.drawdown()
    assert drawdown <= 0.0
    # The trough is a fixed drop from the highest the book had reached by then
    # — not necessarily the lowest point of the whole run.
    peak = max(run.equity[: day + 1])
    assert run.equity[day] == pytest.approx(peak * (1.0 + drawdown))
    assert 0.0 <= run.win_rate <= 1.0
    assert len(run.metrics()) == 9


def test_the_tile_says_it_is_an_example(app: QApplication) -> None:
    tile = ResultsTile()
    tile.resize(600, 420)
    tile.show()
    app.processEvents()

    captions = [child.text() for child in tile.findChildren(QLabel)]
    # The label is what keeps a sample from being mistaken for a result.
    assert any("example data" in text for text in captions)

    image = tile.grab().toImage()
    assert not image.isNull()
    tile.close()


def test_the_metric_row_wraps(app: QApplication) -> None:
    from lalala.strat_results import NARROW_METRICS, WIDE_AT, WIDE_METRICS

    tile = ResultsTile()
    tile.resize(WIDE_AT + 60, 420)
    tile.show()
    app.processEvents()
    assert tile._metric_columns == WIDE_METRICS

    tile.resize(WIDE_AT - 200, 420)
    app.processEvents()
    assert tile._metric_columns == NARROW_METRICS
    # The fourth metric starts a new row once only three fit.
    caption = tile._metric_widgets[3][0]
    assert tile._metrics.getItemPosition(tile._metrics.indexOf(caption))[1] == 0
    tile.close()


def test_the_curve_paints_an_empty_size_without_complaining(
    app: QApplication,
) -> None:
    curve = EquityCurve(sample_run())
    curve.resize(20, 20)  # below the drawable floor
    curve.show()
    app.processEvents()

    assert not curve.grab().toImage().isNull()
    curve.close()
