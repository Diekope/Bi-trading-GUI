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
from lalala.strat_report import ReportTile
from lalala.strat_rules import EXIT_PRESETS, RulesTile
from lalala.theme import CANVAS, CARD_GAP, apply_dark_theme

# The three columns, as a share of the width the tiles share between them.
COLUMN_SHARES = (0.21, 0.47, 0.32)

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
        self.setMinimumSize(560, 560)
        self.resize(1280, 960)

        canvas = QWidget(self)
        canvas.setObjectName("builderCanvas")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas.setStyleSheet(f"#builderCanvas {{ background-color: {CANVAS}; }}")

        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(CARD_GAP, CARD_GAP, CARD_GAP, CARD_GAP)
        layout.setSpacing(CARD_GAP)

        # Vertical split: three tiles side by side, the gap doing the dividing
        # rather than a drawn line. The handles are locked: the 21/47/32 share
        # is fixed, and changes only when the window does.
        self.splitter = LockedSplitter(Qt.Orientation.Horizontal, canvas)
        self.splitter.setObjectName("builderSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(CARD_GAP)

        self.left = Card(self.splitter)
        # The middle column is a vertical split of three tiles, not one tile
        # divided: each has its own card chrome, separated by the same gap.
        self.center = QSplitter(Qt.Orientation.Vertical, self.splitter)
        self.center.setObjectName("builderMiddleSplit")
        self.center.setChildrenCollapsible(False)
        self.center.setHandleWidth(CARD_GAP)

        self.strategy_tile = Card(self.center)
        self.entry_tile = RulesTile("ENTRY RULES", self.center)
        # The exit tile is the same widget, but it reads the trade, not the
        # bar: TP, SL, PNL, price — and no indicators.
        self.exit_tile = RulesTile(
            "EXIT RULES",
            self.center,
            palettes=EXIT_PALETTES,
            fields=EXIT_FIELDS,
            functions=EXIT_FUNCTIONS,
            placeholder="pnl >= tp or pnl <= 0 - sl",
            presets=EXIT_PRESETS,
        )
        # The right rail reports what the rule did over the candles on disk.
        self.report = ReportTile(self.splitter)
        self.right = self.report

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

        for tile in (self.strategy_tile, self.entry_tile, self.exit_tile):
            self.center.addWidget(tile)
            tile.setMinimumWidth(120)
        self.center.setStretchFactor(0, 0)
        self.center.setStretchFactor(1, 0)   # entry: only the height it needs
        self.center.setStretchFactor(2, 1)   # exit: takes the rest
        self._column_set = False
        self._fit_pending = False
        self.entry_tile.installEventFilter(self)
        self.exit_tile.installEventFilter(self)

        for column in (self.left, self.center, self.right):
            self.splitter.addWidget(column)
            # The card's default floor is too high for a 21% rail: it would
            # win the argument with the proportions at ordinary widths.
            column.setMinimumWidth(120)
        for column in range(3):
            self.splitter.setStretchFactor(column, 1)
        self._proportions_set = False

        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(canvas)

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
        usable = max(3, self.splitter.width() - 2 * CARD_GAP)
        left = round(usable * COLUMN_SHARES[0])
        middle = round(usable * COLUMN_SHARES[1])
        return [left, middle, usable - left - middle]

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
        top = self.strategy_tile.sizeHint().height()
        available = max(0, self.center.height() - top - 2 * CARD_GAP)
        # The two rules tiles share the column evenly.
        entry = available // 2
        exit_ = available - entry
        sizes = self.center.sizes()
        wanted = [top, entry, exit_]
        if len(sizes) == 3 and all(
            abs(sizes[i] - wanted[i]) <= 1 for i in range(3)
        ):
            return
        self.center.setSizes(wanted)

    def _fit_column(self) -> None:
        """The two rules tiles share the middle column evenly.

        The strategy tile keeps only the height its content needs; everything
        below it is split half and half between entry and exit.
        """
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
