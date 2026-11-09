"""The hub shell: the configured start page and in-place navigation."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from lalala.main_hub import MainHubWindow  # noqa: E402
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
