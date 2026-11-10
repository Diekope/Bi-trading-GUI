"""Dark theme: the terminal palette and the stylesheet it applies.

The colours live in `theme_colors.py` and the sheet in `theme_qss.py`; this
module re-exports both and sets the application palette.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from lalala.ui.theme_colors import (
    ACCENT, ACCENT_BG, ACCENT_DIM, BAND, BORDER, CANVAS, CARD_GAP, CARD_RADIUS, DOWN, DOWN_BG, DOWN_DIM, DOWN_SOFT, DOWN_SOFT_BG, PANEL, PANEL_ALT, TEXT, TEXT_FAINT, TEXT_MUTED, UP,
)
from lalala.ui.theme_qss import STYLESHEET

__all__ = [
    "ACCENT", "ACCENT_BG", "ACCENT_DIM", "BAND", "BORDER", "CANVAS", "CARD_GAP", "CARD_RADIUS", "DOWN", "DOWN_BG", "DOWN_DIM", "DOWN_SOFT", "DOWN_SOFT_BG", "PANEL", "PANEL_ALT", "TEXT", "TEXT_FAINT", "TEXT_MUTED", "UP",
    "STYLESHEET",
    "apply_dark_theme",
]


def apply_dark_theme(app: QApplication) -> None:
    """Apply palette and stylesheet to an application instance."""
    # The design's two families ship with the package (see lalala.ui.fonts):
    # Inter for the interface, JetBrains Mono for the numbers. Register them
    # and make Inter the default face.
    from lalala.ui.fonts import UI_FAMILY, load_fonts

    load_fonts()

    # Fusion is the only built-in style that honours a custom palette on macOS;
    # the native style ignores most colour roles.
    app.setStyle("Fusion")

    base = app.font()
    base.setFamily(UI_FAMILY)
    app.setFont(base)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(CANVAS))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_FAINT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#06121a"))

    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
