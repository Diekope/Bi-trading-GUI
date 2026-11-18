"""The venues' own marks, where the app used coloured dots."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel  # noqa: E402

from bi_trading.ui import venue_icons  # noqa: E402
from bi_trading.ui.palette import HL_DOT, PM_DOT  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_every_name_the_app_uses_finds_the_same_venue() -> None:
    for name in ("pm", "PM", "Polymarket", "polymarket", PM_DOT):
        assert venue_icons.venue_key(name) == "polymarket"
    for name in ("hl", "Hyperliquid", HL_DOT):
        assert venue_icons.venue_key(name) == "hyperliquid"
    assert venue_icons.venue_key("Binance") is None


def test_the_logo_files_ship_with_the_package() -> None:
    assert (venue_icons.ASSETS / "polymarket.png").exists()
    assert (venue_icons.ASSETS / "hyperliquid.png").exists()
    assert venue_icons.has_logo("hl") and venue_icons.has_logo("Polymarket")
    assert not venue_icons.has_logo("Binance")


def test_the_mark_is_a_square_logo_label(app) -> None:
    mark = venue_icons.venue_mark("hl", 18)
    assert isinstance(mark, QLabel)
    assert (mark.width(), mark.height()) == (18, 18)
    assert mark.toolTip() == "Hyperliquid"
    assert venue_icons.venue_pixmap("hl", 18).devicePixelRatio() == 2  # sharp on a 2x screen


def test_polymarkets_black_mark_is_drawn_white_and_hyperliquids_keeps_its_colour(app) -> None:
    def colours(name: str) -> set[tuple[int, int, int]]:
        image = venue_icons.venue_pixmap(name, 16).toImage()
        found = set()
        for x in range(image.width()):
            for y in range(image.height()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() > 200:
                    found.add((pixel.red(), pixel.green(), pixel.blue()))
        return found

    assert colours("polymarket") == {(255, 255, 255)}      # tinted white
    mint = colours("hyperliquid")
    assert mint and all(g > r for r, g, _ in mint)          # the mint green


def test_an_unknown_venue_falls_back_to_a_coloured_dot(app, monkeypatch) -> None:
    dot = venue_icons.venue_mark("#123456", 16)
    assert isinstance(dot, QFrame) and not isinstance(dot, QLabel)
    assert "#123456" in dot.styleSheet()

    monkeypatch.setattr(venue_icons, "ASSETS", venue_icons.ASSETS / "missing")
    venue_icons._cache.clear()
    assert isinstance(venue_icons.venue_mark("pm", 16), QFrame)   # file gone: the dot
    venue_icons._cache.clear()


def test_the_rail_settings_and_home_use_the_logos(app, monkeypatch, tmp_path) -> None:
    from bi_trading.ui.hub.main_hub import MainHubWindow

    monkeypatch.setenv("BI_TRADING_SETTINGS", str(tmp_path / "settings.json"))
    window = MainHubWindow(autostart=False)
    try:
        marks = [m for m in window.findChildren(QLabel)
                 if m.toolTip() in ("Polymarket", "Hyperliquid") and m.pixmap() is not None
                 and not m.pixmap().isNull()]
        names = {m.toolTip() for m in marks}
        assert names == {"Polymarket", "Hyperliquid"}      # the rail and the Home cards
        window._open("settings")
        again = [m for m in window.findChildren(QLabel)
                 if m.toolTip() in ("Polymarket", "Hyperliquid") and m.pixmap() is not None
                 and not m.pixmap().isNull()]
        assert len(again) >= 4          # rail x2, the two cards' headers, the pills
    finally:
        window.close()
