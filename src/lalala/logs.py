"""A silent log: everything goes to a file, nothing to the screen.

The app is a GUI, so anything that writes to the terminal it was launched from
scribbles over work in progress — a stray `print`, a logging handler on stderr,
or Qt's own chatter. This module points the root logger at a rotating file and
routes Qt's messages into it as well, so the process stays quiet.

    LALALA_LOG          path to the file (`~/.local/share/lalala/lalala.log`)
    LALALA_LOG=off      no file at all
    LALALA_LOG_LEVEL    DEBUG, INFO (default), WARNING, ERROR

Third-party libraries are held at WARNING unless the level is DEBUG: `httpx`
and `websockets` are chatty at INFO and their output is rarely what is wanted.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_PATH = "~/.local/share/lalala/lalala.log"
MAX_BYTES = 1 << 20  # a megabyte per file
BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
NOISY = ("httpx", "httpcore", "websockets", "asyncio", "urllib3")

# Set once, so a second call is a no-op rather than a second handler.
_configured = False


def log_path() -> Path:
    """Where records go, honouring LALALA_LOG."""
    value = os.environ.get("LALALA_LOG", "").strip()
    if not value:
        return Path(DEFAULT_PATH).expanduser()
    return Path(value).expanduser()


def logging_enabled() -> bool:
    """On unless it was explicitly switched off."""
    value = os.environ.get("LALALA_LOG")
    if value is None:
        return True
    return value.strip().lower() not in ("0", "off", "none", "false")


def setup(level: int | str | None = None) -> Path | None:
    """Point logging at a file. Never at the console. Idempotent."""
    global _configured
    root = logging.getLogger()
    if _configured:
        return log_path() if any(isinstance(h, RotatingFileHandler) for h in root.handlers) else None

    # A library that called basicConfig first would leave a console handler
    # behind; drop anything that is not ours.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    resolved = _resolve_level(level)
    root.setLevel(resolved)
    # A NullHandler on its own keeps logging quiet even before the file opens.
    root.addHandler(logging.NullHandler())

    if not logging_enabled():
        _configured = True
        return None

    target = log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            target, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
    except OSError:
        # A read-only home is not a reason to refuse to start.
        _configured = True
        return None

    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)

    # Hold the noisy ones back unless we are actively debugging.
    quiet = logging.WARNING if resolved > logging.DEBUG else logging.NOTSET
    for name in NOISY:
        logging.getLogger(name).setLevel(quiet)

    _configured = True
    logging.getLogger(__name__).info(
        "logging to %s at %s", target, logging.getLevelName(resolved)
    )
    return target


def reset() -> None:
    """Forget that setup ran. For tests only."""
    global _configured
    _configured = False


def install_qt_handler() -> None:
    """Route Qt's own messages to the log instead of the terminal."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:  # a headless run without Qt is fine
        return

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    logger = logging.getLogger("qt")

    def handler(mode, context, message) -> None:  # noqa: ANN001 - Qt's shape
        # Qt calls this from C++; an exception here would be lost or fatal.
        try:
            logger.log(levels.get(mode, logging.INFO), "%s", message)
        except Exception:  # pragma: no cover - defensive
            pass

    qInstallMessageHandler(handler)


def _resolve_level(level: int | str | None) -> int:
    if level is None:
        level = os.environ.get("LALALA_LOG_LEVEL", "INFO")
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


__all__ = [
    "DEFAULT_PATH",
    "install_qt_handler",
    "log_path",
    "logging_enabled",
    "reset",
    "setup",
]
