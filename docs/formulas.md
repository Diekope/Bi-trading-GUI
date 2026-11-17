# Formulas and the evaluator

The entry/exit formula language and how it is evaluated. Back to the [README](../README.md).

## The evaluator

`formula_eval.py` is what makes the language run. Each expression becomes a
value per bar, the condition a truth per bar, and the true bars are the
signals. A series is a list, a float or `None` where there is not enough
history yet — a 20-bar average says nothing about the first nineteen bars — and
nothing looks ahead.

The indicators are `sma`, `ema`, `rsi` (Wilder), `highest`, `lowest`,
`change`, `shift` and the three Bollinger bands, plus `abs`, `min`, `max` and
`sqrt`. An entry rule reads the bar, so it is evaluated over a whole series at
once. An exit rule reads the trade, which only exists while one is open, so it
is checked a bar at a time against the open trade's numbers.

`simulate()` walks the bars: one position at a time, in on an entry signal, out
when the exit rule says so. That is what the preview's markers are, and it is
the shape a real run would take.

**Long or short.** A strategy has a **side**, picked under its name in the
STRATEGY tile and saved with it. A long buys on the entry rule and gains as
price rises; a short sells on it and gains as price falls, buying back at the
exit. A short's take profit sits below the entry and its stop above, and `pnl`
in an exit rule is signed for the side, so `pnl >= tp` means "in profit" either
way. A short can lose at most its margin. One position is open at a time, long
or short.

**Both ways in one strategy.** Pick **Both** and a second tab, **SHORT ENTRY**,
appears beside **LONG ENTRY** and **EXIT RULES**: the first rule opens longs,
the second opens shorts, and the one exit rule closes whichever is open (its
`pnl` is signed for the trade's side). While a trade is open the other rule is
ignored; a bar both rules fire on opens nothing. The random-buy baseline a
two-way strategy is compared with goes long.

The text a build produces is parsed and checked as it is built: a sound formula
gets no error line, a typo gets its place — `line 2, column 9: unknown name
'clsoe'`, or `fill the empty slot before this can be read` while a slot is
blank.

### The formula language

A formula is a list of lines. All but the last define named series; the last is
the condition, evaluated once per bar:

```
mid = sma(close, 20)
close < bollinger_lower(close, 20, 2) and volume > 2 * sma(volume, 50)
```

The names are the bar's own fields — `open`, `high`, `low`, `close`, `volume` —
plus anything a line above defined; an exit rule is given the trade's words
instead (see above). Operators, loosest first: `or`, `and`, `not`, the
comparisons (`< <= > >= == !=`), then `+ -`, `* / %`, a right-associative `^`,
and a unary minus. `#` starts a comment and `;` separates lines. The functions
are `sma`, `ema`, `rsi`, `highest`, `lowest`, `change`, `shift`,
`bollinger_lower`, `bollinger_middle`, `bollinger_upper`, `abs`, `min`, `max`,
`sqrt` — the last four alone for an exit rule.

The checker reports syntax errors, unknown names, unknown functions, the wrong
number of arguments, reassigning a field, redefining a name, and a line that is
not the last but holds the condition. It does **not** type-check: a number where
a truth belongs is the author's business, and it evaluates nothing — that is the
walk's job, later.

`formula.py` has no Qt and no candle data, so the same parser can drive the
walk when the two are joined.
