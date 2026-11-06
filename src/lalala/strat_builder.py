"""The strategy builder window, launched on its own.

Three vertical tiles side by side, splitting the width 21 / 47 / 32: a narrow
rail on the left, a middle column, and a wider rail on the right. The middle
column stacks three tiles: a compact **STRATEGY** tile with the strategy's name
and the timeframe it acts on, then **ENTRY RULES**, then **EXIT RULES**.

Standalone on purpose: nothing in the backtest window opens it, and nothing in
it is wired to the run, the parameters or the candle data.

    uv run lalala-builder

It carries the same canvas, cards and gap as the other windows, so it reads as
another sheet of the same desk rather than a separate application.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
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
from lalala.formula import HINT, FormulaError, parse
from lalala.logs import install_qt_handler, setup
from lalala.panels import Card
from lalala.theme import CANVAS, CARD_GAP, DOWN, apply_dark_theme

# The three columns, as a share of the width the tiles share between them.
COLUMN_SHARES = (0.21, 0.47, 0.32)

# The bar the strategy reads, one of the compactions the store supports.
TIMEFRAMES = ("1m", "5m", "15m", "1h")

# How the entry rules can be written: as rows, as a formula, or as code.
ENTRY_MODES = (("rules", "Rules"), ("formulas", "Formulas"), ("code", "Code"))


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

        # One page per mode. The formula page is the one that works today; the
        # other two say so, rather than pretending.
        self.entry_pages = QStackedWidget(self.entry_tile)
        self.entry_pages.setObjectName("entryPages")
        self.entry_pages.addWidget(self._rules_page())
        self.entry_pages.addWidget(self._formula_page())
        self.entry_pages.addWidget(self._code_page())
        self.entry_tile.body.addWidget(self.entry_pages, 1)
        self.entry_pages.setCurrentIndex(0)

        # The exit tile has only its title for now.
        exit_title = QLabel("EXIT RULES", self.exit_tile)
        exit_title.setObjectName("tileTitle")
        self.exit_tile.body.addWidget(exit_title)
        self.exit_tile.body.addStretch(1)

        for tile in (self.strategy_tile, self.entry_tile, self.exit_tile):
            self.center.addWidget(tile)
            tile.setMinimumWidth(120)
        self.center.setStretchFactor(0, 0)
        self.center.setStretchFactor(1, 1)
        self.center.setStretchFactor(2, 1)
        self._column_set = False

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

    def _rules_page(self) -> QWidget:
        page = QWidget(self.entry_tile)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel("no row editor yet — use Formulas", page)
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _formula_page(self) -> QWidget:
        page = QWidget(self.entry_tile)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.formula_edit = QPlainTextEdit(page)
        self.formula_edit.setObjectName("formulaEdit")
        self.formula_edit.setFont(mono_font(9))
        self.formula_edit.setTabChangesFocus(True)
        self.formula_edit.setPlaceholderText(
            "close < bollinger_lower(close, 20, 2)"
        )
        self.formula_edit.setToolTip(
            "One condition per bar, optionally after `name = …` lines"
        )
        self.formula_edit.textChanged.connect(self._validate_formula)

        # The checker writes here: the first thing wrong, and where.
        self.formula_error = QLabel("", page)
        self.formula_error.setObjectName("formulaError")
        self.formula_error.setWordWrap(True)

        self.formula_hint = QLabel(HINT, page)
        self.formula_hint.setObjectName("hintLabel")
        self.formula_hint.setWordWrap(True)

        layout.addWidget(self.formula_edit, 1)
        layout.addWidget(self.formula_error)
        layout.addWidget(self.formula_hint)

        # A parsed formula, or None while the text is empty or wrong.
        self._formula = None
        return page

    def _code_page(self) -> QWidget:
        page = QWidget(self.entry_tile)
        page.setObjectName("entryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel("no code editor yet", page)
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _validate_formula(self) -> None:
        """Check the text and report the first thing wrong."""
        text = self.formula_edit.toPlainText()
        if not text.strip():
            self._formula = None
            self.formula_error.setText("")
            self._mark_formula("")
            return
        try:
            self._formula = parse(text)
        except FormulaError as exc:
            self._formula = None
            self.formula_error.setText(str(exc))
            self._mark_formula("error")
        else:
            self.formula_error.setText("")
            self._mark_formula("ok")

    def _mark_formula(self, state: str) -> None:
        if self.formula_edit.property("state") == state:
            return
        self.formula_edit.setProperty("state", state)
        style = self.formula_edit.style()
        style.unpolish(self.formula_edit)
        style.polish(self.formula_edit)

    # -- the formula -------------------------------------------------------

    def entry_formula(self) -> str:
        """The text in the formula editor, as typed."""
        return self.formula_edit.toPlainText()

    def set_entry_formula(self, text: str) -> None:
        self.formula_edit.setPlainText(text)

    def entry_formula_error(self) -> str:
        """The checker's message, or "" when the formula is fine."""
        return self.formula_error.text()

    def entry_formula_parsed(self):
        """The parsed formula, or None while it is empty or invalid."""
        return self._formula

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

    def _pick_entry_mode(self, index: int) -> None:
        if not 0 <= index < len(ENTRY_MODES):
            return
        self.entry_pages.setCurrentIndex(index)
        if ENTRY_MODES[index][0] == "formulas":
            self.formula_edit.setFocus()
        self.entry_mode_changed.emit(ENTRY_MODES[index][0])

    def showEvent(self, event) -> None:  # noqa: N802
        """Lay the three tiles out once the real width is known."""
        super().showEvent(event)
        if not self._proportions_set:
            self._proportions_set = True
            self.splitter.setSizes(self.column_sizes())
        if not self._column_set:
            # The strategy tile keeps only the height its content needs; the
            # two under it split the rest evenly.
            self._column_set = True
            top = self.strategy_tile.sizeHint().height()
            rest = max(0, self.center.height() - top - 2 * CARD_GAP)
            first = rest // 2
            self.center.setSizes([top, first, rest - first])

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
