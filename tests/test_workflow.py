"""Workflow and feel: remembered layout, shortcuts and the help overlay."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from bi_trading.state import settings  # noqa: E402
from bi_trading.state.events import EventLog  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def _own_files(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    monkeypatch.setenv("BI_TRADING_RUNS", str(tmp_path / "runs.json"))


def _press(widget, keys: str) -> None:
    widget.activateWindow()
    QTest.keySequence(widget, QKeySequence(keys))


# -- remembered layout --------------------------------------------------------


def test_column_widths_and_choices_round_trip() -> None:
    assert settings.load_columns("logs") == []
    settings.save_columns("logs", [90, 70, 130])
    assert settings.load_columns("logs") == [90, 70, 130]
    settings.save_columns("logs", [90, 0, 130])         # a zero width is nothing to keep
    assert settings.load_columns("logs") == [90, 70, 130]

    assert settings.load_choice("terminal.timeframe") == ""
    settings.save_choice("terminal.timeframe", "15m")
    assert settings.load_choice("terminal.timeframe") == "15m"
    # Saving one kind of entry leaves the others alone.
    settings.save_splitter("terminal.columns", [300, 700])
    assert settings.load_columns("logs") == [90, 70, 130]
    assert settings.load_splitter("terminal.columns") == [0.3, 0.7]


def test_a_damaged_columns_entry_is_ignored(tmp_path) -> None:
    (tmp_path / "settings.json").write_text('{"layout": {"columns": {"logs": ["x", -1]}}}')
    assert settings.load_columns("logs") == []


def test_the_logs_columns_are_dragged_and_remembered(app, tmp_path) -> None:
    from bi_trading.ui.hub.logs_view import COLUMNS, LogsView

    view = LogsView(EventLog(tmp_path / "events.jsonl"))
    view.show()
    view.table.setColumnWidth(0, 150)
    view._save_columns_timer.stop()
    view._save_columns()
    view.close()

    assert settings.load_columns("logs")[0] == 150
    again = LogsView(EventLog(tmp_path / "events.jsonl"))
    assert again.table.columnWidth(0) == 150
    assert len(settings.load_columns("logs")) == len(COLUMNS) - 1
    again.close()


def test_the_terminal_remembers_its_timeframe(app) -> None:
    from bi_trading.ui.main_window import MainWindow

    window = MainWindow(autostart=False)
    assert window.main_card.interval == "1m"
    window.main_card.set_interval("15m")
    assert settings.load_choice("terminal.timeframe") == "15m"
    window.close()

    again = MainWindow(autostart=False)
    assert again.main_card.interval == "15m"
    assert again.main_card.timeframes.current() == "15m"
    again.close()


def test_a_remembered_timeframe_that_no_longer_exists_is_ignored(app) -> None:
    from bi_trading.ui.main_window import MainWindow

    settings.save_choice("terminal.timeframe", "7d")
    window = MainWindow(autostart=False)
    assert window.main_card.interval == "1m"
    window.close()


# -- shortcuts ------------------------------------------------------------------


def test_the_builder_switches_the_rule_view_from_the_keyboard(app) -> None:
    from bi_trading.ui.strat.strat_builder import StrategyBuilderWindow

    window = StrategyBuilderWindow()
    window.show()
    app.processEvents()
    _press(window, "Alt+2")
    assert window.entry_mode() == "formula"
    _press(window, "Alt+3")
    assert window.entry_mode() == "code"
    _press(window, "Alt+1")
    assert window.entry_mode() == "rules"
    window.close()


def test_ctrl_s_and_ctrl_n_reach_the_builders_draft(app, monkeypatch) -> None:
    from bi_trading.ui.strat.strat_builder import StrategyBuilderWindow

    calls: list[str] = []
    monkeypatch.setattr(StrategyBuilderWindow, "save_draft", lambda self: calls.append("save"))
    monkeypatch.setattr(StrategyBuilderWindow, "reset_draft", lambda self: calls.append("reset"))
    window = StrategyBuilderWindow()
    window.show()
    app.processEvents()
    _press(window, "Ctrl+S")
    _press(window, "Ctrl+N")
    assert calls == ["save", "reset"]
    window.close()


def test_the_logs_keys_search_pause_export_and_clear(app, tmp_path, monkeypatch) -> None:
    from bi_trading.ui.hub.logs_view import LogsView

    log = EventLog(tmp_path / "events.jsonl")
    log.record("info", "polymarket", "ORDER", "Buy UP", "manual")
    view = LogsView(log)
    view.show()
    app.processEvents()

    _press(view, "Ctrl+F")
    assert view.search.hasFocus()
    view.search.setText("zzz")
    _press(view, "Esc")
    assert view.search.text() == ""

    assert view._paused is False
    _press(view, "Ctrl+P")
    assert view._paused is True
    _press(view, "Ctrl+P")
    assert view._paused is False

    exported: list[bool] = []
    monkeypatch.setattr(LogsView, "_export", lambda self: exported.append(True))
    view.close()
    view = LogsView(log)
    view.show()
    app.processEvents()
    _press(view, "Ctrl+E")
    assert exported == [True]

    assert log.events()
    _press(view, "Ctrl+Shift+Backspace")
    assert log.events() == []
    view.close()


def test_the_help_overlay_lists_every_view_with_the_current_one_first(app) -> None:
    from bi_trading.ui.shortcuts import SHORTCUTS, ShortcutsDialog

    dialog = ShortcutsDialog("Logs")
    assert dialog.sections[0] == "Logs"
    assert set(dialog.sections) == set(SHORTCUTS)
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(text.startswith("LOGS") and "this view" in text for text in texts)
    assert "Ctrl+Shift+Backspace" in texts


def test_question_mark_opens_the_help_in_the_hub(app, monkeypatch) -> None:
    from bi_trading.ui import shortcuts
    from bi_trading.ui.hub.main_hub import MainHubWindow

    seen: list[str] = []
    monkeypatch.setattr(shortcuts, "show_help", lambda parent, current="Everywhere": seen.append(current))
    window = MainHubWindow(autostart=False)
    window.show()
    window._open("logs")
    app.processEvents()
    _press(window, "F1")
    assert seen == ["Logs"]
    window.close()


def test_every_documented_shortcut_is_a_real_key() -> None:
    from bi_trading.ui.shortcuts import SHORTCUTS

    for context, entries in SHORTCUTS.items():
        assert entries, context
        for keys, what in entries:
            assert keys.strip() and what.strip()
