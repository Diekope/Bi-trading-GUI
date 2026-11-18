"""The venues' own marks, where the app used coloured dots.

`assets/venues/` holds each venue's logo as published on its site (Hyperliquid's
mint mark, Polymarket's two-triangle mark). They are the venues' trademarks,
used here only to say which venue a row or a number belongs to.

Polymarket's mark is black on transparent, drawn for a light page, so it is
tinted white for this dark UI; Hyperliquid's mint mark is used as it is. If a
file is missing the old coloured dot is drawn instead, so nothing breaks.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QWidget

from bi_trading.ui.palette import HL_DOT, PM_DOT

ASSETS = Path(__file__).with_name("assets") / "venues"

# Every way the app names a venue, to one key.
_ALIASES = {
    "pm": "polymarket", "polymarket": "polymarket", PM_DOT: "polymarket",
    "hl": "hyperliquid", "hyperliquid": "hyperliquid", HL_DOT: "hyperliquid",
}
NAMES = {"polymarket": "Polymarket", "hyperliquid": "Hyperliquid"}
FALLBACK = {"polymarket": PM_DOT, "hyperliquid": HL_DOT}
# Polymarket's file is black on transparent, so it is drawn white on the dark UI;
# Hyperliquid's mint mark is used as published.
TINT = {"polymarket": "#ffffff"}

_cache: dict[tuple[str, int], QPixmap] = {}


def venue_key(name: str) -> str | None:
    """`pm`, `Polymarket`, a venue's dot colour… as `polymarket` / `hyperliquid`."""
    return _ALIASES.get(name.strip().lower()) or _ALIASES.get(name.strip())


def has_logo(name: str) -> bool:
    key = venue_key(name)
    return key is not None and (ASSETS / f"{key}.png").exists()


def venue_pixmap(name: str, size: int = 16) -> QPixmap | None:
    """The venue's logo fitted in a `size` square (sharp on a 2x screen), or None."""
    key = venue_key(name)
    if key is None:
        return None
    cached = _cache.get((key, size))
    if cached is not None:
        return cached
    source = QPixmap(str(ASSETS / f"{key}.png"))
    if source.isNull():
        return None
    scale = 2  # drawn at twice the size, shown at `size`
    box = size * scale
    fitted = source.scaled(
        box, box, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    tint = TINT.get(key)
    if tint is not None:
        painter = QPainter(fitted)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(fitted.rect(), QColor(tint))
        painter.end()
    out = QPixmap(box, box)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap((box - fitted.width()) // 2, (box - fitted.height()) // 2, fitted)
    painter.end()
    out.setDevicePixelRatio(scale)
    _cache[(key, size)] = out
    return out


def venue_mark(name: str, size: int = 16) -> QWidget:
    """A widget showing the venue's logo, or its old coloured dot without one."""
    key = venue_key(name)
    pixmap = venue_pixmap(name, size)
    if pixmap is None:
        dot = QFrame()
        side = max(8, size // 2)
        dot.setFixedSize(side, side)
        colour = FALLBACK.get(key or "", name if name.startswith("#") else "#8b8d95")
        dot.setStyleSheet(
            f"background-color: {colour}; border: none; border-radius: {side // 2}px;"
        )
        return dot
    label = QLabel()
    label.setFixedSize(size, size)
    label.setPixmap(pixmap)
    label.setStyleSheet("background: transparent;")
    if key is not None:
        label.setToolTip(NAMES[key])
    return label


__all__ = ["NAMES", "has_logo", "venue_key", "venue_mark", "venue_pixmap"]
