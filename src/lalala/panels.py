"""Card chrome: the floating surfaces the trading widgets live on."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lalala.theme import ACCENT, CARD_GAP, CARD_RADIUS, TEXT_MUTED  # noqa: F401

# Rows stacked in the vertical splitter: the main card plus at most 3 tiles.
# More than that starves each chart, which is the point of the cap.
MAX_TILES = 3

__all__ = [
    "CARD_GAP",
    "CARD_RADIUS",
    "MAX_TILES",
    "Card",
    "VenuePanel",
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


class VenuePanel(Card):
    """Placeholder column: a centred accent mark and a title."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.accent = QFrame(self)
        self.accent.setObjectName("accentBar")
        self.accent.setFixedSize(26, 4)

        self.title = QLabel(title, self)
        self.title.setObjectName("venueTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        font = self.title.font()
        font.setPointSize(20)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.title.setFont(font)

        self.body.addStretch(1)
        self.body.addWidget(self.accent, 0, Qt.AlignmentFlag.AlignHCenter)
        self.body.addSpacing(10)
        self.body.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        self.body.addStretch(1)

    def text(self) -> str:
        return self.title.text()
