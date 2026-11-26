"""Popups, pills, the entry-rule modes, the hub's own widgets and the rest.\n\nA part of the application stylesheet (see `theme_qss`)."""

from __future__ import annotations

from bi_trading.ui.theme_colors import (
    ACCENT, ACCENT_BG, ACCENT_DIM, BAND, BORDER, CANVAS, CARD_RADIUS, DOWN, DOWN_BG, DOWN_DIM, DOWN_SOFT, DOWN_SOFT_BG, PANEL, PANEL_ALT, TEXT, TEXT_FAINT, TEXT_MUTED, UP,  # noqa: F401
)

PART = f"""/* Popup is a top-level window, so it must be styled at app level. */
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
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 11px;
    padding: 3px 9px;
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
    font-size: 11px;
    padding: 6px 8px;
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
    font-size: 11px;
    padding: 4px 11px;
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
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.4px;
    padding: 7px 14px;
}}
QPushButton#sideButton:hover {{
    color: {TEXT};
}}
QPushButton#sideButton:checked {{
    color: {ACCENT};
    background-color: {ACCENT_BG};
    border-color: {ACCENT_DIM};
}}

#latencyLabel {{
    color: {TEXT_MUTED};
    font-size: 10px;
}}

/* The terminal's top-bar exit, in the hub rail's light red. */
QPushButton#topBarQuit {{
    background: transparent;
    border: 1px solid {DOWN};
    border-radius: {CARD_RADIUS}px;
    color: {DOWN_SOFT};
    font-size: 11px;
    padding: 3px 10px;
}}
QPushButton#topBarQuit:hover {{
    background-color: {DOWN_SOFT_BG};
    border-color: {DOWN_SOFT};
    color: {DOWN_SOFT};
}}

/* The bar under the terminal: strategy, reading, bets. */
#strategyBar {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {CARD_RADIUS}px;
}}
QLabel#gl {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QLabel#readingValue {{
    color: {TEXT};
}}
QLabel#readingValue[state="on"] {{
    color: {UP};
}}
QLabel#readingValue[state="off"] {{
    color: {DOWN};
}}
QLabel#armedChip {{
    background-color: #12251a;
    border: 1px solid #1f4530;
    border-radius: 8px;
    color: {UP};
    font-size: 10px;
    font-weight: bold;
    padding: 1px 8px;
}}
QComboBox#strategySelect {{
    background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT};
    padding: 4px 8px;
}}
QPushButton#betUp {{
    background-color: #12251a;
    border: 1px solid #1f4530;
    border-radius: 4px;
    color: {UP};
    font-size: 11px;
    padding: 4px 12px;
}}
QPushButton#betUp:hover {{
    border-color: {UP};
}}
QPushButton#betDown {{
    background-color: #2a1517;
    border: 1px solid #5a2626;
    border-radius: 4px;
    color: #ff8a8a;
    font-size: 11px;
    padding: 4px 12px;
}}
QPushButton#betDown:hover {{
    border-color: {DOWN};
}}
/* The trade form under a market's chart. */
#tradeForm {{
    background-color: #141519;
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QPushButton#buyButton {{
    background-color: #13211a;
    border: 1px solid {UP};
    border-radius: 6px;
    color: #5fe39a;
    font-size: 14px;
    font-weight: bold;
    padding: 11px 0;
}}
QPushButton#buyButton:hover {{
    border-color: #5fe39a;
    color: {TEXT};
}}
QPushButton#sellButton {{
    background-color: #2a1517;
    border: 1px solid {DOWN};
    border-radius: 6px;
    color: #ff8a8a;
    font-size: 14px;
    font-weight: bold;
    padding: 11px 0;
}}
QPushButton#sellButton:hover {{
    border-color: #ff8a8a;
    color: {TEXT};
}}
#positionRow {{
    background-color: #1a1b20;
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#positionText {{
    color: {UP};
}}
QSlider#leverageSlider::groove:horizontal {{
    height: 3px;
    background: #2a2b31;
    border-radius: 2px;
}}
QSlider#leverageSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider#leverageSlider::handle:horizontal {{
    background: {ACCENT};
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
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

# The bars under each venue's card. Kept apart so the hub, whose own sheet would
# otherwise win over the application's for plain labels, can carry them too.
BAR_PART = f"""
/* -- the bars under each venue's card (the bet bar and the order bar) ---------- */
QFrame#betBar, QFrame#orderBar {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {CARD_RADIUS}px;
}}
QFrame#betBar QLabel, QFrame#orderBar QLabel {{ background: transparent; }}
QLabel#barCoin {{ font-weight: 600; font-size: 13px; color: {TEXT}; }}
QLabel#venueTagPm, QLabel#venueTagHl {{
    font-family: monospace; font-size: 10px; font-weight: 700;
    border-radius: 4px; padding: 1px 6px;
}}
QLabel#venueTagPm {{ color: #5b82ff; background: #101830; border: 1px solid #243a7a; }}
QLabel#venueTagHl {{ color: #97fce4; background: #0f2024; border: 1px solid #1f5a4c; }}
QLabel#modeBadge {{
    font-size: 10px; font-weight: 700; letter-spacing: 1px; color: #ffa94d;
    background: #2a1d0c; border: 1px solid #5a3d17; border-radius: 4px; padding: 2px 8px;
}}
QLabel#modeBadge[live="true"] {{
    color: {DOWN}; background: {DOWN_BG}; border-color: {DOWN_DIM};
}}
QFrame#betBar[inline="true"] {{ background: transparent; border: none; }}
QFrame#figureTile {{
    background-color: #141519; border: 1px solid {BORDER}; border-radius: 8px;
}}
QLabel#figureValue {{ background: transparent; color: {TEXT}; }}
QLabel#sectionTitle {{
    font-size: 11px; font-weight: 700; letter-spacing: 2px; color: #c9cad0;
}}
QTableWidget#betsTable {{
    background: transparent; border: none; gridline-color: transparent;
}}
QTableWidget#betsTable QHeaderView::section {{
    background: transparent; color: {TEXT_MUTED}; border: none; padding: 4px 6px;
    text-align: left;
}}
QSpinBox#leverageSpin {{
    background-color: #141519; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 8px; color: {TEXT};
}}
QSpinBox#leverageSpin:focus {{ border-color: {ACCENT}; }}
QSpinBox#leverageSpin::up-button, QSpinBox#leverageSpin::down-button {{
    width: 0px; border: none;
}}

QFrame#betBar QPushButton, QFrame#orderBar QPushButton {{
    padding: 6px 12px; min-height: 0; font-size: 12px;
}}
"""
PART = PART + BAR_PART
