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
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lalala.cards import mono_font
from lalala.formula import FormulaError
from lalala.formula_builder import FormulaBuilder
from lalala.logs import install_qt_handler, setup
from lalala.panels import Card
from lalala.theme import CANVAS, CARD_GAP, apply_dark_theme


class PageStack(QStackedWidget):
    """A stack of pages whose size hints follow the page on show.

    A plain `QStackedWidget` reports the largest hint over *all* its pages
    whether or not they are visible, so the tall formula page would inflate
    the tile's minimum while the Rules page was the one on screen.
    """

    def _current(self):
        widget = self.currentWidget()
        return widget if widget is not None else None

    def minimumSizeHint(self):  # noqa: N802
        current = self._current()
        return (
            current.minimumSizeHint()
            if current is not None
            else super().minimumSizeHint()
        )

    def sizeHint(self):  # noqa: N802
        current = self._current()
        return current.sizeHint() if current is not None else super().sizeHint()

# The three columns, as a share of the width the tiles share between them.
COLUMN_SHARES = (0.21, 0.47, 0.32)

# The bar the strategy reads, one of the compactions the store supports.
TIMEFRAMES = ("1m", "5m", "15m", "1h")

# How the entry rules can be written: as drag-and-drop tiles, or as the code
# those tiles stand for.
ENTRY_MODES = (("formulas", "Formulas"), ("code", "Code"))


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("lalala · create a strategy")
        self.setMinimumSize(560, 420)
        self.resize(1280, 720)

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
        self.entry_tile = Card(self.center)
        self.exit_tile = Card(self.center)
        self.right = Card(self.splitter)

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

        # The entry tile's title shares its row with the three ways a rule can
        # be written: rows, a formula, or code.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        entry_title = QLabel("ENTRY RULES", self.entry_tile)
        entry_title.setObjectName("tileTitle")
        header.addWidget(entry_title)
        header.addStretch(1)

        self.entry_modes = QButtonGroup(self.entry_tile)
        self.entry_modes.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for index, (key, label) in enumerate(ENTRY_MODES):
            button = QPushButton(label, self.entry_tile)
            button.setObjectName("modeButton")
            button.setProperty("mode", key)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.entry_modes.addButton(button, index)
            self.mode_buttons[key] = button
            header.addWidget(button)
        self.entry_modes.idClicked.connect(self._pick_entry_mode)
        self.entry_tile.body.addLayout(header)

        # One page per mode: the tiles, and the code they stand for. Both edit
        # the same formula, so a change in either shows up in the other.
        self.entry_pages = PageStack(self.entry_tile)
        self.entry_pages.setObjectName("entryPages")
        self.entry_pages.addWidget(self._formula_page())
        self.entry_pages.addWidget(self._code_page())
        self.entry_tile.body.addWidget(self.entry_pages, 1)
        self.entry_pages.setCurrentIndex(0)
        self.entry_pages.currentChanged.connect(self._pages_changed)

        # The exit tile has only its title for now.
        exit_title = QLabel("EXIT RULES", self.exit_tile)
        exit_title.setObjectName("tileTitle")
        self.exit_tile.body.addWidget(exit_title)
        self.exit_tile.body.addStretch(1)

        for tile in (self.strategy_tile, self.entry_tile, self.exit_tile):
            self.center.addWidget(tile)
            tile.setMinimumWidth(120)
        self.center.setStretchFactor(0, 0)
        self.center.setStretchFactor(1, 0)   # entry: only the height it needs
        self.center.setStretchFactor(2, 1)   # exit: takes the rest
        self._column_set = False
        self._fit_pending = False
        self.entry_tile.installEventFilter(self)

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

    # -- the entry pages ---------------------------------------------------

    def _formula_page(self) -> QWidget:
        page = QWidget(self.entry_tile)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # The drag-and-drop builder. The formula text it produces is what the
        # checker reads and what a run would use; the chips are just an editor.
        self.formula = FormulaBuilder(page)
        self.formula.changed.connect(self._formula_changed)
        layout.addWidget(self.formula, 1)
        return page

    def _code_page(self) -> QWidget:
        page = QWidget(self.entry_tile)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # The same formula, as text. It starts as what the tiles read, and it
        # can be typed in directly; either side keeps the other in step.
        self.code_edit = QPlainTextEdit(page)
        self.code_edit.setObjectName("codeEdit")
        self.code_edit.setFont(mono_font(9))
        self.code_edit.setTabChangesFocus(True)
        self.code_edit.setMinimumHeight(96)
        self.code_edit.setPlaceholderText(
            "mid = sma(close, 20)\nclose < mid"
        )
        self.code_edit.setToolTip(
            "one condition, optionally after `name = …` lines"
        )
        self.code_edit.textChanged.connect(self._code_edited)

        self.code_error = QLabel("", page)
        self.code_error.setObjectName("formulaError")
        self.code_error.setWordWrap(True)
        self.code_note = QLabel(
            "the code the tiles stand for — edit it and the tiles follow",
            page,
        )
        self.code_note.setObjectName("hintLabel")
        self.code_note.setWordWrap(True)

        layout.addWidget(self.code_edit, 1)
        layout.addWidget(self.code_error)
        layout.addWidget(self.code_note)

        # A guard so the two views do not chase each other around.
        self._syncing = False
        return page

    def _formula_changed(self) -> None:
        """The builder's text changed; pass the word on and re-fit the tile."""
        self.entry_formula_changed.emit()
        self._schedule_fit()
        self._sync_code()

    def _code_edited(self) -> None:
        """The code was typed in; rebuild the tiles to match."""
        if self._syncing:
            return
        text = self.code_edit.toPlainText()
        self._syncing = True
        try:
            self.formula.set_formula(text)
        except FormulaError as exc:
            # A character the language cannot even scan.
            self.code_error.setText(str(exc))
            self._syncing = False
            return
        self._syncing = False
        self.code_error.setText(self.formula.error())

    def _sync_code(self) -> None:
        """Show the builder's text in the code view, and its verdict."""
        if self._syncing:
            return
        text = self.formula.formula_text()
        if self.code_edit.toPlainText() != text:
            self._syncing = True
            self.code_edit.setPlainText(text)
            self._syncing = False
        self.code_error.setText(self.formula.error())

    # -- the formula -------------------------------------------------------

    def entry_formula(self) -> str:
        """The formula text the chips add up to."""
        return self.formula.formula_text()

    def set_entry_formula(self, text: str) -> None:
        self.formula.set_formula(text)

    def entry_formula_error(self) -> str:
        """The checker's message, or "" when the formula is fine."""
        return self.formula.error()

    def entry_formula_parsed(self):
        """The parsed formula, or None while it is empty or invalid."""
        return self.formula.parsed()

    def column_sizes(self) -> list[int]:
        """Pixel widths that satisfy `COLUMN_SHARES`, in the current width."""
        usable = max(3, self.splitter.width() - 2 * CARD_GAP)
        left = round(usable * COLUMN_SHARES[0])
        middle = round(usable * COLUMN_SHARES[1])
        return [left, middle, usable - left - middle]

    def entry_mode(self) -> str:
        """Which of the three entry editors is showing."""
        for index, (key, _) in enumerate(ENTRY_MODES):
            button = self.entry_modes.button(index)
            if button is not None and button.isChecked():
                return key
        return ENTRY_MODES[0][0]

    def set_entry_mode(self, mode: str) -> None:
        for index, (key, _) in enumerate(ENTRY_MODES):
            if key == mode:
                self.entry_modes.button(index).setChecked(True)
                self._pick_entry_mode(index)
                return

    def _pages_changed(self) -> None:
        """A new page may want a different height; fit the tile to it."""
        self.entry_pages.updateGeometry()
        self.entry_tile.updateGeometry()
        self._schedule_fit()

    def _pick_entry_mode(self, index: int) -> None:
        if not 0 <= index < len(ENTRY_MODES):
            return
        self.entry_pages.setCurrentIndex(index)
        mode = ENTRY_MODES[index][0]
        if mode == "formulas":
            self.formula.number_edit.setFocus()
        elif mode == "code":
            # Show what the tiles stand for before taking the caret.
            self._sync_code()
            self.code_edit.setFocus()
        self.entry_mode_changed.emit(mode)

    def showEvent(self, event) -> None:  # noqa: N802
        """Lay the three tiles out once the real width is known."""
        super().showEvent(event)
        if not self._proportions_set:
            self._proportions_set = True
            self.splitter.setSizes(self.column_sizes())
        if not self._column_set:
            self._column_set = True
            self._schedule_fit()

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
        entry = min(available, self.entry_tile.minimumSizeHint().height())
        sizes = self.center.sizes()
        if len(sizes) == 3 and abs(sizes[1] - entry) <= 1:
            return
        self.center.setSizes([top, entry, max(0, available - entry)])

    def _fit_column(self) -> None:
        """The entry tile takes the least height its content needs.

        The strategy tile keeps only what it needs too, and the exit tile takes
        whatever is left. The entry tile's height is therefore fixed by its
        content, not by a share of the column — but it still follows the
        content, which rewraps as the window changes width.
        """
        self._maybe_fit()

    def eventFilter(self, obj, event):  # noqa: N802
        if (
            obj is self.entry_tile
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
