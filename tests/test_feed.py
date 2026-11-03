"""Feed routing tests. No sockets: `dispatch` is fed raw frames directly."""

from __future__ import annotations

import json

from lalala.feed import MarketFeed
from lalala.market_data import Book


def _feed() -> MarketFeed:
    # Constructing does not start the runner, so no network is touched.
    return MarketFeed()


def test_all_mids_frame_becomes_float_map() -> None:
    feed = _feed()
    seen: list[dict[str, float]] = []
    feed.mids_updated.connect(seen.append)

    feed.dispatch(
        json.dumps({"channel": "allMids", "data": {"mids": {"HYPE": "84.4945"}}})
    )

    assert seen == [{"HYPE": 84.4945}]


def test_hip3_book_frame_becomes_book() -> None:
    feed = _feed()
    seen: list[Book] = []
    feed.book_updated.connect(seen.append)

    feed.dispatch(
        json.dumps(
            {
                "channel": "l2Book",
                "data": {
                    "coin": "xyz:CL",
                    "time": 1700000000000,
                    "levels": [
                        [{"px": "97.35", "sz": "2", "n": 1}],
                        [{"px": "97.40", "sz": "1", "n": 1}],
                    ],
                },
            }
        )
    )

    assert len(seen) == 1
    assert seen[0].coin == "xyz:CL"
    assert seen[0].best_bid is not None
    assert seen[0].best_bid.px == 97.35
    assert seen[0].best_ask is not None
    assert seen[0].best_ask.px == 97.40


def test_junk_frames_are_ignored() -> None:
    feed = _feed()
    errors: list[str] = []
    mids: list[dict] = []
    feed.error.connect(errors.append)
    feed.mids_updated.connect(mids.append)

    for raw in ("not json", "[]", '{"channel": "unknown"}', '{"channel": "allMids"}'):
        feed.dispatch(raw)

    assert mids == []
    assert errors == []


def test_error_channel_is_surfaced() -> None:
    feed = _feed()
    errors: list[str] = []
    feed.error.connect(errors.append)

    feed.dispatch(json.dumps({"channel": "error", "data": "bad subscription"}))

    assert errors == ["bad subscription"]


def test_track_is_idempotent() -> None:
    feed = _feed()
    feed.track("HYPE")
    feed.track("HYPE")
    pending = feed._drain_pending()
    assert pending == [("subscribe", {"type": "l2Book", "coin": "HYPE"})]

    feed.untrack("HYPE")
    feed.untrack("HYPE")
    assert feed._drain_pending() == [
        ("unsubscribe", {"type": "l2Book", "coin": "HYPE"})
    ]


# -- candle stream: live bars, no polling ----------------------------------

def _bar(stamp: int, close: float, high: float | None = None, volume: str = "5") -> dict:
    return {
        "t": stamp,
        "T": stamp + 59_999,
        "s": "HYPE",
        "i": "1m",
        "o": "100",
        "c": str(close),
        "h": str(high if high is not None else close),
        "l": "99",
        "v": volume,
        "n": 3,
    }


def test_pushed_bar_updates_the_open_candle_in_place() -> None:
    feed = _feed()
    feed.watch_candles("HYPE", "1m")
    feed._drain_pending()

    seen: list = []
    feed.candles_updated.connect(seen.append)

    feed.dispatch(json.dumps({"channel": "candle", "data": _bar(1_700_000_040_000, 101)}))
    feed.dispatch(json.dumps({"channel": "candle", "data": _bar(1_700_000_040_000, 102, high=103)}))

    assert len(seen) == 2
    series = seen[-1]
    assert len(series.candles) == 1
    assert series.last_price == 102.0
    assert series.candles[0].h == 103.0


def test_pushed_bar_starts_a_new_candle_on_a_new_minute() -> None:
    feed = _feed()
    feed.watch_candles("HYPE", "1m")
    feed._drain_pending()

    seen: list = []
    feed.candles_updated.connect(seen.append)

    feed.dispatch(json.dumps({"channel": "candle", "data": _bar(1_700_000_040_000, 101)}))
    feed.dispatch(json.dumps({"channel": "candle", "data": _bar(1_700_000_100_000, 105)}))

    series = seen[-1]
    assert [c.t for c in series.candles] == [1_700_000_040_000, 1_700_000_100_000]
    assert series.candles[-1].c == 105.0


def test_bar_for_an_unwatched_pair_is_ignored() -> None:
    feed = _feed()
    seen: list = []
    feed.candles_updated.connect(seen.append)

    feed.dispatch(json.dumps({"channel": "candle", "data": _bar(1_700_000_040_000, 101)}))

    assert seen == []


def test_unwatching_drops_the_cached_series() -> None:
    feed = _feed()
    feed.watch_candles("HYPE", "1m")
    feed._drain_pending()
    feed.dispatch(json.dumps({"channel": "candle", "data": _bar(1_700_000_040_000, 101)}))

    feed.unwatch_candles("HYPE", "1m")

    assert ("HYPE", "1m") not in feed._candle_cache


# -- backfill requests -----------------------------------------------------

def test_a_backfill_is_refused_while_the_feed_is_stopped() -> None:
    feed = _feed()
    feed.watch_candles("HYPE", "1m")
    failures: list[tuple[str, str]] = []
    feed.history_failed.connect(lambda c, i: failures.append((c, i)))

    feed.request_older("HYPE", "1m", 1_700_000_000_000)

    # No runner thread is spun up, and the chart is told to try again later.
    assert failures == [("HYPE", "1m")]
    assert feed._history_pending == set()


def test_a_backfill_for_an_unwatched_pair_is_refused() -> None:
    feed = _feed()
    failures: list[tuple[str, str]] = []
    feed.history_failed.connect(lambda c, i: failures.append((c, i)))

    feed.request_older("HYPE", "1m", 1_700_000_000_000)

    assert failures == [("HYPE", "1m")]


def test_two_owners_asking_at_once_do_not_stack_requests() -> None:
    feed = _feed()
    feed.watch_candles("HYPE", "1m")
    feed._started = True  # pretend the app is running, but keep the runner off
    submitted: list[object] = []
    feed._runner.submit = lambda coro: submitted.append(coro)  # type: ignore[method-assign]
    failures: list[tuple[str, str]] = []
    feed.history_failed.connect(lambda c, i: failures.append((c, i)))

    feed.request_older("HYPE", "1m", 1_700_000_000_000)
    feed.request_older("HYPE", "1m", 1_700_000_000_000)

    assert len(submitted) == 1
    assert failures == [("HYPE", "1m")]

    for coro in submitted:
        coro.close()  # type: ignore[attr-defined]  # never scheduled on purpose
