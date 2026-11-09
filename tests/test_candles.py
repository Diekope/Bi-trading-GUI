"""The local candle store: where files live, and what counts as complete."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lalala import candles
from lalala.candles import (
    COMPLETE,
    COMPLETE_STATE,
    MISSING,
    PARTIAL,
    append_rows,
    candle_file,
    coverage,
    expected_rows,
    format_years,
    last_timestamp,
    row_count,
    year_state,
)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LALALA_DATA", str(tmp_path / "candles"))
    candles._ROW_CACHE.clear()


def _rows(count: int, start: int = 0) -> list[tuple[int, float, float, float, float, float]]:
    return [(start + i * 60_000, 1.0, 2.0, 0.5, 1.5, 10.0) for i in range(count)]


def test_files_are_one_per_year_at_one_minute() -> None:
    assert candle_file(2019).name == "BTC-2019-1m.csv"
    assert candle_file(2019).parent == candles.candles_dir()


def test_the_settings_folder_is_used_when_the_environment_is_silent(
    tmp_path, monkeypatch
) -> None:
    import json

    monkeypatch.delenv("LALALA_DATA", raising=False)
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"general": {"data_folder": str(tmp_path / "elsewhere")}})
    )
    monkeypatch.setenv("LALALA_SETTINGS", str(settings))

    assert candles.candles_dir() == tmp_path / "elsewhere"


def test_a_year_is_expected_from_the_calendar() -> None:
    assert expected_rows(2019, datetime(2020, 1, 1, tzinfo=timezone.utc)) == 365 * 1440
    # 2020 is a leap year.
    assert expected_rows(2020, datetime(2021, 1, 1, tzinfo=timezone.utc)) == 366 * 1440
    # The current year only counts up to today: at 2024-03-01T00:00Z the last
    # closed bar is 2024-02-29T23:59Z.
    now = datetime(2024, 3, 1, tzinfo=timezone.utc)
    assert expected_rows(2024, now) == (31 + 29) * 1440


def test_2017_is_only_expected_from_the_pair_listing() -> None:
    # BTCUSDT opened on 2017-08-17T04:00Z, so that year can never hold twelve
    # months of minutes, and its Download must still be able to finish.
    expected = expected_rows(2017, datetime(2018, 1, 1, tzinfo=timezone.utc))

    assert expected == 197_040
    # Binance's real 2017 coverage (with its few outages) clears the bar.
    assert 196_496 >= expected * COMPLETE


def test_append_writes_a_header_once_and_reads_back() -> None:
    path = candle_file(2018)

    assert append_rows(path, _rows(3)) == 3
    assert append_rows(path, _rows(2, start=3 * 60_000)) == 2

    text = path.read_text().splitlines()
    assert text[0] == "timestamp,open,high,low,close,volume"
    assert row_count(path) == 5
    assert last_timestamp(path) == 4 * 60_000


def test_last_timestamp_is_none_for_a_missing_file() -> None:
    assert last_timestamp(candle_file(2018)) is None
    assert row_count(candle_file(2018)) == 0


def test_year_state_reads_missing_partial_complete(monkeypatch) -> None:
    monkeypatch.setattr(candles, "expected_rows", lambda year, now=None: 10)
    path = candle_file(2018)

    assert year_state(2018) == MISSING
    append_rows(path, _rows(5))
    assert year_state(2018) == PARTIAL
    append_rows(path, _rows(5, start=5 * 60_000))
    assert year_state(2018) == COMPLETE_STATE


def test_coverage_splits_missing_from_partial(monkeypatch) -> None:
    monkeypatch.setattr(candles, "expected_rows", lambda year, now=None: 10)
    append_rows(candle_file(2017), _rows(3))   # partial
    append_rows(candle_file(2018), _rows(10))  # complete
    # 2019 is never written.

    missing, partial = coverage(2017, 2019)
    assert missing == [2019]
    assert partial == [2017]


def test_years_are_shown_as_a_range_when_contiguous() -> None:
    assert format_years([]) == ""
    assert format_years([2017]) == "2017"
    assert format_years([2017, 2018, 2019]) == "2017–2019"
    assert format_years([2017, 2019]) == "2017, 2019"
