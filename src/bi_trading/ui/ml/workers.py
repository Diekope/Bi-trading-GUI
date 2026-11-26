"""Training off the GUI thread: a worker that loads the span, trains, reports.

Qt signals carry the progress and the result back to the screen. `cancel()`
only sets a flag the trainer polls between steps, so Stop takes effect at the
next batch or retrain, not instantly.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from bi_trading.ml.features import ordered_mask
from bi_trading.ml.train import MLError, Stopped, TrainConfig, train

log = logging.getLogger(__name__)

__all__ = ["HoldoutWorker", "ScoreWorker", "TrainWorker", "available_years", "load_columns"]


def available_years() -> list[int]:
    """The years that have candles on disk, oldest first."""
    from datetime import UTC, datetime

    from bi_trading.data.candles import candle_file

    return [
        year
        for year in range(2017, datetime.now(UTC).year + 1)
        if candle_file(year).exists()
    ]


def load_columns(years: list[int], timeframe: str):
    """(columns, stamps) for a span, or None when nothing is on disk."""
    from bi_trading.ui.strat.playback_data import load_span

    span = load_span(years, timeframe) if years else None
    if span is None or span.length == 0:
        return None
    columns = {
        "open": span.opens, "high": span.highs, "low": span.lows,
        "close": span.closes, "volume": span.volumes,
    }
    stamps = span.stamps
    keep = ordered_mask(stamps)
    if not keep.all():
        # Stray rows in a candle file (see `candles.repair`) would break the
        # time order every split and lookup depends on: train without them.
        log.warning("dropping %d out-of-order candle rows", int((~keep).sum()))
        columns = {name: series[keep] for name, series in columns.items()}
        stamps = stamps[keep]
    return columns, stamps


class TrainWorker(QThread):
    progress = Signal(float, str)
    trained = Signal(object)
    failed = Signal(str)

    def __init__(self, config: TrainConfig, years: list[int], name: str, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.years = list(years)
        self.model_name = name
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            self.progress.emit(0.0, "reading candles")
            loaded = load_columns(self.years, self.config.timeframe)
            if loaded is None:
                self.failed.emit("no candles on disk: download history in the Backtest view")
                return
            columns, stamps = loaded
            result = train(
                columns, stamps, self.config, self.model_name,
                progress=lambda fraction, text: self.progress.emit(fraction, text),
                cancelled=lambda: self._stop,
            )
        except Stopped:
            self.failed.emit("stopped")
            return
        except MLError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # a broken run must reach the screen, not kill the thread
            log.warning("training failed", exc_info=True)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.trained.emit(result)


class HoldoutWorker(QThread):
    """Score a saved model on its locked hold-out, off the GUI thread. Once."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, model: str, years: list[int], timeframe: str, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.years = list(years)
        self.timeframe = timeframe

    def run(self) -> None:
        try:
            from bi_trading.ml.holdout import score_holdout

            loaded = load_columns(self.years, self.timeframe)
            if loaded is None:
                self.failed.emit("no candles on disk")
                return
            columns, stamps = loaded
            self.done.emit(score_holdout(self.model, columns, stamps))
        except MLError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # reaches the screen, not the thread's end
            log.warning("hold-out scoring failed", exc_info=True)
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ScoreWorker(QThread):
    """Score a span with a saved model off the GUI thread, to warm the cache.

    The backtest asks for the same scores when it starts; once they are cached
    that costs nothing, so the window never waits on a model.
    """

    done = Signal()

    def __init__(self, model: str, years: list[int], timeframe: str, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.years = list(years)
        self.timeframe = timeframe

    def run(self) -> None:
        try:
            loaded = load_columns(self.years, self.timeframe)
            if loaded is not None:
                from bi_trading.ml.store import scored

                columns, stamps = loaded
                scored(self.model, columns, stamps, self.timeframe)
        except Exception:  # the run itself reports why a model cannot be used
            log.info("could not pre-score %s", self.model, exc_info=True)
        self.done.emit()
