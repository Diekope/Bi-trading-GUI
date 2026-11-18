"""Inputs, actions and the strategy/backtest tiles.\n\nA part of the application stylesheet (see `theme_qss`)."""

from __future__ import annotations

from bi_trading.ui.theme_colors import (
    ACCENT, ACCENT_BG, ACCENT_DIM, BAND, BORDER, CANVAS, CARD_RADIUS, DOWN, DOWN_BG, DOWN_DIM, DOWN_SOFT, DOWN_SOFT_BG, PANEL, PANEL_ALT, TEXT, TEXT_FAINT, TEXT_MUTED, UP,  # noqa: F401
)

PART = f"""/* -- inputs ---------------------------------------------------------- */
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

"""
