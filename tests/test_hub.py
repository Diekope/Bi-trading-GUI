"""The hub shell: the configured start page and in-place navigation."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from bi_trading.ui.hub.main_hub import MainHubWindow  # noqa: E402
from bi_trading.state.positions import store  # noqa: E402
from bi_trading.state.settings import Settings, load_window_geometry, save_window_geometry  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_the_hub_opens_home_without_a_start_page(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))

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
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(path))

    window = MainHubWindow(autostart=False)
    try:
        assert window._key == "live"
        assert type(window._view).__name__ == "MainWindow"
    finally:
        window.close()


def test_the_rail_quit_button_closes_the_app(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    window.show()
    app.processEvents()

    button = next(
        b for b in window.findChildren(QPushButton) if b.toolTip() == "Quit bi-trading"
    )
    button.click()
    app.processEvents()

    assert not window.isVisible()


# -- the shortcuts ---------------------------------------------------------


def test_the_hub_binds_view_shortcuts(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    try:
        keys = sorted(s.key().toString() for s in window.findChildren(QShortcut))
        assert keys == [
            "?", "Ctrl+,", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6", "F1",
        ]
    finally:
        window.close()


# -- the window remembers its size -----------------------------------------


def test_the_hub_geometry_round_trips(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))

    assert load_window_geometry() == ""
    save_window_geometry("Z2VvbWV0cnk=")
    assert load_window_geometry() == "Z2VvbWV0cnk="
    # The rest of the file is untouched.
    assert Settings.load().backtest.sizing in ("balance", "fixed", "risk")


# -- the open position card ------------------------------------------------


def test_the_home_shows_a_balance_card_per_provider(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(tmp_path / "secrets.json"))
    window = MainHubWindow(autostart=False)
    try:
        assert window._stat_values["Hyperliquid balance"].text() == "—"
        assert window._stat_subs["Hyperliquid balance"].text() == "not connected"
        assert window._stat_values["Polymarket balance"].text() == "—"
        assert window._stat_subs["Polymarket balance"].text() == "not connected"
    finally:
        window.close()


def test_a_connected_balance_card_shows_the_side(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    from bi_trading.state.accounts import (
        Accounts,
        HL_KEY,
        HyperliquidAccount,
        save_accounts,
        set_secret,
    )

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(tmp_path / "secrets.json"))
    set_secret(HL_KEY, "0x" + "ab" * 32)
    save_accounts(
        Accounts(hyperliquid=HyperliquidAccount(address="0x" + "cd" * 20))
    )

    window = MainHubWindow(autostart=False)
    try:
        window._on_balance("hyperliquid", 1_234.5)
        assert window._stat_values["Hyperliquid balance"].text() == "$1,234.50"
        assert window._stat_subs["Hyperliquid balance"].text() == "USDC · flat"

        store().set({"side": "LONG", "leverage": 5, "size": 100.0, "entry": 1.0})
        window._on_balance("hyperliquid", 1_234.5)
        assert window._stat_subs["Hyperliquid balance"].text() == "USDC · long"
    finally:
        window.close()


def test_the_rail_shows_a_compact_balance_per_venue(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(tmp_path / "secrets.json"))
    window = MainHubWindow(autostart=False)
    try:
        assert set(window._rail_balances) == {"pm", "hl"}

        window._on_balance("hyperliquid", 1_234.5)
        window._on_balance("polymarket", 250.0)
        assert window._rail_balances["hl"].text() == "$1.2k"
        assert window._rail_balances["pm"].text() == "$250"
    finally:
        window.close()


def test_money_short_reads_at_a_glance() -> None:
    from bi_trading.ui.hub.main_hub import _money_short

    assert _money_short(250.0) == "$250"
    assert _money_short(1_234.5) == "$1.2k"
    assert _money_short(12_345.0) == "$12k"
    assert _money_short(2_400_000.0) == "$2.4M"


def test_the_open_position_card_follows_the_shared_store(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
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


def test_the_home_balance_card_says_testnet(app: QApplication, monkeypatch, tmp_path) -> None:
    from bi_trading.state.accounts import Accounts, HL_KEY, HyperliquidAccount, save_accounts, set_secret

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("BI_TRADING_KEYCHAIN", "0")
    set_secret(HL_KEY, "0x" + "ab" * 32)
    for testnet, expected in ((True, True), (False, False)):
        save_accounts(Accounts(hyperliquid=HyperliquidAccount(address="0x" + "cd" * 20, testnet=testnet)))
        window = MainHubWindow(autostart=False)
        window._refresh_balances()
        assert ("TESTNET" in window._stat_subs["Hyperliquid balance"].text()) is expected
        window.close()


def test_the_hub_starts_with_logging_pointed_at_a_file(monkeypatch, tmp_path) -> None:
    """The hub's own entry point set up no logging, so every dropped socket printed
    its traceback over the terminal it was launched from."""
    import logging

    from bi_trading import logs
    from bi_trading.ui.hub import main_hub

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_LOG", str(tmp_path / "bi-trading.log"))
    logs.reset()
    calls: list[str] = []

    class FakeApp:
        def __init__(self, argv) -> None:
            pass

        def setApplicationName(self, name) -> None:  # noqa: N802
            pass

        def setOrganizationName(self, name) -> None:  # noqa: N802
            pass

        @staticmethod
        def setHighDpiScaleFactorRoundingPolicy(policy) -> None:  # noqa: N802
            calls.append("dpi")

        def exec(self) -> int:
            calls.append("exec")
            return 0

    class FakeWindow:
        def show(self) -> None:
            pass

        def raise_(self) -> None:
            pass

        def activateWindow(self) -> None:  # noqa: N802
            pass

    monkeypatch.setattr(main_hub, "QApplication", FakeApp)
    monkeypatch.setattr(main_hub, "MainHubWindow", FakeWindow)
    monkeypatch.setattr("bi_trading.ui.theme.apply_theme", lambda app: None)
    monkeypatch.setattr(logs, "install_qt_handler", lambda: calls.append("qt"))
    try:
        assert main_hub.run([]) == 0
        # Logging goes to the file, and there is no console handler to scribble with.
        handlers = logging.getLogger().handlers
        assert any(getattr(h, "baseFilename", "").endswith("bi-trading.log") for h in handlers)
        assert not any(isinstance(h, logging.StreamHandler) and not hasattr(h, "baseFilename")
                       for h in handlers)
        logging.getLogger("bi_trading.test").warning("a dropped socket")
        for handler in handlers:
            handler.flush()
        assert "a dropped socket" in (tmp_path / "bi-trading.log").read_text()
    finally:
        logs.reset()
    assert calls[:2] == ["qt", "dpi"] and calls[-1] == "exec"
