"""The drag-and-drop formula builder: palettes, chips, slots and lines."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.formula_builder import (  # noqa: E402
    MIME,
    PALETTES,
    Chip,
    ChipStrip,
    FormulaBuilder,
    PaletteBlock,
)
from lalala.theme import apply_dark_theme  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


@pytest.fixture
def builder(app: QApplication) -> FormulaBuilder:
    widget = FormulaBuilder()
    widget.resize(560, 320)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def _tokens(group: str, label: str) -> list:
    for title, items in PALETTES:
        if title == group:
            for item in items:
                if item.label == label:
                    return list(item.tokens)
    raise AssertionError(f"no palette item {group}/{label}")


def _drop(builder: FormulaBuilder, strip: ChipStrip, tokens) -> None:
    builder.drop_tokens(
        {"tokens": list(tokens), "from": None}, strip, len(strip.tokens())
    )


# -- the palette ------------------------------------------------------------


def test_the_palette_is_rows_of_blocks_and_a_number_box(
    builder: FormulaBuilder
) -> None:
    assert [title for title, _ in PALETTES] == [
        "Data",
        "Indicators",
        "Logic & Maths",
    ]
    # One row per group, each a horizontal run of blocks.
    assert list(builder.blocks) == ["Data", "Indicators", "Logic & Maths"]
    for title, blocks in builder.blocks.items():
        assert blocks, f"{title} has something to drag"
        for block in blocks:
            assert isinstance(block, PaletteBlock)
            assert block.item.tokens, "every block drops something"

    assert builder.number_edit is not None
    assert "Add" in builder.number_add.text()
    assert "Reset" in builder.reset_button.text()


def test_the_blocks_sit_in_a_horizontal_row(app: QApplication) -> None:
    from lalala.theme import apply_dark_theme

    apply_dark_theme(QApplication.instance() or app)
    builder = FormulaBuilder()
    builder.resize(620, 320)
    builder.show()
    app.processEvents()

    # The short rows share a row: same top, left to right.
    data = builder.blocks["Data"]
    tops = {block.geometry().top() for block in data}
    assert len(tops) == 1
    lefts = [block.geometry().left() for block in data]
    assert lefts == sorted(lefts)

    # A long row wraps rather than running off; Logic & Maths is the long one.
    logic = builder.blocks["Logic & Maths"]
    rows = {block.geometry().top() for block in logic}
    assert len(rows) > 1
    builder.close()


def test_the_blocks_carry_what_they_would_drop(
    builder: FormulaBuilder
) -> None:
    data = builder.blocks["Data"]
    labels = [block.item.label for block in data]
    assert "close" in labels and "volume" in labels

    # An indicator drops as a call with an empty slot for its period.
    sma = _tokens("Indicators", "SMA")
    assert sma == ["sma", "(", "close", ",", None, ")"]
    bol = _tokens("Indicators", "Boll low")
    assert bol.count(None) == 2  # period and deviations


# -- lines and chips --------------------------------------------------------


def test_a_new_builder_has_one_empty_line(builder: FormulaBuilder) -> None:
    assert len(builder.strips) == 1
    assert builder.strips[0].chips() == []
    assert builder.formula_text() == ""
    assert builder.error() == ""
    assert builder.parsed() is None
    # The last line is the condition; a lone empty line is not yet one.
    assert builder.preview_label.text().startswith("—")


def test_dropping_tokens_builds_the_text_and_parses(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop(builder, strip, _tokens("Data", "close"))
    _drop(builder, strip, _tokens("Logic & Maths", "<"))
    _drop(builder, strip, ("10",))
    app.processEvents()

    assert builder.formula_text() == "close < 10"
    assert builder.error() == ""
    assert builder.parsed() is not None
    # Chips render in order, left to right.
    assert [chip.token for chip in strip.chips()] == ["close", "<", "10"]


def test_an_indicator_arrives_with_an_empty_slot(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop(builder, strip, _tokens("Indicators", "SMA"))
    app.processEvents()

    assert strip.has_empty_slots() is True
    assert builder.parsed() is None
    assert "slot" in builder.error()

    slot = [chip for chip in strip.chips() if chip.token is None][0]
    assert slot.property("slot") is True
    assert slot.acceptDrops() is True


def test_a_slot_is_filled_by_arming_it_and_typing(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop(builder, strip, _tokens("Indicators", "SMA"))
    slot = [chip for chip in strip.chips() if chip.token is None][0]

    builder.arm_slot(slot)
    assert builder.armed is slot
    assert slot.property("armed") is True

    builder.number_edit.setText("20")
    builder.add_number()
    app.processEvents()

    assert slot.token == "20"
    assert builder.armed is None
    assert builder.formula_text() == "sma(close, 20)"
    assert builder.parsed() is not None


def test_a_slot_is_filled_by_dropping_a_number_on_it(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop(builder, strip, _tokens("Indicators", "SMA"))
    slot = [chip for chip in strip.chips() if chip.token is None][0]

    # A drop landing on the slot replaces it.
    builder.fill_slot(slot, "14")
    app.processEvents()

    assert slot.token == "14"
    assert builder.formula_text() == "sma(close, 14)"


def test_the_number_box_adds_a_chip_to_the_active_line(
    app: QApplication, builder: FormulaBuilder
) -> None:
    _drop(builder, builder.strips[0], _tokens("Data", "close"))
    builder.number_edit.setText("2.5")
    builder.add_number()
    app.processEvents()

    assert [chip.token for chip in builder.strips[0].chips()] == ["close", "2.5"]
    assert builder.number_edit.text() == ""


def test_a_chip_can_be_taken_off_a_line(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop(builder, strip, ("close", "<", "10"))
    app.processEvents()

    builder.remove_chip(strip.chips()[1])
    app.processEvents()

    assert [chip.token for chip in strip.chips()] == ["close", "10"]
    assert builder.formula_text() == "close 10"  # no operator: now wrong
    assert builder.parsed() is None


# -- lines ------------------------------------------------------------------


def test_lines_can_be_added_and_removed_but_not_all_the_way_down(
    app: QApplication, builder: FormulaBuilder
) -> None:
    second = builder.add_strip()
    app.processEvents()
    assert len(builder.strips) == 2

    builder.remove_strip(second)
    app.processEvents()
    assert len(builder.strips) == 1
    # The last line cannot be removed.
    builder.remove_strip(builder.strips[0])
    assert len(builder.strips) == 1


def test_a_series_line_then_a_condition(
    app: QApplication, builder: FormulaBuilder
) -> None:
    first = builder.strips[0]
    _drop(builder, first, ("mid", "="))
    _drop(builder, first, _tokens("Indicators", "SMA"))
    # Fill the two-chips-worth of slot.
    for chip in first.chips():
        if chip.token is None:
            builder.fill_slot(chip, "20")

    second = builder.add_strip()
    _drop(builder, second, ("close",))
    _drop(builder, second, _tokens("Logic & Maths", "<"))
    _drop(builder, second, ("mid",))
    app.processEvents()

    assert builder.formula_text() == "mid = sma(close, 20)\nclose < mid"
    assert builder.error() == ""
    parsed = builder.parsed()
    assert parsed is not None and parsed.series_names == ("mid",)


def test_a_condition_before_the_last_line_is_reported(
    app: QApplication, builder: FormulaBuilder
) -> None:
    _drop(builder, builder.strips[0], ("close", "<", "10"))
    second = builder.add_strip()
    _drop(builder, second, ("mid", "=", "5"))
    app.processEvents()

    assert "only the last line can be the condition" in builder.error()


def test_a_chip_can_be_moved_between_lines(
    app: QApplication, builder: FormulaBuilder
) -> None:
    first = builder.strips[0]
    _drop(builder, first, ("close", "<", "10"))
    second = builder.add_strip()
    app.processEvents()

    # Drag the "10" from the first line onto the second.
    builder.drop_tokens(
        {"tokens": ["10"], "from": [0, 2]}, second, 0
    )
    app.processEvents()

    assert [chip.token for chip in first.chips()] == ["close", "<"]
    assert [chip.token for chip in second.chips()] == ["10"]


# -- text, wrapping and signals --------------------------------------------


def test_set_formula_rebuilds_the_lines(builder: FormulaBuilder) -> None:
    builder.set_formula("mid = sma(close, 20)\nclose < mid and volume > 1")

    assert len(builder.strips) == 2
    assert [strip.tokens() for strip in builder.strips] == [
        ["mid", "=", "sma", "(", "close", ",", "20", ")"],
        ["close", "<", "mid", "and", "volume", ">", "1"],
    ]
    assert builder.formula_text() == "mid = sma(close, 20)\nclose < mid and volume > 1"
    assert builder.error() == ""

    # An empty string leaves a single empty line.
    builder.set_formula("")
    assert len(builder.strips) == 1
    assert builder.strips[0].tokens() == []


def test_the_changed_signal_fires_on_every_edit(
    app: QApplication, builder: FormulaBuilder
) -> None:
    seen: list[int] = []
    builder.changed.connect(lambda: seen.append(1))

    _drop(builder, builder.strips[0], ("close",))
    _drop(builder, builder.strips[0], ("<",))
    builder.number_edit.setText("1")
    builder.add_number()
    app.processEvents()

    assert len(seen) == 3


def test_a_long_line_wraps_instead_of_clipping(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    # Enough chips to run past the width.
    for token in _tokens("Indicators", "Boll low") + ["and"] * 20:
        _drop(builder, strip, [token])
    builder.resize(360, 320)
    app.processEvents()

    one_row = strip.chips()[0].height() + 8
    assert strip.heightForWidth(builder.width() - 40) > one_row


def test_the_chip_carries_its_token() -> None:
    app = QApplication.instance() or QApplication([])
    builder = FormulaBuilder()
    chip = Chip("close", builder)
    assert chip.token == "close"
    assert chip.property("slot") is False
    chip.set_token(None)
    assert chip.property("slot") is True
    assert chip.label.text() == "▢"
    builder.close()


def test_the_mime_type_is_private_to_the_builder() -> None:
    assert MIME == "application/x-lalala-chip"
