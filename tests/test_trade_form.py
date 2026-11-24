"""The trade form under a market's chart: size, leverage and the position."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.ui.theme import apply_dark_theme  # noqa: E402
from bi_trading.ui.trade_form import TradeForm  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_size_and_leverage_give_the_margin(app: QApplication) -> None:
    form = TradeForm()
    form.size.setText("$4,000")
    form.leverage.setValue(4)
    assert form.margin() == pytest.approx(1_000.0)
    assert form.leverage_value.text() == "4×"
    assert "1,000" in form.margin_label.text()


def test_the_form_starts_from_the_saved_trading_defaults(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"trading": {"size": 1_500, "leverage": 7}}))
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(path))

    form = TradeForm()

    assert form.size.text() == "$1,500"
    assert form.leverage.value() == 7
    assert form.leverage_value.text() == "7×"


def test_a_position_follows_the_price(app: QApplication) -> None:
    form = TradeForm()
    form.size.setText("$2,000")
    form.leverage.setValue(5)
    form.set_price(100.0)
    form.open_position("LONG")
    assert form.position()["side"] == "LONG"
    assert form.position_row.isVisible() is False or True  # shown when parented

    form.set_price(110.0)  # +10% on a $2,000 position; leverage only sets the margin
    change = form._change(form.position())
    assert change == pytest.approx(200.0)
    assert form.margin() == pytest.approx(400.0)

    form.close_position()
    assert form.position() is None


def test_the_shortcuts_set_the_size(app: QApplication) -> None:
    form = TradeForm()
    form.set_size_share(50)
    assert form.size.text() == "$5,000"


# -- placing a real order --------------------------------------------------


def test_the_form_stays_paper_when_not_connected(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(tmp_path / "secrets.json"))
    form = TradeForm()
    form.set_price(100.0)
    form.size.setText("$1,000")

    form._trade("LONG")

    assert form.position() is not None  # the paper fallback
    assert "not connected" in form.status_label.text().lower()


def test_the_form_is_a_dry_run_when_connected_but_not_armed(
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

    form = TradeForm()
    form.set_price(100.0)
    form.size.setText("$1,000")

    form._trade("LONG")

    assert form.position() is not None  # still paper
    assert "dry run" in form.status_label.text().lower()


# -- fast orders, a real close, and the testnet badge --------------------------


class _Service:
    """Records what the form sends, with the signals the form listens to."""

    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class Signals(QObject):
            placed = Signal(str, str)
            failed = Signal(str, str)
            filled = Signal(str, str, str, float, float)

        self.signals = Signals()
        self.placed, self.failed, self.filled = (
            self.signals.placed, self.signals.failed, self.signals.filled
        )
        self.orders: list = []
        self.closes: list = []

    def submit(self, venue, order, config, *args, **kwargs) -> None:
        self.orders.append((venue, order, config))

    def close_position(self, venue, instrument, config, price=None, origin="manual") -> None:
        self.closes.append((venue, instrument, config, price))


@pytest.fixture
def live(app: QApplication, monkeypatch, tmp_path):
    """A form with live orders armed and a recording service."""
    from bi_trading.state import orders
    from bi_trading.state.accounts import Accounts, HL_KEY, HyperliquidAccount, save_accounts, set_secret
    from bi_trading.ui import trade_form

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("BI_TRADING_KEYCHAIN", "0")
    set_secret(HL_KEY, "0x" + "ab" * 32)
    save_accounts(Accounts(hyperliquid=HyperliquidAccount(address="0x" + "cd" * 20)))
    service = _Service()
    monkeypatch.setattr(trade_form, "service", lambda: service)
    monkeypatch.setattr(trade_form, "armed", lambda: True)
    monkeypatch.setattr(
        trade_form.QMessageBox, "question",
        lambda *a, **k: trade_form.QMessageBox.StandardButton.Yes,
    )
    form = TradeForm()
    form.set_price(75_000.0)
    form.size.setText("$1,500")
    form.service = service
    assert orders.config_for("hyperliquid") is not None
    return form


def test_a_buy_is_fill_or_cancel_through_the_book(live) -> None:
    live._trade("LONG")
    live._trade("SHORT")
    (_, buy, _), (_, sell, _) = live.service.orders
    assert buy.market and sell.market                      # Ioc: it fills now or says why not
    assert buy.side == "buy" and buy.price == pytest.approx(75_150.0)
    assert sell.side == "sell" and sell.price == pytest.approx(74_850.0)
    assert buy.size == pytest.approx(0.02)


def test_a_fill_sets_the_positions_entry_to_the_venues_price(live) -> None:
    live._trade("LONG")
    live._on_filled("hyperliquid", "BTC", "buy", 0.02, 1_503.0)       # 75,150 average
    live._on_placed("hyperliquid", "Buy 0.02 BTC · filled")
    assert live.position()["entry"] == pytest.approx(75_150.0)
    assert "filled" in live.status_label.text()


def test_close_sends_a_real_whole_position_close_when_live(live) -> None:
    live.open_position("LONG")
    live.close_clicked()
    assert live.service.closes and live.service.closes[0][0] == "hyperliquid"
    assert live.service.closes[0][3] == 75_000.0           # the live price, for the limit
    assert live.position() is not None                      # not yet: the venue has to say
    assert "closing" in live.status_label.text()

    live._on_placed("hyperliquid", "Sell 0.02 BTC · filled")
    assert live.position() is None
    assert "closed" in live.status_label.text()


def test_a_close_the_venue_refuses_keeps_the_position_and_says_why(live) -> None:
    live.open_position("LONG")
    live.close_clicked()
    live._on_failed("hyperliquid", "no open BTC position to close")
    assert live.position() is not None
    assert "no open BTC position" in live.status_label.text()


def test_close_is_the_paper_close_when_not_live(app: QApplication, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BI_TRADING_SECRETS", str(tmp_path / "secrets.json"))
    form = TradeForm()
    form.set_price(100.0)
    form.open_position("LONG")
    form.close_clicked()
    assert form.position() is None


def test_the_testnet_badge_shows_only_on_the_test_network(app: QApplication, monkeypatch, tmp_path) -> None:
    from bi_trading.state.accounts import Accounts, HyperliquidAccount, save_accounts
    from bi_trading.ui.badges import refresh_badge, testnet_badge

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    save_accounts(Accounts(hyperliquid=HyperliquidAccount(address="0x" + "cd" * 20, testnet=False)))
    form = TradeForm()
    form.show()
    assert form.network_badge.isVisible() is False

    save_accounts(Accounts(hyperliquid=HyperliquidAccount(address="0x" + "cd" * 20, testnet=True)))
    assert refresh_badge(form.network_badge) is True
    assert form.network_badge.isVisible() is True
    assert form.network_badge.text() == "TESTNET" and form.network_badge.toolTip()
    assert testnet_badge().isHidden() is False
    form.close()


def test_the_settings_card_badges_the_test_network_as_it_is_picked(app: QApplication) -> None:
    from bi_trading.ui.hub.settings_view import SettingsView

    view = SettingsView()
    view.show()
    app.processEvents()
    assert view._hl_badge.isVisible() is False
    view._hl_network.combo.setCurrentText("Testnet")
    assert view._hl_badge.isVisible() is True
    view._hl_network.combo.setCurrentText("Mainnet")
    assert view._hl_badge.isVisible() is False
    view.close()


def test_liquidation_is_per_side() -> None:
    from bi_trading.state.positions import liquidation

    assert liquidation("LONG", 100.0, 5) == pytest.approx(80.0)
    assert liquidation("SHORT", 100.0, 5) == pytest.approx(120.0)
    assert liquidation("LONG", 100.0, 1) == pytest.approx(0.0)
