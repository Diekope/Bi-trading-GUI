"""The two typefaces, as cached QFonts: mono for numbers, Inter for text."""

from __future__ import annotations

from PySide6.QtGui import QFont
from bi_trading.ui.fonts import MONO_FAMILY, UI_FAMILY


_FONTS: dict[tuple, QFont] = {}


def mono_font(points: int = 12, bold: bool = False) -> QFont:
    """Cached JetBrains Mono, for numbers. Callers must `QFont(font)` first."""
    key = (points, bold)
    font = _FONTS.get(key)
    if font is None:
        font = QFont(MONO_FAMILY)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(points)
        font.setBold(bold)
        _FONTS[key] = font
    return font


def ui_font(points: int = 12, bold: bool = False) -> QFont:
    """Cached Inter, for painted interface text (titles, captions)."""
    key = ("ui", points, bold)
    font = _FONTS.get(key)
    if font is None:
        font = QFont(UI_FAMILY)
        font.setPointSize(points)
        font.setWeight(
            QFont.Weight.DemiBold if bold else QFont.Weight.Normal
        )
        _FONTS[key] = font
    return font
