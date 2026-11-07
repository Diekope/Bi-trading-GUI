"""The saved-strategies rail: every kept draft, with what it returned.

Each saved strategy is one row — its name with the bar it reads under it, and
the return it made over the same tail of candles the report reads, with how
many trades and how many of them won under it. The row for the draft you are
on is lit. Each row has a menu to **archive** it (kept, but out of the way) or
**delete** it for good. Under the rows, **Create a strategy** starts a fresh
draft.

The rows come from `lalala.strategies` (one JSON file) and the figures from
`lalala.formula_eval.backtest`, over the tail of the newest year on disk. The
figures are cached per rule text, so re-listing does not re-run the walk.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
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
from lalala.theme import DOWN, TEXT_FAINT, UP

# How a row's badge reads when it has not been run, or has been set aside.
DRAFT_BADGE = "draft"
ARCHIVED_BADGE = "archived"


@lru_cache(maxsize=256)
def strategy_stats(
    entry: str, exit_: str, timeframe: str
) -> tuple[float, int, float] | None:
    """A strategy's (return, trades, win rate) over the tail of candles.

    None when there is nothing to read, or a rule will not parse — the row
    then says so rather than drawing made-up figures.
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
    return report.pnl, report.trades, report.win_rate


def strategy_pnl(entry: str, exit_: str, timeframe: str) -> float | None:
    """Just the return, for callers that want the one number."""
    stats = strategy_stats(entry, exit_, timeframe)
    return stats[0] if stats else None


class StrategyRow(QFrame):
    """One strategy: name and bar on the left, return and record on the right."""

    clicked = Signal(str)
    archived = Signal(str)
    restored = Signal(str)
    deleted = Signal(str)

    def __init__(
        self,
        name: str,
        timeframe: str,
        badge: str,
        colour: str,
        stats: str = "",
        is_draft: bool = False,
        is_archived: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.setObjectName("strategyRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setProperty("draft", bool(is_draft))
        self.setProperty("archived", bool(is_archived))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("load this strategy into the editor")

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 8, 7)
        row.setSpacing(8)

        # Name over the bar it reads.
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(1)
        self.label = QLabel(name, self)
        self.label.setObjectName("strategyRowName")
        left.addWidget(self.label)
        self.time_label = QLabel(timeframe, self)
        self.time_label.setObjectName("strategyRowTime")
        self.time_label.setFont(mono_font(8))
        left.addWidget(self.time_label)
        row.addLayout(left, 1)

        # The return over the trades that produced it.
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(1)
        self.badge = QLabel(badge, self)
        self.badge.setObjectName("strategyRowBadge")
        self.badge.setFont(mono_font(9))
        self.badge.setProperty("tone", colour)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.badge)
        self.stats = QLabel(stats, self)
        self.stats.setObjectName("strategyRowStats")
        self.stats.setFont(mono_font(8))
        self.stats.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.stats.setVisible(bool(stats))
        right.addWidget(self.stats)
        row.addLayout(right, 0)

        # Archive / delete (or restore), on a small menu at the far right.
        self.menu_button = QPushButton("⋯", self)
        self.menu_button.setObjectName("strategyMenuButton")
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_button.setFixedWidth(20)
        self.menu_button.clicked.connect(self._show_menu)
        row.addWidget(self.menu_button, 0, Qt.AlignmentFlag.AlignTop)

        self.menu = QMenu(self)
        if is_archived and not is_draft:
            self.restore_action = self.menu.addAction("Restore")
            self.restore_action.triggered.connect(lambda: self.restored.emit(name))
            self.archive_action = None
        else:
            self.restore_action = None
            self.archive_action = self.menu.addAction("Archive")
            self.archive_action.triggered.connect(
                lambda: self.archived.emit(name)
            )
        self.delete_action = self.menu.addAction("Delete")
        self.delete_action.triggered.connect(lambda: self.deleted.emit(name))

    def _show_menu(self) -> None:
        self.menu.exec(
            self.menu_button.mapToGlobal(
                QPoint(0, self.menu_button.height())
            )
        )

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


def _badge(stats: tuple[float, int, float] | None) -> tuple[str, str, str]:
    """A run's badge text, colour role, and its trades/win-rate line."""
    if stats is None:
        return "—", "muted", ""
    pnl, trades, win_rate = stats
    colour = "up" if pnl >= 0 else "down"
    return (
        f"{pnl * 100:+,.2f}%",
        colour,
        f"{trades} tr · {win_rate * 100:,.0f}%",
    )


class StrategyListTile(Card):
    """The kept drafts, most recent first, over a **Create a strategy**."""

    chosen = Signal(str)
    create_requested = Signal()
    archived = Signal(str)
    restored = Signal(str)
    deleted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[StrategyRow] = []
        self.show_archived = False
        self._saved: list[SavedStrategy] = []
        self._draft: SavedStrategy | None = None

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

        self.archive_toggle = QPushButton("show archived", self)
        self.archive_toggle.setObjectName("archiveToggle")
        self.archive_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.archive_toggle.clicked.connect(self.toggle_archived)
        self.archive_toggle.setVisible(False)
        self.body.addWidget(self.archive_toggle)

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
        """Remember the drafts and rebuild the list.

        `saved` is every kept strategy (archived ones included); `draft` is
        the current editor state, shown at the top badged `draft` when it is
        not already saved.
        """
        self._saved = list(saved)
        self._draft = draft
        self._rebuild()

    def toggle_archived(self) -> None:
        self.show_archived = not self.show_archived
        self._rebuild()

    def _rebuild(self) -> None:
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.rows = []

        live = [item for item in self._saved if not item.archived]
        archived = [item for item in self._saved if item.archived]
        draft = self._draft

        named = draft is not None and bool(draft.name)

        def _same_saved(candidate: SavedStrategy) -> bool:
            # The archived flag is not part of what makes a draft "saved".
            for item in self._saved:
                if item.name != candidate.name:
                    continue
                if (
                    item.timeframe,
                    item.entry,
                    item.exit,
                ) == (
                    candidate.timeframe,
                    candidate.entry,
                    candidate.exit,
                ):
                    return True
            return False

        is_draft_row = named and not _same_saved(draft)
        current = draft.name if named else ""

        entries: list[tuple[SavedStrategy, bool]] = []
        if is_draft_row and draft is not None:
            entries.append((draft, True))
        for item in reversed(live):  # most recent first
            entries.append((item, False))
        if self.show_archived:
            for item in reversed(archived):
                entries.append((item, False))

        self.empty.setVisible(not entries)
        self.empty.setText(
            "nothing here — show archived"
            if not entries and archived
            else "no saved strategies yet"
        )
        self.archive_toggle.setVisible(bool(archived))
        self.archive_toggle.setText(
            "hide archived" if self.show_archived else f"show archived ({len(archived)})"
        )

        insert_at = 0
        for strategy, draft_flag in entries:
            if draft_flag:
                badge, colour, stats = DRAFT_BADGE, "muted", ""
            else:
                stats = strategy_stats(
                    strategy.entry, strategy.exit, strategy.timeframe
                )
                badge, colour, line = _badge(stats)
                stats = line
            row = StrategyRow(
                strategy.name,
                strategy.timeframe,
                badge,
                colour,
                stats,
                is_draft=draft_flag,
                is_archived=strategy.archived,
                parent=self,
            )
            row.clicked.connect(self.chosen)
            row.archived.connect(self.archived)
            row.restored.connect(self.restored)
            row.deleted.connect(self.deleted)
            # The draft row is the one lit; a saved row of the same name is
            # not lit too.
            if draft_flag:
                row.set_selected(is_draft_row)
            else:
                row.set_selected(not is_draft_row and strategy.name == current)
            self.rows_layout.insertWidget(insert_at, row)
            self.rows.append(row)
            insert_at += 1


__all__ = [
    "ARCHIVED_BADGE",
    "DRAFT_BADGE",
    "StrategyListTile",
    "StrategyRow",
    "strategy_pnl",
    "strategy_stats",
]
