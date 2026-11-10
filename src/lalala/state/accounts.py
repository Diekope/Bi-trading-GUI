"""Public account settings and the private keys behind them.

Two layers, on purpose:

    settings.json   the addresses, network and signature type — safe to read,
                    safe to sync, and visible to anyone who opens the file
    keychain        the private keys (macOS Keychain), never written to a
                    settings or strategy file

On macOS the keys live in the login keychain through the `security` tool. On
other systems — and in tests, via `LALALA_SECRETS` — they fall back to a JSON
file beside the settings file, chmod 600.

Nothing here touches the network. Connecting an account is the settings view's
job (it hands the values to `lalala.venues`).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lalala.state.settings import load_raw, save_raw, settings_path

SERVICE = "lalala"

HL_KEY = "hyperliquid.api_private_key"
PM_KEY = "polymarket.private_key"

# A tiny EVM-shaped check: catches a pasted label or a truncated key before a
# round trip. The SDKs still do the real validation.
HEX = set("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class HyperliquidAccount:
    """A Hyperliquid API wallet: the address funds live at, the key signs."""

    address: str = ""
    testnet: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.address and get_secret(HL_KEY))


@dataclass(frozen=True)
class PolymarketAccount:
    """A Polymarket wallet, with the proxy-wallet signature type."""

    address: str = ""
    signature_type: int = 0

    @property
    def configured(self) -> bool:
        return bool(self.address and get_secret(PM_KEY))


@dataclass(frozen=True)
class Accounts:
    hyperliquid: HyperliquidAccount = HyperliquidAccount()
    polymarket: PolymarketAccount = PolymarketAccount()


# -- the account block in settings.json -------------------------------------


def load_accounts(path: Path | str | None = None) -> Accounts:
    """Read the addresses. Broken or missing values become blanks."""
    raw = load_raw(path)
    accounts = raw.get("accounts")
    if not isinstance(accounts, dict):
        return Accounts()

    hl = accounts.get("hyperliquid")
    hl = hl if isinstance(hl, dict) else {}
    pm = accounts.get("polymarket")
    pm = pm if isinstance(pm, dict) else {}

    signature_type = pm.get("signature_type", 0)
    try:
        signature_type = int(signature_type)
    except (TypeError, ValueError):
        signature_type = 0
    if signature_type not in (0, 1, 2):
        signature_type = 0

    return Accounts(
        hyperliquid=HyperliquidAccount(
            address=_text(hl.get("address")),
            testnet=bool(hl.get("testnet", False)),
        ),
        polymarket=PolymarketAccount(
            address=_text(pm.get("address")),
            signature_type=signature_type,
        ),
    )


def save_accounts(accounts: Accounts, path: Path | str | None = None) -> None:
    """Write the addresses back, preserving every other settings key."""
    raw = load_raw(path)
    raw["accounts"] = {
        "hyperliquid": {
            "address": accounts.hyperliquid.address.strip(),
            "testnet": bool(accounts.hyperliquid.testnet),
        },
        "polymarket": {
            "address": accounts.polymarket.address.strip(),
            "signature_type": int(accounts.polymarket.signature_type),
        },
    }
    save_raw(raw, path)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


# -- secrets ----------------------------------------------------------------


def get_secret(name: str) -> str:
    """The stored private key, or an empty string when there is none."""
    if _file_backend():
        return str(_read_secret_file().get(name, ""))
    value = _keychain_read(name)
    return value or str(_read_secret_file().get(name, ""))


def set_secret(name: str, value: str) -> None:
    """Store a private key; an empty value removes it."""
    value = value.strip()
    if _file_backend():
        _write_secret_file(name, value)
        return
    if value:
        if not _keychain_write(name, value):
            # A locked or unavailable keychain must not lose the key the user
            # just pasted: the chmod-600 file is the fallback.
            _write_secret_file(name, value)
        else:
            _write_secret_file(name, "")  # do not keep a stale copy behind
    else:
        _keychain_delete(name)
        _write_secret_file(name, "")


def _file_backend() -> bool:
    if os.environ.get("LALALA_SECRETS"):
        return True
    if sys.platform != "darwin":
        return True
    return os.environ.get("LALALA_KEYCHAIN", "1").strip() == "0"


def _secret_path() -> Path:
    override = os.environ.get("LALALA_SECRETS")
    if override:
        return Path(override).expanduser()
    return settings_path().parent / "secrets.json"


def _read_secret_file() -> dict[str, str]:
    try:
        loaded = json.loads(_secret_path().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(k): str(v) for k, v in loaded.items() if isinstance(v, str)}


def _write_secret_file(name: str, value: str) -> None:
    target = _secret_path()
    values = _read_secret_file()
    if value:
        values[name] = value
    else:
        values.pop(name, None)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(values, indent=2) + "\n")
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        return  # a read-only home is not a reason to crash settings


def _keychain_read(name: str) -> str:
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                SERVICE,
                "-a",
                name,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _keychain_write(name: str, value: str) -> bool:
    try:
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-s",
                SERVICE,
                "-a",
                name,
                "-w",
                value,
                "-U",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _keychain_delete(name: str) -> None:
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE, "-a", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        pass


# -- validation -------------------------------------------------------------


def valid_address(value: str) -> bool:
    """`0x` followed by 40 hex characters."""
    value = value.strip()
    return (
        len(value) == 42
        and value[:2].lower() == "0x"
        and all(char in HEX for char in value[2:])
    )


def valid_private_key(value: str) -> bool:
    """`0x` followed by 64 hex characters, or the bare 64 characters."""
    value = value.strip()
    if value[:2].lower() == "0x":
        value = value[2:]
    return len(value) == 64 and all(char in HEX for char in value)


__all__ = [
    "Accounts",
    "HL_KEY",
    "HyperliquidAccount",
    "PM_KEY",
    "PolymarketAccount",
    "get_secret",
    "load_accounts",
    "save_accounts",
    "set_secret",
    "valid_address",
    "valid_private_key",
]
