"""The formula language: parsing and the checks around it."""

from __future__ import annotations

import pytest

from lalala.formula import (
    FIELDS,
    FUNCTIONS,
    Assignment,
    Binary,
    Call,
    Formula,
    FormulaError,
    Name,
    Number,
    Unary,
    parse,
)


# -- what parses ------------------------------------------------------------


def test_a_bare_comparison_is_the_condition() -> None:
    formula = parse("close < 10")

    assert formula.assignments == ()
    assert formula.condition == Binary("<", Name("close"), Number(10.0))
    assert formula.empty is False


def test_named_series_come_before_the_condition() -> None:
    formula = parse("mid = sma(close, 20)\nclose < mid")

    assert formula.series_names == ("mid",)
    assert formula.assignments[0] == Assignment(
        "mid", Call("sma", (Name("close"), Number(20.0)))
    )
    assert formula.condition == Binary("<", Name("close"), Name("mid"))


def test_the_full_vocabulary_parses() -> None:
    source = (
        "band = bollinger_lower(close, 20, 2)\n"
        "close < band and volume > 2 * sma(volume, 50) and "
        "rsi(close, 14) < 30"
    )
    formula = parse(source)

    assert formula.series_names == ("band",)
    assert isinstance(formula.condition, Binary)  # `and` chains


def test_operators_bind_in_the_usual_order() -> None:
    # `not` is looser than a comparison; `and` is looser than `not`; `or` is
    # loosest of all.
    node = parse("not close > 5 or close < 2 and high > 3").condition

    assert isinstance(node, Binary) and node.op == "or"
    left, right = node.left, node.right
    assert isinstance(left, Unary) and left.op == "not"
    assert left.operand == Binary(">", Name("close"), Number(5.0))
    assert isinstance(right, Binary) and right.op == "and"


def test_arithmetic_precedence_and_a_unary_minus() -> None:
    node = parse("close < 1 + 2 * -3").condition

    assert node == Binary(
        "<",
        Name("close"),
        Binary("+", Number(1.0), Binary("*", Number(2.0), Unary("-", Number(3.0)))),
    )


def test_powers_are_right_associative() -> None:
    node = parse("close < 2 ^ 3 ^ 2").condition

    assert node.right == Binary(
        "^", Number(2.0), Binary("^", Number(3.0), Number(2.0))
    )


def test_comments_and_blank_lines_are_ignored() -> None:
    formula = parse("  # the idea\n\n x = close * 2\n x > close  # check")

    assert formula.series_names == ("x",)
    assert formula.condition == Binary(">", Name("x"), Name("close"))


def test_a_semicolon_separates_lines_like_a_newline() -> None:
    formula = parse("a = close; a > open")

    assert formula.series_names == ("a",)
    assert formula.condition == Binary(">", Name("a"), Name("open"))


def test_an_empty_formula_is_valid_and_empty() -> None:
    for source in ("", "   ", "\n\n", "# only a comment\n"):
        formula = parse(source)
        assert isinstance(formula, Formula)
        assert formula.empty is True
        assert formula.condition is None


def test_positions_are_not_part_of_the_shape() -> None:
    # Two parses of the same expression from different places compare equal:
    # the tree is the shape, not where the characters sat.
    first = parse("x = close * 2\nclose < x")
    second = parse("x    =    close*2\nclose<x")

    assert first.assignments == second.assignments
    assert first.condition == second.condition


# -- what does not parse ----------------------------------------------------


@pytest.mark.parametrize(
    "source, message",
    [
        ("close <", "unexpected end of formula"),
        ("close < (1 + 2", "expected ')'"),
        ("close < 10 20", "expected an operator or a new line"),
        ("close @ 10", "unexpected character '@'"),
        ("close < 5 and or 6", "'or' cannot be used as a name"),
    ],
)
def test_syntax_errors_carry_a_message(source: str, message: str) -> None:
    with pytest.raises(FormulaError) as caught:
        parse(source)
    assert message in caught.value.message
    assert caught.value.line >= 1 and caught.value.column >= 1
    assert str(caught.value).startswith(f"line {caught.value.line}")


def test_an_unknown_name_is_flagged_at_its_place() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("close < clsoe")

    assert "unknown name 'clsoe'" in caught.value.message
    assert (caught.value.line, caught.value.column) == (1, 9)


def test_an_unknown_function_is_flagged() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("close < nosuch(close, 2)")

    assert "unknown function 'nosuch'" in caught.value.message


def test_a_field_used_as_a_function_says_so() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("close(2) > 1")

    assert "is a field, not a function" in caught.value.message


def test_a_function_used_without_arguments_says_to_call_it() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("close < sma")

    assert "is a function — call it" in caught.value.message


def test_the_wrong_argument_count_is_reported() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("close < sma(20)")

    assert "sma() takes 2 argument(s), got 1" in caught.value.message

    with pytest.raises(FormulaError) as caught:
        parse("close < bollinger_lower(close, 20)")

    assert "bollinger_lower() takes 3 argument(s), got 2" in caught.value.message


def test_a_condition_before_the_last_line_is_rejected() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("close < 5\nmid = 3")

    assert "only the last line can be the condition" in caught.value.message


def test_the_last_line_cannot_be_an_assignment() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("mid = 3\nother = 4")

    assert "the last line must be the condition" in caught.value.message


def test_a_name_cannot_be_defined_twice() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("a = close\na = open\na > close")

    assert "'a' is already defined" in caught.value.message


def test_a_field_cannot_be_reassigned() -> None:
    with pytest.raises(FormulaError) as caught:
        parse("close = 5\nclose > 1")

    assert "is a field and cannot be reassigned" in caught.value.message


def test_a_later_line_cannot_use_a_name_from_below_it() -> None:
    # `b` is defined after the line that wants it.
    with pytest.raises(FormulaError) as caught:
        parse("a = b\nb = close\na > b")

    assert "unknown name 'b'" in caught.value.message


# -- the vocabulary itself --------------------------------------------------


def test_the_fields_and_functions_are_the_expected_set() -> None:
    assert FIELDS == ("open", "high", "low", "close", "volume")
    assert set(FUNCTIONS) == {
        "abs", "sqrt", "min", "max", "sma", "ema", "rsi",
        "highest", "lowest", "change", "shift",
        "bollinger_lower", "bollinger_middle", "bollinger_upper",
    }
    # Every entry is a (min, max) arity pair that makes sense.
    for low, high in FUNCTIONS.values():
        assert 1 <= low <= high <= 3


def test_every_function_in_the_catalogue_actually_checks() -> None:
    # A three-argument call that satisfies the widest arity, so each name is
    # exercised at least once.
    for name, (low, _) in FUNCTIONS.items():
        args = ", ".join(["close"] * low)
        formula = parse(f"close < {name}({args})")
        assert formula.condition is not None


# -- the exit vocabulary ----------------------------------------------------


def test_the_exit_vocabulary_is_the_trade_and_no_indicators() -> None:
    from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS

    assert EXIT_FIELDS == ("price", "entry", "tp", "sl", "pnl", "bars")
    assert "sma" not in EXIT_FUNCTIONS
    assert set(EXIT_FUNCTIONS) == {"abs", "sqrt", "min", "max"}

    formula = parse("pnl >= tp or pnl <= 0 - sl", EXIT_FIELDS, EXIT_FUNCTIONS)
    assert formula.fields == EXIT_FIELDS
    assert formula.condition is not None


def test_the_exit_vocabulary_refuses_bar_names_and_indicators() -> None:
    from lalala.formula import EXIT_FIELDS, EXIT_FUNCTIONS

    with pytest.raises(FormulaError) as caught:
        parse("close < 10", EXIT_FIELDS, EXIT_FUNCTIONS)
    assert "unknown name 'close'" in caught.value.message

    with pytest.raises(FormulaError) as caught:
        parse("price < sma(price, 20)", EXIT_FIELDS, EXIT_FUNCTIONS)
    assert "takes no indicators" in caught.value.message

    # Plain maths is fine.
    assert parse(
        "pnl > abs(0 - 1) and bars > max(10, 5)", EXIT_FIELDS, EXIT_FUNCTIONS
    ).condition is not None
