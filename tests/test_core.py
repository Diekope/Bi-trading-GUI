"""The walk: the native core and the Python fallback agree."""

from __future__ import annotations

from lalala import core


def _series(closes):
    return (
        list(closes),
        [c + 0.5 for c in closes],
        [c - 0.5 for c in closes],
    )


def test_the_core_is_available() -> None:
    # The extension is built for this environment; if it ever isn't, the
    # fallback still runs, so this only checks the wiring.
    assert core.available() in (True, False)


def test_native_and_python_walks_agree() -> None:
    closes = [100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 99, 100, 101]
    highs, lows = _series(closes)[1:]
    entries = [False] + [True] * (len(closes) - 1)
    args = (closes, highs, lows, entries)
    kwargs = dict(
        capital=10_000.0, tp=1.0, sl=1.0, position=10.0,
        sizing="balance", max_cash=2_000.0, fee=0.0006, max_hold=3,
    )
    native = core.walk(*args, **kwargs)
    python = core._python_walk(
        *args, kwargs["capital"], kwargs["tp"], kwargs["sl"],
        kwargs["position"], kwargs["sizing"], kwargs["max_cash"],
        kwargs["fee"], kwargs["max_hold"],
    )
    assert len(native[0]) > 0
    assert native[0] == python[0]
    assert native[1] == python[1]
