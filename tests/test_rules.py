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


def test_it_is_titled_with_three_modes(app: QApplication) -> None:
    tile = RulesTile("EXIT RULES")
    tile.show()
    app.processEvents()

    assert tile.title.text() == "EXIT RULES"
    assert tile.title.objectName() == "tileTitle"
    assert [key for key, _ in RULES_MODES] == ["rules", "formula", "code"]
    assert list(tile.mode_buttons) == ["rules", "formula", "code"]
    assert tile.mode() == "rules"  # a rule starts on the conditions
    assert tile.pages.count() == 3
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
    assert exit_.mode() == "rules"  # the other tile is untouched
    assert exit_.code() == "close > sma(close, 50)"
    entry.close()
    exit_.close()


def test_the_rules_tab_reads_a_formula_into_groups(app: QApplication) -> None:
    tile = RulesTile("ENTRY RULES")
    tile.show()
    app.processEvents()

    tile.set_text(
        "band = bollinger_lower(close, 20, 2)\nclose < band and volume > 0"
    )
    tile.set_mode("rules")
    app.processEvents()

    page = tile.conditions
    assert page.assignments == ["band = bollinger_lower(close, 20, 2)"]
    assert len(page.groups) == 1
    rows = page.groups[0].rows
    assert [
        (row.left.currentText(), row.op.currentText(), row.right.currentText())
        for row in rows
    ] == [("close", "<", "band"), ("volume", ">", "0")]
    assert page.groups[0].logic_key() == "and"
    assert "close < band and volume > 0" in page.preview_text.text()
    assert page.preview_status.text().startswith("✓")
    tile.close()


def test_editing_a_row_rewrites_the_formula(app: QApplication) -> None:
    tile = RulesTile("ENTRY RULES")
    tile.show()
    app.processEvents()
    tile.set_text("close < open and volume > 0")

    row = tile.conditions.groups[0].rows[0]
    row.left.setCurrentText("high")
    row.right.setCurrentText("low")
    app.processEvents()

    assert tile.text() == "(high < low and volume > 0)"
    assert tile.error() == ""
    assert tile.code() == "(high < low and volume > 0)"
    tile.close()


def test_add_condition_and_group_change_the_formula(app: QApplication) -> None:
    tile = RulesTile("ENTRY RULES")
    tile.show()
    app.processEvents()
    tile.set_text("close > open")

    page = tile.conditions
    page.groups[0].add_row()
    second = page.groups[0].rows[1]
    second.left.setCurrentText("volume")
    second.op.setCurrentText(">")
    second.right.setCurrentText("0")
    app.processEvents()
    assert tile.text() == "(close > open and volume > 0)"

    group = page.add_group()
    group.rows[0].left.setCurrentText("rsi(close, 14)")
    group.rows[0].op.setCurrentText("<")
    group.rows[0].right.setCurrentText("30")
    group.set_logic("or")
    app.processEvents()

    assert tile.text() == (
        "(close > open and volume > 0) and rsi(close, 14) < 30"
    )
    assert tile.error() == ""
    assert [g.caption.text() for g in page.groups] == ["GROUP 1", "GROUP 2"]
    tile.close()


def test_an_or_of_comparisons_is_one_or_group(app: QApplication) -> None:
    from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS

    tile = RulesTile(
        "EXIT RULES", fields=EXIT_FIELDS, functions=EXIT_FUNCTIONS
    )
    tile.show()
    app.processEvents()
    tile.set_text("pnl >= tp or pnl <= 0 - sl or bars >= 90")

    page = tile.conditions
    assert len(page.groups) == 1
    assert page.groups[0].logic_key() == "or"
    assert len(page.groups[0].rows) == 3
    assert tile.text() == "pnl >= tp or pnl <= 0 - sl or bars >= 90"
    tile.close()


def test_a_condition_the_rows_cannot_hold_is_kept_whole(
    app: QApplication,
) -> None:
    tile = RulesTile("ENTRY RULES")
    tile.show()
    app.processEvents()
    tile.set_text("not (close > open)")

    row = tile.conditions.groups[0].rows[0]
    assert row._raw is True
    assert "not" in tile.text()
    assert tile.error() == ""
    tile.close()


def test_the_signal_rail_is_shown_but_disabled(app: QApplication) -> None:
    tile = RulesTile("ENTRY RULES")
    tile.show()
    app.processEvents()

    page = tile.conditions
    assert page.side_combo.currentText() == "YES"
    assert not page.side_combo.isEnabled()
    assert not page.confirmation_edit.isEnabled()
    assert not page.cooldown_edit.isEnabled()
    assert not page.entries_edit.isEnabled()
    assert not page.together.isEnabled()
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
