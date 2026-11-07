"""The saved-strategies rail: every kept draft, with what it returned.

Each saved strategy is one row — its name, and the return it made over the
same tail of candles the report reads — with the row for the draft you are on
lit. Under the rows, **Create a strategy** starts a fresh draft.

The rows come from `lalala.strategies` (one JSON file) and the returns from
`lalala.formula_eval.backtest`, over the tail of the newest year on disk. The
return is cached per rule text, so re-listing does not re-run the walk.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import mono_font
from lalala.formula import (
    ENTRY_FIELDS,
    EXIT_FIELDS,
    EXIT_FUNCTIONS,
    FUNCTIONS,
    FormulaError,
    parse,
)
from lalala.formula_eval import backtest
from lalala.panels import Card
from lalala.strat_report import PREVIEW_SL, PREVIEW_TP, load_bars
from lalala.strategies import SavedStrategy
from lalala.theme import DOWN, TEXT, TEXT_FAINT, UP

# How a row's badge reads when the run cannot even be made.
DRAFT_BADGE = "draft"


@lru_cache(maxsize=256)
def strategy_pnl(entry: str, exit_: str, timeframe: str) -> float | None:
    """The return a strategy made over the tail of candles, or None.

    None when there is nothing to read, or a rule will not parse — the row
    then says so rather than drawing a made-up number.
    """
    bars, _ = load_bars(timeframe)
    if not bars or not entry.strip():
        return None
    try:
        entry_formula = parse(entry, ENTRY_FIELDS, FUNCTIONS)
        exit_formula = (
            parse(exit_, EXIT_FIELDS, EXIT_FUNCTIONS) if exit_.strip() else None
        )
    except FormulaError:
        return None
    report = backtest(
        bars, entry_formula, exit_formula, tp=PREVIEW_TP, sl=PREVIEW_SL
    )
    return report.pnl


class StrategyRow(QFrame):
    """One saved strategy: its name on the left, its return on the right."""

    clicked = Signal(str)

    def __init__(
        self,
        name: str,
        badge: str,
        colour: str,
        is_draft: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.setObjectName("strategyRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setProperty("draft", bool(is_draft))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("load this strategy into the editor")

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        self.label = QLabel(name, self)
        self.label.setObjectName("strategyRowName")
        row.addWidget(self.label, 1)

        self.badge = QLabel(badge, self)
        self.badge.setObjectName("strategyRowBadge")
        self.badge.setFont(mono_font(9))
        self.badge.setProperty("tone", colour)
        row.addWidget(self.badge, 0)

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)


def _badge(pnl: float | None) -> tuple[str, str]:
    """A return's text and its colour role."""
    if pnl is None:
        return "—", "muted"
    return f"{pnl * 100:+,.2f}%", ("up" if pnl >= 0 else "down")


class StrategyListTile(Card):
    """The kept drafts, most recent first, over a **Create a strategy**."""

    chosen = Signal(str)
    create_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[StrategyRow] = []

        scroll = QScrollArea(self)
        scroll.setObjectName("listScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        inner = QWidget()
        inner.setObjectName("listInner")
        self.rows_layout = QVBoxLayout(inner)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch(1)
        scroll.setWidget(inner)
        self.body.addWidget(scroll, 1)

        self.empty = QLabel("no saved strategies yet", self)
        self.empty.setObjectName("hintLabel")
        self.empty.setWordWrap(True)
        self.body.addWidget(self.empty)

        self.create_button = QPushButton("Create a strategy", self)
        self.create_button.setObjectName("createStrategy")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.setToolTip("start a fresh draft")
        self.create_button.clicked.connect(self.create_requested)
        self.body.addWidget(self.create_button)

    # -- the rows ----------------------------------------------------------

    def set_strategies(
        self,
        saved: list[SavedStrategy],
        draft: SavedStrategy | None = None,
    ) -> None:
        """Rebuild the list: the saved drafts, then the one being written.

        `draft` is the current editor state. When it is not already saved it
        appears at the top as a `draft` row, lit like the row you are on.
        """
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.rows = []

        saved_by_name = {item.name: item for item in saved}
        named = draft is not None and bool(draft.name)
        is_draft_row = named and saved_by_name.get(draft.name) != draft
        current = draft.name if named else ""

        entries: list[tuple[SavedStrategy, bool]] = []
        if is_draft_row and draft is not None:
            entries.append((draft, True))
        for item in reversed(saved):  # most recent first
            entries.append((item, False))

        self.empty.setVisible(not entries)
        insert_at = 0
        for strategy, draft_flag in entries:
            if draft_flag:
                badge, colour = DRAFT_BADGE, "muted"
            else:
                badge, colour = _badge(
                    strategy_pnl(
                        strategy.entry, strategy.exit, strategy.timeframe
                    )
                )
            row = StrategyRow(strategy.name, badge, colour, draft_flag, self)
            row.clicked.connect(self.chosen)
            row.set_selected(strategy.name == current)
            self.rows_layout.insertWidget(insert_at, row)
            self.rows.append(row)
            insert_at += 1


__all__ = [
    "DRAFT_BADGE",
    "StrategyListTile",
    "StrategyRow",
    "strategy_pnl",
]
