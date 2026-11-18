"""Remembering where the splitters and windows were left."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QSplitter, QWidget  # noqa: E402

from bi_trading.state import settings  # noqa: E402
from bi_trading.ui.layout_memory import remember_splitter, remember_window  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def own_file(monkeypatch, tmp_path):
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    return tmp_path / "settings.json"


def _splitter(count: int = 2, width: int = 1000) -> QSplitter:
    splitter = QSplitter(Qt.Orientation.Horizontal)
    for _ in range(count):
        splitter.addWidget(QWidget())
    splitter.resize(width, 200)
    splitter.show()
    return splitter


def test_a_split_is_saved_as_ratios_and_read_back(own_file) -> None:
    settings.save_splitter("a", [300, 700])
    assert settings.load_splitter("a") == [0.3, 0.7]
    assert json.loads(own_file.read_text())["layout"]["splitters"]["a"] == [0.3, 0.7]


def test_saving_one_keeps_the_others_and_the_rest_of_the_file(own_file) -> None:
    own_file.write_text(json.dumps({"backtest": {"tp": 3.0}}))
    settings.save_splitter("a", [1, 1])
    settings.save_splitter("b", [1, 3])

    data = json.loads(own_file.read_text())
    assert data["backtest"] == {"tp": 3.0}
    assert data["layout"]["splitters"] == {"a": [0.5, 0.5], "b": [0.25, 0.75]}


@pytest.mark.parametrize("sizes", [[0, 500], [500, 0], [], [0, 0]])
def test_a_collapsed_or_empty_split_is_not_saved(sizes) -> None:
    settings.save_splitter("a", sizes)
    assert settings.load_splitter("a") == []


@pytest.mark.parametrize(
    "junk",
    [{"layout": "nope"}, {"layout": {"splitters": []}}, {"layout": {"splitters": {"a": "x"}}},
     {"layout": {"splitters": {"a": [1, -1]}}}, {"layout": {"splitters": {"a": [True, 1]}}}],
)
def test_a_damaged_setting_is_ignored(own_file, junk) -> None:
    own_file.write_text(json.dumps(junk))
    assert settings.load_splitter("a") == []


def test_a_splitter_opens_as_it_was_left(app, own_file) -> None:
    settings.save_splitter("cols", [250, 750])
    splitter = _splitter()
    remember_splitter(splitter, "cols")
    app.processEvents()

    left, right = splitter.sizes()
    assert left / (left + right) == pytest.approx(0.25, abs=0.03)
    splitter.close()


def test_the_same_split_holds_at_another_window_size(app, own_file) -> None:
    settings.save_splitter("cols", [250, 750])
    splitter = _splitter(width=2000)
    remember_splitter(splitter, "cols")
    app.processEvents()
    left, right = splitter.sizes()
    assert left / (left + right) == pytest.approx(0.25, abs=0.03)
    splitter.close()


def test_dragging_saves_the_new_split_after_a_pause(app, own_file, qtbot=None) -> None:
    import time

    splitter = _splitter()
    remember_splitter(splitter, "cols")
    splitter.setSizes([400, 600])
    splitter.splitterMoved.emit(400, 1)          # what a drag emits

    assert settings.load_splitter("cols") == []     # not yet: it waits for a pause
    deadline = time.time() + 3
    while not settings.load_splitter("cols") and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    saved = settings.load_splitter("cols")
    assert saved and saved[0] == pytest.approx(0.4, abs=0.03)
    splitter.close()


def test_a_different_pane_count_keeps_the_default(app, own_file) -> None:
    settings.save_splitter("cols", [1, 1, 1])        # saved for three panes
    splitter = _splitter(count=2)
    before = splitter.sizes()
    remember_splitter(splitter, "cols")
    assert splitter.sizes() == before
    splitter.close()


def test_a_window_is_restored_and_saved_on_quit(app, own_file) -> None:
    window = QWidget()
    window.resize(777, 555)
    window.show()
    remember_window(window, "demo")
    app.aboutToQuit.emit()
    assert settings.load_window("demo")

    other = QWidget()
    other.show()
    remember_window(other, "demo")
    app.processEvents()
    assert (other.width(), other.height()) == (777, 555)
    window.close()
    other.close()


def test_the_backtest_and_terminal_columns_remember_their_split(app, own_file) -> None:
    from bi_trading.ui.main_window import MainWindow
    from bi_trading.ui.strat.strat_window import StratWindow

    settings.save_splitter("backtest.columns", [200, 800])
    settings.save_splitter("terminal.columns", [700, 300])
    strat = StratWindow()
    terminal = MainWindow(autostart=False)
    try:
        for window in (strat, terminal):
            window.show()
        app.processEvents()
        a, b = strat.splitter.sizes()
        assert a / (a + b) == pytest.approx(0.2, abs=0.04)
        c, d = terminal.splitter.sizes()
        assert c / (c + d) == pytest.approx(0.7, abs=0.04)
    finally:
        strat.close()
        terminal.close()
