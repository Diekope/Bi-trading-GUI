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
DOWN_DIM = "#5a2626"    # red border for a destructive control
DOWN_BG = "#2a1414"     # red fill for the same
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
/* A rules tile inside the switcher: the switcher's card is the surface, so
   the inner tile draws no border of its own. */
#venuePanel[inset="true"] {{
    background-color: transparent;
    border: none;
    border-radius: 0;
}}
#rulesStack {{
    background-color: transparent;
}}
#resultsStack {{
    background-color: transparent;
}}
#venuePanel QLabel {{
    background-color: transparent;
    color: {TEXT_MUTED};
}}
QSplitter#cardSplitter, QSplitter#tileSplitter, QSplitter#stratSplitter,
QSplitter#stratOuter, QSplitter#stratColumn, QSplitter#builderSplitter,
QSplitter#builderMiddleSplit, QSplitter#formulaSplit {{
    background-color: transparent;
}}
QSplitter#cardSplitter::handle:horizontal,
QSplitter#tileSplitter::handle:vertical,
QSplitter#stratSplitter::handle:horizontal,
QSplitter#stratOuter::handle:vertical,
QSplitter#stratColumn::handle:vertical,
QSplitter#builderSplitter::handle:horizontal,
QSplitter#builderMiddleSplit::handle:vertical,
QSplitter#formulaSplit::handle:vertical {{
    background-color: transparent;
}}

/* Plain containers inside a card must not paint the canvas colour. */
#resolutionPicker, #paramsGrid, #entryPages, #entryPage, #resultsPage,
#formulaBuilder, #formulaCanvas, #stripArea, #stripHolder,
#paletteInner, #paletteBlocks, #dropZone,
#stratColumnScroll, #stratColumn,
#stratColumnScroll > QWidget > QWidget {{
    background-color: transparent;
}}

/* The palette card: the sources, colour-coded by what they are. */
#formulaPalette {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#paletteTitle {{
    color: {TEXT_MUTED};
    font-size: 9px;
    font-weight: bold;
}}

#paletteRule {{
    background-color: {BORDER};
    border: none;
}}
QLabel#dragHandle {{
    color: {TEXT_FAINT};
    font-size: 10px;
}}

/* A palette block and a chip: one tile, coloured by group. */
#paletteBlock, #formulaChip {{
    border-radius: 6px;
}}
#paletteBlock:hover {{
    border-width: 1px;
}}
QLabel#blockLabel, QLabel#chipLabel {{
    font-size: 10px;
    font-weight: bold;
}}
QLabel#blockLabel {{
    font-size: 9px;
}}

/* Data: the bar's own fields, in the indigo the bands already use. */
#paletteBlock[group="data"], #formulaChip[group="data"] {{
    background-color: #1b2340;
    border: 1px solid #2f3c63;
}}
#paletteBlock[group="data"] QLabel, #formulaChip[group="data"] QLabel {{
    color: #aebdf0;
}}

/* Indicators: amber, the app's accent. */
#paletteBlock[group="indicator"], #formulaChip[group="indicator"] {{
    background-color: {ACCENT_BG};
    border: 1px solid {ACCENT_DIM};
}}
#paletteBlock[group="indicator"] QLabel, #formulaChip[group="indicator"] QLabel {{
    color: {ACCENT};
}}

/* Logic: the words, in the up colour. */
#paletteBlock[group="logic"], #formulaChip[group="logic"] {{
    background-color: #12251a;
    border: 1px solid #1f4530;
}}
#paletteBlock[group="logic"] QLabel, #formulaChip[group="logic"] QLabel {{
    color: {UP};
}}

/* Maths: a cool teal, its own colour. */
#paletteBlock[group="maths"], #formulaChip[group="maths"] {{
    background-color: #0e2a2f;
    border: 1px solid #1c5058;
}}
#paletteBlock[group="maths"] QLabel, #formulaChip[group="maths"] QLabel {{
    color: #58cfe0;
}}
/* A variable's name: a rose chip like any other, but you type in it. */
#paletteBlock[group="name"], #formulaChip[group="name"] {{
    background-color: #2b1622;
    border: 1px solid #5a2942;
}}
#paletteBlock[group="name"] QLabel, #formulaChip[group="name"] QLabel,
#formulaChip[group="name"] QLineEdit {{
    color: #ef8fc0;
}}
#formulaChip[slot="true"] {{
    background-color: {CANVAS};
    border: 1px dashed {ACCENT_DIM};
}}
#formulaChip[slot="true"] QLabel {{
    color: {TEXT_FAINT};
}}
#formulaChip[armed="true"] {{
    border: 1px solid {ACCENT};
}}
/* The fixed `=` of a named series: text, not a tile to move. */
#formulaChip[fixed="true"] {{
    background-color: transparent;
    border: none;
}}
#formulaChip[fixed="true"] QLabel {{
    color: {TEXT_MUTED};
}}
/* A palette block nothing here carries: dashed, in a dimmer shade of its
   group's colour, so it reads as the same kind of thing, not a different one. */
#paletteBlock[missing="true"] {{
    border-style: dashed;
}}
#paletteBlock[group="data"][missing="true"] {{
    background-color: #141a30;
    border-color: #26325a;
}}
#paletteBlock[group="data"][missing="true"] QLabel {{
    color: #7f8bbf;
}}

QLabel#formulaWarning {{
    color: {ACCENT};
    font-size: 9px;
}}

QPushButton#chipRemove, QPushButton#stripRemove {{
    border: none;
    background: transparent;
    color: {TEXT_FAINT};
    font-size: 11px;
    padding: 0px;
}}

/* The number inside an indicator tile. */
QLineEdit#chipField {{
    background-color: {CANVAS};
    border: 1px solid {ACCENT_DIM};
    border-radius: 8px;
    color: {ACCENT};
    font-size: 9px;
    padding: 0px 2px;
}}
QLineEdit#chipField:focus {{
    border-color: {ACCENT};
    color: {TEXT};
}}
QPushButton#chipRemove {{
    max-width: 12px;
}}
QPushButton#chipRemove:hover, QPushButton#stripRemove:hover {{
    color: {DOWN};
}}

/* A line: caption, the run of chips, a remove button. */
#chipStrip {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#chipStrip[target="true"] {{
    border: 1px solid {ACCENT};
    background-color: {ACCENT_BG};
}}
QLabel#stripCaption {{
    color: {ACCENT};
    font-size: 9px;
    font-weight: bold;
}}
QLabel#formulaSection, QLabel#formulaCondition {{
    color: {ACCENT};
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 0.5px;
    padding: 2px 0 1px 2px;
}}
QPushButton#addLine {{
    background-color: transparent;
    border: 1px dashed {BORDER};
    border-radius: 12px;
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 7px;
}}
QPushButton#addLine:hover {{
    border-color: {ACCENT_DIM};
    color: {TEXT};
}}
QPushButton#addLine:disabled {{
    color: {TEXT_FAINT};
}}

/* The formula text and the checker's word on it, in one line that scrolls
   sideways. The fill matches the card so the text does not sit on a darker
   patch; the border is what marks the field. */
QLabel#formulaPreview, QLineEdit#formulaPreview {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
    font-size: 10px;
    padding: 3px 8px;
}}

/* The code view: the same formula as text, editable. */
QPlainTextEdit#codeEdit {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
    font-size: 10px;
    padding: 5px 7px;
    selection-background-color: {ACCENT};
    selection-color: {CANVAS};
}}
QPlainTextEdit#codeEdit:focus {{
    border-color: {ACCENT};
}}
QLabel#formulaStatus {{
    border-radius: 9px;
    font-size: 9px;
    font-weight: bold;
    padding: 2px 9px;
}}
QLabel#formulaStatus[state="ok"] {{
    background-color: #12251a;
    border: 1px solid #1f4530;
    color: {UP};
}}
QLabel#formulaStatus[state="error"] {{
    background-color: {ACCENT_BG};
    border: 1px solid {DOWN};
    color: {DOWN};
}}
QLabel#formulaStatus[state="idle"] {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    color: {TEXT_FAINT};
}}
QLabel#formulaError {{
    color: {DOWN};
    font-size: 9px;
}}

QLineEdit#numberEdit {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
    font-size: 10px;
    padding: 5px 8px;
}}
QLineEdit#numberEdit:focus {{
    border-color: {ACCENT};
}}
/* -- the builder's three columns ------------------------------------- */
#formulaCard, #selectedCard {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
#blocksScroll, #blocksInner, #selectedHolder, #valuesBox, #pageScroll,
#valueRow, #codeValues, #listScroll, #listInner, #stripArea,
#selectedScroll, #selectedBody, #codeRail, #resultsRail {{
    background-color: transparent;
}}
#pageScroll > QWidget > QWidget {{
    background-color: transparent;
}}
/* The groups are boxes, not different colours: the card behind them shows
   through, so the list reads as one surface. */
#blockGroup {{
    background-color: transparent;
    border: 1px dashed {BORDER};
    border-radius: 8px;
}}
QLabel#panelTitle {{
    color: {TEXT};
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 1px;
}}
QLabel#groupLabel {{
    color: {TEXT_MUTED};
    font-size: 10px;
}}
QLineEdit#searchEdit {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
    font-size: 10px;
    padding: 5px 8px;
}}
QLineEdit#searchEdit:focus {{
    border-color: {ACCENT};
}}
QLabel#selectedName {{
    color: {ACCENT};
    font-size: 11px;
    font-weight: bold;
    padding: 1px 0;
}}
QComboBox#sourceSelect {{
    background-color: {CANVAS};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
    font-size: 10px;
    padding: 4px 8px;
}}
QLabel#valueKey {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-family: monospace;
}}
QLabel#valueNumber {{
    color: {TEXT};
    font-size: 10px;
    font-family: monospace;
}}
QLabel#valueResult[state="on"] {{
    color: {UP};
    font-size: 10px;
    font-weight: bold;
}}
QLabel#valueResult[state="off"] {{
    color: {DOWN};
    font-size: 10px;
    font-weight: bold;
}}
/* A word in the vocabulary: hovering says it is a choice, and the picked one
   stays lit while its description shows below. */
#valueRow[selectable="true"]:hover {{
    background-color: {PANEL};
    border-radius: 4px;
}}
#valueRow[selected="true"] {{
    background-color: {ACCENT_BG};
    border-radius: 4px;
}}
QLabel#variableNote {{
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 2px 2px 6px 2px;
}}

QLabel#draftLabel {{
    color: {TEXT_MUTED};
    font-size: 10px;
}}
QPushButton#ghostButton {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT_MUTED};
    font-size: 11px;
    padding: 6px 14px;
}}
QPushButton#ghostButton:hover {{
    color: {TEXT};
    border-color: {ACCENT_DIM};
}}
QPushButton#saveButton {{
    background-color: {ACCENT_BG};
    border: 1px solid {ACCENT_DIM};
    border-radius: 6px;
    color: {ACCENT};
    font-size: 11px;
    padding: 6px 14px;
}}
QPushButton#saveButton:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}

/* The saved-strategies rail: one row per kept draft, the current one lit. */
QFrame#strategyRow {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#strategyRow:hover {{
    border-color: {ACCENT_DIM};
}}
QFrame#strategyRow[selected="true"] {{
    background-color: {ACCENT_BG};
    border-color: {ACCENT};
}}
QLabel#strategyRowName {{
    color: {TEXT};
    font-size: 12px;
    font-weight: 500;
}}
QLabel#strategyRowBadge[tone="up"] {{
    color: {UP};
    font-size: 10px;
}}
QLabel#strategyRowBadge[tone="down"] {{
    color: {DOWN};
    font-size: 10px;
}}
QLabel#strategyRowBadge[tone="muted"] {{
    color: {TEXT_FAINT};
    font-size: 10px;
}}
QPushButton#createStrategy {{
    background-color: {ACCENT_BG};
    border: 1px solid {ACCENT_DIM};
    border-radius: 6px;
    color: {ACCENT};
    font-size: 11px;
    padding: 7px 14px;
}}
QPushButton#createStrategy:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}

/* Delete strategy: quiet until a saved strategy is on show, then red. */
QPushButton#deleteStrategy {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT_FAINT};
    font-size: 11px;
    padding: 6px 14px;
}}
QPushButton#deleteStrategy:hover {{
    color: {TEXT_MUTED};
}}
QPushButton#deleteStrategy[armed="true"] {{
    background-color: {DOWN_BG};
    border-color: {DOWN_DIM};
    color: {DOWN};
}}
QPushButton#deleteStrategy[armed="true"]:hover {{
    border-color: {DOWN};
    color: {TEXT};
}}

/* The compare subwindow: the compared runs, the table and the split. */
#compareTag {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
#compareTag:hover {{
    border-color: {ACCENT_DIM};
}}
#compareTagText {{
    color: {TEXT};
    font-size: 11px;
}}
#compareTagAdd {{
    color: {TEXT_FAINT};
    font-size: 11px;
}}
QLabel#sweepHint {{
    color: {TEXT_FAINT};
    font-size: 9px;
}}
QMenu {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    color: {TEXT};
    font-size: 11px;
    padding: 6px 18px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT_BG};
    color: {TEXT};
}}
QMenu::item:disabled {{
    color: {TEXT_FAINT};
}}
QMenu::separator {{
    height: 1px;
    background-color: {BORDER};
    margin: 4px 6px;
}}
QLabel#tableHead {{
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 2px 0 6px 0;
    border-bottom: 1px solid {BORDER};
}}
QLabel#tableMetric {{
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 3px 0;
}}
QLabel#tableCell {{
    color: {TEXT};
    font-size: 10px;
    padding: 3px 0;
}}
QLabel#tableCell[tone="up"] {{
    color: {UP};
}}
QLabel#tableCell[tone="down"] {{
    color: {DOWN};
}}
QLabel#tableCell[tone="muted"] {{
    color: {TEXT_MUTED};
}}

/* -- the Rules tab: condition groups ---------------------------------- */
#conditionsInner, #conditionRow, #extraCell {{
    background-color: transparent;
}}
#conditionGroup {{
    background-color: #141519;
    border: 1px dashed {BORDER};
    border-radius: 8px;
}}
QLabel#groupCaption {{
    color: {ACCENT};
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1px;
}}
QComboBox#conditionOperand, QComboBox#conditionOp, QComboBox#groupLogic {{
    background-color: {PANEL};
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    padding: 4px 6px;
    min-height: 20px;
}}
/* The operand and value come from the Variables rail: no dropdown arrow. */
QComboBox#conditionOperand::drop-down {{
    width: 0;
    border: none;
}}
QComboBox#conditionOperand::down-arrow {{
    image: none;
    width: 0;
    height: 0;
}}
QComboBox#conditionOperand:focus {{
    border-color: {ACCENT};
}}
/* A math or value cell: a little box of its own, the × inside it. */
#extraCell {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 2px 4px;
}}
QLineEdit#assignName {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {ACCENT};
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    padding: 4px 6px;
    min-height: 20px;
}}
QLineEdit#assignName:focus {{
    border-color: {ACCENT};
}}
QLabel#assignEquals {{
    color: {TEXT_MUTED};
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
}}
QPushButton#removeCondition {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 12px;
    padding: 0;
}}
QPushButton#removeCondition:hover {{
    border-color: {DOWN};
    color: {DOWN};
}}
QPushButton#addCondition, QPushButton#addGroup, QPushButton#addVariable {{
    background-color: transparent;
    border: none;
    color: {ACCENT};
    font-size: 10px;
    padding: 3px 2px;
    text-align: left;
}}
QPushButton#addGroup, QPushButton#addVariable {{
    color: {TEXT_MUTED};
}}
QPushButton#addCondition:hover, QPushButton#addGroup:hover,
QPushButton#addVariable:hover {{
    color: {TEXT};
}}
QPushButton#addCell {{
    background-color: transparent;
    border: 1px dashed {BORDER};
    border-radius: 4px;
    color: {ACCENT};
    font-size: 13px;
    padding: 0;
}}
QPushButton#addCell:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}
QLineEdit#chipNameEdit {{
    background-color: transparent;
    border: none;
    color: {TEXT};
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    padding: 0;
}}
#conditionPreview {{
    background-color: #101114;
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QLabel#conditionText {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    color: {TEXT};
}}
QLabel#conditionStatus {{
    font-family: "JetBrains Mono", monospace;
    font-size: 9px;
    color: {TEXT_FAINT};
}}
QLabel#conditionStatus[state="ok"] {{
    color: {UP};
}}
QLabel#conditionStatus[state="error"] {{
    color: {DOWN};
}}
QLabel#railNote {{
    color: {TEXT_FAINT};
    font-size: 9px;
}}
QPushButton#variablePick {{
    background-color: transparent;
    border: none;
    border-radius: 4px;
    color: {TEXT};
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    padding: 3px 6px;
    text-align: left;
}}
QPushButton#variablePick:hover {{
    background-color: {PANEL_ALT};
    color: {ACCENT};
}}
QPushButton#variablePick[defined="true"] {{
    color: {ACCENT};
}}
QComboBox:disabled {{
    background-color: #121216;
    border-color: #1c1c20;
    color: #3a3a40;
}}
QListView#completionPopup {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    color: {TEXT};
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    outline: none;
}}
QListView#completionPopup::item {{
    padding: 3px 8px;
}}
QListView#completionPopup::item:selected {{
    background-color: {ACCENT};
    color: {CANVAS};
}}

/* The little confirm prompt on top of the window. */
QDialog#confirmDialog {{
    background-color: {PANEL};
}}
QDialog#confirmDialog QLabel {{
    background-color: transparent;
}}
QLabel#confirmTitle {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#confirmBody {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QPushButton#deleteConfirm {{
    background-color: {DOWN_BG};
    border: 1px solid {DOWN_DIM};
    border-radius: 6px;
    color: {DOWN};
    font-size: 11px;
    padding: 6px 14px;
}}
QPushButton#deleteConfirm:hover {{
    border-color: {DOWN};
    color: {TEXT};
}}

QPushButton#numberAdd, QPushButton#formulaReset {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 5px 12px;
}}
QPushButton#numberAdd:hover, QPushButton#formulaReset:hover {{
    color: {TEXT};
    border-color: {ACCENT_DIM};
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

/* The Run / Pause switch in the playback tile's header. */
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
/* The Restart button beside it: a quiet ghost. */
QPushButton#restartButton {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 1px 10px;
}}
QPushButton#restartButton:hover {{
    border-color: {ACCENT_DIM};
    color: {TEXT};
}}
QComboBox#speedSelect {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    font-size: 10px;
    padding: 1px 6px;
}}
QComboBox#speedSelect:hover {{
    border-color: {ACCENT_DIM};
}}
/* The progress bar: an amber fill in a dark groove. */
QProgressBar#playbackProgress {{
    background-color: {PANEL_ALT};
    border: none;
    border-radius: 3px;
}}
QProgressBar#playbackProgress::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}
QLabel#progressCount {{
    color: {TEXT_MUTED};
}}
/* The trades detail panel. */
#tradesPage, #tradeSpark {{
    background-color: transparent;
}}
QFrame#tradeDetail {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QLabel#tradeValue {{
    color: {TEXT};
}}
QLineEdit#tradeSearch {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    padding: 4px 8px;
}}
QLineEdit#tradeSearch:focus {{
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

QLineEdit#runName {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    padding: 4px 8px;
}}
QLineEdit#runName:focus {{
    border-color: {ACCENT};
}}
QPushButton#saveRun {{
    background-color: {ACCENT_BG};
    border: 1px solid {ACCENT_DIM};
    border-radius: 4px;
    color: {ACCENT};
    font-size: 11px;
    padding: 4px 12px;
}}
QPushButton#saveRun:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}
QPushButton#loadRun {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    font-size: 11px;
    padding: 4px 12px;
}}
QPushButton#loadRun:hover {{
    border-color: {ACCENT_DIM};
    color: {TEXT};
}}
QPushButton#loadRun:disabled {{
    color: {TEXT_FAINT};
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
#venuePanel QLabel#emptyNote {{
    color: {TEXT_FAINT};
    font-size: 10px;
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
/* Overview / Trades pills in the results header. */
QPushButton#resultTab {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 2px 12px;
}}
QPushButton#resultTab:hover {{
    color: {TEXT};
}}
QPushButton#resultTab:checked {{
    background-color: {ACCENT_BG};
    border-color: {ACCENT_DIM};
    color: {ACCENT};
}}
#resultsStack, #overviewPage {{
    background-color: transparent;
}}
/* The trades table: quiet rows, a hairline under each. */
QTableWidget#tradesTable {{
    background-color: transparent;
    border: none;
    color: {TEXT};
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
}}
QTableWidget#tradesTable::item {{
    padding: 4px 8px;
    border-bottom: 1px solid #1f2024;
}}
QTableWidget#tradesTable QHeaderView::section {{
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {BORDER};
    color: {TEXT_MUTED};
    font-family: "Inter", sans-serif;
    font-size: 10px;
    padding: 4px 8px;
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

/* The rule titles double as the switch: one lit, the other quiet. */
QPushButton#sideButton {{
    background-color: transparent;
    border: none;
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.4px;
    padding: 3px 8px;
}}
QPushButton#sideButton:hover {{
    color: {TEXT};
}}
QPushButton#sideButton:checked {{
    color: {ACCENT};
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
