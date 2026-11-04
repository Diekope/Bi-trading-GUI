"""Tiles for the backtest/strategy window.

The first tile picks a span of history and a resolution, then offers to
download it or to start a run on it. Only the controls exist so far: the
Download button reports whether the span is already on disk, and Start is
deliberately unwired.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
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


def data_dir() -> Path:
    """Where downloaded history lives. `LALALA_DATA` overrides the default."""
    return Path(
        os.environ.get("LALALA_DATA", "~/.local/share/lalala/data")
    ).expanduser()


def span_name(start_year: int, end_year: int, resolution: str) -> str:
    """File stem for one span: `2017-2026-1m`."""
    return f"{start_year}-{end_year}-{resolution}"


class ResolutionPicker(QWidget):
    """Exclusive 1m / 5m / 1h pills."""

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._values: dict[int, str] = {}
        for index, value in enumerate(RESOLUTIONS):
            button = QPushButton(value)
            button.setObjectName("tfButton")
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
    """Pick a span and a resolution; Download grays out when it is on disk."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        actions.setSpacing(6)
        self.download_button = QPushButton("Download")
        self.download_button.setObjectName("actionButton")
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setToolTip("Fetch this span of history")
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("startButton")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setToolTip("Not wired up yet")
        actions.addWidget(self.download_button, 1)
        actions.addWidget(self.start_button, 1)
        self.body.addLayout(actions)

        # Grays the Download button the moment the chosen span changes.
        self.start_year.currentIndexChanged.connect(self.refresh)
        self.end_year.currentIndexChanged.connect(self.refresh)
        self.resolution.changed.connect(self.refresh)
        self.download_button.clicked.connect(self.refresh)
        self.start_button.clicked.connect(self._on_start)

        self.refresh()

    # -- state -------------------------------------------------------------

    def span(self) -> tuple[int, int, str]:
        return (
            int(self.start_year.currentText()),
            int(self.end_year.currentText()),
            self.resolution.current(),
        )

    def span_name(self) -> str:
        return span_name(*self.span())

    def has_data(self) -> bool:
        """Whether this exact span is already on disk."""
        return (data_dir() / f"{self.span_name()}.parquet").exists()

    def refresh(self) -> None:
        """Download is only offered for a span that is not already local."""
        self.download_button.setEnabled(not self.has_data())

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
