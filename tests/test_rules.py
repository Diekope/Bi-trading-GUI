"""The rules tile: one formula, written with tiles or as code."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.formula_builder import CallChip  # noqa: E402
from lalala.strat_rules import RULES_MODES, RulesTile  # noqa: E402
from lalala.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def tile(app: QApplication) -> RulesTile:
    widget = RulesTile("ENTRY RULES")
    widget.resize(560, 320)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def test_it_is_titled_with_two_modes(app: QApplication) -> None:
    tile = RulesTile("EXIT RULES")
    tile.show()
    app.processEvents()

    assert tile.title.text() == "EXIT RULES"
    assert tile.title.objectName() == "tileTitle"
    assert [key for key, _ in RULES_MODES] == ["formulas", "code"]
    assert list(tile.mode_buttons) == ["formulas", "code"]
    assert tile.mode() == "formulas"
    assert tile.pages.count() == 2
    tile.close()


def test_the_code_is_filled_from_the_tiles(
    app: QApplication, tile: RulesTile
) -> None:
    tile.set_text("mid = sma(close, 20)\nclose < mid")
    tile.set_mode("code")
    app.processEvents()

    assert tile.code() == "mid = sma(close, 20)\nclose < mid"
    assert tile.code_error.text() == ""


def test_typing_code_rebuilds_the_tiles(
    app: QApplication, tile: RulesTile
) -> None:
    tile.set_mode("code")
    tile.set_code("close < bollinger_lower(close, 20, 2)")
    app.processEvents()

    assert tile.text() == "close < bollinger_lower(close, 20, 2)"
    assert tile.code_error.text() == ""
    strip = tile.formula.strips[0]
    # The indicator came back as one tile, not a run of tokens.
    assert any(isinstance(chip, CallChip) for chip in strip.chips())


def test_an_unknown_name_is_accepted_and_flagged(
    app: QApplication, tile: RulesTile
) -> None:
    tile.set_mode("code")
    tile.set_code("close < clsoe")
    app.processEvents()

    # The edit is kept — only the checker complains.
    assert tile.code() == "close < clsoe"
    assert tile.code_error.text() == "line 1, column 9: unknown name 'clsoe'"
    assert tile.parsed() is None

    # Defining the name above clears it.
    tile.set_code("clsoe = close * 2\nclose < clsoe")
    app.processEvents()
    assert tile.code_error.text() == ""
    assert tile.parsed() is not None


def test_a_line_the_language_cannot_read_is_refused(
    app: QApplication, tile: RulesTile
) -> None:
    tile.set_text("close < sma(close, 20)")
    tile.set_mode("code")
    app.processEvents()
    assert tile.code() == "close < sma(close, 20)"

    # A character the scanner rejects: the edit does not stick.
    tile.set_code("close @ 10")
    app.processEvents()

    assert tile.code() == "close < sma(close, 20)"  # put back
    assert tile.code_error.text().startswith("refused —")
    assert "unexpected character '@'" in tile.code_error.text()
    # The tiles never moved either.
    assert tile.text() == "close < sma(close, 20)"
    assert tile.parsed() is not None


def test_the_tiles_and_the_code_agree_after_an_edit(
    app: QApplication, tile: RulesTile
) -> None:
    tile.set_mode("code")
    tile.set_code("close < sma(close, 20)")
    app.processEvents()
    # Back to the tiles: they hold what the code said.
    tile.set_mode("formulas")
    app.processEvents()
    assert tile.text() == "close < sma(close, 20)"

    # Change the tiles; the code follows.
    strip = tile.formula.strips[0]
    chip = [c for c in strip.chips() if isinstance(c, CallChip)][0]
    chip.fields[0].setText("50")
    app.processEvents()
    tile.set_mode("code")
    app.processEvents()
    assert tile.code() == "close < sma(close, 50)"
    assert tile.code_error.text() == ""


def test_two_tiles_do_not_share_a_formula(
    app: QApplication
) -> None:
    entry = RulesTile("ENTRY RULES")
    exit_ = RulesTile("EXIT RULES")
    entry.show()
    exit_.show()
    app.processEvents()

    entry.set_text("close < sma(close, 20)")
    exit_.set_text("close > sma(close, 50)")
    app.processEvents()

    assert entry.text() == "close < sma(close, 20)"
    assert exit_.text() == "close > sma(close, 50)"

    entry.set_mode("code")
    app.processEvents()
    assert exit_.mode() == "formulas"  # the other tile is untouched
    assert exit_.code() == "close > sma(close, 50)"
    entry.close()
    exit_.close()


def test_presets_fill_the_tile(app: QApplication) -> None:
    from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS
    from lalala.formula_builder import EXIT_PALETTES
    from lalala.strat_rules import EXIT_PRESETS, Preset

    tile = RulesTile(
        "EXIT RULES",
        presets=EXIT_PRESETS,
        palettes=EXIT_PALETTES,
        fields=EXIT_FIELDS,
        functions=EXIT_FUNCTIONS,
    )
    tile.show()
    app.processEvents()

    assert [b.text() for b in tile.preset_buttons] == [
        p.label for p in EXIT_PRESETS
    ]
    assert all(isinstance(p, Preset) for p in tile.presets)

    tile.preset_buttons[0].click()  # Take profit
    app.processEvents()
    assert tile.text() == "pnl >= tp"
    assert tile.error() == ""

    # A preset is an ordinary formula once it lands: editable like any other.
    tile.set_code("pnl >= tp * 0.5")
    app.processEvents()
    assert tile.text() == "pnl >= tp * 0.5"
    tile.close()


def test_the_changed_signal_fires_on_a_tile_edit(
    app: QApplication, tile: RulesTile
) -> None:
    seen: list[int] = []
    tile.changed.connect(lambda: seen.append(1))
    tile.formula.drop_tokens(
        {"tokens": ["close"], "from": None}, tile.formula.strips[0], 0
    )
    app.processEvents()
    assert seen
