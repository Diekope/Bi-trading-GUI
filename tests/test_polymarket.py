"""Polymarket: slug math, parsing, feed routing, and the panel.

The data and routing tests touch no network. The panel tests use the same
headless fixture as the shell tests and construct `MainWindow(autostart=False)`,
so neither feed starts a thread.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.main_window import MainWindow  # noqa: E402
from lalala.market_data import Candle, CandleSeries  # noqa: E402
from lalala.polymarket_data import (  # noqa: E402
    Level,
    PriceChange,
    PricePoint,
    TokenBook,
    Trade,
    apply_price_change,
    format_cents,
    format_compact,
    format_countdown,
    format_shares,
    market_slug,
    parse_book,
    parse_last_trade,
    parse_market,
    parse_price_changes,
    slug_window,
    window_price_points,
)
from lalala.polymarket_feed import PolymarketFeed  # noqa: E402
from lalala.polymarket_panel import SAMPLE_EVERY_MS  # noqa: E402
from lalala.theme import apply_dark_theme  # noqa: E402

TOKENS = (
    "30110116130057740446680476683553482539418691871252512101755124689500345437707",
    "15600458027167774022928657278841750685414367468053057352843604870644860496187",
)
UP_TOKEN, DOWN_TOKEN = TOKENS


# -- fixtures ---------------------------------------------------------------


def gamma_payload(
    *, slug: str | None = None, end_ms: int | None = None
) -> list[dict]:
    """A Gamma response in the venue's real shape (some fields are strings)."""
    if end_ms is None:
        end_ms = int(time.time() * 1000) + 180_000
    start_ms = end_ms - 300_000
    if slug is None:
        slug = f"btc-updown-5m-{start_ms // 1000}"
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    return [
        {
            "slug": slug,
            "question": "Bitcoin Up or Down - November 3, 2:30PM-2:35PM ET",
            "conditionId": (
                "0x7561fa95b688baff81024b0af566edfc3152d2336b99acaad479362fb0762234"
            ),
            "clobTokenIds": json.dumps(list(TOKENS)),
            "outcomes": json.dumps(["Up", "Down"]),
            "outcomePrices": json.dumps(["0.5", "0.5"]),
            "bestBid": "0.49",
            "bestAsk": "0.51",
            "spread": "0.02",
            "liquidity": "16587.6",
            "volume": None,
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "startDate": "2026-11-02T19:38:51.040208Z",
            "orderPriceMinTickSize": "0.01",
            "acceptingOrders": True,
        }
    ]


def book_payload(
    token: str,
    *,
    bids: tuple[tuple[float, float], ...] = ((0.66, 100), (0.65, 250)),
    asks: tuple[tuple[float, float], ...] = ((0.68, 80), (0.69, 140)),
) -> dict:
    # The venue sends bids ascending and asks descending; preserve that.
    return {
        "asset_id": token,
        "timestamp": "1793734282794",
        "bids": [
            {"price": str(price), "size": str(size)}
            for price, size in sorted(bids)
        ],
        "asks": [
            {"price": str(price), "size": str(size)}
            for price, size in sorted(asks, reverse=True)
        ],
    }


def market_from_gamma(**kwargs):
    market = parse_market(gamma_payload(**kwargs))
    assert market is not None
    return market


# -- slug math --------------------------------------------------------------


def test_the_slug_is_aligned_to_five_minutes() -> None:
    # 1793734241 is 19:30:41 UTC; the window opened at 19:30:00.
    assert market_slug(1_793_734_241) == "btc-updown-5m-1793734200"


def test_a_window_keeps_its_slug_until_the_boundary() -> None:
    assert market_slug(1_793_734_499.9) == "btc-updown-5m-1793734200"
    assert market_slug(1_793_734_500) == "btc-updown-5m-1793734500"


def test_slug_window_is_the_five_minutes_after_the_stamp() -> None:
    assert slug_window("btc-updown-5m-1793734200") == (
        1_793_734_200_000,
        1_793_734_500_000,
    )


def test_a_foreign_slug_has_no_window() -> None:
    assert slug_window("will-the-democratic-party-control-the-house") is None
    assert slug_window("btc-updown-5m-dynamic_time_utc") is None


# -- market parsing ---------------------------------------------------------


def test_gamma_market_parses_its_string_encoded_arrays() -> None:
    market = market_from_gamma()

    assert market.question.startswith("Bitcoin Up or Down")
    assert [outcome.name for outcome in market.outcomes] == ["Up", "Down"]
    assert [outcome.token_id for outcome in market.outcomes] == list(TOKENS)
    assert market.liquidity == pytest.approx(16587.6)
    assert market.tick_size == pytest.approx(0.01)
    assert market.volume == 0.0
    assert market.start_ms < market.end_ms


def test_gamma_quotes_land_on_the_first_outcome() -> None:
    market = market_from_gamma()
    up, down = market.outcomes

    assert up.best_bid == pytest.approx(0.49)
    assert up.best_ask == pytest.approx(0.51)
    assert down.best_bid is None
    assert up.mid == pytest.approx(0.50)


def test_an_empty_gamma_response_is_none() -> None:
    assert parse_market([]) is None
    assert parse_market({}) is None
    assert parse_market(None) is None


def test_a_market_finds_its_outcome_by_token() -> None:
    market = market_from_gamma()
    assert market.outcome_for_token(DOWN_TOKEN).name == "Down"
    assert market.outcome_for_token("0xdead") is None


def test_a_market_is_open_until_its_end_time() -> None:
    market = market_from_gamma()
    assert market.is_open(market.start_ms / 1000 + 1) is True
    assert market.is_open(market.end_ms / 1000 + 1) is False


# -- book parsing -----------------------------------------------------------


def test_a_book_is_sorted_best_level_first_on_both_sides() -> None:
    book = parse_book(book_payload(UP_TOKEN))

    assert book.best_bid == pytest.approx(0.66)
    assert book.best_ask == pytest.approx(0.68)
    assert book.bids[0].price > book.bids[-1].price
    assert book.asks[0].price < book.asks[-1].price
    assert book.mid == pytest.approx(0.67)
    assert book.spread == pytest.approx(0.02)


def test_a_book_sums_resting_notional() -> None:
    book = parse_book(
        book_payload(
            UP_TOKEN, bids=((0.5, 100),), asks=((0.6, 50),)
        )
    )
    assert book.notional == pytest.approx(0.5 * 100 + 0.6 * 50)


def test_zero_size_levels_are_dropped() -> None:
    book = parse_book(
        {
            "asset_id": UP_TOKEN,
            "bids": [{"price": "0.5", "size": "0"}],
            "asks": [{"price": "0.6", "size": "10"}],
        }
    )
    assert book.bids == ()
    assert book.best_bid is None


def test_a_book_without_a_token_is_ignored() -> None:
    assert parse_book({"bids": [], "asks": []}) is None
    assert parse_book(None) is None


# -- window price points ----------------------------------------------------


def _bar(t_ms: int, o: float, c: float) -> Candle:
    return Candle(t=t_ms, o=o, h=max(o, c), l=min(o, c), c=c, v=1.0)


START = 1_793_734_200_000
END = START + 300_000


def test_window_prices_seed_the_target_and_one_point_per_minute() -> None:
    target, points = window_price_points(
        (
            _bar(START, 78_000.0, 78_010.0),
            _bar(START + 60_000, 78_010.0, 78_030.0),
        ),
        START,
        END,
    )

    assert target == pytest.approx(78_000.0)
    assert [(point.timestamp_ms, point.price) for point in points] == [
        (START, pytest.approx(78_000.0)),
        (START + 60_000, pytest.approx(78_010.0)),
        (START + 120_000, pytest.approx(78_030.0)),
    ]


def test_window_prices_come_from_the_bar_that_contains_the_start() -> None:
    target, points = window_price_points(
        (_bar(START + 60_000, 78_100.0, 78_200.0),), START, END
    )

    assert target == pytest.approx(78_100.0)
    assert points[0].timestamp_ms == START
    assert points[0].price == pytest.approx(78_100.0)


def test_window_prices_from_a_previous_window_are_rejected() -> None:
    target, points = window_price_points(
        (
            _bar(START - 120_000, 77_800.0, 77_810.0),
            _bar(START - 60_000, 77_810.0, 77_820.0),
        ),
        START,
        END,
    )

    assert target is None
    assert points == ()


def test_window_prices_tolerate_an_empty_response() -> None:
    assert window_price_points((), START, END) == (None, ())
    assert window_price_points((object(),), START, END) == (None, ())


# -- incremental changes ----------------------------------------------------


def _change(price: float, size: float, side: str = "BUY") -> PriceChange:
    return PriceChange(
        token_id=UP_TOKEN,
        price=price,
        size=size,
        side=side,
        timestamp_ms=1_793_734_282_794,
    )


def test_a_bid_change_replaces_the_level_and_keeps_the_order() -> None:
    book = parse_book(book_payload(UP_TOKEN))

    updated = apply_price_change(book, _change(0.66, 400))

    assert updated.bids[0] == Level(0.66, 400)
    assert updated.best_bid == pytest.approx(0.66)


def test_a_new_bid_becomes_the_best_bid() -> None:
    book = parse_book(book_payload(UP_TOKEN))

    updated = apply_price_change(book, _change(0.67, 30))

    assert updated.best_bid == pytest.approx(0.67)
    assert updated.bids[0] == Level(0.67, 30)


def test_a_zero_size_change_removes_the_level() -> None:
    book = parse_book(book_payload(UP_TOKEN))

    updated = apply_price_change(book, _change(0.66, 0))

    assert updated.best_bid == pytest.approx(0.65)
    assert all(level.price != 0.66 for level in updated.bids)


def test_a_sell_change_lands_on_the_ask_side_in_ascending_order() -> None:
    book = parse_book(book_payload(UP_TOKEN))

    updated = apply_price_change(book, _change(0.67, 25, side="SELL"))

    assert updated.best_ask == pytest.approx(0.67)
    assert updated.asks[0] == Level(0.67, 25)
    assert updated.bids == book.bids


def test_price_changes_parse_a_whole_frame() -> None:
    changes = parse_price_changes(
        {
            "event_type": "price_change",
            "timestamp": "1793734282794",
            "price_changes": [
                {
                    "asset_id": UP_TOKEN,
                    "price": "0.18",
                    "size": "400.4",
                    "side": "BUY",
                    "best_bid": "0.32",
                    "best_ask": "0.33",
                },
                {"asset_id": "", "price": "0.1", "size": "1"},
            ],
        }
    )

    assert len(changes) == 1
    assert changes[0].token_id == UP_TOKEN
    assert changes[0].size == pytest.approx(400.4)
    assert changes[0].best_bid == pytest.approx(0.32)
    assert changes[0].timestamp_ms == 1_793_734_282_794


# -- trades -----------------------------------------------------------------


def test_a_last_trade_frame_becomes_a_trade() -> None:
    trade = parse_last_trade(
        {
            "event_type": "last_trade_price",
            "asset_id": UP_TOKEN,
            "price": "0.62",
            "size": "200",
            "side": "BUY",
            "timestamp": "1793734282794",
        }
    )

    assert trade == Trade(
        token_id=UP_TOKEN,
        price=0.62,
        size=200.0,
        side="BUY",
        timestamp_ms=1_793_734_282_794,
    )


def test_a_malformed_trade_is_ignored() -> None:
    assert parse_last_trade({"asset_id": UP_TOKEN}) is None
    assert parse_last_trade({"price": "0.6"}) is None


# -- formatting -------------------------------------------------------------


def test_cents_are_whole_when_the_price_is_on_a_cent() -> None:
    assert format_cents(0.67) == "67¢"
    assert format_cents(0.505) == "50.5¢"
    assert format_cents(None) == "—"


def test_compact_money_keeps_a_width_that_fits_a_column() -> None:
    assert format_compact(6_300_000) == "$6.3M"
    assert format_compact(16_587.6) == "$16.6k"
    assert format_compact(842.4) == "$842"
    assert format_compact(0) == "—"
    assert format_compact(None) == "—"


def test_the_countdown_never_shows_zero_before_the_close() -> None:
    assert format_countdown(0.2) == "00:01"
    assert format_countdown(61) == "01:01"
    assert format_countdown(3661) == "1:01:01"
    assert format_countdown(0) == "closed"
    assert format_countdown(-4) == "closed"
    assert format_countdown(None) == "—"


def test_fractional_trade_sizes_do_not_round_to_zero() -> None:
    assert format_shares(0.01) == "0.01"
    assert format_shares(3.333334) == "3.33"
    assert format_shares(5) == "5"
    assert format_shares(66.666) == "66.7"
    assert format_shares(2_494) == "2,494"
    assert format_shares(None) == "—"


# -- feed routing -----------------------------------------------------------


def _feed() -> PolymarketFeed:
    # Constructing does not start the runner, so nothing touches the network.
    return PolymarketFeed()


def _book_frame(token: str = UP_TOKEN) -> dict:
    return {"event_type": "book", **book_payload(token)}


def test_a_book_frame_reaches_the_panel() -> None:
    feed = _feed()
    seen: list[TokenBook] = []
    feed.book_updated.connect(seen.append)

    feed.dispatch(json.dumps([_book_frame()]))
    feed.flush_books()

    assert len(seen) == 1
    assert seen[0].token_id == UP_TOKEN
    assert seen[0].best_bid == pytest.approx(0.66)


def test_many_updates_coalesce_into_one_emit_per_token() -> None:
    feed = _feed()
    feed.dispatch(json.dumps([_book_frame(UP_TOKEN), _book_frame(DOWN_TOKEN)]))
    seen: list[TokenBook] = []
    feed.book_updated.connect(seen.append)

    for price in ("0.67", "0.68", "0.69"):
        feed.dispatch(
            json.dumps(
                [
                    {
                        "event_type": "price_change",
                        "timestamp": "1793734282794",
                        "price_changes": [
                            {
                                "asset_id": UP_TOKEN,
                                "price": price,
                                "size": "10",
                                "side": "BUY",
                            }
                        ],
                    },
                    _book_frame(DOWN_TOKEN),
                ]
            )
        )

    assert seen == []
    feed.flush_books()

    assert [book.token_id for book in seen] == [UP_TOKEN, DOWN_TOKEN]
    assert seen[0].best_bid == pytest.approx(0.69)

    # A second flush with nothing new emits nothing.
    feed.flush_books()
    assert len(seen) == 2


def test_a_price_change_updates_the_held_book_once() -> None:
    feed = _feed()
    feed.dispatch(json.dumps(_book_frame()))
    feed.flush_books()
    seen: list[TokenBook] = []
    feed.book_updated.connect(seen.append)

    feed.dispatch(
        json.dumps(
            {
                "event_type": "price_change",
                "timestamp": "1793734282794",
                "price_changes": [
                    {
                        "asset_id": UP_TOKEN,
                        "price": "0.67",
                        "size": "30",
                        "side": "BUY",
                    },
                    {
                        "asset_id": UP_TOKEN,
                        "price": "0.66",
                        "size": "120",
                        "side": "BUY",
                    },
                ],
            }
        )
    )
    feed.flush_books()

    assert len(seen) == 1
    assert seen[0].best_bid == pytest.approx(0.67)
    assert seen[0].bids[1].size == pytest.approx(120)


def test_a_change_before_the_snapshot_is_dropped() -> None:
    feed = _feed()
    seen: list[TokenBook] = []
    feed.book_updated.connect(seen.append)

    feed.dispatch(
        json.dumps(
            {
                "event_type": "price_change",
                "price_changes": [
                    {"asset_id": UP_TOKEN, "price": "0.5", "size": "1", "side": "BUY"}
                ],
            }
        )
    )
    feed.flush_books()

    assert seen == []


def test_both_tokens_keep_their_own_books() -> None:
    feed = _feed()
    seen: list[TokenBook] = []
    feed.book_updated.connect(seen.append)

    feed.dispatch(json.dumps([_book_frame(UP_TOKEN), _book_frame(DOWN_TOKEN)]))
    feed.flush_books()

    assert [book.token_id for book in seen] == [UP_TOKEN, DOWN_TOKEN]


def test_a_last_trade_frame_reaches_the_tape() -> None:
    feed = _feed()
    seen: list[Trade] = []
    feed.trade.connect(seen.append)

    feed.dispatch(
        json.dumps(
            {
                "event_type": "last_trade_price",
                "asset_id": UP_TOKEN,
                "price": "0.62",
                "size": "200",
                "side": "BUY",
                "timestamp": "1793734282794",
            }
        )
    )

    assert len(seen) == 1
    assert seen[0].price == pytest.approx(0.62)


def test_subscription_acks_and_garbage_are_ignored() -> None:
    feed = _feed()
    seen: list[object] = []
    feed.book_updated.connect(seen.append)
    feed.trade.connect(seen.append)

    feed.dispatch("not json")
    feed.dispatch(json.dumps({"event_type": "tick_size_change", "asset_id": UP_TOKEN}))
    feed.dispatch(json.dumps([1, 2, 3]))

    assert seen == []


# -- panel ------------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def window(app: QApplication) -> MainWindow:
    win = MainWindow(autostart=False)
    win.show()
    app.processEvents()
    yield win
    win.close()


def test_the_column_is_still_named_polymarket(window: MainWindow) -> None:
    assert window.polymarket.text() == "Polymarket"


def test_neither_feed_starts_in_tests(window: MainWindow) -> None:
    assert window.feed._started is False
    assert window.polymarket_feed._started is False


def test_a_market_fills_the_header_and_tiles(window: MainWindow) -> None:
    panel = window.polymarket
    market = market_from_gamma()

    panel.set_market(market)

    assert "Bitcoin Up or Down" in panel.question.text()
    assert panel.target_value.text() == "—"
    assert panel.liquidity_value.text() == "$16.6k"
    assert panel.up_tile.price == pytest.approx(0.50)
    assert panel.down_tile.price == pytest.approx(0.50)
    assert panel.up_tile.name == "Up"
    assert panel.down_tile.name == "Down"
    assert "UTC" in panel.window_label.text()


def test_the_countdown_is_live_and_formatted(window: MainWindow) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma(end_ms=int(time.time() * 1000) + 125_000))

    panel._tick()

    assert panel.countdown.text()[0] == "0"
    assert ":" in panel.countdown.text()
    assert panel.countdown.text() != "—"


def test_a_book_updates_the_tile_and_depth(window: MainWindow) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma())
    book = parse_book(book_payload(UP_TOKEN))

    panel.apply_book(book)

    assert panel.up_tile.bid == pytest.approx(0.66)
    assert panel.up_tile.ask == pytest.approx(0.68)
    assert panel.up_tile.price == pytest.approx(0.67)
    assert panel.spread_value.text() == "2¢"
    assert panel.depth_value.text().startswith("$")
    assert panel.books[UP_TOKEN] is book
    assert panel.price_chart.market is panel.market


def test_clicking_down_highlights_the_tile(window: MainWindow) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma())
    panel.apply_book(parse_book(book_payload(UP_TOKEN)))
    panel.apply_book(parse_book(book_payload(DOWN_TOKEN)))

    panel._select_token(1)

    assert panel.down_tile.selected is True
    assert panel.up_tile.selected is False
    assert panel.spread_value.text() == "2¢"


def test_the_price_chart_samples_at_most_once_a_second(
    window: MainWindow,
) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma())
    panel.set_window_prices(100_000.0, ())

    panel.set_btc(100_010.0)
    assert len(panel.points) == 1

    # A second mid inside the same second must not add a point.
    panel.set_btc(100_020.0)
    assert len(panel.points) == 1

    # Move the clock back one sampling interval; the next mid is recorded.
    panel._last_sample -= SAMPLE_EVERY_MS
    panel.set_btc(100_030.0)
    assert len(panel.points) == 2
    assert panel.points[-1].price == pytest.approx(100_030.0)
    assert panel.price_chart.points is panel.points
    assert panel.price_chart.target == pytest.approx(100_000.0)


def test_window_prices_backfill_and_keep_the_line_sorted(
    window: MainWindow,
) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma())
    market = panel.market
    panel.set_btc(100_100.0)

    panel.set_window_prices(
        100_000.0,
        (
            PricePoint(market.start_ms, 100_000.0),
            PricePoint(market.start_ms + 60_000, 100_040.0),
        ),
    )

    assert panel.target == pytest.approx(100_000.0)
    assert panel.target_value.text() == "100,000.0"
    stamps = [point.timestamp_ms for point in panel.points]
    assert stamps == sorted(stamps)
    assert panel.points[0].price == pytest.approx(100_000.0)
    assert panel.points[-1].price == pytest.approx(100_100.0)
    assert panel.move_value.text() == "+0.10%"


def test_window_prices_are_ignored_without_a_target(window: MainWindow) -> None:
    panel = window.polymarket
    panel.set_window_prices(100_000.0, ())  # no market yet
    assert panel.target is None

    panel.set_market(market_from_gamma())
    panel.set_window_prices(0.0, ())
    panel.set_window_prices(None, ())
    assert panel.target is None
    assert panel.target_value.text() == "—"


def test_the_price_range_is_sticky_and_resets_on_rollover(
    window: MainWindow,
) -> None:
    chart = window.polymarket.price_chart
    panel = window.polymarket
    panel.set_market(market_from_gamma())

    # A wide window pins the range…
    lo, hi = chart._range([78_000.0, 78_100.0], 78_000.0)
    assert lo == pytest.approx(77_980.5)
    assert hi == pytest.approx(78_119.5)
    # …and a later, narrower sample must not shrink it.
    lo, hi = chart._range([78_040.0, 78_050.0], 78_000.0)
    assert lo == pytest.approx(77_980.5)
    assert hi == pytest.approx(78_119.5)
    # A wider sample still widens it.
    lo, hi = chart._range([77_000.0, 78_100.0], 78_000.0)
    assert lo == pytest.approx(76_802.0)
    assert hi == pytest.approx(78_298.0)

    # A new five-minute window starts from a fresh scale.
    panel.set_market(market_from_gamma(slug="btc-updown-5m-1793734500"))
    assert chart._lo is None and chart._hi is None
    lo, hi = chart._range([100_000.0, 100_050.0], 100_000.0)
    assert lo == pytest.approx(99_975.0)
    assert hi == pytest.approx(100_075.0)


def test_trades_fill_the_tape_newest_first(window: MainWindow) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma())

    panel.apply_trade(Trade(UP_TOKEN, 0.61, 100, "BUY", 1_793_734_280_000))
    panel.apply_trade(Trade(DOWN_TOKEN, 0.39, 50, "SELL", 1_793_734_281_000))

    assert len(panel.tape.trades) == 2
    assert panel.tape.trades[0][0].price == pytest.approx(0.39)
    assert panel.tape.trades[1][1] == "Up"


def test_the_tape_stops_at_a_screenful(window: MainWindow) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma())

    for index in range(40):
        panel.apply_trade(Trade(UP_TOKEN, 0.5, index + 1, "BUY", 1_793_734_280_000))

    assert len(panel.tape.trades) == panel.tape.MAX_ROWS
    assert panel.tape.trades[0][0].size == 40


def test_a_new_window_clears_the_old_book_chart_and_tape(
    window: MainWindow,
) -> None:
    panel = window.polymarket
    first = market_from_gamma(slug="btc-updown-5m-1793734200")
    panel.set_market(first)
    panel.apply_book(parse_book(book_payload(UP_TOKEN)))
    panel.apply_trade(Trade(UP_TOKEN, 0.6, 10, "BUY", 1_793_734_280_000))
    panel.set_window_prices(78_000.0, (PricePoint(first.start_ms, 78_000.0),))
    panel.set_btc(78_100.0)
    assert panel.points

    second = market_from_gamma(slug="btc-updown-5m-1793734500")
    panel.set_market(second)

    assert panel.market is second
    assert panel.books == {}
    assert panel.tape.trades == []
    assert panel.points == []
    assert panel.target is None
    assert panel.price_chart.market is second


def test_the_btc_reference_shows_above_and_below_the_target(
    window: MainWindow,
) -> None:
    panel = window.polymarket
    panel.set_market(market_from_gamma())
    panel.set_window_prices(100_000.0, ())

    panel.set_btc(100_500.0)

    assert panel.btc_value.text() == "100,500.0"
    assert panel.move_value.text() == "+0.50%"
    assert "#3ddc84" in panel.move_value.styleSheet()
    assert "Above" in panel.move_value.toolTip()

    panel.set_btc(99_500.0)

    assert panel.move_value.text() == "-0.50%"
    assert "#ff5c5c" in panel.move_value.styleSheet()
    assert "Below" in panel.move_value.toolTip()


def test_status_changes_are_visible(window: MainWindow) -> None:
    panel = window.polymarket

    panel.set_status("live")
    assert panel.status_text.text() == "live"

    panel.set_status("waiting")
    assert "waiting" in panel.status_text.text()

    panel.set_status("nonsense")  # ignored
    assert "waiting" in panel.status_text.text()


def test_the_polymarket_delay_lands_in_the_top_bar(window: MainWindow) -> None:
    window.polymarket_feed.latency.emit(42)

    assert window.pm_latency_label.text() == "PM ● 42 ms"
    assert "#3ddc84" in window.pm_latency_label.styleSheet()

    window.polymarket_feed.latency.emit(250)
    assert "#e0b341" in window.pm_latency_label.styleSheet()

    window.polymarket_feed.latency.emit(900)
    assert "#ff5c5c" in window.pm_latency_label.styleSheet()


def test_the_window_forwards_the_btc_mid_to_the_panel(window: MainWindow) -> None:
    window.polymarket.set_market(market_from_gamma())

    window._on_mids({"BTC": 84_512.5})

    assert window.polymarket.btc_value.text() == "84,512.5"


def test_the_btc_bbo_is_the_fast_path_into_the_panel(window: MainWindow) -> None:
    assert "BTC" in window.feed._bbo

    window._on_bbo("HYPE", 40.0)
    assert window.polymarket.btc_value.text() == "—"

    window._on_bbo("BTC", 78_123.5)
    assert window.polymarket.btc_value.text() == "78,123.5"


def test_a_new_market_seeds_the_target_from_its_opening_bars(
    window: MainWindow,
) -> None:
    market = market_from_gamma()
    window._on_polymarket_market(market)

    assert window.polymarket.market is market

    window._on_window_candles(
        CandleSeries(
            "BTC",
            "1m",
            (
                _bar(market.start_ms, 78_000.0, 78_010.0),
                _bar(market.start_ms + 60_000, 78_010.0, 78_030.0),
            ),
        )
    )

    assert window.polymarket.target == pytest.approx(78_000.0)
    assert window.polymarket.target_value.text() == "78,000.0"
    assert [point.price for point in window.polymarket.points] == [
        pytest.approx(78_000.0),
        pytest.approx(78_010.0),
        pytest.approx(78_030.0),
    ]


def test_a_candle_response_for_an_old_window_is_ignored(
    window: MainWindow,
) -> None:
    market = market_from_gamma()
    window.polymarket.set_market(market)
    old = market.start_ms - 300_000

    window._on_window_candles(
        CandleSeries(
            "BTC",
            "1m",
            (_bar(old, 77_000.0, 77_010.0), _bar(old + 60_000, 77_010.0, 77_020.0)),
        )
    )

    assert window.polymarket.target is None
    assert window.polymarket.points == []


def test_the_panel_paints_before_and_after_data(window: MainWindow) -> None:
    panel = window.polymarket
    empty = panel.grab().toImage()
    assert not empty.isNull()

    panel.set_market(market_from_gamma())
    panel.apply_book(parse_book(book_payload(UP_TOKEN)))
    panel.apply_trade(Trade(UP_TOKEN, 0.61, 100, "BUY", 1_793_734_280_000))

    painted = panel.grab().toImage()
    assert not painted.isNull()
    assert painted != empty
