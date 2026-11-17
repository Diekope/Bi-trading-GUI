"""The trading log: what happened, in order, kept for the Logs view.

Not the debug log (`logs.py` writes that to a file for developers). This is the
user's own record of the session: orders sent and what became of them, fills,
closes and results, signals the strategy fired, limits it warned about, and
connections that dropped. Each is an `Event`, appended to a JSON-lines file as
it happens.

Only the newest 500 are loaded at launch (more only when today alone has more,
so the day's figures stay right); the rest stay on disk until asked for. A small
history stays in the JSON-lines file. Once that file grows past a couple of
thousand lines, the older rows move into a Parquet archive beside it, so the
file the app reads at launch stays small however long it has been running.

    BI_TRADING_EVENTS   path to the file (`~/.local/share/bi-trading/events.jsonl`)
"""

from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

DEFAULT_PATH = "~/.local/share/bi-trading/events.jsonl"
KEEP = 5_000          # most events held in memory
LOAD = 500            # how many are loaded at launch, and per "load older"
ROTATE_LINES = 2_000  # a hot file longer than this moves its older rows to Parquet
ROTATE_BYTES = 1_000_000

LEVELS = ("info", "warn", "error")
SOURCES = ("system", "hyperliquid", "polymarket", "strategy")
ORIGINS = ("manual", "auto")


@dataclass(frozen=True)
class Event:
    """One thing that happened."""

    stamp: float            # epoch seconds
    level: str              # info | warn | error
    source: str             # system | hyperliquid | polymarket | strategy
    kind: str               # ORDER, FILLED, REJECTED, SIGNAL, CLOSED, LIMIT, …
    message: str
    origin: str = ""        # manual | auto | "" (not an action of the user's)
    strategy: str = ""      # the strategy behind it, when one was ("" otherwise)
    # Optional extras the details panel shows: `latency_ms`, `pnl` (dollars),
    # `why` (lines: what made a signal fire) and `request` (lines: what was
    # sent and what came back).
    detail: dict = field(default_factory=dict)

    @property
    def pnl(self) -> float | None:
        value = self.detail.get("pnl")
        return float(value) if isinstance(value, (int, float)) else None

    def clock(self) -> str:
        """`21:20:41.902`, in local time."""
        moment = datetime.fromtimestamp(self.stamp)
        return moment.strftime("%H:%M:%S.") + f"{moment.microsecond // 1000:03d}"

    def is_today(self) -> bool:
        return datetime.fromtimestamp(self.stamp).date() == datetime.now().date()


def path() -> Path:
    return Path(os.environ.get("BI_TRADING_EVENTS", DEFAULT_PATH)).expanduser()


class EventLog(QObject):
    """The events of this session and the last, newest last."""

    added = Signal(object)   # an Event
    cleared = Signal()
    reloaded = Signal()      # older events were brought in

    def __init__(
        self, file: Path | None = None, keep: int = KEEP, load: int = LOAD
    ) -> None:
        super().__init__()
        self._file = file if file is not None else path()
        self._keep = keep
        self._load_count = load
        self._events: deque[Event] = deque(maxlen=keep)
        self._lock = threading.Lock()
        # Stored but not loaded: raw lines of the hot file older than what was
        # loaded, and how many archive rows (oldest first) are still unread.
        self._older_hot: list[str] = []
        self._archived = 0
        self._start()

    # -- reading -----------------------------------------------------------

    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def today(self, strategy: str = "") -> list[Event]:
        return [
            event for event in self.events()
            if event.is_today() and (not strategy or event.strategy == strategy)
        ]

    def strategies(self) -> list[str]:
        """The strategies that appear in the loaded events, sorted."""
        return sorted({event.strategy for event in self.events() if event.strategy})

    def counts(self, strategy: str = "") -> dict[str, float]:
        """The figures above the table, for today (and one strategy, if named)."""
        today = self.today(strategy)
        return {
            "orders": sum(1 for e in today if e.kind == "ORDER"),
            "filled": sum(1 for e in today if e.kind == "FILLED"),
            "rejected": sum(1 for e in today if e.kind == "REJECTED"),
            "warnings": sum(1 for e in today if e.level == "warn"),
            "signals": sum(1 for e in today if e.kind == "SIGNAL"),
            "pnl": sum(e.pnl or 0.0 for e in today),
        }

    def has_older(self) -> bool:
        """Whether more is stored than is loaded."""
        return bool(self._older_hot) or self._archived > 0

    def stored(self) -> int:
        """How many events are on disk but not loaded."""
        return len(self._older_hot) + self._archived

    # -- writing -----------------------------------------------------------

    def record(
        self,
        level: str,
        source: str,
        kind: str,
        message: str,
        origin: str = "",
        strategy: str = "",
        **detail: object,
    ) -> Event:
        """Add an event. Safe from any thread; `added` arrives on the main one."""
        event = Event(
            time.time(), level, source, kind.upper(), message, origin, strategy,
            {key: value for key, value in detail.items() if value is not None},
        )
        with self._lock:
            self._events.append(event)
        self._append(event)
        self.added.emit(event)
        return event

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._older_hot = []
            self._archived = 0
        for target in (self._file, self._archive_file()):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                log.debug("could not remove %s", target, exc_info=True)
        self.cleared.emit()

    def load_older(self, count: int | None = None) -> int:
        """Bring the next older events into memory; how many came."""
        want = min(count or self._load_count, self._keep - len(self._events))
        if want <= 0 or not self.has_older():
            return 0
        brought: list[Event] = []
        with self._lock:
            while self._older_hot and len(brought) < want:
                event = _parse(self._older_hot.pop())
                if event is not None:
                    brought.append(event)
            if len(brought) < want and self._archived > 0:
                rows = self._read_archive(0, self._archived)
                take = rows[max(0, len(rows) - (want - len(brought))):]
                self._archived = len(rows) - len(take)
                brought.extend(reversed(take))
            for event in brought:  # newest of the older first, so appendleft orders them
                self._events.appendleft(event)
        if brought:
            self.reloaded.emit()
        return len(brought)

    def all_events(self) -> list[Event]:
        """Everything stored, oldest first: the archive, the hot file, memory."""
        with self._lock:
            archived = self._read_archive(0, self._archived) if self._archived else []
            hot = [e for e in map(_parse, self._older_hot) if e is not None]
            return [*archived, *hot, *self._events]

    def export_csv(self, target: Path | str, everything: bool = True) -> int:
        """Write the events to a CSV file; the number written."""
        events = self.all_events() if everything else self.events()
        with open(target, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["time", "level", "source", "origin", "strategy", "event", "message", "pnl"]
            )
            for event in events:
                moment = datetime.fromtimestamp(event.stamp).isoformat(
                    sep=" ", timespec="milliseconds"
                )
                writer.writerow(
                    [moment, event.level, event.source, event.origin, event.strategy,
                     event.kind, event.message, "" if event.pnl is None else event.pnl]
                )
        return len(events)

    # -- the files ---------------------------------------------------------

    def _archive_file(self) -> Path:
        return self._file.with_suffix(".parquet")

    def _start(self) -> None:
        """Load the newest events; move a long history's older rows to Parquet."""
        try:
            lines = [line for line in self._file.read_text().splitlines() if line.strip()]
            size = self._file.stat().st_size
        except OSError:
            lines, size = [], 0
        if len(lines) > ROTATE_LINES or size > ROTATE_BYTES:
            lines = self._rotate(lines)
        self._archived = self._archive_rows()

        keep = max(0, len(lines) - self._load_count)
        self._older_hot = lines[:keep]
        for event in filter(None, map(_parse, lines[keep:])):
            self._events.append(event)
        # A day with more than `load` events: load back to its first, so the
        # day's figures are whole (bounded by `keep`).
        while (
            self._events
            and self._events[0].is_today()
            and self.has_older()
            and len(self._events) < self._keep
        ):
            if not self.load_older():
                break

    def _rotate(self, lines: list[str]) -> list[str]:
        """Move all but the newest `load` lines into the Parquet archive."""
        old, hot = lines[: -self._load_count], lines[-self._load_count :]
        rows = [e for e in map(_parse, old) if e is not None]
        try:
            self._write_archive(rows)
            self._file.write_text("".join(line + "\n" for line in hot))
        except (OSError, ValueError):
            log.warning("could not archive the older events", exc_info=True)
            return lines  # leave the file as it was
        return hot

    def _archive_rows(self) -> int:
        target = self._archive_file()
        if not target.exists():
            return 0
        try:
            import pyarrow.parquet as pq

            return int(pq.ParquetFile(target).metadata.num_rows)
        except (OSError, ValueError):
            return 0

    def _write_archive(self, rows: list[Event]) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        target = self._archive_file()
        existing = self._read_archive(0, self._archive_rows()) if target.exists() else []
        every = [*existing, *rows]
        table = pa.table(
            {
                "stamp": pa.array([e.stamp for e in every], type=pa.float64()),
                "level": pa.array([e.level for e in every], type=pa.string()),
                "source": pa.array([e.source for e in every], type=pa.string()),
                "kind": pa.array([e.kind for e in every], type=pa.string()),
                "message": pa.array([e.message for e in every], type=pa.string()),
                "origin": pa.array([e.origin for e in every], type=pa.string()),
                "strategy": pa.array([e.strategy for e in every], type=pa.string()),
                "detail": pa.array([json.dumps(e.detail) for e in every], type=pa.string()),
            }
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, target, compression="zstd")

    def _read_archive(self, start: int, stop: int) -> list[Event]:
        """Archive rows `start:stop` (oldest first)."""
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(self._archive_file()).slice(start, stop - start)
        except (OSError, ValueError):
            return []
        columns = {name: table.column(name).to_pylist() for name in table.column_names}
        events = []
        for index in range(table.num_rows):
            try:
                detail = json.loads(columns["detail"][index] or "{}")
            except ValueError:
                detail = {}
            events.append(
                Event(
                    columns["stamp"][index], columns["level"][index],
                    columns["source"][index], columns["kind"][index],
                    columns["message"][index], columns["origin"][index],
                    columns["strategy"][index], detail,
                )
            )
        return events

    def _append(self, event: Event) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file, "a") as handle:
                handle.write(json.dumps(asdict(event)) + "\n")
        except (OSError, TypeError, ValueError):
            log.debug("could not write an event", exc_info=True)


def _parse(line: str) -> Event | None:
    """One stored line as an Event; None for a torn or foreign one."""
    try:
        return Event(**json.loads(line))
    except (ValueError, TypeError):
        return None


_log: EventLog | None = None


def event_log() -> EventLog:
    """The shared log, built on first use."""
    global _log
    if _log is None:
        _log = EventLog()
    return _log


__all__ = [
    "Event",
    "EventLog",
    "LEVELS",
    "ORIGINS",
    "SOURCES",
    "event_log",
    "path",
]
