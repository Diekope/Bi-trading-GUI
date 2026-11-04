"""Dark theme, Arch-flavoured.

Two surface levels, darkest first:
    CANVAS  the main window — the "desk" the panels float on, nearly black
    PANEL   the floating cards, a shade lighter than the desk

The panels sit *above* the canvas, so they are the lighter surface. The accent
is Arch Linux's cyan (#1793d1), used sparingly: one mark per panel.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

CANVAS = "#0b0b0d"      # main window, darkest: the panels read as raised
PANEL = "#17181b"       # floating cards, a shade lighter than the canvas
PANEL_ALT = "#1e1f23"   # hover / striping inside a card, lighter still
BORDER = "#25262a"      # card edges, splitter hairline

CARD_RADIUS = 6
CARD_GAP = 8

TEXT = "#e4e4e6"
TEXT_MUTED = "#8a8a90"
TEXT_FAINT = "#57575c"

ACCENT = "#1793d1"      # Arch cyan
UP = "#3ddc84"
DOWN = "#ff5c5c"
BAND = "#6f7bd8"        # Bollinger bands, deliberately quieter than ACCENT

STYLESHEET = f"""
QWidget {{
    background-color: {CANVAS};
    color: {TEXT};
}}
QMainWindow, QDialog {{
    background-color: {CANVAS};
}}
QToolTip {{
    background-color: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 6px;
}}
QStatusBar {{
    background-color: {PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QStatusBar::item {{ border: none; }}

/* -- floating cards ------------------------------------------------- */
#venuePanel {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {CARD_RADIUS}px;
}}
#venuePanel QLabel {{
    background-color: transparent;
    color: {TEXT_MUTED};
}}
QSplitter#cardSplitter, QSplitter#tileSplitter, QSplitter#stratSplitter,
QSplitter#stratColumn {{
    background-color: transparent;
}}
QSplitter#cardSplitter::handle:horizontal,
QSplitter#tileSplitter::handle:vertical,
QSplitter#stratSplitter::handle:horizontal,
QSplitter#stratColumn::handle:vertical {{
    background-color: transparent;
}}

/* -- inputs ---------------------------------------------------------- */
QLineEdit {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 7px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

QComboBox {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 2px 6px;
    color: {TEXT};
    min-width: 54px;
}}
QComboBox:hover {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 14px;
}}
QComboBox QAbstractItemView {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    color: {TEXT};
    selection-background-color: {ACCENT};
    outline: none;
}}

/* -- actions --------------------------------------------------------- */
QPushButton#actionButton {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    padding: 3px 16px;
}}
QPushButton#actionButton:hover {{
    border-color: {ACCENT};
}}
QPushButton#actionButton:disabled {{
    background-color: #121216;
    border-color: #1c1c20;
    color: #3a3a40;
}}

QPushButton#startButton {{
    background-color: #10202a;
    border: 1px solid #1d3a4a;
    border-radius: 4px;
    color: {ACCENT};
    padding: 3px 16px;
}}
QPushButton#startButton:hover {{
    border-color: {ACCENT};
}}

#venuePanel QLabel#tileTitle {{
    color: {TEXT};
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1px;
}}
#venuePanel QLabel#spanArrow {{
    color: {TEXT_FAINT};
    font-size: 11px;
}}

/* Popup is a top-level window, so it must be styled at app level. */
QListWidget#marketResults {{
    background-color: #111116;
    border: 1px solid {BORDER};
    border-radius: 4px;
    outline: none;
    padding: 2px;
}}
QListWidget#marketResults::item {{
    padding: 4px 6px;
    border-radius: 3px;
    color: {TEXT};
}}
QListWidget#marketResults::item:selected {{
    background-color: #1d2a35;
    color: {ACCENT};
}}

QPushButton#addTile {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 14px;
    padding: 0px;
}}
QPushButton#addTile:hover {{
    color: {ACCENT};
    border-color: {ACCENT};
}}
QPushButton#addTile:disabled {{
    color: #3a3a40;
    border-color: #1c1c20;
}}

QPushButton#closeTile {{
    background: transparent;
    border: none;
    color: #6f6f76;
    font-size: 14px;
    padding: 0px;
}}
QPushButton#closeTile:hover {{
    color: {TEXT};
}}

QPushButton#tfButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    color: #6f6f76;
    font-size: 9px;
    padding: 1px 5px;
}}
QPushButton#tfButton:hover {{
    color: {TEXT};
}}
QPushButton#tfButton:checked {{
    color: {ACCENT};
    border-color: #1d3a4a;
    background-color: #10202a;
}}

#latencyLabel {{
    color: {TEXT_MUTED};
    font-size: 10px;
}}

QCheckBox#overlayToggle {{
    color: {TEXT_MUTED};
    font-size: 10px;
    spacing: 4px;
}}
QCheckBox#overlayToggle:hover {{
    color: {TEXT};
}}
QCheckBox#overlayToggle::indicator {{
    width: 10px;
    height: 10px;
    border: 1px solid #3a3b40;
    border-radius: 3px;
    background: #0e0e11;
}}
QCheckBox#overlayToggle::indicator:hover {{
    border-color: #4a4b52;
}}
QCheckBox#overlayToggle::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Apply palette and stylesheet to an application instance."""
    # Fusion is the only built-in style that honours a custom palette on macOS;
    # the native style ignores most colour roles.
    app.setStyle("Fusion")

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
