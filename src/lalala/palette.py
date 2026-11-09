"""The hub's palette, in one place.

The Home hub (`main_hub`) and its Settings view (`settings_view`) render the
same design, taken from `MainHub.dc.html`, so they share one set of colours and
one mono font. They used to declare their own copies and drift apart; they
import from here now.

The terminal and the strategy builder predate the hub and use `theme.py`, a
separate palette — deliberately not merged here, so the older windows keep
their established look.
"""

from __future__ import annotations

from lalala.fonts import MONO_FAMILY

# Surfaces, darkest first.
CANVAS = "#0f1013"      # the desk the panels float on
PANEL = "#17181c"       # a card
INNER = "#141519"       # a recessed well inside a card
WELL = "#101114"        # the deepest inset (formula blocks)
HOVER = "#1b1c21"       # a hovered row
BORDER = "#25262b"      # card edges, hairlines
TRACK = "#1d1e23"       # slider / progress tracks

# Text.
TEXT = "#e8e8ea"
SOFT = "#c9cad0"
MUTED = "#8b8d95"
FAINT = "#a9abb2"

# Accents.
ACCENT = "#f2c94c"      # amber, used sparingly
UP = "#3ddc84"
UP_BRIGHT = "#5fe39a"
DOWN = "#ff6b6b"
DOWN_SOFT = "#ff8a8a"   # light red: the exit affordance
DOWN_SOFT_BG = "#2c1a1a"  # light-red tint behind a hovered exit control
AMBER_DOT = "#ffa94d"
INDIGO = "#6c72e8"

# Venue dots, in each venue's own colour.
PM_DOT = "#2d5bff"      # Polymarket
HL_DOT = "#97fce4"      # Hyperliquid

MONO = f'"{MONO_FAMILY}"'

__all__ = [
    "ACCENT",
    "AMBER_DOT",
    "BORDER",
    "CANVAS",
    "DOWN",
    "DOWN_SOFT",
    "DOWN_SOFT_BG",
    "FAINT",
    "HL_DOT",
    "HOVER",
    "INDIGO",
    "INNER",
    "MONO",
    "MUTED",
    "PANEL",
    "PM_DOT",
    "SOFT",
    "TEXT",
    "TRACK",
    "UP",
    "UP_BRIGHT",
    "WELL",
]
