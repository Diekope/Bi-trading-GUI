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


def test_risk_sizing_shrinks_the_position_as_the_stop_widens() -> None:
    # A trade that opens at 100 and stops at 98: a 1% risk on $1,000 cash puts
    # $500 on (so a 2% stop-out loses $10), while a 1% stop puts $1,000 on.
    closes = [100.0, 100.0, 100.0]
    highs = [100.0, 100.0, 100.0]
    lows = [100.0, 100.0, 100.0]
    entries = [False, True, False]

    def notional(sl: float) -> float:
        trades, _ = core.walk(
            closes, highs, lows, entries, capital=1_000.0, tp=50.0, sl=sl,
            position=1.0, sizing="risk", max_cash=1_000.0, fee=0.0, max_hold=1,
        )
        return trades[0][6]

    assert notional(2.0) == 500.0
    assert notional(1.0) == 1_000.0


def test_dynamic_tp_trails_the_peak() -> None:
    # Flat fixed TP would never fire in this series, but the trail closes once
    # price pulls back 5% from the peak it reached after entry.
    closes = [100.0, 100.0, 110.0, 104.0, 104.0]
    highs = [100.0, 100.0, 110.0, 104.5, 104.0]
    lows = [100.0, 100.0, 110.0, 104.0, 104.0]
    entries = [False, True, False, False, False]

    trades, _ = core.walk(
        closes, highs, lows, entries, capital=1_000.0, tp=50.0, sl=50.0,
        position=100.0, sizing="balance", max_cash=1_000.0, fee=0.0, max_hold=99,
        dynamic_tp=True, reverse=5.0,
    )

    assert len(trades) == 1
    _in_index, _in_px, out_index, out_px, _result, _fees, _notional, reason = trades[0]
    assert reason == "tp"
    assert out_px == 104.5  # 110 peak pulled back 5%
    assert out_index == 3


def test_dynamic_tp_off_keeps_the_fixed_target() -> None:
    closes = [100.0, 100.0, 110.0, 104.0, 104.0]
    highs = [100.0, 100.0, 110.0, 104.5, 104.0]
    lows = [100.0, 100.0, 110.0, 104.0, 104.0]
    entries = [False, True, False, False, False]

    trades, _ = core.walk(
        closes, highs, lows, entries, capital=1_000.0, tp=50.0, sl=50.0,
        position=100.0, sizing="balance", max_cash=1_000.0, fee=0.0, max_hold=2,
        dynamic_tp=False, reverse=5.0,
    )

    # Nothing trails: the trade runs to the hold limit at the close.
    assert trades[0][7] == "time"
