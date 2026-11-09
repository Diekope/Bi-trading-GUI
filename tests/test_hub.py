"""The hub shell: the configured start page and in-place navigation."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from lalala.main_hub import MainHubWindow  # noqa: E402
from lalala.positions import store  # noqa: E402
from lalala.settings import Settings, load_window_geometry, save_window_geometry  # noqa: E402
from lalala.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_the_hub_opens_home_without_a_start_page(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("LALALA_SETTINGS", str(tmp_path / "settings.json"))

    window = MainHubWindow(autostart=False)
    try:
        assert window._key == "home"
    finally:
        window.close()


def test_the_hub_opens_the_configured_start_page(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"general": {"start_page": "live"}}))
    monkeypatch.setenv("LALALA_SETTINGS", str(path))

    window = MainHubWindow(autostart=False)
    try:
        assert window._key == "live"
        assert type(window._view).__name__ == "MainWindow"
    finally:
        window.close()


def test_the_rail_quit_button_closes_the_app(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("LALALA_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    window.show()
    app.processEvents()

    button = next(
        b for b in window.findChildren(QPushButton) if b.toolTip() == "Quit lalala"
    )
    button.click()
    app.processEvents()

    assert not window.isVisible()


# -- the shortcuts ---------------------------------------------------------


def test_the_hub_binds_view_shortcuts(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("LALALA_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    try:
        keys = sorted(s.key().toString() for s in window.findChildren(QShortcut))
        assert keys == ["Ctrl+,", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4"]
    finally:
        window.close()


# -- the window remembers its size -----------------------------------------


def test_the_hub_geometry_round_trips(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LALALA_SETTINGS", str(tmp_path / "settings.json"))

    assert load_window_geometry() == ""
    save_window_geometry("Z2VvbWV0cnk=")
    assert load_window_geometry() == "Z2VvbWV0cnk="
    # The rest of the file is untouched.
    assert Settings.load().backtest.sizing in ("balance", "fixed", "risk")


# -- the open position card ------------------------------------------------


def test_the_open_position_card_follows_the_shared_store(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("LALALA_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    try:
        value = window._stat_values["Open position"]
        sub = window._stat_subs["Open position"]
        assert sub.text() == "no position"

        window._btc_price = 110.0
        store().set({"side": "LONG", "leverage": 5, "size": 2_000.0, "entry": 100.0})

        assert "▲" in value.text()
        assert "+$1,000.00" in value.text()
        assert sub.text() == "LONG 5× · BTC"

        store().set(None)
        assert value.text() == "—"
        assert sub.text() == "no position"
    finally:
        window.close()
