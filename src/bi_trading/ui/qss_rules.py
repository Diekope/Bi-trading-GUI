"""The Rules tab: condition groups and the rows inside them.\n\nA part of the application stylesheet (see `theme_qss`)."""

from __future__ import annotations

from bi_trading.ui.theme_colors import (
    ACCENT, ACCENT_BG, ACCENT_DIM, BAND, BORDER, CANVAS, CARD_RADIUS, DOWN, DOWN_BG, DOWN_DIM, DOWN_SOFT, DOWN_SOFT_BG, PANEL, PANEL_ALT, TEXT, TEXT_FAINT, TEXT_MUTED, UP,  # noqa: F401
)

PART = f"""/* -- the Rules tab: condition groups ---------------------------------- */
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

"""
