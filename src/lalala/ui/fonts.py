"""The design's two families, bundled and registered at startup.

The mocks load them from Google Fonts; a desktop app cannot, so the same files
ship with the package and are registered on the Qt font database:

    Inter            the interface — titles, labels, fields, buttons, tabs
    JetBrains Mono   the technical content — stats, prices, PnL, latencies,
                     formula blocks, tables and chart labels

Weights carried: Inter 400/500/600, JetBrains Mono 400/600.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

FONT_DIR = Path(__file__).with_name("assets")

FILES: tuple[str, ...] = (
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-SemiBold.ttf",
)

UI_FAMILY = "Inter"
MONO_FAMILY = "JetBrains Mono"


def load_fonts() -> bool:
    """Register the bundled fonts. True when every file loaded.

    Missing files are not fatal: Qt then falls back to the system's UI and mono
    faces, so the window still opens.
    """
    loaded = True
    for name in FILES:
        path = FONT_DIR / name
        if not path.exists() or QFontDatabase.addApplicationFont(str(path)) == -1:
            loaded = False
    return loaded


__all__ = ["FILES", "FONT_DIR", "MONO_FAMILY", "UI_FAMILY", "load_fonts"]
