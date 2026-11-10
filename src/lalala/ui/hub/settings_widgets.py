"""The Settings view's small builders and its venue connection tester.

Split out of `settings_view` so that module is the screen alone. The view
imports them back, so every name still lives there too.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lalala.ui.palette import DOWN_SOFT
from lalala.venues import get_venue
from lalala.venues.runner import AsyncRunner


def _label(text: str, name: str = "", *, rich: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    if rich:
        label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _dot(color: str, size: int = 10) -> QFrame:
    dot = QFrame()
    dot.setFixedSize(size, size)
    dot.setStyleSheet(
        f"background-color: {color}; border: none; border-radius: {size // 2}px;"
    )
    return dot


def _button(text: str, name: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _accent(text: str, color: str, size: int = 9) -> str:
    return f'<span style="color:{color};font-size:{size}px">{text}</span>'


class _ConnectionTester(QObject):
    """Runs one venue handshake off the GUI thread and reports back."""

    finished = Signal(str, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner = AsyncRunner("settings-connect")
        self._runner.start()

    def test(self, venue: str, config: dict[str, object]) -> None:
        self._runner.submit(self._probe(venue, config))

    async def _probe(self, venue: str, config: dict[str, object]) -> None:
        ok = False
        adapter = None
        try:
            adapter = get_venue(venue, **config)
            await asyncio.wait_for(adapter.connect(), timeout=30)
            if venue == "hyperliquid":
                ok, text = await self._probe_hyperliquid(adapter, config)
            else:
                ok, text = self._probe_polymarket(adapter, config)
        except Exception as exc:  # the SDKs raise a wide variety of types
            text = f"{type(exc).__name__}: {exc}"[:180]
        finally:
            if adapter is not None:
                try:
                    await adapter.close()
                except Exception:
                    pass
        self.finished.emit(venue, ok, text)

    @staticmethod
    async def _probe_hyperliquid(
        adapter, config: dict[str, object]
    ) -> tuple[bool, str]:
        address = str(config.get("account_address", ""))
        signer = await adapter.signer_address()
        if not signer:
            return False, "The private key could not be read."

        agents = await adapter.authorized_agents()
        approved = {agent.lower() for agent in agents}
        if signer.lower() != address.lower() and signer.lower() not in approved:
            return (
                False,
                f"Key signs as {_short(signer)}, not an approved API wallet "
                f"for {_short(address)}.",
            )

        balances = await asyncio.wait_for(adapter.balances(), timeout=30)
        value = balances[0].free if balances else 0.0
        return True, f"Connected · ${value:,.2f} USDC available"

    @staticmethod
    def _probe_polymarket(adapter, config: dict[str, object]) -> tuple[bool, str]:
        signer = _signer_address(str(config.get("private_key", "")))
        funder = str(config.get("funder", ""))
        try:
            kind = int(config.get("signature_type", 0))
        except (TypeError, ValueError):
            kind = 0
        # An EOA signs for its own address; a proxy wallet is funded at another
        # address and is reached through the Magic/browser signature types.
        if kind == 0 and signer and signer.lower() != funder.lower():
            return (
                False,
                f"Key signs as {_short(signer)}, not {_short(funder)}. Choose "
                "Email / Magic or Browser proxy for a proxy wallet.",
            )
        return True, "Connected · API credentials derived"

    def shutdown(self) -> None:
        self._runner.stop()


def _signer_address(private_key: str) -> str | None:
    try:
        from eth_account import Account
    except ModuleNotFoundError:  # noqa: BLE001 - optional extra
        return None
    try:
        return Account.from_key(private_key).address
    except Exception:
        return None


def _short(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}" if len(address) > 12 else address


def _this_year() -> int:
    return datetime.now(tz=timezone.utc).year


def _number_text(value: float) -> str:
    """`10000` not `10000.0`, `0.035` not `0.03500000001`."""
    return f"{float(value):g}"


def _read_number(
    field: QWidget,
    label: str,
    problems: list[str],
    low: float,
    high: float,
) -> float:
    text = field.edit.text().strip()
    try:
        value = float(text)
    except ValueError:
        problems.append(f"{label} must be a number")
        return low
    if not (low <= value <= high):
        problems.append(f"{label} must be between {low:g} and {high:g}")
        return min(max(value, low), high)
    return value


def _label_field(text: str, widget: QWidget) -> QWidget:
    holder = QWidget()
    holder.setObjectName("setHolder")
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(5)
    box.addWidget(_label(text, "setLabel"))
    box.addWidget(widget)
    return holder


def _field(
    text: str,
    value: str = "",
    *,
    secret: bool = False,
    combo: list[str] | None = None,
    current: str = "",
) -> QWidget:
    if combo is not None:
        box = QComboBox()
        box.setObjectName("setCombo")
        box.addItems(combo)
        box.setCurrentText(current or (combo[0] if combo else ""))
        holder = _label_field(text, box)
        holder.combo = box  # type: ignore[attr-defined]
        return holder
    if secret:
        edit = QLineEdit(value)
        edit.setObjectName("setField")
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        show = _button("Show", "setGhost")
        show.setCheckable(True)
        show.setFixedWidth(56)
        show.toggled.connect(
            lambda on, e=edit, b=show: (
                e.setEchoMode(
                    QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
                ),
                b.setText("Hide" if on else "Show"),
            )
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(edit, 1)
        row.addWidget(show)
        holder = QWidget()
        holder.setObjectName("setHolder")
        holder.setLayout(row)
        holder = _label_field(text, holder)
        holder.edit = edit  # type: ignore[attr-defined]
        return holder

    edit = QLineEdit(value)
    edit.setObjectName("setField")
    holder = _label_field(text, edit)
    holder.edit = edit  # type: ignore[attr-defined]
    return holder


def _grid(columns: int) -> QGridLayout:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)
    for column in range(columns):
        grid.setColumnStretch(column, 1)
    return grid


def _check(text: str, checked: bool) -> QWidget:
    box = QCheckBox(text)
    box.setObjectName("setCheck")
    box.setChecked(checked)
    box.setCursor(Qt.CursorShape.PointingHandCursor)
    holder = QWidget()
    holder.setObjectName("setHolder")
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    layout.addWidget(box)
    holder.box = box  # type: ignore[attr-defined]
    return holder


def _pill(color: str, name: str, ms: float | None, *, lent: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(_dot(color, 8))
    label = _label("", "setPill", rich=True)
    row.addWidget(label)
    # Keep the label addressable from the caller.
    row._label = label  # type: ignore[attr-defined]
    row._name = name  # type: ignore[attr-defined]
    row._lent = lent  # type: ignore[attr-defined]
    _fill_pill(row, name, ms, lent=lent)
    return row


def _fill_pill(
    row: QHBoxLayout, name: str, ms: float | None, *, lent: bool | None = None
) -> None:
    if lent is None:
        lent = getattr(row, "_lent", False)
    tail = f"{int(ms)} ms" if ms is not None else "—"
    text = f"{name} {tail}"
    if lent:
        text += f' <span style="color:{DOWN_SOFT}">· lent</span>'
    row._label.setText(text)  # type: ignore[attr-defined]


__all__ = [
    "_ConnectionTester",
    "_accent",
    "_button",
    "_check",
    "_dot",
    "_field",
    "_fill_pill",
    "_grid",
    "_label",
    "_label_field",
    "_number_text",
    "_pill",
    "_read_number",
    "_short",
    "_signer_address",
    "_this_year",
]
