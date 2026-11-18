"""The Logs view: the session's trading events, searchable, with the why.

Built from a design mockup. A strip of today's figures, a row of
filters, the event table beside a details panel, and a footer. It reads the
shared `EventLog` and keeps itself current while it is open.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bi_trading.state.events import Event, EventLog, event_log
from bi_trading.state.settings import load_columns, save_columns
from bi_trading.ui.shortcuts import bind
from bi_trading.ui.venue_icons import venue_pixmap
from bi_trading.ui.palette import (
    ACCENT,
    AMBER_DOT,
    BORDER,
    DOWN,
    HL_DOT,
    MONO,
    MUTED,
    PANEL,
    PM_DOT,
    SOFT,
    TEXT,
    TRACK,
    UP,
    WELL,
)

# How many rows the table holds at once; the log itself keeps more.
SHOWN = 1_000

SOURCE_FILTERS = (
    ("all", "All"),
    ("polymarket", "Polymarket"),
    ("hyperliquid", "Hyperliquid"),
    ("strategy", "Strategy"),
    ("system", "System"),
)

# Source badge: (letter, background, letter colour, display name).
BADGES = {
    "system": ("i", "#2a2b31", SOFT, "System"),
    "hyperliquid": ("H", HL_DOT, "#04060c", "Hyperliquid"),
    "polymarket": ("P", PM_DOT, "#ffffff", "Polymarket"),
    "strategy": ("S", ACCENT, "#101114", "Strategy"),
}

# Level: (word, colour, icon). Info has no icon, as in the design.
LEVEL_STYLE = {
    "info": ("INFO", MUTED, None),
    "warn": ("WARN", AMBER_DOT, "warn"),
    "error": ("ERROR", DOWN, "error"),
}


def _level_pixmap(icon: str, colour: str, size: int = 14):
    """The level's stroke icon, from the same set as the rail's."""
    from bi_trading.ui.hub.hub_widgets import _svg_icon

    return _svg_icon(icon, colour, size).pixmap(size, size)

# Origin chip: (text colour, border, fill).
CHIPS = {
    "manual": (ACCENT, "#4a3f1a", "#1d1b12"),
    "auto": ("#a3a8ff", "#33366b", "#181a30"),
}

COLUMNS = ("Time", "Level", "Source", "Origin", "Event", "Message")
WIDTHS = (116, 80, 124, 84, 104)

QSS = f"""
QWidget#logsView {{ background: transparent; }}
QLabel {{ background: transparent; }}
QHeaderView {{ background: transparent; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QLabel#logK {{ font-size: 11px; color: {MUTED}; }}
QLabel#logV {{ font-family: {MONO}; font-size: 13px; font-weight: 600; color: #ffffff; }}
QLabel#logH {{ font-size: 11px; font-weight: 600; letter-spacing: 2px; color: #e2e2e5; }}
QLabel#logGl {{ font-size: 10px; font-weight: 600; letter-spacing: 1px; color: {MUTED}; }}
QLabel#logRowK {{ font-family: {MONO}; font-size: 12px; color: {MUTED}; }}
QLabel#logRowV {{ font-family: {MONO}; font-size: 12px; color: {TEXT}; }}
QLabel#logFoot {{ font-size: 11px; color: {MUTED}; }}
QLabel#logCode {{
    font-family: {MONO}; font-size: 12px; color: {SOFT};
    background: {WELL}; border-radius: 6px; padding: 9px 10px;
}}
QFrame#logPanel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#logRule {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QLineEdit#logSearch, QComboBox#logCombo {{
    background: {TRACK}; border: 1px solid #2a2b31; border-radius: 6px;
    color: {TEXT}; padding: 6px 10px; font-size: 13px;
}}
QComboBox#logCombo QAbstractItemView {{
    background: {TRACK}; color: {TEXT}; border: 1px solid #2a2b31;
    selection-background-color: #231f10; selection-color: {ACCENT};
}}
QPushButton#logPill {{
    background: {TRACK}; border: 1px solid #2a2b31; border-radius: 5px;
    color: {MUTED}; padding: 4px 10px; font-size: 11px; font-weight: 500;
}}
QPushButton#logPill:checked {{ background: #231f10; border-color: #4a3f1a; color: {ACCENT}; }}
QPushButton#logGhost {{
    background: {TRACK}; border: 1px solid #2a2b31; border-radius: 6px;
    color: {SOFT}; padding: 8px 12px; font-size: 13px; font-weight: 500;
}}
QPushButton#logGhost:hover {{ background: #25262b; }}
QPushButton#logAccent {{
    background: #231f10; border: 1px solid #4a3f1a; border-radius: 6px;
    color: {ACCENT}; padding: 9px 14px; font-size: 13px; font-weight: 500;
}}
QCheckBox#logAuto {{ font-size: 12px; color: {TEXT}; spacing: 6px; }}
QTableWidget#logTable {{
    background: transparent; border: none; outline: none;
    font-family: {MONO}; font-size: 12px; color: {SOFT};
    selection-background-color: #1d1b12; selection-color: {SOFT};
}}
QTableWidget#logTable::item {{ padding: 0 6px; border-bottom: 1px solid #1f2024; }}
QHeaderView::section {{
    background: transparent; border: none; border-bottom: 1px solid {BORDER};
    color: {MUTED}; font-size: 11px; font-weight: 500; padding: 8px 6px; text-align: left;
}}
"""


def _badge_pixmap(letter: str, fill: str, ink: str, size: int = 14):
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.25, size * 0.25)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(9)
    painter.setFont(font)
    painter.setPen(QColor(ink))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return pixmap


class _SourceDelegate(QStyledItemDelegate):
    """A coloured letter badge and the source's name."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        source = index.data(Qt.ItemDataRole.UserRole)
        letter, fill, ink, name = BADGES.get(source, BADGES["system"])
        if option.state & option.state.State_Selected:  # type: ignore[attr-defined]
            painter.fillRect(option.rect, QColor("#1d1b12"))
        rect = option.rect
        painter.save()
        # A venue shows its own mark; strategy and system keep the letter badge.
        mark = venue_pixmap(source, 14) if source in ("polymarket", "hyperliquid") else None
        painter.drawPixmap(rect.left() + 6, rect.top() + (rect.height() - 14) // 2,
                           mark if mark is not None else _badge_pixmap(letter, fill, ink))
        painter.setPen(QColor(SOFT))
        painter.drawText(rect.adjusted(26, 0, 0, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        painter.setPen(QPen(QColor("#1f2024")))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()


class _LevelDelegate(QStyledItemDelegate):
    """The level's icon (warn, error) and its word."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        level = index.data(Qt.ItemDataRole.UserRole) or "info"
        word, colour, icon = LEVEL_STYLE.get(level, LEVEL_STYLE["info"])
        rect = option.rect
        painter.save()
        if option.state & option.state.State_Selected:  # type: ignore[attr-defined]
            painter.fillRect(rect, QColor("#1d1b12"))
        left = rect.left() + 6
        if icon is not None:
            painter.drawPixmap(left, rect.top() + (rect.height() - 14) // 2,
                               _level_pixmap(icon, colour))
            left += 19
        font = QFont(painter.font())
        font.setBold(icon is not None)
        painter.setFont(font)
        painter.setPen(QColor(colour))
        painter.drawText(rect.adjusted(left - rect.left(), 0, 0, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, word)
        painter.setPen(QPen(QColor("#1f2024")))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()


class _OriginDelegate(QStyledItemDelegate):
    """Manual / Auto as a small bordered chip; a dash when there is none."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        origin = index.data(Qt.ItemDataRole.UserRole) or ""
        rect = option.rect
        painter.save()
        if option.state & option.state.State_Selected:  # type: ignore[attr-defined]
            painter.fillRect(rect, QColor("#1d1b12"))
        if origin in CHIPS:
            ink, edge, fill = CHIPS[origin]
            text = origin.capitalize()
            font = QFont(painter.font())
            font.setPixelSize(11)
            painter.setFont(font)
            width = painter.fontMetrics().horizontalAdvance(text) + 14
            chip = QRectF(rect.left() + 6, rect.top() + (rect.height() - 20) / 2, width, 20)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(edge)))
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(chip, 5, 5)
            painter.setPen(QColor(ink))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        else:
            painter.setPen(QColor(MUTED))
            painter.drawText(rect.adjusted(8, 0, 0, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "—")
        painter.setPen(QPen(QColor("#1f2024")))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        return QSize(78, 30)


class LogsView(QWidget):
    """Today's figures, filters, the event table and the details of one event."""

    open_live = Signal()

    def __init__(self, log: EventLog | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("logsView")
        self.setStyleSheet(QSS)
        self._log = log if log is not None else event_log()
        self._source = "all"
        self._paused = False
        self._rows: list[Event] = []
        self._selected: Event | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(12)
        column.addLayout(self._stats())
        column.addLayout(self._filters())
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._table_panel(), 1)
        body.addWidget(self._details_panel(), 0)
        column.addLayout(body, 1)
        column.addLayout(self._footer())

        self._log.added.connect(self._on_added)
        self._log.cleared.connect(self.refresh)
        self._log.reloaded.connect(self.refresh)
        self.refresh()

        # Keys that work anywhere in this view (see ui/shortcuts.py).
        for keys in ("Ctrl+F", "/"):
            bind(self, keys, self._focus_search)
        bind(self, "Esc", self.search.clear)
        bind(self, "Ctrl+P", self._toggle_pause)
        bind(self, "Ctrl+E", self._export)
        bind(self, "Ctrl+Shift+Backspace", self._log.clear)

    # -- building ----------------------------------------------------------

    def _stats(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(34)
        self._stat: dict[str, QLabel] = {}
        self._stat_icon: dict[str, QLabel] = {}
        for key, caption in (
            ("orders", "Orders"), ("filled", "Filled"), ("rejected", "Rejected"),
            ("warnings", "Warnings"), ("pnl", "Day PnL"),
        ):
            box = QVBoxLayout()
            box.setSpacing(5)
            name = QLabel(caption)
            name.setObjectName("logK")
            value = QLabel("0")
            value.setObjectName("logV")
            value.setTextFormat(Qt.TextFormat.RichText)
            box.addWidget(name)
            if key in ("rejected", "warnings"):
                # The level's own icon beside the count, shown while it is > 0.
                line = QHBoxLayout()
                line.setSpacing(5)
                icon = QLabel()
                icon.setFixedSize(14, 14)
                icon.setVisible(False)
                line.addWidget(icon)
                line.addWidget(value)
                line.addStretch(1)
                box.addLayout(line)
                self._stat_icon[key] = icon
            else:
                box.addWidget(value)
            row.addLayout(box)
            self._stat[key] = value
        row.addStretch(1)
        return row

    def _filters(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("logSearch")
        self.search.setPlaceholderText("Search logs…")
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search)

        pills = QHBoxLayout()
        pills.setSpacing(4)
        self._pills: dict[str, QPushButton] = {}
        for key, text in SOURCE_FILTERS:
            pill = QPushButton(text)
            pill.setObjectName("logPill")
            pill.setCheckable(True)
            pill.setChecked(key == "all")
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.clicked.connect(lambda _=False, k=key: self._pick_source(k))
            pills.addWidget(pill)
            self._pills[key] = pill
        row.addLayout(pills)

        self.origin = self._combo(("Origin: all", "Manual", "Auto"), 110)
        self.level = self._combo(("Level: all", "Info", "Warn", "Error"), 104)
        self.strategy = self._combo(("Strategy: all",), 150)
        row.addWidget(self.origin)
        row.addWidget(self.level)
        row.addWidget(self.strategy)
        row.addStretch(1)

        self.pause_button = self._ghost("Pause", self._toggle_pause)
        row.addWidget(self.pause_button)
        row.addWidget(self._ghost("Clear", self._log.clear))
        row.addWidget(self._ghost("Export", self._export))
        return row

    def _combo(self, items: tuple[str, ...], width: int) -> QComboBox:
        box = QComboBox()
        box.setObjectName("logCombo")
        box.addItems(items)
        box.setFixedWidth(width)
        box.currentIndexChanged.connect(self.refresh)
        return box

    @staticmethod
    def _ghost(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("logGhost")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _=False: slot())
        return button

    def _table_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("logPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 6, 12, 6)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("logTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        # The columns can be dragged, and are kept where they are left (the last
        # one takes what remains, so it is not saved).
        remembered = load_columns("logs")
        if len(remembered) != len(COLUMNS) - 1:
            remembered = list(WIDTHS)
        for column, width in enumerate(remembered):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self._save_columns_timer = QTimer(self)
        self._save_columns_timer.setSingleShot(True)
        self._save_columns_timer.setInterval(400)
        self._save_columns_timer.timeout.connect(self._save_columns)
        header.sectionResized.connect(
            lambda index, *_: index < len(COLUMNS) - 1 and self._save_columns_timer.start()
        )
        self.table.setItemDelegateForColumn(1, _LevelDelegate(self.table))
        self.table.setItemDelegateForColumn(2, _SourceDelegate(self.table))
        self.table.setItemDelegateForColumn(3, _OriginDelegate(self.table))
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table)
        return panel

    def _save_columns(self) -> None:
        save_columns(
            "logs", [self.table.columnWidth(i) for i in range(len(COLUMNS) - 1)]
        )

    def _details_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("logPanel")
        panel.setFixedWidth(310)
        column = QVBoxLayout(panel)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(8)
        title = QLabel("DETAILS")
        title.setObjectName("logH")
        column.addWidget(title)

        head = QHBoxLayout()
        head.setSpacing(8)
        self._d_level_icon = QLabel()
        self._d_level_icon.setFixedSize(14, 14)
        self._d_level = QLabel("")
        self._d_level.setFont(self._mono(bold=True))
        self._d_kind = QLabel("")
        self._d_kind.setFont(self._mono())
        head.addWidget(self._d_level_icon)
        head.addWidget(self._d_level)
        head.addWidget(self._d_kind)
        head.addStretch(1)
        column.addLayout(head)

        self._d_rows: dict[str, QLabel] = {}
        for key, caption in (
            ("time", "Time"), ("source", "Source"), ("origin", "Origin"),
            ("latency", "Latency"),
        ):
            rule = QFrame()
            rule.setObjectName("logRule")
            column.addWidget(rule)
            line = QHBoxLayout()
            name = QLabel(caption)
            name.setObjectName("logRowK")
            value = QLabel("")
            value.setObjectName("logRowV")
            line.addWidget(name)
            line.addStretch(1)
            line.addWidget(value)
            column.addLayout(line)
            self._d_rows[key] = value
        self._d_latency_row = (name, value)

        self._d_why_title = self._gl("Why it fired")
        self._d_why = self._code()
        self._d_request_title = self._gl("Request / response")
        self._d_request = self._code()
        for widget in (self._d_why_title, self._d_why, self._d_request_title, self._d_request):
            column.addWidget(widget)
        column.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        copy = self._ghost("Copy", self._copy)
        live = QPushButton("Open in Live")
        live.setObjectName("logAccent")
        live.setCursor(Qt.CursorShape.PointingHandCursor)
        live.clicked.connect(lambda _=False: self.open_live.emit())
        buttons.addWidget(copy, 1)
        buttons.addWidget(live, 1)
        column.addLayout(buttons)
        self._show_details(None)
        return panel

    @staticmethod
    def _gl(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("logGl")
        return label

    @staticmethod
    def _code() -> QLabel:
        label = QLabel("")
        label.setObjectName("logCode")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _mono(bold: bool = False) -> QFont:
        from bi_trading.ui.fonts import MONO_FAMILY

        font = QFont(MONO_FAMILY)
        font.setPixelSize(12)
        font.setBold(bold)
        return font

    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        self._count = QLabel("")
        self._count.setObjectName("logFoot")
        self.autoscroll = QCheckBox("Auto-scroll")
        self.autoscroll.setObjectName("logAuto")
        self.autoscroll.setChecked(True)
        row.addWidget(self._count)
        self.older_button = QPushButton("Load older")
        self.older_button.setObjectName("logPill")
        self.older_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.older_button.clicked.connect(lambda _=False: self._log.load_older())
        row.addWidget(self.older_button)
        row.addStretch(1)
        row.addWidget(self.autoscroll)
        return row

    # -- behaviour ---------------------------------------------------------

    def _pick_source(self, key: str) -> None:
        self._source = key
        for name, pill in self._pills.items():
            pill.setChecked(name == key)
        self.refresh()

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.setText("Resume" if self._paused else "Pause")
        if not self._paused:
            self.refresh()

    def _export(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self, "Export the log", "bi-trading-log.csv", "CSV (*.csv)"
        )
        if target:
            self._log.export_csv(target)

    def _copy(self) -> None:
        event = self._selected
        if event is not None:
            QGuiApplication.clipboard().setText(
                f"{event.clock()} {event.level.upper()} {event.source} "
                f"{event.kind} {event.message}"
            )

    def _matches(self, event: Event) -> bool:
        if self._source != "all" and event.source != self._source:
            return False
        origin = self.origin.currentText()
        if origin != "Origin: all" and event.origin != origin.lower():
            return False
        level = self.level.currentText()
        if level != "Level: all" and event.level != level.lower():
            return False
        if self._strategy() and event.strategy != self._strategy():
            return False
        needle = self.search.text().strip().lower()
        if needle:
            haystack = f"{event.message} {event.kind} {event.source} {event.origin}".lower()
            return needle in haystack
        return True

    def _strategy(self) -> str:
        """The strategy picked in the filter, or "" for all."""
        index = self.strategy.currentIndex()
        return "" if index <= 0 else self.strategy.currentText()

    def _sync_strategies(self) -> None:
        """Offer the strategies seen so far, keeping the pick."""
        names = self._log.strategies()
        have = [self.strategy.itemText(i) for i in range(1, self.strategy.count())]
        if names == have:
            return
        keep = self._strategy()
        self.strategy.blockSignals(True)
        self.strategy.clear()
        self.strategy.addItem("Strategy: all")
        self.strategy.addItems(names)
        if keep in names:
            self.strategy.setCurrentText(keep)
        self.strategy.blockSignals(False)

    def _on_added(self, _event: Event) -> None:
        if not self._paused:
            self.refresh()

    def refresh(self, *_: object) -> None:
        """Rebuild the table and the figures from the log, newest first."""
        self._sync_strategies()
        today = self._log.today(self._strategy())
        self._rows = [e for e in reversed(self._log.events()) if self._matches(e)][:SHOWN]

        keep = self._selected
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.clearSelection()  # a stale row index would name another event
        self.table.setRowCount(len(self._rows))
        selected_row = -1
        for row, event in enumerate(self._rows):
            self._fill_row(row, event)
            if event is keep:
                selected_row = row
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            # Dropping rows moves the current cell, which would select a
            # neighbour on its own: leave nothing selected instead.
            self.table.setCurrentCell(-1, -1)
            self.table.clearSelection()
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        if self.autoscroll.isChecked() and not self._paused:
            self.table.scrollToTop()

        self._show_stats()
        self._count.setText(
            f"Showing {len(self._rows):,} of {len(today):,} events · today"
            + (f" · {self._log.stored():,} older stored" if self._log.has_older() else "")
        )
        self.older_button.setVisible(self._log.has_older())
        if keep is not None and selected_row < 0:
            self._selected = None
            self._show_details(None)

    def _fill_row(self, row: int, event: Event) -> None:
        cells = (
            event.clock(), "", "", "", event.kind, event.message,
        )
        roles = {1: event.level, 2: event.source, 3: event.origin}
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if column in roles:  # drawn by the column's delegate
                item.setData(Qt.ItemDataRole.UserRole, roles[column])
            item.setForeground(QColor(SOFT))
            self.table.setItem(row, column, item)

    def _show_stats(self) -> None:
        counts = self._log.counts(self._strategy())
        self._stat["orders"].setText(f"{counts['orders']:,.0f}")
        self._stat["filled"].setText(f"{counts['filled']:,.0f}")
        for key, level in (("rejected", "error"), ("warnings", "warn")):
            _, colour, icon = LEVEL_STYLE[level]
            count = counts[key]
            self._stat[key].setText(self._tinted(count, colour))
            mark = self._stat_icon[key]
            mark.setVisible(bool(count))
            if count and icon is not None:
                mark.setPixmap(_level_pixmap(icon, colour))
        pnl = counts["pnl"]
        if pnl:
            sign, tint = ("+", UP) if pnl > 0 else ("−", DOWN)
            arrow = "▲" if pnl > 0 else "▼"
            self._stat["pnl"].setText(
                f'<span style="color:{tint}"><span style="font-size:9px">{arrow}</span> '
                f"{sign}${abs(pnl):,.2f}</span>"
            )
        else:
            self._stat["pnl"].setText("$0.00")

    @staticmethod
    def _tinted(count: float, colour: str) -> str:
        if not count:
            return "0"
        return f'<span style="color:{colour}">{count:,.0f}</span>'

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._rows):
            return
        self._selected = self._rows[rows[0].row()]
        self._show_details(self._selected)

    def _show_details(self, event: Event | None) -> None:
        if event is None:
            self._d_level_icon.clear()
            self._d_level.setText("")
            self._d_kind.setText("Select an event")
            for label in self._d_rows.values():
                label.setText("")
            for widget in (self._d_why_title, self._d_why, self._d_request_title, self._d_request):
                widget.setVisible(False)
            return
        word, colour, icon = LEVEL_STYLE.get(event.level, LEVEL_STYLE["info"])
        self._d_level.setText(word)
        self._d_level.setStyleSheet(f"color: {colour};")
        if icon is None:
            self._d_level_icon.clear()
        else:
            self._d_level_icon.setPixmap(_level_pixmap(icon, colour))
        self._d_kind.setText(event.kind)
        self._d_rows["time"].setText(event.clock())
        self._d_rows["source"].setText(BADGES.get(event.source, BADGES["system"])[3])
        origin = event.origin.capitalize() if event.origin else "—"
        who = event.strategy
        self._d_rows["origin"].setText(f"{origin} · {who}" if event.origin and who else origin)
        latency = event.detail.get("latency_ms")
        self._d_rows["latency"].setText("—" if latency is None else f"{latency:,.0f} ms")

        why = event.detail.get("why")
        self._d_why_title.setVisible(bool(why))
        self._d_why.setVisible(bool(why))
        if why:
            self._d_why.setText(self._lines(why))
        request = event.detail.get("request")
        self._d_request_title.setVisible(bool(request))
        self._d_request.setVisible(bool(request))
        if request:
            self._d_request.setText(self._lines(request, error_colour=DOWN))

    @staticmethod
    def _lines(lines: object, error_colour: str = DOWN) -> str:
        import html

        out = []
        for line in lines if isinstance(lines, (list, tuple)) else [str(lines)]:
            text = html.escape(str(line))
            if text.startswith("error:"):
                text = f'<span style="color:{error_colour}">{text}</span>'
            elif text.startswith("→ TRUE"):
                text = f'<span style="color:{UP}">{text}</span>'
            out.append(text)
        return "<br>".join(out)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._log.added.disconnect(self._on_added)
            self._log.cleared.disconnect(self.refresh)
            self._log.reloaded.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass  # already disconnected
        super().closeEvent(event)


__all__ = ["LogsView"]
