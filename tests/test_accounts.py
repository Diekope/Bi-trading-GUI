"""Accounts: the public half in settings.json, the keys in a private store."""

from __future__ import annotations

import json
import os
import stat

import pytest

from lalala.state.accounts import (
    Accounts,
    HL_KEY,
    HyperliquidAccount,
    PM_KEY,
    PolymarketAccount,
    get_secret,
    load_accounts,
    save_accounts,
    set_secret,
    valid_address,
    valid_private_key,
)
from lalala.state.settings import Settings


@pytest.fixture
def paths(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    secrets = tmp_path / "secrets.json"
    monkeypatch.setenv("LALALA_SETTINGS", str(settings))
    monkeypatch.setenv("LALALA_SECRETS", str(secrets))
    return settings, secrets


def test_missing_file_means_empty_accounts(paths) -> None:
    assert load_accounts() == Accounts()


def test_accounts_round_trip_and_preserve_other_keys(paths) -> None:
    settings, _ = paths
    settings.write_text(json.dumps({"smooth": 0.2, "accounts": {"stale": True}}))

    accounts = Accounts(
        hyperliquid=HyperliquidAccount(address="0x" + "1" * 40, testnet=True),
        polymarket=PolymarketAccount(address="0x" + "2" * 40, signature_type=2),
    )
    save_accounts(accounts)

    assert load_accounts() == accounts
    raw = json.loads(settings.read_text())
    assert raw["smooth"] == 0.2  # untouched
    assert raw["accounts"]["hyperliquid"]["testnet"] is True
    assert raw["accounts"]["polymarket"]["signature_type"] == 2


def test_a_broken_file_falls_back_to_blanks(paths) -> None:
    settings, _ = paths
    settings.write_text("{not json")
    assert load_accounts() == Accounts()


def test_an_out_of_range_signature_type_is_clamped(paths) -> None:
    settings, _ = paths
    settings.write_text(
        json.dumps({"accounts": {"polymarket": {"signature_type": 9}}})
    )
    assert load_accounts().polymarket.signature_type == 0


def test_secrets_are_written_private_and_can_be_cleared(paths) -> None:
    _, secrets = paths
    set_secret(HL_KEY, "0x" + "a" * 64)
    set_secret(PM_KEY, "0x" + "b" * 64)

    assert get_secret(HL_KEY) == "0x" + "a" * 64
    assert get_secret(PM_KEY) == "0x" + "b" * 64
    assert stat.S_IMODE(os.stat(secrets).st_mode) == 0o600

    set_secret(HL_KEY, "")  # empty value removes it
    assert get_secret(HL_KEY) == ""


def test_configured_needs_both_an_address_and_a_key(paths) -> None:
    set_secret(HL_KEY, "0x" + "a" * 64)
    with_address = HyperliquidAccount(address="0x" + "1" * 40)

    assert with_address.configured
    assert not HyperliquidAccount().configured


def test_the_polymarket_account_is_configured_by_the_key_alone(paths) -> None:
    # The V2 deposit-wallet flow needs no wallet address: the key is enough.
    set_secret(PM_KEY, "0x" + "a" * 64)
    assert PolymarketAccount().configured

    set_secret(PM_KEY, "")
    assert not PolymarketAccount().configured


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0x" + "a" * 40, True),
        ("0X" + "A" * 40, True),
        ("0x" + "a" * 39, False),
        ("0x" + "g" * 40, False),
        ("not-an-address", False),
        ("", False),
    ],
)
def test_address_validation(value: str, expected: bool) -> None:
    assert valid_address(value) is expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0x" + "a" * 64, True),
        ("a" * 64, True),
        ("0x" + "a" * 63, False),
        ("0x" + "z" * 64, False),
        ("", False),
    ],
)
def test_private_key_validation(value: str, expected: bool) -> None:
    assert valid_private_key(value) is expected


def test_the_settings_form_saves_and_flags_a_bad_address(paths) -> None:
    from PySide6.QtWidgets import QApplication

    from lalala.ui.hub.settings_view import SettingsView
    from lalala.ui.theme import apply_dark_theme

    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)

    address = "0x" + "1" * 40
    key = "0x" + "a" * 64
    view = SettingsView()
    view._pm_address.edit.setText(address)
    view._pm_key.edit.setText(key)
    view._save()

    assert load_accounts().polymarket.address == address
    assert get_secret(PM_KEY) == key
    assert "Credentials saved" in view._pm_status.text()

    view._hl_address.edit.setText("not-an-address")
    view._hl_key.edit.setText(key)
    view._save()
    assert load_accounts().hyperliquid.address == ""
    assert "not a 0x" in view._save_state.text()

    view.close()


def test_the_settings_form_saves_backtest_defaults(paths) -> None:
    from PySide6.QtWidgets import QApplication

    from lalala.ui.hub.settings_view import SettingsView
    from lalala.ui.theme import apply_dark_theme

    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)

    view = SettingsView()
    view._bt_capital.edit.setText("25000")
    view._bt_sizing.combo.setCurrentText("Risk %")
    view._bt_position.edit.setText("7.5")
    view._bt_tp.edit.setText("3.5")
    view._bt_sl.edit.setText("1.25")
    view._bt_cash.edit.setText("1500")
    view._bt_fee.edit.setText("0.04")
    view._bt_timeframe.combo.setCurrentText("15m")
    view._bt_start.combo.setCurrentText("2021")
    view._bt_end.combo.setCurrentText("2023")
    view._bt_dynamic.box.setChecked(True)
    view._bt_reverse.edit.setText("0.7")
    view._save()

    saved = Settings.load().backtest
    assert saved.initial_capital == 25_000.0
    assert saved.sizing == "risk"
    assert saved.position == 7.5
    assert saved.tp == 3.5
    assert saved.sl == 1.25
    assert saved.cash == 1_500.0
    assert saved.fee == 0.04
    assert saved.timeframe == "15m"
    assert (saved.start_year, saved.end_year) == (2021, 2023)
    assert saved.dynamic_tp is True
    assert saved.dyn_tp_reverse == 0.7

    # A backwards span is refused rather than written.
    view._bt_start.combo.setCurrentText("2024")
    view._bt_end.combo.setCurrentText("2020")
    view._save()
    assert "must not be after" in view._save_state.text()
    assert Settings.load().backtest.start_year == 2021

    view.close()


def test_the_settings_form_saves_trading_and_general(paths) -> None:
    from PySide6.QtWidgets import QApplication

    from lalala.ui.hub.settings_view import SettingsView
    from lalala.ui.theme import apply_dark_theme

    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)

    view = SettingsView()
    view._td_leverage.edit.setText("8")
    view._td_margin.combo.setCurrentText("Cross")
    view._td_size.edit.setText("1234")
    view._td_stake.edit.setText("25")
    view._td_max_stake.edit.setText("125")
    view._td_loss.edit.setText("300")
    view._td_confirm.box.setChecked(False)
    view._td_auto.box.setChecked(True)
    view._gen_start.combo.setCurrentText("Live")
    view._gen_folder.edit.setText("/tmp/bars")
    view._save()

    loaded = Settings.load()
    assert loaded.trading.leverage == 8
    assert loaded.trading.margin_mode == "cross"
    assert loaded.trading.size == 1234.0
    assert loaded.trading.polymarket_stake == 25.0
    assert loaded.trading.max_stake == 125.0
    assert loaded.trading.daily_loss_limit == 300.0
    assert loaded.trading.confirm_orders is False
    assert loaded.trading.auto_bet is True
    assert loaded.general.start_page == "live"
    assert loaded.general.data_folder == "/tmp/bars"

    # An out-of-range leverage is refused, not silently bent.
    view._td_leverage.edit.setText("99")
    view._save()
    assert "between 1 and 20" in view._save_state.text()
    view.close()


def test_saving_the_built_in_data_folder_keeps_the_file_portable(paths) -> None:
    from PySide6.QtWidgets import QApplication

    from lalala.data.candles import default_candles_dir
    from lalala.ui.hub.settings_view import SettingsView
    from lalala.ui.theme import apply_dark_theme

    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)

    view = SettingsView()
    assert view._gen_folder.edit.text() == str(default_candles_dir())
    view._save()

    # The untouched default is stored as "", so moving the repo still works.
    assert Settings.load().general.data_folder == ""

    view.close()


def test_disconnect_signs_the_venue_out(paths) -> None:
    from PySide6.QtWidgets import QApplication

    from lalala.ui.hub.settings_view import SettingsView
    from lalala.ui.theme import apply_dark_theme

    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)

    settings, _ = paths
    set_secret(HL_KEY, "0x" + "ab" * 32)
    save_accounts(
        Accounts(
            hyperliquid=HyperliquidAccount(address="0x" + "cd" * 20, testnet=True),
            polymarket=PolymarketAccount(address="0x" + "ee" * 20, signature_type=1),
        )
    )

    view = SettingsView()
    view._disconnect("hyperliquid")

    # The key, the address and the network reset; Polymarket is left alone.
    assert get_secret(HL_KEY) == ""
    assert view._hl_address.edit.text() == ""
    assert view._hl_network.combo.currentText() == "Mainnet"
    assert load_accounts().hyperliquid.address == ""
    assert load_accounts().polymarket.address == "0x" + "ee" * 20
    assert "Not configured" in view._hl_status.text()
    # Disconnecting is a save, not an edit: nothing left unsaved.
    assert view._save_state.text() == "All changes saved"

    raw = json.loads(settings.read_text())
    assert raw["accounts"]["hyperliquid"]["address"] == ""

    view.close()
