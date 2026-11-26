"""The venue basis report: the gap between the stored history and the venue's bars."""

from __future__ import annotations

import json

import numpy as np
import pytest

from bi_trading.data import basis


@pytest.fixture(autouse=True)
def where(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_BASIS", str(tmp_path / "basis.json"))


def bars(count=500, seed=1, offset=0.0, wick=1.0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, count)))
    open_ = np.r_[close[0], close[:-1]]
    span = np.abs(rng.normal(0.001, 0.0004, count)) * close
    return {
        "stamps": np.arange(count, dtype=np.int64) * basis.MINUTE_MS,
        "open": open_ + offset, "close": close + offset,
        "high": np.maximum(open_, close) + offset + span * wick,
        "low": np.minimum(open_, close) + offset - span * wick,
    }


def test_identical_bars_have_no_gap() -> None:
    report = basis.compare(bars(), bars())
    assert report["bars"] == 500
    assert report["median_abs_bps"] == pytest.approx(0.0)
    assert report["range_ratio"] == pytest.approx(1.0)
    assert report["touch_disagree_up"] == 0.0 and report["touch_disagree_down"] == 0.0


def test_a_price_offset_shows_as_basis_points() -> None:
    report = basis.compare(bars(), bars(offset=0.05))     # about 5 bps on a price near 100
    assert report["mean_bps"] == pytest.approx(5.0, abs=1.0)
    assert report["median_abs_bps"] == pytest.approx(5.0, abs=1.0)


def test_wider_venue_wicks_show_in_the_range_and_the_touches() -> None:
    report = basis.compare(bars(), bars(wick=3.0))
    assert report["range_ratio"] > 1.5
    assert report["touch_disagree_up"] > 0.05 or report["touch_disagree_down"] > 0.05


def test_bars_are_matched_by_stamp_not_position() -> None:
    mine = bars()
    theirs = {k: v[10:] for k, v in bars().items()}
    assert basis.compare(mine, theirs)["bars"] == 490
    assert basis.compare(bars(20), bars(20)) == {"bars": 20}        # too few to say


def test_fetch_parses_the_venues_rows_and_skips_bad_ones() -> None:
    seen = {}

    def post(body):
        seen.update(body)
        return [
            {"t": 120_000, "o": "2", "h": "3", "l": "1", "c": "2.5"},
            {"t": 60_000, "o": "1", "h": "2", "l": "0.5", "c": "1.5"},
            {"t": "x"},
        ]

    out = basis.fetch_venue(post)
    assert seen["type"] == "candleSnapshot" and seen["req"]["interval"] == "1m"
    assert out["stamps"].tolist() == [60_000, 120_000]       # sorted
    assert out["close"].tolist() == [1.5, 2.5]


def test_the_summary_says_so_when_nothing_was_compared() -> None:
    assert "not compared" in basis.summary(None)
    assert basis.latest_basis() is None


def test_a_saved_report_is_read_back_and_summarised() -> None:
    report = basis.compare(bars(), bars(offset=0.05, wick=2.0))
    report["made_at"] = 1_000.0
    basis.report_path().write_text(json.dumps(report))
    line = basis.summary(basis.latest_basis(), now=1_000.0 + 40 * 86400)
    assert "500 bars" in line and "40 days old" in line and "bps" in line
