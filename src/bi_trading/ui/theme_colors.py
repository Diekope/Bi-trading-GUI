"""The terminal's palette — the darker surface the older windows use.

Deliberately its own set, not `ui.palette` (which the hub and Settings share):
the terminal's cards sit on a darker desk and its amber is quieter. Values live
here so both `theme.py` (which applies them) and `theme_qss.py` (the sheet) can
read one copy.
"""

from __future__ import annotations

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
DOWN_SOFT = "#ff8a8a"   # light red: the exit affordance, softer than DOWN
DOWN_SOFT_BG = "#2c1a1a"  # light-red tint behind a hovered exit control
BAND = "#6f7bd8"        # Bollinger bands, deliberately quieter than ACCENT
