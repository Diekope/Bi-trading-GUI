"""Bridge between Qt's event loop and the venue adapters' asyncio loop.

Qt and asyncio cannot share a thread, so all network coroutines run on a single
dedicated loop. `submit` returns a `concurrent.futures.Future`; poll it from a
QTimer or wrap it in a QThread signal to get results back onto the GUI thread.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any, TypeVar

T = TypeVar("T")


class AsyncRunner:
    def __init__(self, name: str = "venue-io") -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._spin, name=name, daemon=True
        )
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> "AsyncRunner":
        with self._lock:
            if not self._started:
                self._thread.start()
                self._started = True
        return self

    def _spin(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, T]) -> Future[T]:
        if not self._started:
            self.start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self, timeout: float = 3.0) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
        self._loop.call_soon_threadsafe(self._cancel_and_stop)
        self._thread.join(timeout)
        # A websocket close handshake can outlast the join. Closing a loop that
        # is still running raises "Cannot close a running event loop", so leave
        # it alone: the thread is a daemon and exits with the process.
        if not self._thread.is_alive():
            self._loop.close()

    def _cancel_and_stop(self) -> None:
        """Cancel in-flight coroutines and let them unwind before stopping.

        Stopping the loop in the same tick as `cancel()` leaves the tasks
        pending, which prints "Task was destroyed but it is pending" and lets
        half-dead coroutines emit into deleted QObjects.
        """

        async def shutdown() -> None:
            current = asyncio.current_task()
            pending = [t for t in asyncio.all_tasks() if t is not current]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._loop.stop()

        self._loop.create_task(shutdown())

    def __enter__(self) -> "AsyncRunner":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
