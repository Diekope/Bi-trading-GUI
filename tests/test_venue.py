"""The venue switch: Polymarket, Hyperliquid, or both, and what each shows."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bi_trading.data.market_data import Book, Level  # noqa: E402
from bi_trading.state import venue  # noqa: E402
from bi_trading.ui.hl_panels import LEVELS, OrderBookCard  # noqa: E402
from bi_trading.ui.hub.main_hub import MainHubWindow  # noqa: E402
from bi_trading.ui.main_window import MainWindow  # noqa: E402
from bi_trading.ui.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))


def book(mid: float = 100.0) -> Book:
    return Book(
        "BTC",
        tuple(Level(mid - 0.5 - i, 1.0 + i) for i in range(8)),
        tuple(Level(mid + 0.5 + i, 1.0 + i) for i in range(8)),
    )


def test_polymarket_is_the_first_venue_and_the_choice_is_remembered() -> None:
    assert venue.current() == venue.PM
    venue.save(venue.HL)
    assert venue.current() == venue.HL
    venue.save("nonsense")
    assert venue.current() == venue.HL


def test_the_rail_switch_shows_the_venues_logos_with_their_delay_inside(app: QApplication) -> None:
    window = MainHubWindow(autostart=False)
    try:
        for name in ("pm", "hl"):
            box = window._venue_buttons[name]
            assert box.logo.pixmap() is not None and not box.logo.pixmap().isNull()
            assert box.delay is not None and box.delay.parent() is box   # inside the box
        both = window._venue_buttons["both"]
        assert both.logo.text() == "⇄" and both.delay is None
        window._on_pm_latency(42)
        window._on_hl_latency(300.0)
        assert window._latency_labels["pm"].text() == "42ms"
        assert window._latency_labels["hl"].text() == "300ms"
        assert "#" in window._latency_labels["pm"].styleSheet()
    finally:
        window.close()


def test_the_switch_changes_the_tag_and_remembers(app: QApplication) -> None:
    window = MainHubWindow(autostart=False)
    try:
        # The tag is the venue's logo (two for both), named in its tooltip.
        assert window.venue_tag.toolTip() == "Polymarket"
        assert window.venue_tag.layout().count() == 1
        window._set_venue("hl")
        assert window.venue_tag.toolTip() == "Hyperliquid"
        assert venue.current() == "hl"
        window._set_venue("both")
        assert window.venue_tag.toolTip() == "PM + HL"
        assert window.venue_tag.layout().count() == 3   # logo, "+", logo
    finally:
        window.close()


def test_both_venues_have_no_strategy_screens(app: QApplication) -> None:
    window = MainHubWindow(autostart=False)
    try:
        window._open("builder")
        assert window._key == "builder"
        window._set_venue("both")
        # Strategy work is per venue: the screen redirects home and the rail hides.
        assert window._key == "home"
        window._open("backtest")
        assert window._key == "home"
        for key in ("builder", "backtest"):
            assert all(button.isHidden() for button in window._nav_buttons[key])
        window._set_venue("hl")
        assert all(not button.isHidden() for button in window._nav_buttons["builder"])
        window._open("builder")
        assert window._key == "builder"
    finally:
        window.close()


def test_home_shows_what_the_venue_has(app: QApplication) -> None:
    window = MainHubWindow(autostart=False)
    try:
        window._set_venue("hl")
        frames = window._stat_frames
        assert frames["Hyperliquid balance"].isHidden() is False
        assert frames["Polymarket balance"].isHidden() is True
        assert frames["Next market"].isHidden() is True
        assert window._live_pm.isHidden() and not window._live_hl.isHidden()
        window._set_venue("pm")
        assert frames["Hyperliquid balance"].isHidden() is True
        assert not window._live_pm.isHidden() and window._live_hl.isHidden()
        window._set_venue("both")
        assert not window._live_pm.isHidden() and not window._live_hl.isHidden()
    finally:
        window.close()


def test_the_polymarket_screen_has_a_detail_card_and_the_bets_in_the_bar(app: QApplication) -> None:
    window = MainWindow(autostart=False, venue="pm")
    try:
        window.show()
        app.processEvents()
        assert hasattr(window, "pm_detail") and not hasattr(window, "book_card")
        bar = window.strategy_bar
        assert bar.bet_bar.parent() is bar and bar.bet_bar.property("inline") == "true"
        assert window._hl_column.isHidden()           # alive, not shown
        assert window.pm_detail.table.rowCount() == 1  # "none open"
        assert bar.auto.text() == "Auto-bet"
    finally:
        window.close()


def test_the_hyperliquid_screen_has_a_book_a_positions_card_and_a_trade_card(app: QApplication) -> None:
    window = MainWindow(autostart=False, venue="hl")
    try:
        window.show()
        app.processEvents()
        assert window._pm_column.isHidden()
        form = window.main_card.trade_form
        assert form.bar_enabled is False
        form.show_bar(True)
        assert form.bar.isHidden()                    # the card owns the controls now
        assert window.strategy_bar.auto.text() == "Auto-trade"
        assert window.strategy_bar.bet_bar.isHidden()
        window._on_book(book())
        assert window.book_card.view.book is not None
        # The size and buy buttons still drive the same form, in their new card.
        assert form.buy.isVisibleTo(window) and form.size_field.isVisibleTo(window)
    finally:
        window.close()


def test_both_keeps_the_two_columns_with_their_bars(app: QApplication) -> None:
    window = MainWindow(autostart=False, venue="both")
    try:
        window.show()
        app.processEvents()
        assert not hasattr(window, "pm_detail") and not hasattr(window, "book_card")
        assert window.strategy_bar.bet_bar.parent() is window._pm_column
        assert window.main_card.trade_form.bar.parent() is window._hl_column
    finally:
        window.close()


def test_the_order_book_paints_five_levels_a_side(app: QApplication) -> None:
    card = OrderBookCard()
    card.resize(380, 340)
    card.show()
    card.set_book(book(), 1)
    card.set_latency(42.0)
    app.processEvents()
    assert card.latency.text() == "42 ms"
    image = card.grab().toImage()
    colours = {image.pixelColor(x, y).name() for x in range(0, image.width(), 7)
               for y in range(0, image.height(), 5)}
    assert len(colours) > 4                           # bars and text, not an empty card
    assert LEVELS == 5
    card.set_book(None)
    app.processEvents()
    card.close()


def test_a_manual_wrap_in_the_strategy_list_never_scrolls_sideways(app: QApplication) -> None:
    from bi_trading.state.strategies import SavedStrategy
    from bi_trading.ui.strat.strat_saved import StrategyListTile

    tile = StrategyListTile()
    tile.resize(260, 400)
    tile.set_strategies([
        SavedStrategy(name="A strategy with a very long name that cannot possibly fit "
                           "in a narrow rail on one line", timeframe="5m", entry="close > 1", exit="")
    ])
    tile.show()
    app.processEvents()
    scroll = tile.findChild(__import__("PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
