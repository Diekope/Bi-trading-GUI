"""Tiles for the backtest/strategy window.

The first tile picks a span of history and a resolution, then offers to
download it or to start a run on it. History is kept as one OHLCV file per
(year, resolution) under `data/candles`, so the tile can say exactly which
years are missing and which are only partly there.

Only the controls exist so far: Download reports coverage, Start is
deliberately unwired.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lalala.panels import Card

# History starts here: the venues' pre-2017 coverage is thin, so the picker
# should not imply it is there.
FIRST_YEAR = 2017
RESOLUTIONS = ("1m", "5m", "1h")
ASSET = "BTC"

# One file per (year, resolution): `BTC-2017-1m.csv`, a plain OHLCV table with
# a header. Expected rows come from the calendar, so a short file is a real
# gap rather than a guess.
CANDLES_PER_DAY = {"1m": 1440, "5m": 288, "1h": 24}
COMPLETE = 0.99  # a full year with a few venue outages is still "complete"

REPO_ROOT = Path(__file__).resolve().parents[2]

# Row counts are stable between writes, so a span change does not re-scan a
# half-million-line file every time the picker moves.
_ROW_CACHE: dict[tuple[str, float], int] = {}


def candles_dir() -> Path:
    """Where the OHLCV files live. `LALALA_DATA` overrides the default."""
    return Path(os.environ.get("LALALA_DATA", REPO_ROOT / "data" / "candles"))


def candle_file(year: int, resolution: str) -> Path:
    return candles_dir() / f"{ASSET}-{year}-{resolution}.csv"


def ensure_data_dir() -> Path:
    """Create `data/candles` on first use so a download has somewhere to go."""
    target = candles_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return target


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def expected_rows(year: int, resolution: str, now: datetime) -> int:
    """Candles a whole year holds — or the part of this year already elapsed."""
    days = 366 if _is_leap(year) else 365
    if year == now.year:
        days = max(1, now.timetuple().tm_yday)
    return days * CANDLES_PER_DAY[resolution]


def row_count(path: Path) -> int:
    """Data rows in a CSV, minus the header. Zero when the file is absent."""
    try:
        stat = path.stat()
    except OSError:
        return 0
    key = (str(path), stat.st_mtime)
    cached = _ROW_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        with path.open("rb") as handle:
            lines = sum(1 for _ in handle)
    except OSError:
        return 0
    count = max(0, lines - 1)
    _ROW_CACHE[key] = count
    return count


def format_years(years: list[int]) -> str:
    """`2017 2018 2019` as `2017–2019`, gaps kept explicit."""
    if not years:
        return ""
    if len(years) == 1:
        return str(years[0])
    if years == list(range(years[0], years[-1] + 1)):
        return f"{years[0]}–{years[-1]}"
    return ", ".join(str(year) for year in years)


class ResolutionPicker(QWidget):
    """Exclusive 1m / 5m / 1h pills."""

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resolutionPicker")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._values: dict[int, str] = {}
        for index, value in enumerate(RESOLUTIONS):
            button = QPushButton(value)
            button.setObjectName("resButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(index == 0)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.group.addButton(button, index)
            self._values[index] = value
            layout.addWidget(button, 1)

        self.group.idClicked.connect(
            lambda index: self.changed.emit(self._values[index])
        )

    def current(self) -> str:
        return self._values.get(self.group.checkedId(), RESOLUTIONS[0])


class DownloadTile(Card):
    """Pick a span and a resolution; Download reflects what is on disk."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._adjusting = False
        this_year = datetime.now(tz=timezone.utc).year
        years = list(range(FIRST_YEAR, this_year + 1))

        title = QLabel("HISTORY")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        span = QHBoxLayout()
        span.setSpacing(6)
        self.start_year = self._year_select(years, years[0])
        self.end_year = self._year_select(years, years[-1])
        arrow = QLabel("→")
        arrow.setObjectName("spanArrow")
        span.addWidget(self.start_year, 1)
        span.addWidget(arrow)
        span.addWidget(self.end_year, 1)
        self.body.addLayout(span)

        self.resolution = ResolutionPicker()
        self.body.addWidget(self.resolution)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_button = QPushButton("Start backtest")
        self.start_button.setObjectName("startButton")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setToolTip("Not wired up yet")
        self.download_button = QPushButton("Download")
        self.download_button.setObjectName("actionButton")
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setToolTip("Fetch this span of history")
        self.status = QLabel("")
        self.status.setObjectName("coverageLabel")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setVisible(False)

        # Start keeps the left half. On the right, the note only takes room
        # from Download, so the split shifts only when it has something to say.
        self._right_group = QWidget()
        self._right_group.setObjectName("coverageRow")
        right_row = QHBoxLayout(self._right_group)
        right_row.setContentsMargins(0, 0, 0, 0)
        right_row.setSpacing(8)
        right_row.addWidget(self.download_button, 1)
        right_row.addWidget(self.status, 1)

        actions.addWidget(self.start_button, 1)
        actions.addWidget(self._right_group, 1)
        self.body.addLayout(actions)

        # Which of the two is the one to press breathes gently: Download while
        # the span still needs fetching, Start once it is all there.
        self._glow_download = QGraphicsOpacityEffect(self.download_button)
        self.download_button.setGraphicsEffect(self._glow_download)
        self._pulse_download = self._pulse_animation(self._glow_download)
        self._glow_start = QGraphicsOpacityEffect(self.start_button)
        self.start_button.setGraphicsEffect(self._glow_start)
        self._pulse_start = self._pulse_animation(self._glow_start)

        # Re-check coverage the moment the chosen span or resolution changes.
        self.start_year.currentIndexChanged.connect(self.refresh)
        self.end_year.currentIndexChanged.connect(self.refresh)
        self.resolution.changed.connect(self.refresh)
        self.start_button.clicked.connect(self._on_start)

        ensure_data_dir()
        self.refresh()

    # -- coverage ----------------------------------------------------------

    def span(self) -> tuple[int, int, str]:
        return (
            int(self.start_year.currentText()),
            int(self.end_year.currentText()),
            self.resolution.current(),
        )

    def coverage(self) -> tuple[list[int], list[int]]:
        """(years with no file at all, years whose file is short of full)."""
        start, end, resolution = self.span()
        now = datetime.now(tz=timezone.utc)
        missing: list[int] = []
        partial: list[int] = []
        for year in range(start, end + 1):
            rows = row_count(candle_file(year, resolution))
            if rows == 0:
                missing.append(year)
            elif rows < expected_rows(year, resolution, now) * COMPLETE:
                partial.append(year)
        return missing, partial

    def has_data(self) -> bool:
        """Every year of the span is on disk, and each one is complete."""
        missing, partial = self.coverage()
        return not missing and not partial

    def refresh(self) -> None:
        """Keep the span ordered, report coverage, flag the Download button."""
        self._normalize_span()
        missing, partial = self.coverage()
        if missing:
            self._set_status(f"missing {format_years(missing)}", "missing")
        elif partial:
            self._set_status(f"partial {format_years(partial)}", "partial")
        else:
            self._set_status("")

        needs = bool(missing or partial)
        self.download_button.setEnabled(needs)
        self._set_attention(needs)
        # The actionable one breathes: Download while data is missing, Start
        # once the span is complete.
        self._pulse(self._glow_download, self._pulse_download, needs)
        self._pulse(self._glow_start, self._pulse_start, not needs)

    # -- state helpers -----------------------------------------------------

    def _pulse_animation(
        self, effect: QGraphicsOpacityEffect
    ) -> QPropertyAnimation:
        blink = QPropertyAnimation(effect, b"opacity", self)
        blink.setDuration(1500)
        blink.setKeyValueAt(0.0, 1.0)
        blink.setKeyValueAt(0.5, 0.55)
        blink.setKeyValueAt(1.0, 1.0)
        blink.setLoopCount(-1)
        return blink

    def _pulse(
        self,
        effect: QGraphicsOpacityEffect,
        animation: QPropertyAnimation,
        active: bool,
    ) -> None:
        if active:
            if animation.state() != QPropertyAnimation.State.Running:
                animation.start()
        else:
            animation.stop()
            effect.setOpacity(1.0)

    def _normalize_span(self) -> None:
        """A reversed pick is not an error: flip it back into order.

        Setting one combo's text re-enters `refresh` through its signal, so
        the guard keeps the correction to a single pass.
        """
        if self._adjusting:
            return
        start = int(self.start_year.currentText())
        end = int(self.end_year.currentText())
        if start <= end:
            return
        self._adjusting = True
        try:
            self.start_year.setCurrentText(str(end))
            self.end_year.setCurrentText(str(start))
        finally:
            self._adjusting = False

    def _set_status(self, text: str, state: str | None = None) -> None:
        """Show the note; `state` names the color it borrows from the theme."""
        self.status.setText(text)
        self.status.setVisible(bool(text))
        if state is not None:
            self.status.setProperty("state", state)
            style = self.status.style()
            style.unpolish(self.status)
            style.polish(self.status)

    def _set_attention(self, flag: bool) -> None:
        """Give Download a little color while the span is not complete."""
        if self.download_button.property("attention") == flag:
            return
        self.download_button.setProperty("attention", flag)
        style = self.download_button.style()
        style.unpolish(self.download_button)
        style.polish(self.download_button)

    def _on_start(self) -> None:
        """Deliberately inert: the backtest is not wired up yet."""

    # -- widgets -----------------------------------------------------------

    def _year_select(self, years: list[int], current: int) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("yearSelect")
        combo.addItems([str(year) for year in years])
        combo.setCurrentText(str(current))
        combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        return combo
