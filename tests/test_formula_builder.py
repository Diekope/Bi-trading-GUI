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
    CallChip,
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


def _call(group: str, label: str) -> dict:
    for title, items in PALETTES:
        if title == group:
            for item in items:
                if item.label == label:
                    func, series, params, display = item.call
                    return {
                        "func": func,
                        "series": series,
                        "params": list(params),
                        "label": display,
                    }
    raise AssertionError(f"no indicator {group}/{label}")


def _drop_call(builder: FormulaBuilder, strip: ChipStrip, group: str, label: str) -> None:
    builder.drop_tokens(
        {"tokens": [], "call": _call(group, label), "from": None},
        strip,
        len(strip.chips()),
    )


def _drop(builder: FormulaBuilder, strip: ChipStrip, tokens) -> None:
    builder.drop_tokens(
        {"tokens": list(tokens), "from": None}, strip, len(strip.chips())
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
            # Every block drops something: tokens, or an indicator call.
            assert block.item.tokens or block.item.call

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

    # A row of blocks reads left to right from the same top edge.
    data = builder.blocks["Data"]
    first_row = [b for b in data if b.geometry().top() == data[0].geometry().top()]
    assert len(first_row) >= 3
    lefts = [block.geometry().left() for block in first_row]
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

    # An indicator carries its call: function, series and default numbers.
    sma = _call("Indicators", "SMA")
    assert sma["func"] == "sma"
    assert sma["series"] == "close"
    assert sma["params"] == ["20"]
    bol = _call("Indicators", "Boll low")
    assert bol["func"] == "bollinger_lower"
    assert bol["params"] == ["20", "2"]  # period and deviations


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


def test_an_indicator_drops_as_one_tile(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop_call(builder, strip, "Indicators", "SMA")
    app.processEvents()

    # Exactly one chip, and nothing else came with it.
    assert len(strip.chips()) == 1
    chip = strip.chips()[0]
    assert isinstance(chip, CallChip)
    assert chip.property("group") == "indicator"
    assert chip.property("slot") is False
    assert chip.is_slot() is False
    # It carries its own number, and the text reads as the whole call.
    assert [field.text() for field in chip.fields] == ["20"]
    assert builder.formula_text() == "sma(close, 20)"
    assert builder.error() == ""
    assert builder.parsed() is not None


def test_an_indicators_number_is_edited_in_the_tile(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop_call(builder, strip, "Indicators", "SMA")
    _drop(builder, strip, _tokens("Logic & Maths", "<"))
    _drop(builder, strip, ("10",))
    app.processEvents()
    assert builder.formula_text() == "sma(close, 20) < 10"

    chip = strip.chips()[0]
    chip.fields[0].setText("50")
    app.processEvents()

    assert builder.formula_text() == "sma(close, 50) < 10"
    assert builder.parsed() is not None


def test_an_indicator_with_two_numbers_is_still_one_tile(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    _drop_call(builder, strip, "Indicators", "Boll low")
    app.processEvents()

    chip = strip.chips()[0]
    assert isinstance(chip, CallChip)
    assert len(strip.chips()) == 1
    assert [field.text() for field in chip.fields] == ["20", "2"]
    assert builder.formula_text() == "bollinger_lower(close, 20, 2)"

    chip.fields[1].setText("3")
    app.processEvents()
    assert builder.formula_text() == "bollinger_lower(close, 20, 3)"


def test_an_indicator_tile_moves_between_lines_as_one_tile(
    app: QApplication, builder: FormulaBuilder
) -> None:
    first = builder.strips[0]
    _drop_call(builder, first, "Indicators", "SMA")
    second = builder.add_strip()
    app.processEvents()

    # Drag it across, carrying its call.
    chip = first.chips()[0]
    builder.drop_tokens(
        {"tokens": [], "call": chip.call(), "from": [0, 0]}, second, 0
    )
    app.processEvents()

    assert first.chips() == []
    assert len(second.chips()) == 1
    assert isinstance(second.chips()[0], CallChip)
    assert second.chips()[0].fields[0].text() == "20"


def test_a_slot_can_still_be_filled_by_arming_it_and_typing(
    app: QApplication, builder: FormulaBuilder
) -> None:
    # Nothing in the palette makes a slot now, but the machinery stays: build
    # one by hand and fill it.
    strip = builder.strips[0]
    slot = strip.add_chip(None)
    app.processEvents()
    assert slot.is_slot() is True
    assert strip.has_empty_slots() is True

    builder.arm_slot(slot)
    assert builder.armed is slot
    builder.number_edit.setText("7")
    builder.add_number()
    app.processEvents()

    assert slot.token == "7"
    assert builder.armed is None
    assert builder.formula_text() == "7"
    assert builder.parsed() is not None


def test_a_slot_is_filled_by_dropping_a_number_on_it(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    slot = strip.add_chip(None)
    app.processEvents()

    # A drop landing on the slot replaces it.
    builder.fill_slot(slot, "14")
    app.processEvents()

    assert slot.token == "14"
    assert builder.formula_text() == "14"


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
    _drop_call(builder, first, "Indicators", "SMA")

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


def test_reading_text_back_keeps_indicator_tiles(
    app: QApplication, builder: FormulaBuilder
) -> None:
    builder.set_formula(
        "band = bollinger_lower(close, 20, 2)\nclose < band and rsi(close, 14) < 30"
    )
    app.processEvents()

    # The indicators come back as single tiles, not runs of tokens.
    kinds = [
        [type(chip).__name__ for chip in strip.chips()]
        for strip in builder.strips
    ]
    assert kinds[0] == ["Chip", "Chip", "CallChip"]
    assert kinds[1].count("CallChip") == 1
    calls = [
        chip
        for strip in builder.strips
        for chip in strip.chips()
        if isinstance(chip, CallChip)
    ]
    assert [chip.func for chip in calls] == ["bollinger_lower", "rsi"]
    assert [field.text() for field in calls[0].fields] == ["20", "2"]
    assert builder.formula_text() == (
        "band = bollinger_lower(close, 20, 2)\nclose < band and rsi(close, 14) < 30"
    )
    assert builder.error() == ""


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
    for token in ["close"] + ["and"] * 24:
        _drop(builder, strip, [token])
    builder.resize(360, 360)
    app.processEvents()

    # The chips wrap onto more than one row, and the flow asks for the room.
    rows = {chip.geometry().top() for chip in strip.chips()}
    assert len(rows) > 1
    assert strip.zone.flow.heightForWidth(strip.zone.width()) > (
        strip.chips()[0].height() + 4
    )


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


# -- the drag picture and the colours --------------------------------------


def test_a_drag_carries_a_picture_of_what_is_moving(
    app: QApplication, builder: FormulaBuilder
) -> None:
    from lalala.formula_builder import drag_pixmap

    block = builder.blocks["Data"][0]
    picture = drag_pixmap(block)

    assert picture.isNull() is False
    # The picture is the block itself, not the tile behind it.
    assert picture.size() == block.size()
    assert picture.width() < builder.width()
    assert picture.height() < builder.height()


def test_blocks_and_chips_are_coloured_by_what_they_are(
    app: QApplication, builder: FormulaBuilder
) -> None:
    from lalala.formula_builder import group_for_token

    assert group_for_token("close") == "data"
    assert group_for_token("volume") == "data"
    assert group_for_token("sma") == "indicator"
    assert group_for_token("bollinger_lower") == "indicator"
    assert group_for_token("and") == "logic"
    assert group_for_token("not") == "logic"
    assert group_for_token("+") == "maths"
    assert group_for_token(None) == ""

    assert builder.blocks["Data"][0].property("group") == "data"
    assert builder.blocks["Indicators"][0].property("group") == "indicator"

    # A chip wears its own group, and an indicator tile is one chip.
    strip = builder.strips[0]
    _drop(builder, strip, _tokens("Data", "close"))
    _drop(builder, strip, _tokens("Logic & Maths", "AND"))
    _drop(builder, strip, _tokens("Logic & Maths", "+"))
    _drop_call(builder, strip, "Indicators", "SMA")
    app.processEvents()

    groups = [(chip.tokens()[0], chip.property("group")) for chip in strip.chips()]
    assert groups[0] == ("close", "data")
    assert groups[1] == ("and", "logic")
    assert groups[2] == ("+", "maths")
    # The indicator tile is one chip whose first token is its function.
    assert groups[3] == ("sma", "indicator")


def test_a_line_shows_as_the_drop_target_while_dragging(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    assert bool(strip.property("target")) is False

    # Qt calls these when a drag is over the widget.
    class _Mime:
        def hasFormat(self, _):  # noqa: ANN001
            return True

        def data(self, _):  # noqa: ANN001
            from PySide6.QtCore import QByteArray

            return QByteArray(b'{"tokens": ["close"], "from": null}')

    class _Event:
        def mimeData(self):  # noqa: ANN201
            return _Mime()

        def acceptProposedAction(self):  # noqa: ANN201
            pass

    strip.dragEnterEvent(_Event())
    assert bool(strip.property("target")) is True
    strip.dragLeaveEvent(_Event())
    assert bool(strip.property("target")) is False


def test_a_blank_line_shows_the_dashed_hint(
    app: QApplication, builder: FormulaBuilder
) -> None:
    strip = builder.strips[0]
    assert strip.zone.empty is True

    _drop(builder, strip, ("close",))
    assert strip.zone.empty is False

    builder.remove_chip(strip.chips()[0])
    assert strip.zone.empty is True
