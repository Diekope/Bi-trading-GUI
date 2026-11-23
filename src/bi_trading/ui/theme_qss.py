"""The whole application stylesheet, as one string.

App-level, so popups and menus inherit it. Split out of `theme.py`, which
applies it, so the palette and the sheet are each their own file.
"""

from __future__ import annotations


from bi_trading.ui.theme_colors import (
    BORDER, CANVAS, CARD_RADIUS, PANEL, PANEL_ALT, TEXT, TEXT_MUTED,
)

from bi_trading.ui.qss_builder import PART as _BUILDER
from bi_trading.ui.qss_forms import PART as _FORMS
from bi_trading.ui.qss_hub import PART as _HUB
from bi_trading.ui.qss_rules import PART as _RULES

_BASE = f"""
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
#formulaBuilder, #formulaCanvas, #stripArea, #stripHolder, #stripScroll,
#stripScroll > QWidget > QWidget,
#paletteInner, #paletteBlocks, #dropZone, #stratColumn {{
    background-color: transparent;
}}

"""

# The sheet is one string, in five parts so no file is a wall of CSS. The order is
# the order the rules were written in, which is the order they win in.
# The design sets its text a step larger than the first draft of this sheet did
# (11 to 13px where it was 9 to 11), so every pixel font size in the sheet is
# scaled once here instead of being edited in a hundred rules.
FONT_SCALE = 1.2


def _scaled(sheet: str) -> str:
    import re

    return re.sub(
        r"font-size:\s*(\d+)px",
        lambda match: f"font-size: {round(int(match.group(1)) * FONT_SCALE)}px",
        sheet,
    )


STYLESHEET = _scaled(_BASE + _BUILDER + _RULES + _FORMS + _HUB)
