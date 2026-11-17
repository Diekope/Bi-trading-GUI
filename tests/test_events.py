"""The trading log: the store, and the Logs view that reads it."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.state.events import EventLog  # noqa: E402
from bi_trading.ui.hub.logs_view import LogsView  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def log(tmp_path, app) -> EventLog:
    return EventLog(tmp_path / "events.jsonl")


def _fill(log: EventLog) -> None:
    log.record("info", "polymarket", "ORDER", "Buy UP 40c x 60", "auto")
    log.record("info", "polymarket", "FILLED", "UP 40c x 60 · $24.00", "auto", latency_ms=167)
    log.record("error", "polymarket", "REJECTED", "Buy UP 38c · no liquidity", "auto",
               request=["side: BUY", "error: insufficient liquidity"])
    log.record("warn", "hyperliquid", "LATENCY", "High latency 333 ms (limit 250 ms)")
    log.record("info", "hyperliquid", "CLOSED", "Close LONG BTC · +$0.31", "manual", pnl=0.31)
    log.record("info", "strategy", "SIGNAL", "Bollinger reversion", "auto",
               strategy="Bollinger", why=["close < band", "→ TRUE"])


# -- the store ----------------------------------------------------------------


def test_events_are_kept_in_order_and_counted(log: EventLog) -> None:
    _fill(log)

    assert [e.kind for e in log.events()][:3] == ["ORDER", "FILLED", "REJECTED"]
    counts = log.counts()
    assert counts["orders"] == 1
    assert counts["filled"] == 1
    assert counts["rejected"] == 1
    assert counts["warnings"] == 1
    assert counts["pnl"] == pytest.approx(0.31)


def test_events_survive_a_restart(tmp_path, app) -> None:
    first = EventLog(tmp_path / "events.jsonl")
    _fill(first)

    again = EventLog(tmp_path / "events.jsonl")
    assert [e.kind for e in again.events()] == [e.kind for e in first.events()]
    assert again.events()[1].detail["latency_ms"] == 167


def test_a_torn_line_in_the_file_is_skipped(tmp_path, app) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"not": "an event"}\nnot json at all\n')
    assert EventLog(path).events() == []


def test_clear_empties_the_log_and_the_file(tmp_path, app) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    _fill(log)
    log.clear()

    assert log.events() == []
    assert EventLog(tmp_path / "events.jsonl").events() == []


def test_the_log_is_capped(tmp_path, app) -> None:
    log = EventLog(tmp_path / "events.jsonl", keep=3)
    for number in range(10):
        log.record("info", "system", "NOTE", f"event {number}")
    assert [e.message for e in log.events()] == ["event 7", "event 8", "event 9"]


def test_export_writes_a_csv(log: EventLog, tmp_path) -> None:
    _fill(log)
    target = tmp_path / "out.csv"

    assert log.export_csv(target) == 6
    lines = target.read_text().splitlines()
    assert lines[0].startswith("time,level,source,origin,strategy,event,message,pnl")
    assert len(lines) == 7


# -- the view -----------------------------------------------------------------


def test_the_view_shows_newest_first_and_todays_figures(app, log: EventLog) -> None:
    _fill(log)
    view = LogsView(log)
    try:
        assert view.table.rowCount() == 6
        assert view.table.item(0, 4).text() == "SIGNAL"      # the newest
        assert view.table.item(5, 4).text() == "ORDER"
        assert "$0.31" in view._stat["pnl"].text()
        assert "Showing 6 of 6 events" in view._count.text()
    finally:
        view.close()


def test_the_filters_narrow_the_table(app, log: EventLog) -> None:
    _fill(log)
    view = LogsView(log)
    try:
        view._pick_source("polymarket")
        assert view.table.rowCount() == 3

        view.level.setCurrentText("Error")
        assert view.table.rowCount() == 1
        assert view.table.item(0, 4).text() == "REJECTED"

        view.level.setCurrentIndex(0)
        view.origin.setCurrentText("Manual")
        assert view.table.rowCount() == 0          # polymarket + manual: none

        view._pick_source("all")
        assert view.table.rowCount() == 1          # the manual close
        view.origin.setCurrentIndex(0)

        view.search.setText("liquidity")
        assert view.table.rowCount() == 1
    finally:
        view.close()


def test_picking_an_event_shows_why_and_the_request(app, log: EventLog) -> None:
    _fill(log)
    view = LogsView(log)
    try:
        view.search.setText("liquidity")
        view.table.selectRow(0)
        assert view._d_kind.text() == "REJECTED"
        assert view._d_request.isHidden() is False
        assert "insufficient liquidity" in view._d_request.text()
        assert view._d_why.isHidden() is True

        view.search.setText("")
        view._pick_source("strategy")
        view.table.selectRow(0)
        assert view._d_why.isHidden() is False
        assert "→ TRUE" in view._d_why.text()
        assert "Auto · Bollinger" in view._d_rows["origin"].text()
    finally:
        view.close()


def test_a_new_event_appears_unless_paused(app, log: EventLog) -> None:
    view = LogsView(log)
    try:
        log.record("info", "system", "CONNECTION", "Hyperliquid reconnected")
        assert view.table.rowCount() == 1

        view._toggle_pause()
        log.record("info", "system", "CONNECTION", "Polymarket reconnected")
        assert view.table.rowCount() == 1           # held while paused
        assert view.pause_button.text() == "Resume"

        view._toggle_pause()
        assert view.table.rowCount() == 2
    finally:
        view.close()


def test_clear_empties_the_table(app, log: EventLog) -> None:
    _fill(log)
    view = LogsView(log)
    try:
        log.clear()
        assert view.table.rowCount() == 0
        assert "Showing 0 of 0" in view._count.text()
    finally:
        view.close()


def test_open_in_live_is_signalled(app, log: EventLog) -> None:
    view = LogsView(log)
    seen: list[bool] = []
    view.open_live.connect(lambda: seen.append(True))
    try:
        view.findChildren(type(view.pause_button))[-1]  # the buttons exist
        next(b for b in view.findChildren(type(view.pause_button))
             if b.text() == "Open in Live").click()
        assert seen == [True]
    finally:
        view.close()


# -- the hub ------------------------------------------------------------------


def test_the_hub_opens_the_logs_view_from_the_rail(app, monkeypatch, tmp_path) -> None:
    from bi_trading.state import events
    from bi_trading.ui.hub.main_hub import MainHubWindow

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(events, "_log", EventLog(tmp_path / "events.jsonl"))
    window = MainHubWindow(autostart=False)
    try:
        window._open("logs")
        assert type(window._view).__name__ == "LogsView"
        assert "logs" in window._nav_buttons
    finally:
        window.close()


def test_the_hub_logs_a_latency_warning_once_and_the_recovery(
    app, monkeypatch, tmp_path
) -> None:
    from bi_trading.state import events
    from bi_trading.ui.hub.main_hub import MainHubWindow

    log = EventLog(tmp_path / "events.jsonl")
    monkeypatch.setattr(events, "_log", log)
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    try:
        window._on_hl_latency(120.0)
        window._on_hl_latency(333.0)
        window._on_hl_latency(340.0)               # still slow: no second warning
        window._on_hl_latency(90.0)
        kinds = [(e.level, e.kind) for e in log.events()]
        assert kinds == [("warn", "LATENCY"), ("info", "LATENCY")]
        assert "limit 250 ms" in log.events()[0].message
    finally:
        window.close()


def test_a_connection_that_drops_and_returns_is_logged(
    app, monkeypatch, tmp_path
) -> None:
    from bi_trading.state import events
    from bi_trading.ui.hub.main_hub import MainHubWindow

    log = EventLog(tmp_path / "events.jsonl")
    monkeypatch.setattr(events, "_log", log)
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    try:
        window._on_hl_connected(False)             # not connected yet: not news
        window._on_hl_connected(True)
        window._on_hl_connected(False)
        window._on_hl_connected(True)
        assert [e.message for e in log.events()] == [
            "Hyperliquid connected", "Hyperliquid disconnected",
            "Hyperliquid reconnected",
        ]
    finally:
        window.close()


# -- loading only the newest, and the Parquet archive -------------------------


def _write_lines(path, count: int, start: float = 1_000.0) -> None:
    """`count` old events, one per second from `start`, as the hot file holds them."""
    import json
    from dataclasses import asdict

    from bi_trading.state.events import Event

    with open(path, "w") as handle:
        for number in range(count):
            event = Event(start + number, "info", "system", "NOTE", f"event {number}")
            handle.write(json.dumps(asdict(event)) + "\n")


def test_only_the_newest_500_are_loaded(tmp_path, app) -> None:
    _write_lines(tmp_path / "events.jsonl", 1_200)

    log = EventLog(tmp_path / "events.jsonl")
    assert len(log.events()) == 500
    assert log.events()[-1].message == "event 1199"
    assert log.events()[0].message == "event 700"
    assert log.has_older() and log.stored() == 700


def test_load_older_brings_the_next_500(tmp_path, app) -> None:
    _write_lines(tmp_path / "events.jsonl", 1_200)
    log = EventLog(tmp_path / "events.jsonl")
    heard: list[bool] = []
    log.reloaded.connect(lambda: heard.append(True))

    assert log.load_older() == 500
    assert log.events()[0].message == "event 200"
    assert log.events()[-1].message == "event 1199"      # still in order
    assert log.load_older() == 200
    assert log.has_older() is False
    assert len(log.events()) == 1_200
    assert heard == [True, True]


def test_a_short_history_stays_json_and_a_long_one_moves_to_parquet(tmp_path, app) -> None:
    small = tmp_path / "small"
    small.mkdir()
    _write_lines(small / "events.jsonl", 900)
    EventLog(small / "events.jsonl")
    assert not (small / "events.parquet").exists()          # small: JSON only

    big = tmp_path / "big"
    big.mkdir()
    _write_lines(big / "events.jsonl", 2_600)
    log = EventLog(big / "events.jsonl")
    assert (big / "events.parquet").exists()                # long: archived
    assert len((big / "events.jsonl").read_text().splitlines()) == 500
    assert len(log.events()) == 500
    assert log.stored() == 2_100


def test_archived_events_load_back_and_export(tmp_path, app) -> None:
    _write_lines(tmp_path / "events.jsonl", 2_600)
    log = EventLog(tmp_path / "events.jsonl")

    assert log.load_older() == 500                          # from the archive
    assert log.events()[0].message == "event 1600"
    assert log.events()[-1].message == "event 2599"

    out = tmp_path / "all.csv"
    assert log.export_csv(out) == 2_600                     # export is everything
    assert len(out.read_text().splitlines()) == 2_601
    assert log.export_csv(out, everything=False) == 1_000   # or only what is loaded


def test_a_restart_after_archiving_loses_nothing(tmp_path, app) -> None:
    _write_lines(tmp_path / "events.jsonl", 2_600)
    first = EventLog(tmp_path / "events.jsonl")
    first.record("info", "system", "NOTE", "fresh")

    again = EventLog(tmp_path / "events.jsonl")
    assert again.events()[-1].message == "fresh"
    assert len(again.all_events()) == 2_601


def test_a_busy_day_is_loaded_whole(tmp_path, app) -> None:
    import json
    from dataclasses import asdict
    from datetime import datetime, time as clock

    from bi_trading.state.events import Event

    midnight = datetime.combine(datetime.now().date(), clock.min).timestamp()
    with open(tmp_path / "events.jsonl", "w") as handle:
        for number in range(700):          # 700 warnings, all of today
            event = Event(midnight + 1 + number * 0.001, "warn", "system", "NOTE", str(number))
            handle.write(json.dumps(asdict(event)) + "\n")

    log = EventLog(tmp_path / "events.jsonl")
    # More than 500 were loaded, because the day's figures must count the day.
    assert len(log.events()) == 700
    assert log.counts()["warnings"] == 700
    assert log.has_older() is False


def test_clear_removes_the_archive_too(tmp_path, app) -> None:
    _write_lines(tmp_path / "events.jsonl", 2_600)
    log = EventLog(tmp_path / "events.jsonl")
    log.clear()

    assert not (tmp_path / "events.parquet").exists()
    assert log.has_older() is False
    assert EventLog(tmp_path / "events.jsonl").all_events() == []


# -- per-strategy -------------------------------------------------------------


def _two_strategies(log: EventLog) -> None:
    log.record("info", "strategy", "SIGNAL", "a fired", "auto", "Bollinger")
    log.record("info", "polymarket", "ORDER", "a bet", "auto", "Bollinger")
    log.record("info", "polymarket", "FILLED", "a fill", "auto", "Bollinger")
    log.record("info", "polymarket", "CLOSED", "a close", "auto", "Bollinger", pnl=5.0)
    log.record("info", "strategy", "SIGNAL", "b fired", "auto", "Momentum")
    log.record("info", "polymarket", "ORDER", "b bet", "auto", "Momentum")
    log.record("error", "polymarket", "REJECTED", "b refused", "auto", "Momentum")
    log.record("info", "hyperliquid", "CLOSED", "manual close", "manual", pnl=-1.5)


def test_the_figures_can_be_taken_for_one_strategy(log: EventLog) -> None:
    _two_strategies(log)

    assert log.strategies() == ["Bollinger", "Momentum"]
    everything = log.counts()
    assert everything["orders"] == 2 and everything["pnl"] == pytest.approx(3.5)

    bollinger = log.counts("Bollinger")
    assert bollinger == {"orders": 1, "filled": 1, "rejected": 0, "warnings": 0,
                         "signals": 1, "pnl": 5.0}
    momentum = log.counts("Momentum")
    assert momentum["rejected"] == 1 and momentum["pnl"] == 0.0


def test_the_view_filters_and_totals_by_strategy(app, log: EventLog) -> None:
    _two_strategies(log)
    view = LogsView(log)
    try:
        assert [view.strategy.itemText(i) for i in range(view.strategy.count())] == [
            "Strategy: all", "Bollinger", "Momentum",
        ]
        assert view.table.rowCount() == 8

        view.strategy.setCurrentText("Bollinger")
        assert view.table.rowCount() == 4
        assert "+$5.00" in view._stat["pnl"].text()
        assert view._stat["orders"].text() == "1"
        assert "Showing 4 of 4 events" in view._count.text()

        view.strategy.setCurrentText("Momentum")
        assert view._stat["rejected"].text() != "0"
        assert view._stat["pnl"].text() == "$0.00"

        view.strategy.setCurrentIndex(0)
        assert view.table.rowCount() == 8
    finally:
        view.close()


def test_a_strategy_that_first_appears_later_joins_the_filter(app, log: EventLog) -> None:
    view = LogsView(log)
    try:
        assert view.strategy.count() == 1
        log.record("info", "strategy", "SIGNAL", "fired", "auto", "Fresh")
        assert view.strategy.findText("Fresh") == 1
    finally:
        view.close()


def test_the_view_offers_older_events_and_loads_them(tmp_path, app) -> None:
    _write_lines(tmp_path / "events.jsonl", 1_200)
    log = EventLog(tmp_path / "events.jsonl")
    view = LogsView(log)
    try:
        assert view.older_button.isHidden() is False
        assert "700 older stored" in view._count.text()
        view.older_button.click()
        assert view.older_button.isHidden() is False        # 200 still stored
        view.older_button.click()
        assert view.older_button.isHidden() is True
    finally:
        view.close()
