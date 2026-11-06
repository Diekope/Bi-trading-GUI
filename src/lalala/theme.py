"""Dark theme.

Two surface levels, darkest first:
    CANVAS  the main window — the "desk" the panels float on, nearly black
    PANEL   the floating cards, a shade lighter than the desk

The panels sit *above* the canvas, so they are the lighter surface. The accent
is amber (#e0b341), used sparingly: one mark per panel.
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

ACCENT = "#e0b341"      # amber
ACCENT_DIM = "#4a3a1d"  # accent-tinted border for checked / raised controls
ACCENT_BG = "#241d0e"   # accent-tinted fill for the same
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
QSplitter#stratColumn, QSplitter#builderSplitter,
QSplitter#builderMiddleSplit {{
    background-color: transparent;
}}
QSplitter#cardSplitter::handle:horizontal,
QSplitter#tileSplitter::handle:vertical,
QSplitter#stratSplitter::handle:horizontal,
QSplitter#stratColumn::handle:vertical,
QSplitter#builderSplitter::handle:horizontal,
QSplitter#builderMiddleSplit::handle:vertical {{
    background-color: transparent;
}}

/* Plain containers inside a card must not paint the canvas colour. */
#resolutionPicker, #paramsGrid, #entryPages, #entryPage,
#formulaBuilder, #formulaCanvas, #stripArea, #stripHolder,
#paletteScroll, #paletteInner, #paletteBlocks {{
    background-color: transparent;
}}

/* The palette subtile: an inset well on the card, holding the sources. */
#formulaPalette {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QLabel#paletteTitle {{
    color: {TEXT_MUTED};
    font-size: 9px;
    font-weight: bold;
}}

/* A palette block: one draggable thing, sitting in a horizontal row. */
#paletteBlock {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 3px;
}}
#paletteBlock:hover {{
    border-color: {ACCENT_DIM};
}}
QLabel#paletteBlockLabel {{
    color: {TEXT};
    font-size: 10px;
}}

/* A chip on a line, and an empty slot waiting to be filled. */
#formulaChip {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 3px;
}}
#formulaChip[slot="true"] {{
    background-color: {CANVAS};
    border: 1px dashed {ACCENT_DIM};
}}
#formulaChip[armed="true"] {{
    border: 1px solid {ACCENT};
}}
QLabel#chipLabel {{
    color: {TEXT};
    font-size: 10px;
}}
#formulaChip[slot="true"] QLabel#chipLabel {{
    color: {TEXT_FAINT};
}}

/* A line: the drop target. */
#chipStrip {{
    background-color: {CANVAS};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}

/* The formula text and the checker's word on it. */
QLabel#formulaPreview {{
    color: {TEXT_MUTED};
    font-size: 10px;
}}
QLabel#formulaError {{
    color: {DOWN};
    font-size: 9px;
}}

QLineEdit#numberEdit {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    font-size: 10px;
    padding: 2px 5px;
}}
QLineEdit#numberEdit:focus {{
    border-color: {ACCENT};
}}
QPushButton#numberAdd, QPushButton#lineButton {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 9px;
    padding: 2px 6px;
}}
QPushButton#numberAdd:hover, QPushButton#lineButton:hover {{
    color: {TEXT};
    border-color: {ACCENT_DIM};
}}
QPushButton#lineButton:disabled {{
    color: {TEXT_FAINT};
    border-color: {BORDER};
}}

/* Slim scrollbars, so the palette's lists do not wear OS-default chrome. */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 18px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT_DIM};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 18px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
#venuePanel QCheckBox {{
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
    selection-color: {CANVAS};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled {{
    background-color: #121216;
    border-color: #1c1c20;
    color: #3a3a40;
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
    selection-color: {CANVAS};
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
/* Incomplete span: the button keeps its amber edge until it is downloaded. */
QPushButton#actionButton[attention="true"] {{
    background-color: {ACCENT_BG};
    border-color: {ACCENT_DIM};
    color: {ACCENT};
}}

QPushButton#startButton {{
    background-color: {ACCENT_BG};
    border: 1px solid {ACCENT_DIM};
    border-radius: 4px;
    color: {ACCENT};
    padding: 3px 16px;
}}
QPushButton#startButton:hover {{
    border-color: {ACCENT};
}}

/* The compact Run/Restart switch in the playback tile's header. */
QPushButton#runButton {{
    background-color: {ACCENT_BG};
    border: 1px solid {ACCENT_DIM};
    border-radius: 4px;
    color: {ACCENT};
    font-size: 10px;
    padding: 1px 10px;
}}
QPushButton#runButton:hover {{
    border-color: {ACCENT};
}}

/* A placeholder for building a strategy, so it reads as a real action. */
QPushButton#createStrategy {{
    background-color: {ACCENT_BG};
    border: 1px solid {ACCENT_DIM};
    border-radius: 4px;
    color: {ACCENT};
    font-size: 11px;
    padding: 6px 20px;
}}
QPushButton#createStrategy:hover {{
    border-color: {ACCENT};
    color: {TEXT};
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
#venuePanel QLabel#coverageLabel {{
    font-size: 9px;
}}
#venuePanel QLabel#coverageLabel[state="missing"] {{
    color: {DOWN};
}}
#venuePanel QLabel#coverageLabel[state="partial"] {{
    color: {ACCENT};
}}
#venuePanel QLabel#fieldLabel {{
    color: {TEXT_FAINT};
    font-size: 10px;
}}
#venuePanel QLabel#fieldLabel:disabled {{
    color: #3a3a40;
}}
#venuePanel QLabel#hintLabel {{
    color: {TEXT_FAINT};
    font-size: 9px;
}}
#venuePanel QCheckBox#paramToggle {{
    color: {TEXT_MUTED};
    font-size: 10px;
    spacing: 7px;
}}
#venuePanel QCheckBox#paramToggle:hover {{
    color: {TEXT};
}}
/* Legends in the results tile: one colour per curve. */
#venuePanel QLabel#legend_strategy {{
    color: {ACCENT};
}}
#venuePanel QLabel#legend_random {{
    color: {BAND};
}}
#venuePanel QLabel#legend_hold {{
    color: {TEXT_MUTED};
}}
/* Metric values in the results tile, coloured by what they mean. */
#venuePanel QLabel#metricValue_accent {{
    color: {ACCENT};
}}
#venuePanel QLabel#metricValue_down {{
    color: {DOWN};
}}
#venuePanel QLabel#metricValue_muted {{
    color: {TEXT_MUTED};
}}
#venuePanel QLabel#metricValue_text {{
    color: {TEXT};
}}
/* A visible box: the default indicator nearly disappears on this background. */
#venuePanel QCheckBox#paramToggle::indicator {{
    width: 12px;
    height: 12px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background-color: {PANEL_ALT};
}}
#venuePanel QCheckBox#paramToggle::indicator:hover {{
    border-color: {ACCENT_DIM};
}}
#venuePanel QCheckBox#paramToggle::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
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
    background-color: {ACCENT_BG};
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
    border-color: {ACCENT_DIM};
    background-color: {ACCENT_BG};
}}

/* Resolution pills in the strategy tile: a light fill sets each one apart
   from the tile behind it, so the row reads as three separate choices. */
QPushButton#resButton {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 9px;
    padding: 3px 5px;
}}
QPushButton#resButton:hover {{
    color: {TEXT};
    border-color: {ACCENT_DIM};
}}
QPushButton#resButton:checked {{
    color: {ACCENT};
    border-color: {ACCENT_DIM};
    background-color: {ACCENT_BG};
}}

/* The entry-rule modes: rows, formula or code, in the same pill shape. */
QPushButton#modeButton {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 9px;
    padding: 2px 8px;
}}
QPushButton#modeButton:hover {{
    color: {TEXT};
    border-color: {ACCENT_DIM};
}}
QPushButton#modeButton:checked {{
    color: {ACCENT};
    border-color: {ACCENT_DIM};
    background-color: {ACCENT_BG};
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
