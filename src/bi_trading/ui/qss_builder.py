"""The formula builder: the palette card, the chips, the strips and the code view.\n\nA part of the application stylesheet (see `theme_qss`)."""

from __future__ import annotations

from bi_trading.ui.theme_colors import (
    ACCENT, ACCENT_BG, ACCENT_DIM, BAND, BORDER, CANVAS, CARD_RADIUS, DOWN, DOWN_BG, DOWN_DIM, DOWN_SOFT, DOWN_SOFT_BG, PANEL, PANEL_ALT, TEXT, TEXT_FAINT, TEXT_MUTED, UP,  # noqa: F401
)

PART = f"""/* The palette card: the sources, colour-coded by what they are. */
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

/* Polymarket market words (up_price, minute, ...): blue, the venue's colour. */
#paletteBlock[group="polymarket"], #formulaChip[group="polymarket"] {{
    background-color: #141a33;
    border: 1px solid #2c3b78;
}}
#paletteBlock[group="polymarket"] QLabel, #formulaChip[group="polymarket"] QLabel {{
    color: #7f9bff;
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

"""
