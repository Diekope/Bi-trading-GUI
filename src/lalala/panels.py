"""Card chrome: the floating surfaces the trading widgets live on."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from lalala.theme import CARD_GAP, CARD_RADIUS

# Rows stacked in the vertical splitter: the main card plus at most 3 tiles.
# More than that starves each chart, which is the point of the cap.
MAX_TILES = 3

__all__ = [
    "CARD_GAP",
    "CARD_RADIUS",
    "MAX_TILES",
    "Card",
]


class Card(QFrame):
    """Floating surface. Subclasses fill `self.body`.

    No drop shadow: QGraphicsDropShadowEffect re-renders the whole card into a
    pixmap on every repaint, which is a full extra pass per card per market
    update. The flat panel against the lighter canvas is enough separation.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("venuePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(220)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 10, 12, 10)
        self.body.setSpacing(6)
