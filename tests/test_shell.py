"""Shell smoke tests. Run headless: QT_QPA_PLATFORM=offscreen is set below."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.ui.cards import format_axis_time  # noqa: E402
from lalala.ui.main_window import MainWindow  # noqa: E402
from lalala.data.market_data import (  # noqa: E402
    TIMEFRAMES,
    Candle,
    CandleSeries,
    Market,
)
from lalala.ui.theme import CANVAS, CARD_GAP, PANEL, apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def window(app: QApplication) -> MainWindow:
    # autostart=False: no sockets, no threads, no network in tests.
    win = MainWindow(autostart=False)
    win.show()
    app.processEvents()
    yield win
    win.close()


def _series(coin: str = "HYPE", interval: str = "1m", count: int = 3) -> CandleSeries:
    candles = tuple(
        Candle(t=1_700_000_000_000 + i * 60_000, o=100 + i, h=101 + i, l=99 + i, c=100.5 + i)
        for i in range(count)
    )
    return CandleSeries(coin, interval, candles)


def test_console_entry_point_resolves() -> None:
    from lalala.__main__ import main

    assert callable(main)


def test_canvas_is_lighter_than_floating_cards(window: MainWindow) -> None:
    # The canvas is the darker surface: the panels read as raised above it.
    assert QColor(CANVAS).lightness() < QColor(PANEL).lightness()
    assert window.palette().window().color() == QColor(CANVAS)


def test_two_columns(window: MainWindow) -> None:
    assert window.splitter.orientation() == Qt.Orientation.Horizontal
    assert window.splitter.count() == 2
    assert window.polymarket.text() == "Polymarket"


def test_vertical_stack_uses_the_same_gap(window: MainWindow) -> None:
    assert window.stack.orientation() == Qt.Orientation.Vertical
    assert window.stack.handleWidth() == CARD_GAP
    assert window.splitter.handleWidth() == CARD_GAP


def test_cards_carry_no_drop_shadow(window: MainWindow) -> None:
    # A graphics effect re-renders the whole card per repaint; with live charts
    # that cost is not worth a decorative shadow.
    for card in (window.polymarket, window.main_card):
        assert card.graphicsEffect() is None


def test_order_book_is_gone(window: MainWindow) -> None:
    assert not hasattr(window.main_card, "ladder")
    assert not hasattr(window.main_card, "book")


# -- the + button follows the newest card ---------------------------------


# -- search collapses ------------------------------------------------------


# -- candles ---------------------------------------------------------------


def test_default_timeframe_is_one_minute(window: MainWindow) -> None:
    assert window.main_card.interval == "1m"
    assert window.main_card.timeframes.current() == "1m"


def test_timeframes_span_one_minute_to_one_hour(window: MainWindow) -> None:
    labels = [
        window.main_card.timeframes.group.button(i).text()
        for i in range(window.main_card.timeframes.group.buttons().__len__())
    ]
    assert labels == ["1m", "3m", "5m", "15m", "30m", "1h"]


def test_chart_paints_without_a_backend(app: QApplication, window: MainWindow) -> None:
    window._on_candles(_series())
    image = window.main_card.chart.grab().toImage()
    assert image.width() > 0
    # Something was actually drawn: the placeholder is not the only content.
    colors = {image.pixelColor(x, y).name() for x in range(0, image.width(), 17)
              for y in range(0, image.height(), 11)}
    assert len(colors) > 1


def test_interval_change_rewatches_candles(app: QApplication, window: MainWindow) -> None:
    window._markets = {"HYPE": Market("HYPE", sz_decimals=2)}
    window.main_card.set_market(window._markets["HYPE"])
    window._sync_watches()
    assert ("HYPE", "1m") in window._watched

    window.main_card.timeframes.changed.emit("15m")
    app.processEvents()

    assert window.main_card.interval == "15m"
    assert window._watched == {("HYPE", "15m")}


# -- latency ---------------------------------------------------------------


def test_latency_shows_milliseconds_and_colours(app: QApplication, window: MainWindow) -> None:
    window._on_latency(42.0)
    assert window.latency_label.text() == "HL ● 42 ms"
    assert "#3ddc84" in window.latency_label.styleSheet()

    window._on_latency(250.0)
    assert "#e0b341" in window.latency_label.styleSheet()

    window._on_latency(900.0)
    assert "#ff5c5c" in window.latency_label.styleSheet()


def test_disconnect_replaces_the_latency_readout(window: MainWindow) -> None:
    window._on_connected(False)
    assert window.latency_label.text() == "HL ● reconnecting…"


# -- search: inline results, no popup window -------------------------------


# -- chart navigation ------------------------------------------------------


def _long_series(count: int = 200) -> tuple[Candle, ...]:
    return tuple(
        Candle(t=1_700_000_000_000 + i * 60_000, o=100.0, h=101.0, l=99.0, c=100.0)
        for i in range(count)
    )


def test_chart_opens_pinned_to_the_live_edge(window: MainWindow) -> None:
    window.main_card.chart.set_series(_long_series())
    chart = window.main_card.chart
    assert chart.is_live is True
    assert chart.offset == 0
    assert len(chart.visible_candles()) == chart.visible_count


def test_chart_zoom_changes_visible_count(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    before = chart.visible_count

    chart.zoom(1)
    zoomed_in = chart.visible_count
    assert zoomed_in < before

    chart.zoom(-1)
    assert chart.visible_count > zoomed_in


def test_chart_zoom_is_clamped(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(50))
    for _ in range(20):
        chart.zoom(1)
    assert chart.visible_count == chart.MIN_VISIBLE
    for _ in range(20):
        chart.zoom(-1)
    assert chart.visible_count <= chart.candle_count


def test_zoom_out_stops_at_a_sane_window(window: MainWindow) -> None:
    """The wheel used to ratchet `_visible` past 75k while the series was short."""
    chart = window.main_card.chart
    chart.set_series(_long_series(200))

    for _ in range(200):
        chart.zoom(-1)

    assert chart._visible == chart.MAX_VISIBLE
    assert chart.visible_count == 200  # still capped by the data


def test_a_short_series_still_grows_back_into_the_window(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(40))
    for _ in range(50):
        chart.zoom(-1)
    assert chart.visible_count == 40

    chart.set_series(_long_series(300))

    assert chart.visible_count == 300


def test_history_paging_cannot_widen_the_drawn_window_past_the_cap(
    window: MainWindow,
) -> None:
    """Regression: 60 zoom-outs + deep history made every repaint 50ms."""
    chart = window.main_card.chart
    chart.set_series(_long_series(300))
    for _ in range(100):
        chart.zoom(-1)

    chart.add_history(_stamped_series(1_500_000_000_000, 3000))

    assert chart.candle_count == 3300
    assert chart.visible_count == chart.MAX_VISIBLE


def test_chart_pans_back_and_forth(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart.pan(20)
    assert chart.offset == 20
    assert chart.is_live is False

    chart.pan(-20)
    assert chart.is_live is True


def test_chart_pan_cannot_leave_the_data(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(100))
    chart.pan(10_000)
    assert chart.offset == 100 - chart.visible_count
    assert len(chart.visible_candles()) == chart.visible_count

    chart.pan(-10_000)
    assert chart.offset == 0


def test_chart_double_click_returns_to_live(app: QApplication, window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart.pan(30)
    chart.reset_view()
    assert chart.is_live is True
    assert chart.visible_count == chart.DEFAULT_VISIBLE


def test_scrolled_back_chart_still_paints(app: QApplication, window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart.pan(40)
    image = chart.grab().toImage()
    assert image.width() > 0
    assert len({image.pixelColor(x, 5).name() for x in range(0, image.width(), 9)}) >= 1


# -- grabbing the chart ----------------------------------------------------


def _plot_center(chart) -> QPoint:
    """A point in the middle of the candlestick area, clear of both axes."""
    return QPoint(chart.width() // 2, chart.height() // 2)


def test_dragging_the_chart_walks_back_through_time(
    app: QApplication, window: MainWindow
) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    for _ in range(40):
        chart.zoom(1)
    slot = (chart.width() - chart.GUTTER) / chart.visible_count
    start = _plot_center(chart)

    QTest.mousePress(
        chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
    )
    # Cross the dead zone, then drag exactly two on-screen slots.
    QTest.mouseMove(chart, QPoint(start.x() + 8, start.y()))
    QTest.mouseMove(chart, QPoint(start.x() + 8 + int(slot * 2), start.y()))
    app.processEvents()
    QTest.mouseRelease(
        chart,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(start.x() + 8 + int(slot * 2), start.y()),
    )

    assert chart.offset == 2


def test_dragging_down_moves_the_price_window(
    app: QApplication, window: MainWindow
) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    start = _plot_center(chart)

    QTest.mousePress(
        chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
    )
    QTest.mouseMove(chart, QPoint(start.x(), start.y() + 8))
    QTest.mouseMove(chart, QPoint(start.x(), start.y() + 68))
    app.processEvents()
    QTest.mouseRelease(
        chart,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(start.x(), start.y() + 68),
    )

    # One-to-one with the pointer, measured from where the dead zone ended.
    assert chart.price_shift == pytest.approx(60.0)
    assert chart.offset == 0  # a vertical grab must not walk through time


def test_the_price_window_cannot_be_dragged_out_of_reach(
    app: QApplication, window: MainWindow
) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    start = _plot_center(chart)

    QTest.mousePress(
        chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
    )
    QTest.mouseMove(chart, QPoint(start.x(), start.y() + 8))
    QTest.mouseMove(chart, QPoint(start.x(), start.y() + 10_000))
    app.processEvents()
    QTest.mouseRelease(
        chart,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(start.x(), start.y() + 10_000),
    )

    assert chart.price_shift == pytest.approx(chart._price_shift_limit())


def test_a_click_that_wobbles_does_not_grab_the_chart(
    app: QApplication, window: MainWindow
) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    start = _plot_center(chart)

    QTest.mousePress(
        chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
    )
    QTest.mouseMove(chart, QPoint(start.x() + 2, start.y() + 2))
    app.processEvents()
    QTest.mouseRelease(
        chart,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(start.x() + 2, start.y() + 2),
    )

    assert chart.offset == 0
    assert chart.is_live is True
    assert chart.price_shift == 0.0


def test_double_click_releases_the_vertical_grab(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart.pan(20)
    chart._price_shift = 45.0

    chart.reset_view()

    assert chart.price_shift == 0.0
    assert chart.offset == 0


def test_a_new_series_releases_the_vertical_grab(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart._price_shift = 45.0

    chart.set_series(())

    assert chart.price_shift == 0.0


# -- chart time axis -------------------------------------------------------

def test_axis_time_is_hours_and_minutes_for_intraday() -> None:
    stamp = 1_700_000_045_000
    assert len(format_axis_time(stamp, "1m").split(":")) == 2


def test_axis_time_includes_the_date_for_1h() -> None:
    label = format_axis_time(1_700_000_045_000, "1h")
    assert len(label.split(":")) == 2
    assert len(label) > 6  # "dd Mon HH:MM"


def test_chart_takes_its_interval_for_labelling(window: MainWindow) -> None:
    window.main_card.timeframes.changed.emit("15m")
    assert window.main_card.chart._interval == "15m"
    window.main_card.timeframes.changed.emit("1h")
    assert window.main_card.chart._interval == "1h"


# -- every card can be closed while another survives -----------------------

def test_single_card_has_no_close_button(window: MainWindow) -> None:
    assert window.main_card.close_button.isVisible() is False


def test_viewport_recovers_as_history_grows(window: MainWindow) -> None:
    # A freshly opened chart starts with a couple of bars; the window must not
    # latch at the minimum once more data arrives.
    chart = window.main_card.chart
    chart.set_series(_long_series(3))
    assert chart.visible_count == 3

    chart.set_series(_long_series(200))
    assert chart.visible_count == chart.DEFAULT_VISIBLE


# -- four stacked cards must fit the minimum window ------------------------

# -- volume + Bollinger overlays ------------------------------------------

def _overlay_series(count: int = 120) -> tuple[Candle, ...]:
    out = []
    for i in range(count):
        close = 100.0 + (i % 17) * 0.4 - (i % 7) * 0.3
        out.append(
            Candle(
                t=1_700_000_000_000 + i * 60_000,
                o=close - 0.2,
                h=close + 0.5,
                l=close - 0.6,
                c=close,
                v=10.0 + (i % 11) * 3.0,
            )
        )
    return tuple(out)


def test_overlay_defaults(window: MainWindow) -> None:
    chart = window.main_card.chart
    assert chart.show_volume is True
    assert chart.show_bollinger is False


def test_volume_toggle_repaints_the_chart(app: QApplication, window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_overlay_series())

    chart.set_show_volume(True)
    with_volume = chart.grab().toImage()
    chart.set_show_volume(False)
    without = chart.grab().toImage()

    assert with_volume != without


def test_bollinger_toggle_repaints_the_chart(app: QApplication, window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_overlay_series())
    chart.set_show_volume(False)

    chart.set_show_bollinger(False)
    without = chart.grab().toImage()
    chart.set_show_bollinger(True)
    with_bands = chart.grab().toImage()

    assert with_bands != without


def test_volume_stays_out_of_the_way_without_volume_data(app: QApplication, window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(120))  # v defaults to 0.0
    chart.set_show_volume(True)
    on = chart.grab().toImage()
    chart.set_show_volume(False)
    off = chart.grab().toImage()
    # No volume to draw, so the layout should be identical.
    assert on == off


# -- axis-specific wheel zoom ---------------------------------------------

def _wheel(chart, x: float, y: float, notches: int = 1) -> None:
    """Deliver a wheel notch at (x, y) inside the chart."""
    event = QWheelEvent(
        QPointF(x, y),
        QPointF(x, y),
        QPoint(0, 0),
        QPoint(0, 120 * notches),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    chart.wheelEvent(event)


def _price_axis_point(chart) -> tuple[float, float]:
    return (chart.width() - 8.0, chart.height() / 2)


def _time_axis_point(chart) -> tuple[float, float]:
    return (chart.width() / 2, chart.height() - 4.0)


def test_wheel_over_the_price_axis_stretches_prices_only(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    before_visible = chart.visible_count

    _wheel(chart, *_price_axis_point(chart), notches=2)

    assert chart.price_zoom > 1.0
    assert chart.visible_count == before_visible
    assert chart.offset == 0


def test_wheel_over_the_time_axis_zooms_time_only(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    before_visible = chart.visible_count

    _wheel(chart, *_time_axis_point(chart), notches=2)

    assert chart.visible_count < before_visible
    assert chart.price_zoom == 1.0


def test_wheel_over_the_plot_still_zooms_time(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    before_visible = chart.visible_count

    _wheel(chart, chart.width() / 2, chart.height() / 2, notches=1)

    assert chart.visible_count < before_visible
    assert chart.price_zoom == 1.0


def test_price_zoom_clamps_both_ways(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())

    for _ in range(200):
        chart.zoom_price(1)
    assert chart.price_zoom == chart.MAX_PRICE_ZOOM

    for _ in range(400):
        chart.zoom_price(-1)
    assert chart.price_zoom == chart.MIN_PRICE_ZOOM


def test_reset_view_restores_the_price_zoom(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart.zoom_price(1)
    chart.pan(10)
    assert chart.price_zoom > 1.0

    chart.reset_view()

    assert chart.price_zoom == 1.0
    assert chart.is_live is True


def test_a_new_series_resets_the_price_zoom(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart.zoom_price(1)

    chart.set_series(())

    assert chart.price_zoom == 1.0


def test_price_zoom_changes_what_is_painted(app: QApplication, window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series())
    chart.set_show_volume(False)

    natural = chart.grab().toImage()
    chart.zoom_price(1)
    chart.zoom_price(1)
    stretched = chart.grab().toImage()

    assert chart.price_zoom > 1.0
    assert natural != stretched


# -- deeper history -------------------------------------------------------

def _detach_feed(window: MainWindow) -> None:
    """Stop the (unstarted) feed from answering, so `awaiting` can be observed."""
    try:
        window.main_card.history_requested.disconnect()
    except RuntimeError:
        pass


def _stamped_series(start: int, count: int, step: int = 60_000) -> tuple[Candle, ...]:
    return tuple(
        Candle(t=start + i * step, o=1.0, h=2.0, l=0.5, c=1.5)
        for i in range(count)
    )


def test_panning_to_the_left_edge_asks_for_older_history(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    _detach_feed(window)
    asked: list[int] = []
    chart.history_requested.connect(asked.append)

    chart.pan(10_000)  # clamps at the oldest bar

    assert asked == [chart.visible_candles()[0].t]
    assert chart.awaiting_history is True


def test_only_one_history_request_is_in_flight(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    _detach_feed(window)
    asked: list[int] = []
    chart.history_requested.connect(asked.append)

    for _ in range(5):
        chart.pan(10_000)

    assert len(asked) == 1


def test_a_page_is_prepended_without_moving_the_viewport(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    chart.pan(10_000)
    shown = chart.visible_candles()

    chart.add_history(_stamped_series(1_600_000_000_000, 50))

    assert chart.candle_count == 250
    assert chart.visible_candles() == shown
    assert chart.awaiting_history is False
    assert chart.offset == 120  # unchanged: the page landed to the left


def test_an_empty_page_means_the_history_is_exhausted(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    chart.pan(10_000)
    asked: list[int] = []
    chart.history_requested.connect(asked.append)

    chart.add_history(())
    assert chart.history_exhausted is True

    chart.pan(10_000)
    assert asked == []  # no more requests


def test_a_failed_page_can_be_retried(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    _detach_feed(window)
    asked: list[int] = []
    chart.history_requested.connect(asked.append)

    chart.pan(10_000)
    assert chart.awaiting_history is True

    chart.cancel_history_request()
    assert chart.awaiting_history is False
    assert chart.history_exhausted is False

    chart.pan(10_000)
    assert len(asked) == 2


def test_a_reconcile_does_not_drop_history(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    chart.add_history(_stamped_series(1_600_000_000_000, 100))
    assert chart.candle_count == 300

    # The venue's 60s reconcile sends only the recent window.
    chart.merge_series(_long_series(200))

    assert chart.candle_count == 300
    assert chart.visible_candles()[-1].t == _long_series(200)[-1].t


def test_a_live_bar_does_not_drag_a_scrolled_back_view(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    chart.pan(50)
    shown = chart.visible_candles()

    # One new bar printed at the venue.
    newer = _stamped_series(1_700_000_000_000 + 200 * 60_000, 1)
    chart.merge_series(newer)

    assert chart.candle_count == 201
    assert chart.visible_candles()[0].t == shown[0].t
    assert chart.visible_candles()[-1].t == shown[-1].t
    assert chart.offset == 51


def test_a_live_bar_keeps_a_live_chart_live(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))

    chart.merge_series(_stamped_series(1_700_000_000_000 + 200 * 60_000, 1))

    assert chart.is_live is True
    assert chart.visible_candles()[-1].t == 1_700_000_000_000 + 200 * 60_000


def test_a_new_series_resets_the_history_flags(window: MainWindow) -> None:
    chart = window.main_card.chart
    chart.set_series(_long_series(200))
    chart.pan(10_000)
    chart.add_history(())
    assert chart.history_exhausted is True

    chart.set_series(_long_series(50))

    assert chart.history_exhausted is False
    assert chart.awaiting_history is False


def test_the_card_routes_history_requests_to_the_feed(window: MainWindow) -> None:
    """The feed is not started in tests, so this exercises the failure path."""
    chart = window.main_card.chart
    chart.set_series(_long_series(200))

    chart.pan(10_000)

    assert window.feed._started is False
    # The immediate failure unblocks the chart instead of leaving it waiting.
    assert chart.awaiting_history is False
    assert chart.history_exhausted is False


def test_a_fetched_page_reaches_the_right_card(window: MainWindow) -> None:
    card = window.main_card
    card.chart.set_series(_long_series(200))
    before = card.chart.candle_count

    window._on_older_candles(
        CandleSeries(card.coin, card.interval, _stamped_series(1_600_000_000_000, 40))
    )

    assert card.chart.candle_count == before + 40


def test_a_page_for_another_market_is_ignored(window: MainWindow) -> None:
    card = window.main_card
    card.chart.set_series(_long_series(200))
    before = card.chart.candle_count

    window._on_older_candles(
        CandleSeries("xyz:CL", card.interval, _stamped_series(1_600_000_000_000, 40))
    )

    assert card.chart.candle_count == before


# -- keyboard shortcuts ---------------------------------------------------

def test_digit_keys_switch_the_timeframe(app: QApplication, window: MainWindow) -> None:
    card = window.main_card
    card.chart.setFocus()

    QTest.keyClick(card.chart, Qt.Key.Key_3)

    assert card.interval == "5m"
    assert card.timeframes.current() == "5m"


def test_digit_keys_reach_the_window_when_nothing_has_focus(
    app: QApplication, window: MainWindow
) -> None:
    QTest.keyClick(window, Qt.Key.Key_5)

    assert window.main_card.interval == "30m"


def test_timeframe_pills_advertise_their_key(window: MainWindow) -> None:
    group = window.main_card.timeframes.group
    for index in range(len(TIMEFRAMES)):
        assert f"press {index + 1}" in group.button(index).toolTip()


# -- the top bar's exit ----------------------------------------------------


def test_the_terminal_top_bar_carries_a_quit_button(window: MainWindow) -> None:
    assert window.quit_button.toolTip() == "Quit lalala"
    assert window.quit_button.text() == "Quit"

    window.quit_button.click()

    assert not window.isVisible()


def test_the_embedded_terminal_hides_its_top_bar(app: QApplication) -> None:
    window = MainWindow(autostart=False, show_top_bar=False)
    try:
        assert window.top_bar.isVisible() is False
    finally:
        window.close()
