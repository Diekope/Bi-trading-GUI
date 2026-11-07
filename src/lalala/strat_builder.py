"""The strategy builder window, launched on its own.

Three vertical tiles side by side, splitting the width 21 / 47 / 32: a narrow
rail on the left, a middle column, and a wider rail on the right. The middle
column stacks three tiles: a compact **STRATEGY** tile with the strategy's name
and the timeframe it acts on, then **ENTRY RULES**, then **EXIT RULES**.

The entry tile offers two ways to write a rule: **Formulas**, the drag-and-drop
builder (`lalala.formula_builder`), and **Code**, the same formula as editable
text. Both edit one formula — the code starts as what the tiles read, typing in
it rebuilds the tiles, and a change on either side shows up on the other. The
checker (`lalala.formula`) is what keeps them honest.

Standalone on purpose: nothing in the backtest window opens it, and nothing in
it is wired to the run, the parameters or the candle data.

    uv run lalala-builder

It carries the same canvas, cards and gap as the other windows, so it reads as
another sheet of the same desk rather than a separate application.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QVBoxLayout,
    QWidget,
)

from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS
from lalala.formula_builder import EXIT_PALETTES
from lalala.logs import install_qt_handler, setup
from lalala.panels import Card
from lalala import strategies
from lalala.strategies import SavedStrategy
from lalala.strat_report import ReportTile
from lalala.strat_rules import EXIT_PRESETS, RulesSwitcher, RulesTile
from lalala.theme import CANVAS, CARD_GAP, apply_dark_theme

# The three columns, as a share of the width the tiles share between them.
COLUMN_SHARES = (0.21, 0.79)

# How much of the right column the two rules take; the report has the rest.
RULES_SHARE = 0.58

# The bar the strategy reads, one of the compactions the store supports.
TIMEFRAMES = ("1m", "5m", "15m", "1h")


class LockedHandle(QSplitterHandle):
    """A splitter handle that swallows a drag instead of moving a column.

    The columns keep the share they were given, at whatever size the window
    is; only the window itself changes them.
    """

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.ignore()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class LockedSplitter(QSplitter):
    """A splitter whose panes only move when the window resizes."""

    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return LockedHandle(self.orientation(), self)


class StrategyBuilderWindow(QMainWindow):
    """Two rails, then a compact strategy tile over the entry and exit rules."""

    entry_mode_changed = Signal(str)
    entry_formula_changed = Signal()
    exit_mode_changed = Signal(str)
    exit_formula_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("lalala · create a strategy")
        # The panels scroll, so the window does not have to be wide.
        self.setMinimumSize(900, 620)
        self.resize(1280, 960)

        canvas = QWidget(self)
        canvas.setObjectName("builderCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#builderCanvas {{ background-color: {CANVAS}; }}")

        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(CARD_GAP)

        # Three regions: a narrow rail on the left, then the two rules side by
        # side with the report under them. The outer handles are locked: the
        # share is fixed, and changes only when the window does.
        self.splitter = LockedSplitter(Qt.Orientation.Horizontal, canvas)
        self.splitter.setObjectName("builderSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(CARD_GAP)

        # The left rail: the small naming tile over an empty tile.
        self.left_column = QSplitter(Qt.Orientation.Vertical, self.splitter)
        self.left_column.setObjectName("builderLeft")
        self.left_column.setChildrenCollapsible(False)
        self.left_column.setHandleWidth(CARD_GAP)

        self.strategy_tile = Card(self.left_column)
        self.left = Card(self.left_column)

        # The rest: one rules tile switching between ENTRY and EXIT, with the
        # report under it.
        self.right_column = QSplitter(Qt.Orientation.Vertical, self.splitter)
        self.right_column.setObjectName("builderRight")
        self.right_column.setChildrenCollapsible(False)
        self.right_column.setHandleWidth(CARD_GAP)

        self.entry_tile = RulesTile("ENTRY RULES", header=False)
        # The exit tile is the same widget, but it reads the trade, not the
        # bar: TP, SL, PNL, price — and no indicators.
        self.exit_tile = RulesTile(
            "EXIT RULES",
            palettes=EXIT_PALETTES,
            fields=EXIT_FIELDS,
            functions=EXIT_FUNCTIONS,
            placeholder="pnl >= tp or pnl <= 0 - sl",
            presets=EXIT_PRESETS,
            header=False,
        )
        # The two rules are one tile now: their titles switch between them,
        # and the Rules / Formula / Code pills belong to the side on top.
        self.rules = RulesSwitcher(
            self.entry_tile, self.exit_tile, self.right_column
        )
        # Under the rules: what they did over the candles on disk.
        self.report = ReportTile(self.right_column)
        self.right = self.right_column

        # One tile, one row: the strategy's name and the timeframe it acts on.
        # The tile is titled, and nothing else is spaced around them.
        title = QLabel("STRATEGY", self.strategy_tile)
        title.setObjectName("tileTitle")
        self.strategy_tile.body.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.name_edit = QLineEdit(self.strategy_tile)
        self.name_edit.setObjectName("strategyName")
        self.name_edit.setPlaceholderText("name")

        self.timeframe = QComboBox(self.strategy_tile)
        self.timeframe.setObjectName("strategyTimeframe")
        self.timeframe.addItems(TIMEFRAMES)
        self.timeframe.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        row.addWidget(self.name_edit, 1)
        row.addWidget(self.timeframe)
        self.strategy_tile.body.addLayout(row)

        # The strategy tile is only as tall as its title and row; the two
        # below it share whatever is left.
        self.strategy_tile.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )

        # Both rules tiles read the same way — a title row of Formulas/Code
        # pills over one formula each. Nothing is shared between them.
        self.entry = self.entry_tile
        self.exit = self.exit_tile

        # The entry/exit tiles are the same widget; these are the entry's, kept
        # here because that is the one the window's fit and signals act on.
        self.formula = self.entry.formula
        self.entry_pages = self.entry.pages
        self.mode_buttons = self.entry.mode_buttons
        self.entry_modes = self.entry.modes
        self.code_edit = self.entry.code_edit
        self.code_error = self.entry.code_error
        self.entry.changed.connect(self._formula_changed)
        self.entry.mode_changed.connect(self.entry_mode_changed)
        self.exit.changed.connect(self._exit_changed)
        self.exit.mode_changed.connect(self.exit_mode_changed)
        self.timeframe.currentTextChanged.connect(self._sync_report)
        self.timeframe.currentTextChanged.connect(self._describe_draft)
        self.name_edit.textChanged.connect(self._describe_draft)

        # The naming tile is small and sits at the top of the left rail; the
        # empty tile takes the rest of it. The rules tile takes the width above
        # the report.
        self.left_column.addWidget(self.strategy_tile)
        self.left_column.addWidget(self.left)
        self.right_column.addWidget(self.rules)
        self.right_column.addWidget(self.report)
        self.strategy_tile.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self.left_column.setStretchFactor(0, 0)   # naming: its own small height
        self.left_column.setStretchFactor(1, 1)
        self.right_column.setStretchFactor(0, 1)  # the rules take the upper part
        self.right_column.setStretchFactor(1, 1)
        self._column_set = False
        self._fit_pending = False
        self.entry_tile.installEventFilter(self)
        self.exit_tile.installEventFilter(self)

        for column in (self.left_column, self.right_column):
            self.splitter.addWidget(column)
            column.setMinimumWidth(160)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self._proportions_set = False

        layout.addWidget(self.splitter, 1)
        layout.addLayout(self._footer())
        self.setCentralWidget(canvas)

    # -- the footer ---------------------------------------------------------

    def _footer(self) -> QHBoxLayout:
        """The draft on the left, Reset and Save on the right."""
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)

        self.draft = QLabel("untitled · unsaved", self)
        self.draft.setObjectName("draftLabel")
        row.addWidget(self.draft)
        row.addStretch(1)

        self.reset_button = QPushButton("Reset", self)
        self.reset_button.setObjectName("ghostButton")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.setToolTip("clear the draft: name, bar and both rules")
        self.reset_button.clicked.connect(self.reset_draft)

        self.save_button = QPushButton("Save", self)
        self.save_button.setObjectName("saveButton")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.setToolTip("keep this strategy under its name")
        self.save_button.clicked.connect(self.save_draft)

        row.addWidget(self.reset_button)
        row.addWidget(self.save_button)
        return row

    def _describe_draft(self) -> None:
        name = self.name_edit.text().strip()
        self.draft.setText(f"{name or 'untitled'} · unsaved")

    def reset_draft(self) -> None:
        """Clear the draft back to nothing."""
        self.name_edit.setText("")
        self.timeframe.setCurrentIndex(0)
        self.entry.reset_draft()
        self.exit.reset_draft()
        self._describe_draft()
        self._sync_report()

    def save_draft(self) -> None:
        """Keep the draft under its name, and say so."""
        name = self.name_edit.text().strip()
        if not name:
            self.draft.setText("give it a name first")
            return
        if self.entry.error() or self.exit.error():
            self.draft.setText("fix the rules before saving")
            return
        saved = strategies.save(
            SavedStrategy(
                name=name,
                timeframe=self.timeframe.currentText(),
                entry=self.entry_formula(),
                exit=self.exit_formula(),
            )
        )
        self.draft.setText(f"saved “{name}” · {len(saved)} kept")

    # -- the formula -------------------------------------------------------

    def _formula_changed(self) -> None:
        """The entry builder changed; pass the word on and re-fit the tiles."""
        self.entry_formula_changed.emit()
        self._schedule_fit()
        self._sync_report()

    def _exit_changed(self) -> None:
        self.exit_formula_changed.emit()
        self._schedule_fit()
        self._sync_report()

    def _sync_report(self) -> None:
        """Show the rules as they now stand on the candles."""
        self.report.configure(
            self.entry.parsed(),
            self.exit.parsed(),
            self.timeframe.currentText(),
        )
        # The panel beside the editor shows the newest bar's numbers.
        values, result = self.report.watch
        self.entry.set_values(values, result)

    def entry_formula(self) -> str:
        """The entry formula text the tiles add up to."""
        return self.entry.text()

    def set_entry_formula(self, text: str) -> None:
        self.entry.set_text(text)

    def entry_formula_error(self) -> str:
        """The checker's message, or "" when the formula is fine."""
        return self.entry.error()

    def entry_formula_parsed(self):
        """The parsed formula, or None while it is empty or invalid."""
        return self.entry.parsed()

    def exit_formula(self) -> str:
        return self.exit.text()

    def set_exit_formula(self, text: str) -> None:
        self.exit.set_text(text)

    def exit_formula_error(self) -> str:
        return self.exit.error()

    def exit_formula_parsed(self):
        return self.exit.parsed()

    def column_sizes(self) -> list[int]:
        """Pixel widths that satisfy `COLUMN_SHARES`, in the current width."""
        usable = max(3, self.splitter.width() - CARD_GAP)
        left = round(usable * COLUMN_SHARES[0])
        return [left, usable - left]

    def entry_mode(self) -> str:
        """Which entry editor is showing."""
        return self.entry.mode()

    def set_entry_mode(self, mode: str) -> None:
        self.entry.set_mode(mode)

    def exit_mode(self) -> str:
        return self.exit.mode()

    def set_exit_mode(self, mode: str) -> None:
        self.exit.set_mode(mode)

    def showEvent(self, event) -> None:  # noqa: N802
        """Lay the three tiles out once the real width is known."""
        super().showEvent(event)
        if not self._proportions_set:
            self._proportions_set = True
            self.splitter.setSizes(self.column_sizes())
        if not self._column_set:
            self._column_set = True
            self._schedule_fit()
        self._sync_report()

    def _schedule_fit(self) -> None:
        """Fit the column once Qt has settled, not mid-change.

        The entry tile's minimum only reflects the newly shown page after the
        stack has laid it out, and that lands a turn later. Rather than guess,
        the tile's own layout requests drive the fit: every time its layout
        changes, we re-check. `_maybe_fit` only resizes when the height really
        differs, so the loop stops as soon as it settles.
        """
        self._fit_pending = True
        QTimer.singleShot(0, self._maybe_fit)

    def _maybe_fit(self) -> None:
        self._fit_pending = False
        # The rail and the rest keep their exact share of the width.
        columns = self.column_sizes()
        if self.splitter.sizes() != columns and self.splitter.width() > 0:
            self.splitter.setSizes(columns)

        # The naming tile at the top of the rail, the empty tile under it.
        top = self.strategy_tile.sizeHint().height()
        rest = max(0, self.left_column.height() - top - CARD_GAP)
        heights = self.left_column.sizes()
        wanted = [top, rest]
        if len(heights) != 2 or any(
            abs(heights[i] - wanted[i]) > 1 for i in range(2)
        ):
            self.left_column.setSizes(wanted)

        # The rules on the upper part of the right column, the report under
        # them.
        available = max(0, self.right_column.height() - CARD_GAP)
        upper = int(available * RULES_SHARE)
        heights = self.right_column.sizes()
        wanted = [upper, available - upper]
        if len(heights) != 2 or any(
            abs(heights[i] - wanted[i]) > 1 for i in range(2)
        ):
            self.right_column.setSizes(wanted)

    def _fit_column(self) -> None:
        """The rail keeps its share; the rules over the report in the rest."""
        self._maybe_fit()

    def eventFilter(self, obj, event):  # noqa: N802
        if (
            obj in (self.entry_tile, self.exit_tile)
            and self._column_set
            and event.type() == QEvent.Type.LayoutRequest
        ):
            self._maybe_fit()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # A new width rewraps the palette rows, so the least height changes.
        if self._column_set:
            self._schedule_fit()

    def is_open(self) -> bool:
        return self.isVisible()


def run(argv: list[str] | None = None) -> int:
    """Open the builder on its own. Returns the Qt exit code."""
    # A file, never the console, like the other windows.
    setup()
    install_qt_handler()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setApplicationName("lalala")
    QApplication.setOrganizationName("lalala")

    app = QApplication(list(sys.argv if argv is None else argv))
    apply_dark_theme(app)

    window = StrategyBuilderWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    return app.exec()


__all__ = ["StrategyBuilderWindow", "run"]
