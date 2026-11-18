"""Small badges that say which network an order would go to."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from bi_trading.ui.typefaces import mono_font

TESTNET_TIP = (
    "Orders go to Hyperliquid's test network: play money, prices that differ "
    "from the real market. Change it in Settings → Accounts → Network."
)


def testnet_badge(parent: QWidget | None = None) -> QLabel:
    """An amber TESTNET chip, hidden unless the account is set to the test network.

    Call `refresh_badge` when the setting may have changed.
    """
    badge = QLabel("TESTNET", parent)
    badge.setObjectName("testnetBadge")
    badge.setFont(mono_font(8, bold=True))
    badge.setToolTip(TESTNET_TIP)
    badge.setStyleSheet(
        "QLabel#testnetBadge { color: #06121a; background: #e0b341;"
        " border-radius: 4px; padding: 1px 6px; }"
    )
    refresh_badge(badge)
    return badge


def refresh_badge(badge: QLabel) -> bool:
    """Show or hide the badge for the saved network; returns whether it shows."""
    from bi_trading.state.orders import is_testnet

    on = is_testnet("hyperliquid")
    badge.setVisible(on)
    return on


__all__ = ["TESTNET_TIP", "refresh_badge", "testnet_badge"]
