"""JSON parsing for the hot paths.

`orjson` when it is installed — the websocket frames hit it hundreds of times a
second — and the standard library otherwise, so the parse never depends on it.
"""

from __future__ import annotations

try:
    import orjson

    def loads(data):
        return orjson.loads(data)

    def dumps(value) -> str:
        return orjson.dumps(value).decode()

except ModuleNotFoundError:  # pragma: no cover - orjson is a dependency
    import json

    def loads(data):
        return json.loads(data)

    def dumps(value) -> str:
        return json.dumps(value)


__all__ = ["dumps", "loads"]
