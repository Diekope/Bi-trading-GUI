"""Tiles for the backtest/strategy window.

The first tile picks a span of history and a resolution, then offers to
download it or to start a run on it. History is kept as one 1m OHLCV file per
year under `data/candles` (see `lalala.candles`), so the tile can say exactly
which years are missing and which are only partly there; the resolution only
chooses what the run compacts those bars into.

Only the controls and the download exist so far: Start is deliberately
unwired.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from lalala.candle_download import CandleDownloader
from lalala.candles import (
    coverage,
    ensure_data_dir,
    expected_rows,
    format_years,
)
from lalala.panels import Card
from lalala.settings import FIRST_YEAR, TIMEFRAMES, Settings

RESOLUTIONS = TIMEFRAMES


class ResolutionPicker(QWidget):
    """Exclusive 1m / 3m / 5m / 15m / 30m / 1h pills."""

    changed = Signal(str)

    def __init__(
        self, current: str = RESOLUTIONS[0], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resolutionPicker")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        try:
            selected = RESOLUTIONS.index(current)
        except ValueError:
            selected = 0

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._values: dict[int, str] = {}
        for index, value in enumerate(RESOLUTIONS):
            button = QPushButton(value)
            button.setObjectName("resButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(index == selected)
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
    """Pick a span; Download fills in the 1m bars that are missing."""

    span_changed = Signal()
    started = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._adjusting = False
        self._busy = False
        self._error: str | None = None
        self._defaults = Settings.load().backtest
        this_year = datetime.now(tz=timezone.utc).year
        years = list(range(FIRST_YEAR, this_year + 1))
        start = (
            self._defaults.start_year
            if FIRST_YEAR <= self._defaults.start_year <= this_year
            else FIRST_YEAR
        )
        end = (
            self._defaults.end_year
            if FIRST_YEAR <= self._defaults.end_year <= this_year
            else this_year
        )

        title = QLabel("HISTORY")
        title.setObjectName("tileTitle")
        self.body.addWidget(title)

        span = QHBoxLayout()
        span.setSpacing(6)
        self.start_year = self._year_select(years, start)
        self.end_year = self._year_select(years, end)
        arrow = QLabel("→")
        arrow.setObjectName("spanArrow")
        span.addWidget(self.start_year, 1)
        span.addWidget(arrow)
        span.addWidget(self.end_year, 1)
        self.body.addLayout(span)

        self.resolution = ResolutionPicker(self._defaults.timeframe)
        self.resolution.setToolTip(
            "Bars are stored at 1m; this is what the run compacts them to"
        )
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
        self.download_button.setToolTip("Fetch the missing years at 1m")
        self.status = QLabel("")
        self.status.setObjectName("coverageLabel")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setVisible(False)

        # Only one of the two is ever shown: Download while something is
        # missing, Start backtest once the span is complete and runnable.
        actions.addWidget(self.start_button, 1)
        actions.addWidget(self.download_button, 1)
        actions.addWidget(self.status, 1)
        self.body.addLayout(actions)

        # Which of the two is the one to press breathes gently.
        self._glow_download = QGraphicsOpacityEffect(self.download_button)
        self.download_button.setGraphicsEffect(self._glow_download)
        self._pulse_download = self._pulse_animation(self._glow_download)
        self._glow_start = QGraphicsOpacityEffect(self.start_button)
        self.start_button.setGraphicsEffect(self._glow_start)
        self._pulse_start = self._pulse_animation(self._glow_start)

        self.downloader = CandleDownloader(self)
        self.downloader.progressed.connect(self._on_progress)
        self.downloader.finished.connect(self._on_finished)
        self.downloader.failed.connect(self._on_failed)

        self.start_year.currentIndexChanged.connect(self._span_changed)
        self.end_year.currentIndexChanged.connect(self._span_changed)
        self.resolution.changed.connect(self._span_changed)
        self.download_button.clicked.connect(self._start_download)
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

    def set_span(self, start: int, end: int, resolution: str) -> None:
        """Point the picker at a saved run's span and resolution."""
        self.start_year.setCurrentText(str(start))
        self.end_year.setCurrentText(str(end))
        try:
            index = RESOLUTIONS.index(resolution)
        except ValueError:
            index = 0
        self.resolution.group.button(index).click()

    def coverage(self) -> tuple[list[int], list[int]]:
        start, end, _ = self.span()
        return coverage(start, end)

    def has_data(self) -> bool:
        """Every year of the span is on disk, and each one is complete."""
        missing, partial = self.coverage()
        return not missing and not partial

    def refresh(self) -> None:
        """Keep the span ordered, report coverage, show the button that fits."""
        self._normalize_span()
        missing, partial = self.coverage()
        needs = bool(missing or partial) or self._busy

        self.download_button.setVisible(needs)
        self.start_button.setVisible(not needs)

        if self._busy:
            self.download_button.setEnabled(False)
            self._set_attention(False)
            self._pulse(self._glow_download, self._pulse_download, True)
            self._pulse(self._glow_start, self._pulse_start, False)
            return

        if self._error is not None:
            self._set_status(f"download failed: {self._error}", "missing")
            self.download_button.setEnabled(True)
            self._set_attention(True)
            self._pulse(self._glow_download, self._pulse_download, True)
            self._pulse(self._glow_start, self._pulse_start, False)
            return

        if missing:
            self._set_status(f"missing {format_years(missing)}", "missing")
        elif partial:
            self._set_status(f"partial {format_years(partial)}", "partial")
        else:
            self._set_status("")

        self.download_button.setEnabled(needs)
        self._set_attention(needs)
        # The actionable one breathes.
        self._pulse(self._glow_download, self._pulse_download, needs)
        self._pulse(self._glow_start, self._pulse_start, not needs)

    # -- downloading -------------------------------------------------------

    def _start_download(self) -> None:
        missing, partial = self.coverage()
        years = sorted(set(missing) | set(partial))
        if not years:
            return
        self._error = None
        self._busy = True
        self._set_status(f"downloading {format_years(years)}…")
        if not self.downloader.start(years):
            self._busy = False
        self.refresh()

    def _on_progress(self, year: int, rows: int) -> None:
        expected = expected_rows(year)
        percent = min(100, round(rows / expected * 100)) if expected else 0
        self._set_status(f"downloading {year}… {percent}%")

    def _on_finished(self) -> None:
        self._busy = False
        self.refresh()

    def _on_failed(self, message: str) -> None:
        self._busy = False
        self._error = message
        self.refresh()

    def _on_start(self) -> None:
        """Start backtest: hand off to the playback, which owns the walk."""
        self.started.emit()

    # -- state helpers -----------------------------------------------------

    def _span_changed(self) -> None:
        self._error = None
        self.refresh()
        self.span_changed.emit()

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
