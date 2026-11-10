"""Settings: accounts, defaults and safety limits, built from `settings.html`.

A full-width header (title + the two venue latencies), two equal columns of
cards — Polymarket, Hyperliquid and Security on the left; Backtest defaults,
Trading defaults and General on the right — and a footer with the save row.

The account cards, the backtest defaults, the trading defaults and the general
section are live. `Save` writes them to `settings.json`, stores the private
keys in the system keychain (see `lalala.state.accounts`), and `Test connection`
really connects through the venue adapters. Trading defaults seed the trade
form; orders themselves are not sent yet.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lalala.state.accounts import (
    Accounts,
    HL_KEY,
    HyperliquidAccount,
    PM_BUILDER_KEY,
    PM_BUILDER_PASSPHRASE,
    PM_BUILDER_SECRET,
    PM_KEY,
    PolymarketAccount,
    get_secret,
    load_accounts,
    save_accounts,
    set_secret,
    valid_address,
    valid_private_key,
)
from lalala.data.candles import candles_dir, default_candles_dir
from lalala.state.settings import (
    FIRST_YEAR,
    TIMEFRAMES,
    BacktestDefaults,
    GeneralSettings,
    Settings,
    TradingDefaults,
    save_backtest_defaults,
    save_general,
    save_trading_defaults,
)

# The hub's palette, imported so the view matches it exactly.
from lalala.ui.palette import (  # noqa: E402
    ACCENT,
    AMBER_DOT,
    BORDER,
    CANVAS,
    DOWN_SOFT,
    HL_DOT,
    MONO,
    MUTED,
    PANEL,
    PM_DOT,
    SOFT,
    TEXT,
    UP,
)

SIZING_LABELS = {
    "balance": "Balance %",
    "fixed": "Fixed $",
    "risk": "Risk %",
}
SIZING_MODES = {label: mode for mode, label in SIZING_LABELS.items()}

START_PAGE_LABELS = {
    "home": "Home",
    "live": "Live",
    "builder": "Strategy builder",
    "backtest": "Backtest engine",
}
START_PAGES = {label: key for key, label in START_PAGE_LABELS.items()}

MARGIN_LABELS = {"isolated": "Isolated", "cross": "Cross"}

QSS = f"""
#settingsView, #settingsBody, QScrollArea {{ background: transparent; }}
QScrollArea {{ border: none; }}
QWidget#setHolder {{ background: transparent; }}
QFrame#setCard {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QLabel {{ background: transparent; color: {TEXT}; }}
QLabel#setH1 {{ font-size: 18px; font-weight: 600; }}
QLabel#setSub {{ font-size: 11px; color: {MUTED}; }}
QLabel#setH2 {{
    font-size: 11px; font-weight: 600; letter-spacing: 2px; color: #e2e2e5;
}}
QLabel#setLabel {{ font-size: 11px; color: {MUTED}; }}
QLabel#setNote {{
    font-size: 10px; font-weight: 600; letter-spacing: 1.2px; color: {MUTED};
}}
QLabel#setBody {{ font-size: 13px; color: {SOFT}; }}
QLabel#setStatus {{ font-family: {MONO}; font-size: 11px; color: {SOFT}; }}
QLabel#setPill {{ font-family: {MONO}; font-size: 12px; color: {SOFT}; }}

QLineEdit#setField {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
    color: {TEXT}; font-family: {MONO}; font-size: 13px; padding: 8px 10px;
    selection-background-color: {ACCENT}; selection-color: {CANVAS};
}}
QLineEdit#setField:focus {{ border-color: {ACCENT}; }}
QLineEdit#setField[invalid="true"] {{ border-color: {DOWN_SOFT}; }}
QComboBox#setCombo {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
    color: {TEXT}; font-family: {MONO}; font-size: 13px; padding: 6px 10px;
}}
QComboBox#setCombo::drop-down {{ border: none; width: 16px; }}
QComboBox#setCombo QAbstractItemView {{
    background-color: {PANEL}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; selection-color: {CANVAS};
}}

QPushButton#setPrimary {{
    background: #231f10; border: 1px solid #4a3f1a; color: {ACCENT};
    border-radius: 6px; padding: 9px 14px; font-size: 13px; font-weight: 500;
}}
QPushButton#setPrimary:hover {{ border-color: {ACCENT}; }}
QPushButton#setPrimary:disabled {{ color: #6f6748; border-color: #3a3318; }}
QPushButton#setGhost {{
    background: {PANEL}; border: 1px solid #2a2b31; color: {SOFT};
    border-radius: 6px; padding: 8px 12px; font-size: 13px; font-weight: 500;
}}
QPushButton#setGhost:hover {{ border-color: #4a3b1a; color: {TEXT}; }}
QPushButton#setGhost:disabled {{ color: #5d5f66; }}

QCheckBox#setCheck {{ color: {SOFT}; font-size: 13px; spacing: 8px; }}
QCheckBox#setCheck::indicator {{
    width: 14px; height: 14px; border: 1px solid #3a3b40;
    border-radius: 3px; background: {PANEL};
}}
QCheckBox#setCheck::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
"""


# The small builders and the venue connection tester live in one place.
from lalala.ui.hub.settings_widgets import (  # noqa: E402
    _ConnectionTester,
    _accent,
    _button,
    _check,
    _dot,
    _field,
    _fill_pill,
    _grid,
    _label,
    _number_text,
    _pill,
    _read_number,
    _this_year,
)


class SettingsView(QWidget):
    """The settings screen, laid out like the mock."""

    def __init__(
        self,
        pm_ms: float | None = None,
        hl_ms: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(QSS)

        self._accounts = load_accounts()
        self._backtest = BacktestDefaults()
        self._trading = TradingDefaults()
        self._general = GeneralSettings()
        self._tested: dict[str, str] = {}
        self._busy: set[str] = set()
        self._dirty = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        outer.addWidget(self._header(pm_ms, hl_ms))

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("settingsBody")
        columns = QHBoxLayout(inner)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(8)
        columns.addLayout(self._left_column(), 1)
        columns.addLayout(self._right_column(), 1)
        body.setWidget(inner)
        outer.addWidget(body, 1)

        outer.addWidget(self._footer())

        self._tester = _ConnectionTester(self)
        self._tester.finished.connect(self._on_test_finished)
        self._tester.builder_ready.connect(self._on_builder_ready)
        self._tester.builder_failed.connect(self._on_builder_failed)

        self._load_values()
        self._refresh_statuses()
        self._mark_clean()

    # -- the top strip -----------------------------------------------------

    def _header(self, pm_ms: float | None, hl_ms: float | None) -> QFrame:
        card = QFrame()
        card.setObjectName("setCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        titles.addWidget(_label("Settings", "setH1"))
        titles.addWidget(_label("Accounts, defaults and safety limits.", "setSub"))
        row.addLayout(titles)
        row.addStretch(1)

        pills = QHBoxLayout()
        pills.setContentsMargins(0, 0, 0, 0)
        pills.setSpacing(18)
        self._pm_pill = _pill(PM_DOT, "Polymarket", pm_ms)
        self._hl_pill = _pill(HL_DOT, "Hyperliquid", hl_ms, lent=True)
        pills.addLayout(self._pm_pill)
        pills.addLayout(self._hl_pill)
        row.addLayout(pills)
        return card

    # -- columns -----------------------------------------------------------

    def _left_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self._polymarket_card())
        column.addWidget(self._hyperliquid_card())
        column.addWidget(self._security_card())
        column.addStretch(1)
        return column

    def _right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self._backtest_card())
        column.addWidget(self._trading_card())
        column.addWidget(self._general_card())
        column.addStretch(1)
        return column

    # -- cards -------------------------------------------------------------

    @staticmethod
    def _card(title: str, dot: str | None) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
        card = QFrame()
        card.setObjectName("setCard")
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 16, 18, 16)
        body.setSpacing(14)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        if dot is not None:
            header.addWidget(_dot(dot))
        header.addWidget(_label(title.upper(), "setH2"))
        header.addStretch(1)
        body.addLayout(header)
        return card, body, header

    def _polymarket_card(self) -> QFrame:
        card, body, _ = self._card("Polymarket", PM_DOT)
        self._pm_status = _label("", "setStatus", rich=True)
        self._pm_status.setWordWrap(True)
        body.addWidget(self._pm_status)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self._pm_key = _field("Private key", secret=True)
        self._pm_key.edit.setPlaceholderText("0x…")
        self._pm_address = _field("Wallet address")
        self._pm_address.edit.setPlaceholderText(
            "0x… (optional — blank uses the deposit wallet for the key)"
        )
        self._pm_type = _field(
            "Wallet type",
            combo=["EOA / wallet", "Email / Magic", "Browser proxy"],
            current="EOA / wallet",
        )
        # The V2 gasless steps need a Builder API Key; the three parts are
        # optional and stay in the keychain.
        self._pm_builder_key = _field("Builder key", secret=True)
        self._pm_builder_key.edit.setPlaceholderText("optional — for gasless (deposit wallet)")
        self._pm_builder_secret = _field("Builder secret", secret=True)
        self._pm_builder_pass = _field("Builder passphrase", secret=True)
        grid.addWidget(self._pm_key, 0, 0)
        grid.addWidget(self._pm_address, 0, 1)
        grid.addWidget(self._pm_type, 1, 0)
        grid.addWidget(self._pm_builder_key, 1, 1)
        grid.addWidget(self._pm_builder_secret, 2, 0)
        grid.addWidget(self._pm_builder_pass, 2, 1)
        body.addLayout(grid)
        actions = self._card_actions(
            lambda: self._test_polymarket(),
            lambda: self._disconnect("polymarket"),
        )
        builder = _button("Create builder key", "setGhost")
        builder.setToolTip(
            "Ask Polymarket to issue a Builder API Key for this signer "
            "(needed for the gasless deposit-wallet flow)"
        )
        builder.clicked.connect(self._create_builder_key)
        actions.insertWidget(1, builder)
        body.addLayout(actions)
        return card

    def _hyperliquid_card(self) -> QFrame:
        card, body, _ = self._card("Hyperliquid", HL_DOT)
        self._hl_status = _label("", "setStatus", rich=True)
        self._hl_status.setWordWrap(True)
        body.addWidget(self._hl_status)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self._hl_address = _field("Wallet address")
        self._hl_address.edit.setPlaceholderText("0x… (the account, or its API wallet)")
        self._hl_key = _field("API wallet private key", secret=True)
        self._hl_key.edit.setPlaceholderText("0x…")
        self._hl_network = _field(
            "Network", combo=["Mainnet", "Testnet"], current="Mainnet"
        )
        grid.addWidget(self._hl_address, 0, 0)
        grid.addWidget(self._hl_key, 0, 1)
        grid.addWidget(self._hl_network, 1, 0)
        body.addLayout(grid)
        body.addLayout(
            self._card_actions(
                lambda: self._test_hyperliquid(),
                lambda: self._disconnect("hyperliquid"),
            )
        )
        return card

    @staticmethod
    def _security_card() -> QFrame:
        card = QFrame()
        card.setObjectName("setCard")
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 14, 18, 14)
        body.setSpacing(6)
        body.addWidget(_label("SECURITY", "setNote"))
        note = _label(
            "Use an API wallet that can trade but not withdraw. Private keys are "
            "kept in your system keychain, never in strategy or settings files.",
            "setBody",
        )
        note.setWordWrap(True)
        body.addWidget(note)
        return card

    def _backtest_card(self) -> QFrame:
        card, body, _ = self._card("Backtest defaults", None)
        grid = _grid(3)
        years = [str(year) for year in range(FIRST_YEAR, _this_year() + 1)]
        self._bt_capital = _field("Initial capital $")
        self._bt_sizing = _field("Sizing", combo=list(SIZING_LABELS.values()))
        self._bt_position = _field("Position %")
        self._bt_tp = _field("TP %")
        self._bt_sl = _field("SL %")
        self._bt_cash = _field("Max cash $")
        self._bt_timeframe = _field("Timeframe", combo=list(TIMEFRAMES))
        self._bt_start = _field("From", combo=years)
        self._bt_end = _field("To", combo=years)
        self._bt_fee = _field("Fees %")
        self._bt_reverse = _field("Reverse % to close")
        self._bt_dynamic = _check("Dynamic TP on by default", False)
        grid.addWidget(self._bt_capital, 0, 0)
        grid.addWidget(self._bt_sizing, 0, 1)
        grid.addWidget(self._bt_position, 0, 2)
        grid.addWidget(self._bt_tp, 1, 0)
        grid.addWidget(self._bt_sl, 1, 1)
        grid.addWidget(self._bt_cash, 1, 2)
        grid.addWidget(self._bt_timeframe, 2, 0)
        grid.addWidget(self._bt_start, 2, 1)
        grid.addWidget(self._bt_end, 2, 2)
        grid.addWidget(self._bt_fee, 3, 0)
        grid.addWidget(self._bt_reverse, 3, 1)
        grid.addWidget(self._bt_dynamic, 3, 2)
        body.addLayout(grid)

        # The reverse field only matters while the trail is on.
        self._bt_dynamic.box.toggled.connect(self._bt_reverse.setEnabled)
        return card

    def _trading_card(self) -> QFrame:
        card, body, _ = self._card("Trading defaults", None)
        grid = _grid(3)
        self._td_leverage = _field("Leverage ×")
        self._td_margin = _field(
            "Margin mode", combo=list(MARGIN_LABELS.values()), current="Isolated"
        )
        self._td_size = _field("Default size (USD)")
        self._td_stake = _field("Polymarket stake $")
        self._td_max_stake = _field("Max stake per bet $")
        self._td_loss = _field("Daily loss limit $")
        grid.addWidget(self._td_leverage, 0, 0)
        grid.addWidget(self._td_margin, 0, 1)
        grid.addWidget(self._td_size, 0, 2)
        grid.addWidget(self._td_stake, 1, 0)
        grid.addWidget(self._td_max_stake, 1, 1)
        grid.addWidget(self._td_loss, 1, 2)
        body.addLayout(grid)

        self._td_confirm = _check("Confirm before placing an order", True)
        self._td_auto = _check("Auto-bet when a strategy is armed", False)
        self._td_live = _check("Place real orders (off = dry run)", False)
        checks = QHBoxLayout()
        checks.setContentsMargins(0, 0, 0, 0)
        checks.setSpacing(24)
        checks.addWidget(self._td_confirm)
        checks.addWidget(self._td_auto)
        checks.addWidget(self._td_live)
        checks.addStretch(1)
        body.addLayout(checks)
        return card

    def _general_card(self) -> QFrame:
        card, body, _ = self._card("General", None)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self._gen_start = _field(
            "Start page",
            combo=list(START_PAGE_LABELS.values()),
            current="Home",
        )
        row.addWidget(self._gen_start, 1)
        self._gen_folder = _field("Data folder")
        browse = _button("Browse", "setGhost")
        browse.clicked.connect(self._browse_folder)
        holder = QHBoxLayout()
        holder.setSpacing(6)
        holder.addWidget(self._gen_folder, 1)
        holder.addWidget(browse, 0, Qt.AlignmentFlag.AlignBottom)
        row.addLayout(holder, 2)
        body.addLayout(row)
        return card

    def _browse_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        current = self._gen_folder.edit.text().strip() or str(candles_dir())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the candle data folder", current
        )
        if chosen:
            self._gen_folder.edit.setText(chosen)

    # -- the save row ------------------------------------------------------

    @staticmethod
    def _card_actions(test, disconnect) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        test_button = _button("Test connection", "setPrimary")
        test_button.clicked.connect(test)
        dis_button = _button("Disconnect", "setGhost")
        dis_button.clicked.connect(disconnect)
        row.addWidget(test_button)
        row.addWidget(dis_button)
        row.addStretch(1)
        return row

    def _footer(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("setHolder")
        row = QHBoxLayout(bar)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(8)
        self._save_state = _label("All changes saved", "setSub")
        row.addWidget(self._save_state)
        row.addStretch(1)
        reset = _button("Reset to defaults", "setGhost")
        reset.clicked.connect(self._reset)
        cancel = _button("Cancel", "setGhost")
        cancel.clicked.connect(self._cancel)
        save = _button("Save", "setPrimary")
        save.clicked.connect(self._save)
        row.addWidget(reset)
        row.addWidget(cancel)
        row.addWidget(save)
        self._save_button = save
        return bar

    # -- values ------------------------------------------------------------

    def _load_values(self) -> None:
        accounts = self._accounts
        self._hl_address.edit.setText(accounts.hyperliquid.address)
        self._hl_key.edit.setText(get_secret(HL_KEY))
        self._hl_network.combo.setCurrentText(
            "Testnet" if accounts.hyperliquid.testnet else "Mainnet"
        )
        self._pm_key.edit.setText(get_secret(PM_KEY))
        self._pm_address.edit.setText(accounts.polymarket.address)
        self._pm_type.combo.setCurrentIndex(
            max(0, min(accounts.polymarket.signature_type, 2))
        )
        self._pm_builder_key.edit.setText(get_secret(PM_BUILDER_KEY))
        self._pm_builder_secret.edit.setText(get_secret(PM_BUILDER_SECRET))
        self._pm_builder_pass.edit.setText(get_secret(PM_BUILDER_PASSPHRASE))

        loaded = Settings.load()
        self._backtest = loaded.backtest
        self._fill_backtest(self._backtest)
        self._trading = loaded.trading
        self._general = loaded.general
        self._fill_trading(self._trading)
        self._fill_general(self._general)

        # Watch for edits only after the stored values are in place.
        for field in (
            self._hl_address,
            self._hl_key,
            self._pm_key,
            self._pm_address,
            self._pm_builder_key,
            self._pm_builder_secret,
            self._pm_builder_pass,
            self._bt_capital,
            self._bt_position,
            self._bt_tp,
            self._bt_sl,
            self._bt_cash,
            self._bt_fee,
            self._bt_reverse,
            self._td_leverage,
            self._td_size,
            self._td_stake,
            self._td_max_stake,
            self._td_loss,
            self._gen_folder,
        ):
            field.edit.textChanged.connect(self._mark_dirty)
        for field in (
            self._hl_network,
            self._pm_type,
            self._bt_sizing,
            self._bt_timeframe,
            self._bt_start,
            self._bt_end,
            self._td_margin,
            self._gen_start,
        ):
            field.combo.currentTextChanged.connect(self._mark_dirty)
        self._bt_dynamic.box.toggled.connect(self._mark_dirty)
        self._td_confirm.box.toggled.connect(self._mark_dirty)
        self._td_auto.box.toggled.connect(self._mark_dirty)
        self._td_live.box.toggled.connect(self._mark_dirty)

    def _fill_backtest(self, defaults: BacktestDefaults) -> None:
        self._bt_capital.edit.setText(_number_text(defaults.initial_capital))
        self._bt_sizing.combo.setCurrentText(
            SIZING_LABELS.get(defaults.sizing, SIZING_LABELS["balance"])
        )
        self._bt_position.edit.setText(_number_text(defaults.position))
        self._bt_tp.edit.setText(_number_text(defaults.tp))
        self._bt_sl.edit.setText(_number_text(defaults.sl))
        self._bt_cash.edit.setText(_number_text(defaults.cash))
        self._bt_timeframe.combo.setCurrentText(defaults.timeframe)
        self._bt_start.combo.setCurrentText(str(defaults.start_year))
        self._bt_end.combo.setCurrentText(str(defaults.end_year))
        self._bt_fee.edit.setText(_number_text(defaults.fee))
        self._bt_reverse.edit.setText(_number_text(defaults.dyn_tp_reverse))
        self._bt_dynamic.box.setChecked(defaults.dynamic_tp)
        self._bt_reverse.setEnabled(defaults.dynamic_tp)

    def _fill_trading(self, defaults: TradingDefaults) -> None:
        self._td_leverage.edit.setText(str(defaults.leverage))
        self._td_margin.combo.setCurrentText(
            MARGIN_LABELS.get(defaults.margin_mode, "Isolated")
        )
        self._td_size.edit.setText(_number_text(defaults.size))
        self._td_stake.edit.setText(_number_text(defaults.polymarket_stake))
        self._td_max_stake.edit.setText(_number_text(defaults.max_stake))
        self._td_loss.edit.setText(_number_text(defaults.daily_loss_limit))
        self._td_confirm.box.setChecked(defaults.confirm_orders)
        self._td_auto.box.setChecked(defaults.auto_bet)
        self._td_live.box.setChecked(defaults.live_orders)

    def _fill_general(self, settings: GeneralSettings) -> None:
        self._gen_start.combo.setCurrentText(
            START_PAGE_LABELS.get(settings.start_page, "Home")
        )
        self._gen_folder.edit.setText(settings.data_folder or str(candles_dir()))

    def _values(self) -> Accounts:
        return Accounts(
            hyperliquid=HyperliquidAccount(
                address=self._hl_address.edit.text().strip(),
                testnet=self._hl_network.combo.currentText() == "Testnet",
            ),
            polymarket=PolymarketAccount(
                address=self._pm_address.edit.text().strip(),
                signature_type=self._pm_type.combo.currentIndex(),
            ),
        )

    def _mark_dirty(self, *_args: object) -> None:
        if not self._dirty:
            self._dirty = True
        self._save_state.setText("Unsaved changes")
        self._save_state.setStyleSheet(f"color: {ACCENT};")

    def _mark_clean(self) -> None:
        self._dirty = False
        self._save_state.setText("All changes saved")
        self._save_state.setStyleSheet(f"color: {MUTED};")

    def _save(self) -> None:
        accounts = self._values()
        problems: list[str] = []

        for label, value in (
            ("Hyperliquid address", accounts.hyperliquid.address),
            ("Polymarket address", accounts.polymarket.address),
        ):
            if value and not valid_address(value):
                problems.append(f"{label} is not a 0x… address")

        for label, field in (
            ("Hyperliquid private key", self._hl_key.edit),
            ("Polymarket private key", self._pm_key.edit),
        ):
            value = field.text().strip()
            if value and not valid_private_key(value):
                problems.append(f"{label} is not a 0x… 32-byte key")

        self._flag_invalid(self._hl_address.edit, accounts.hyperliquid.address, valid_address)
        self._flag_invalid(self._pm_address.edit, accounts.polymarket.address, valid_address)
        self._flag_invalid(self._hl_key.edit, self._hl_key.edit.text().strip(), valid_private_key)
        self._flag_invalid(self._pm_key.edit, self._pm_key.edit.text().strip(), valid_private_key)

        backtest = self._backtest_values(problems)
        start = int(self._bt_start.combo.currentText())
        end = int(self._bt_end.combo.currentText())
        if start > end:
            problems.append("From must not be after To")

        trading = self._trading_values(problems)
        general = self._general_values()

        if problems:
            self._save_state.setText(problems[0])
            self._save_state.setStyleSheet(f"color: {DOWN_SOFT};")
            return

        save_accounts(accounts)
        set_secret(HL_KEY, self._hl_key.edit.text().strip())
        set_secret(PM_KEY, self._pm_key.edit.text().strip())
        set_secret(PM_BUILDER_KEY, self._pm_builder_key.edit.text().strip())
        set_secret(PM_BUILDER_SECRET, self._pm_builder_secret.edit.text().strip())
        set_secret(PM_BUILDER_PASSPHRASE, self._pm_builder_pass.edit.text().strip())
        save_backtest_defaults(backtest)
        save_trading_defaults(trading)
        save_general(general)
        self._accounts = accounts
        self._backtest = backtest
        self._trading = trading
        self._general = general
        self._tested.clear()
        self._refresh_statuses()
        self._mark_clean()

    def _trading_values(self, problems: list[str]) -> TradingDefaults:
        leverage = int(
            round(
                _read_number(
                    self._td_leverage, "Leverage", problems, 1.0, 20.0
                )
            )
        )
        return TradingDefaults(
            leverage=leverage,
            margin_mode={
                "Cross": "cross",
                "Isolated": "isolated",
            }.get(self._td_margin.combo.currentText(), "isolated"),
            size=_read_number(self._td_size, "Default size", problems, 0.0, 1e12),
            polymarket_stake=_read_number(
                self._td_stake, "Polymarket stake", problems, 0.0, 1e12
            ),
            max_stake=_read_number(
                self._td_max_stake, "Max stake", problems, 0.0, 1e12
            ),
            daily_loss_limit=_read_number(
                self._td_loss, "Daily loss limit", problems, 0.0, 1e12
            ),
            confirm_orders=self._td_confirm.box.isChecked(),
            auto_bet=self._td_auto.box.isChecked(),
            live_orders=self._td_live.box.isChecked(),
        )

    def _general_values(self) -> GeneralSettings:
        folder = self._gen_folder.edit.text().strip()
        # Showing the built-in location and saving it untouched keeps the file
        # portable: an empty value follows the repo.
        if folder and Path(folder).expanduser() == default_candles_dir():
            folder = ""
        return GeneralSettings(
            start_page=START_PAGES.get(
                self._gen_start.combo.currentText(), "home"
            ),
            data_folder=folder,
        )

    def _backtest_values(self, problems: list[str]) -> BacktestDefaults:
        return BacktestDefaults(
            initial_capital=_read_number(
                self._bt_capital, "Initial capital", problems, 0.0, 1e12
            ),
            tp=_read_number(self._bt_tp, "TP", problems, 0.0, 10_000.0),
            sl=_read_number(self._bt_sl, "SL", problems, 0.0, 100.0),
            position=_read_number(
                self._bt_position, "Position", problems, 0.0, 1e9
            ),
            cash=_read_number(self._bt_cash, "Max cash", problems, 0.0, 1e12),
            fee=_read_number(self._bt_fee, "Fees", problems, 0.0, 100.0),
            dynamic_tp=self._bt_dynamic.box.isChecked(),
            dyn_tp_reverse=_read_number(
                self._bt_reverse, "Reverse %", problems, 0.0, 100.0
            ),
            sizing=SIZING_MODES.get(
                self._bt_sizing.combo.currentText(), "balance"
            ),
            timeframe=self._bt_timeframe.combo.currentText() or "1m",
            start_year=int(self._bt_start.combo.currentText() or FIRST_YEAR),
            end_year=int(self._bt_end.combo.currentText() or _this_year()),
        )

    def _reset(self) -> None:
        self._hl_address.edit.setText("")
        self._hl_key.edit.setText("")
        self._hl_network.combo.setCurrentText("Mainnet")
        self._pm_key.edit.setText("")
        self._pm_address.edit.setText("")
        self._pm_type.combo.setCurrentIndex(0)
        self._pm_builder_key.edit.setText("")
        self._pm_builder_secret.edit.setText("")
        self._pm_builder_pass.edit.setText("")
        self._accounts = Accounts()
        self._backtest = BacktestDefaults()
        self._trading = TradingDefaults()
        self._general = GeneralSettings()
        self._fill_backtest(self._backtest)
        self._fill_trading(self._trading)
        self._fill_general(self._general)
        self._tested.clear()
        for venue in ("hyperliquid", "polymarket"):
            self._busy.discard(venue)
        self._refresh_statuses()

    def _cancel(self) -> None:
        self._accounts = load_accounts()
        self._hl_address.edit.setText(self._accounts.hyperliquid.address)
        self._hl_key.edit.setText(get_secret(HL_KEY))
        self._hl_network.combo.setCurrentText(
            "Testnet" if self._accounts.hyperliquid.testnet else "Mainnet"
        )
        self._pm_key.edit.setText(get_secret(PM_KEY))
        self._pm_address.edit.setText(self._accounts.polymarket.address)
        self._pm_type.combo.setCurrentIndex(self._accounts.polymarket.signature_type)
        self._pm_builder_key.edit.setText(get_secret(PM_BUILDER_KEY))
        self._pm_builder_secret.edit.setText(get_secret(PM_BUILDER_SECRET))
        self._pm_builder_pass.edit.setText(get_secret(PM_BUILDER_PASSPHRASE))
        self._flag_invalid(
            self._hl_address.edit,
            self._accounts.hyperliquid.address,
            valid_address,
        )
        self._flag_invalid(
            self._pm_address.edit,
            self._accounts.polymarket.address,
            valid_address,
        )
        self._flag_invalid(self._hl_key.edit, get_secret(HL_KEY), valid_private_key)
        self._flag_invalid(self._pm_key.edit, get_secret(PM_KEY), valid_private_key)
        loaded = Settings.load()
        self._backtest = loaded.backtest
        self._fill_backtest(self._backtest)
        self._trading = loaded.trading
        self._general = loaded.general
        self._fill_trading(self._trading)
        self._fill_general(self._general)
        self._tested.clear()
        self._refresh_statuses()
        self._mark_clean()

    @staticmethod
    def _flag_invalid(edit: QLineEdit, value: str, check) -> None:
        invalid = bool(value) and not check(value)
        current = edit.property("invalid") == "true"
        if current == invalid:
            return
        edit.setProperty("invalid", "true" if invalid else "false")
        style = edit.style()
        style.unpolish(edit)
        style.polish(edit)

    # -- connection tests ---------------------------------------------------

    def _test_hyperliquid(self) -> None:
        if "hyperliquid" in self._busy:
            return
        address = self._hl_address.edit.text().strip()
        key = self._hl_key.edit.text().strip()
        if not address or not key:
            self._set_status(
                self._hl_status, "error", "Enter the wallet address and API private key."
            )
            return
        if not valid_address(address) or not valid_private_key(key):
            self._set_status(
                self._hl_status, "error", "Check the address and private key format."
            )
            return
        self._begin_test("hyperliquid", self._hl_status)
        self._tester.test(
            "hyperliquid",
            {
                "private_key": key,
                "account_address": address,
                "testnet": self._hl_network.combo.currentText() == "Testnet",
            },
        )

    def _test_polymarket(self) -> None:
        if "polymarket" in self._busy:
            return
        address = self._pm_address.edit.text().strip()
        key = self._pm_key.edit.text().strip()
        if not key:
            self._set_status(
                self._pm_status, "error", "Enter the private key."
            )
            return
        if not valid_private_key(key):
            self._set_status(
                self._pm_status, "error", "Check the private key format."
            )
            return
        # The wallet address is optional: left blank, the client acts for the
        # signer's Polymarket deposit wallet (the V2 flow).
        if address and not valid_address(address):
            self._set_status(self._pm_status, "error", "Check the wallet address format.")
            return
        self._begin_test("polymarket", self._pm_status)
        builder_key = self._pm_builder_key.edit.text().strip()
        builder_secret = self._pm_builder_secret.edit.text().strip()
        builder_pass = self._pm_builder_pass.edit.text().strip()
        builder = (
            {"key": builder_key, "secret": builder_secret, "passphrase": builder_pass}
            if builder_key and builder_secret and builder_pass
            else None
        )
        self._tester.test(
            "polymarket",
            {
                "private_key": key,
                "funder": address,
                "signature_type": self._pm_type.combo.currentIndex(),
                "builder": builder,
            },
        )

    def _create_builder_key(self) -> None:
        """Mint a Builder API Key for this signer, off the GUI thread."""
        key = self._pm_key.edit.text().strip()
        if not key or not valid_private_key(key):
            self._set_status(
                self._pm_status, "error", "Enter the private key first."
            )
            return
        self._set_status(self._pm_status, "warn", "Requesting a builder key…")
        self._tester.mint_builder_key(
            {
                "private_key": key,
                "funder": self._pm_address.edit.text().strip(),
            }
        )

    def _on_builder_ready(self, key: str, secret: str, passphrase: str) -> None:
        self._pm_builder_key.edit.setText(key)
        self._pm_builder_secret.edit.setText(secret)
        self._pm_builder_pass.edit.setText(passphrase)
        self._set_status(
            self._pm_status, "ok", "Builder key created · Save to keep it"
        )
        self._mark_dirty()

    def _on_builder_failed(self, text: str) -> None:
        self._set_status(self._pm_status, "error", text)

    def _begin_test(self, venue: str, status: QLabel) -> None:
        self._busy.add(venue)
        self._set_status(status, "warn", "Testing connection…")

    def _on_test_finished(self, venue: str, ok: bool, message: str) -> None:
        self._busy.discard(venue)
        self._tested[venue] = message
        status = self._hl_status if venue == "hyperliquid" else self._pm_status
        self._set_status(status, "ok" if ok else "error", message)

    def _disconnect(self, venue: str) -> None:
        """Sign a venue out: drop its key and address, and persist that."""
        if venue in self._busy:
            return
        was_dirty = self._dirty
        if venue == "hyperliquid":
            set_secret(HL_KEY, "")
            self._accounts = Accounts(
                hyperliquid=HyperliquidAccount(),
                polymarket=self._accounts.polymarket,
            )
            self._hl_key.edit.setText("")
            self._hl_address.edit.setText("")
            self._hl_network.combo.setCurrentText("Mainnet")
            self._flag_invalid(self._hl_address.edit, "", valid_address)
            self._flag_invalid(self._hl_key.edit, "", valid_private_key)
            status = self._hl_status
        else:
            set_secret(PM_KEY, "")
            set_secret(PM_BUILDER_KEY, "")
            set_secret(PM_BUILDER_SECRET, "")
            set_secret(PM_BUILDER_PASSPHRASE, "")
            self._accounts = Accounts(
                hyperliquid=self._accounts.hyperliquid,
                polymarket=PolymarketAccount(),
            )
            self._pm_key.edit.setText("")
            self._pm_address.edit.setText("")
            self._pm_type.combo.setCurrentIndex(0)
            self._pm_builder_key.edit.setText("")
            self._pm_builder_secret.edit.setText("")
            self._pm_builder_pass.edit.setText("")
            self._flag_invalid(self._pm_address.edit, "", valid_address)
            self._flag_invalid(self._pm_key.edit, "", valid_private_key)
            status = self._pm_status

        save_accounts(self._accounts)
        self._tested.pop(venue, None)
        self._set_status(status, "idle", "Not configured")
        # Clearing the fields raised the dirty flag; only the user's own edits
        # should count as unsaved.
        if was_dirty:
            self._mark_dirty()
        else:
            self._mark_clean()

    # -- status lines -------------------------------------------------------

    def _refresh_statuses(self) -> None:
        for venue, label, account in (
            ("hyperliquid", self._hl_status, self._accounts.hyperliquid),
            ("polymarket", self._pm_status, self._accounts.polymarket),
        ):
            if venue in self._tested:
                continue
            if account.configured:
                self._set_status(label, "idle", "Credentials saved")
            elif account.address:
                self._set_status(label, "warn", "Address saved · private key missing")
            else:
                self._set_status(label, "idle", "Not configured")

    @staticmethod
    def _set_status(label: QLabel, kind: str, text: str) -> None:
        colors = {
            "ok": UP,
            "warn": AMBER_DOT,
            "error": DOWN_SOFT,
            "idle": MUTED,
        }
        dots = {"ok": "●", "warn": "◐", "error": "●", "idle": "○"}
        color = colors.get(kind, MUTED)
        body = html.escape(str(text))
        label.setText(
            f'{_accent(dots.get(kind, "○"), color, 9)} '
            f'<span style="color:{color}">{body}</span>'
        )

    # -- live latencies ----------------------------------------------------

    def set_pm_latency(self, milliseconds: float) -> None:
        self._pm_ms = int(milliseconds)
        _fill_pill(self._pm_pill, "Polymarket", self._pm_ms)

    def set_hl_latency(self, milliseconds: float) -> None:
        self._hl_ms = int(milliseconds)
        _fill_pill(self._hl_pill, "Hyperliquid", self._hl_ms)

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's spelling
        self._tester.shutdown()
        super().closeEvent(event)


# -- small field builders ----------------------------------------------------


__all__ = ["SettingsView"]
