//! A native core for the backtest walk.
//!
//! The Python walk (`lalala.engine.core._python_walk`) is the reference; this
//! mirrors it exactly — one position at a time, long or short, take profit and
//! stop loss read off a candle's range (the stop wins when one candle holds
//! both), an optional trailing take profit, an optional exit rule, a fee each
//! way, a hold limit — but runs the bar loop in Rust, so a long span is walked
//! without the Python-level cost.
//!
//! An exit rule arrives as a small program (see `lalala.engine.core.compile_exit`)
//! of `(opcode, argument)` pairs for a stack machine. `NaN` stands for the
//! evaluator's "unknown", exactly as `None` does in Python.

use numpy::PyReadonlyArray1;
use pyo3::prelude::*;

/// One closed trade: (entry index, entry price, exit index, exit price, result,
/// fees, notional, reason, side).
type Trade = (usize, f64, usize, f64, f64, f64, f64, &'static str, &'static str);

struct Settings {
    tp: f64,
    sl: f64,
    position: f64,
    fixed: bool,
    risk: bool,
    max_cash: f64,
    fee: f64,
    max_hold: i64,
    dynamic_tp: bool,
    reverse: f64,
    slippage: f64,
}

fn budget(cash: f64, s: &Settings) -> f64 {
    let deployable = cash.min(s.max_cash);
    if s.fixed {
        s.position.clamp(0.0, deployable)
    } else if s.risk {
        // A stop-out should cost `position` percent of the cash in play, so a
        // wider stop means a smaller position.
        if s.sl > 0.0 {
            (deployable * s.position.max(0.0) / s.sl).clamp(0.0, deployable)
        } else {
            deployable
        }
    } else {
        deployable * s.position.max(0.0) / 100.0
    }
}

// -- the exit rule's stack machine -------------------------------------------

const CONST: i64 = 0;
const LOAD: i64 = 1;
const STORE: i64 = 2;
const NEG: i64 = 3;
const NOT: i64 = 4;
const ADD: i64 = 5;
const SUB: i64 = 6;
const MUL: i64 = 7;
const DIV: i64 = 8;
const MOD: i64 = 9;
const POW: i64 = 10;
const LT: i64 = 11;
const LE: i64 = 12;
const GT: i64 = 13;
const GE: i64 = 14;
const EQ: i64 = 15;
const NE: i64 = 16;
const AND: i64 = 17;
const OR: i64 = 18;
const ABS: i64 = 19;
const SQRT: i64 = 20;
const MIN: i64 = 21;
const MAX: i64 = 22;

/// The rule's own truth: known and above zero.
fn truth(v: f64) -> bool {
    !v.is_nan() && v > 0.0
}

fn flag(b: bool) -> f64 {
    if b {
        1.0
    } else {
        0.0
    }
}

/// Run the program over the slots `vars` (the trade's words first, then the
/// rule's own named values) and say whether the rule holds.
fn run_rule(program: &[(i64, f64)], vars: &mut [f64], stack: &mut Vec<f64>) -> bool {
    stack.clear();
    for &(op, arg) in program {
        match op {
            CONST => stack.push(arg),
            LOAD => stack.push(vars[arg as usize]),
            STORE => {
                let v = stack.pop().unwrap_or(f64::NAN);
                vars[arg as usize] = v;
            }
            NEG => {
                let v = stack.pop().unwrap_or(f64::NAN);
                stack.push(-v);
            }
            NOT => {
                let v = stack.pop().unwrap_or(f64::NAN);
                stack.push(if v.is_nan() { 0.0 } else { flag(!truth(v)) });
            }
            ABS => {
                let v = stack.pop().unwrap_or(f64::NAN);
                stack.push(v.abs());
            }
            SQRT => {
                let v = stack.pop().unwrap_or(f64::NAN);
                stack.push(if v.is_nan() {
                    v
                } else if v >= 0.0 {
                    v.sqrt()
                } else {
                    0.0
                });
            }
            _ => {
                let b = stack.pop().unwrap_or(f64::NAN);
                let a = stack.pop().unwrap_or(f64::NAN);
                let unknown = a.is_nan() || b.is_nan();
                let v = match op {
                    AND => flag(truth(a) && truth(b)),
                    OR => flag(truth(a) || truth(b)),
                    _ if unknown => f64::NAN,
                    ADD => a + b,
                    SUB => a - b,
                    MUL => a * b,
                    DIV => {
                        if b == 0.0 {
                            f64::NAN
                        } else {
                            a / b
                        }
                    }
                    MOD => {
                        if b == 0.0 {
                            f64::NAN
                        } else {
                            // Python's remainder takes the divisor's sign.
                            let r = a % b;
                            if r != 0.0 && (r < 0.0) != (b < 0.0) {
                                r + b
                            } else {
                                r
                            }
                        }
                    }
                    POW => a.powf(b),
                    LT => flag(a < b),
                    LE => flag(a <= b),
                    GT => flag(a > b),
                    GE => flag(a >= b),
                    EQ => flag(a == b),
                    NE => flag(a != b),
                    MIN => a.min(b),
                    MAX => a.max(b),
                    _ => f64::NAN,
                };
                stack.push(v);
            }
        }
    }
    truth(stack.pop().unwrap_or(f64::NAN))
}

/// Walk `closes` (with `highs`/`lows` for the exits), opening a long where
/// `longs` is true and a short where `shorts` is. A bar that is both is left
/// alone. Returns the trades and the realised equity per bar.
///
/// The columns arrive as NumPy arrays, so a long span is not copied into a
/// Python list first.
#[pyfunction]
#[pyo3(signature = (closes, highs, lows, longs, shorts, capital, tp, sl, position,
                    sizing, max_cash, fee, max_hold, dynamic_tp=false, reverse=0.0,
                    rule=None, slots=0, slippage=0.0))]
#[allow(clippy::too_many_arguments)]
fn walk(
    closes: PyReadonlyArray1<f64>,
    highs: PyReadonlyArray1<f64>,
    lows: PyReadonlyArray1<f64>,
    longs: PyReadonlyArray1<bool>,
    shorts: PyReadonlyArray1<bool>,
    capital: f64,
    tp: f64,
    sl: f64,
    position: f64,
    sizing: &str,
    max_cash: f64,
    fee: f64,
    max_hold: i64,
    dynamic_tp: bool,
    reverse: f64,
    rule: Option<Vec<(i64, f64)>>,
    slots: usize,
    slippage: f64,
) -> PyResult<(Vec<Trade>, Vec<f64>)> {
    let closes = closes.as_slice()?;
    let highs = highs.as_slice()?;
    let lows = lows.as_slice()?;
    let longs = longs.as_slice()?;
    let shorts = shorts.as_slice()?;
    let n = closes.len();
    let s = Settings {
        tp,
        sl,
        position,
        fixed: sizing == "fixed",
        risk: sizing == "risk",
        max_cash,
        fee,
        max_hold,
        dynamic_tp,
        reverse,
        slippage,
    };

    let mut trades: Vec<Trade> = Vec::new();
    let mut equity_curve: Vec<f64> = Vec::with_capacity(n);

    let mut vars = vec![0.0_f64; slots.max(6)];
    let mut stack: Vec<f64> = Vec::with_capacity(16);

    let mut cash = capital;
    let mut qty = 0.0_f64;
    let mut short = false;
    let mut entry_price = 0.0_f64;
    let mut entry_index = 0_usize;
    let mut entry_cost = 0.0_f64;
    let mut entry_fee = 0.0_f64;
    let mut entry_notional = 0.0_f64;
    // The best price since entry: the high of a long, the low of a short.
    let mut best = 0.0_f64;

    for index in 0..n {
        let close = closes[index];
        let high = highs[index];
        let low = lows[index];

        if qty > 0.0 {
            let (target, stop, hit_tp, hit_sl, hit_trail);
            if short {
                target = entry_price * (1.0 - s.tp / 100.0);
                stop = entry_price * (1.0 + s.sl / 100.0);
                if s.dynamic_tp && s.reverse > 0.0 {
                    best = best.min(low);
                }
                hit_tp = s.tp > 0.0 && low <= target;
                hit_sl = s.sl > 0.0 && high >= stop;
                hit_trail = s.dynamic_tp
                    && s.reverse > 0.0
                    && best > 0.0
                    && best < entry_price
                    && high >= best * (1.0 + s.reverse / 100.0);
            } else {
                target = entry_price * (1.0 + s.tp / 100.0);
                stop = entry_price * (1.0 - s.sl / 100.0);
                if s.dynamic_tp && s.reverse > 0.0 {
                    best = best.max(high);
                }
                hit_tp = s.tp > 0.0 && high >= target;
                hit_sl = s.sl > 0.0 && low <= stop;
                hit_trail = s.dynamic_tp
                    && s.reverse > 0.0
                    && best > entry_price
                    && low <= best * (1.0 - s.reverse / 100.0);
            }
            let trail = if short {
                best * (1.0 + s.reverse / 100.0)
            } else {
                best * (1.0 - s.reverse / 100.0)
            };
            let held = (index - entry_index) as i64;
            let mut price: Option<f64> = None;
            let mut reason = "time";
            // A candle that holds both the target and the stop cannot say which
            // came first, so the stop is taken: the cautious reading.
            if hit_sl {
                price = Some(stop);
                reason = "sl";
            } else if hit_tp {
                price = Some(target);
                reason = "tp";
            } else if hit_trail {
                price = Some(trail);
                reason = "tp";
            } else if let Some(program) = rule.as_deref() {
                let ratio = if entry_price != 0.0 { close / entry_price - 1.0 } else { 0.0 };
                vars[0] = close;
                vars[1] = entry_price;
                vars[2] = s.tp;
                vars[3] = s.sl;
                vars[4] = (if short { -ratio } else { ratio }) * 100.0;
                vars[5] = held as f64;
                if run_rule(program, &mut vars, &mut stack) {
                    price = Some(close);
                    reason = "rule";
                }
            }
            if price.is_none() && s.max_hold > 0 && held >= s.max_hold {
                price = Some(close);
                reason = "time";
            }
            if let Some(mut price) = price {
                // A take profit is a resting limit order and fills at its
                // price; every other exit is a market order and slips against
                // the trade.
                if reason != "tp" {
                    price *= if short { 1.0 + s.slippage } else { 1.0 - s.slippage };
                }
                // A long is worth qty * price; a short is its margin back plus
                // what the price fell, never less than nothing.
                let value = if short {
                    (qty * (2.0 * entry_price - price)).max(0.0)
                } else {
                    qty * price
                };
                let cost = qty * price * s.fee;
                cash += value - cost;
                let result = if entry_cost > 0.0 {
                    (value - cost) / entry_cost - 1.0
                } else {
                    0.0
                };
                trades.push((
                    entry_index,
                    entry_price,
                    index,
                    price,
                    result,
                    entry_fee + cost,
                    entry_notional,
                    reason,
                    if short { "short" } else { "long" },
                ));
                qty = 0.0;
                entry_cost = 0.0;
                best = 0.0;
            }
        } else if index != 0 && (longs[index] != shorts[index]) {
            let notional = budget(cash, &s);
            if notional > 0.0 && close > 0.0 {
                let cost = notional * s.fee;
                short = shorts[index];
                // The entry is a market order too: it fills a little worse
                // than the close it was decided on.
                let fill = close * if short { 1.0 - s.slippage } else { 1.0 + s.slippage };
                qty = notional / fill;
                cash -= notional + cost;
                entry_price = fill;
                entry_index = index;
                entry_fee = cost;
                entry_notional = notional;
                entry_cost = notional + cost;
                best = if short { low } else { high };
            }
        }

        // Realised book: an open position is carried at what it cost.
        equity_curve.push(cash + qty * entry_price);
    }

    Ok((trades, equity_curve))
}

#[pyfunction]
#[pyo3(signature = (highs, lows, closes, draws, tp, sl, max_hold, chance, short=false))]
#[allow(clippy::too_many_arguments)]
fn random_entries(
    highs: PyReadonlyArray1<f64>,
    lows: PyReadonlyArray1<f64>,
    closes: PyReadonlyArray1<f64>,
    draws: PyReadonlyArray1<f64>,
    tp: f64,
    sl: f64,
    max_hold: i64,
    chance: f64,
    short: bool,
) -> PyResult<Vec<bool>> {
    let highs = highs.as_slice()?;
    let lows = lows.as_slice()?;
    let closes = closes.as_slice()?;
    let draws = draws.as_slice()?;
    let n = closes.len();

    // The coin-flip baseline: one position at a time, a draw on each bar that
    // is flat, exits the same as the walk. `draws` is one uniform per bar, so
    // this matches the Python version draw for draw.
    let mut entries = vec![false; n];
    let mut in_position = false;
    let mut entry_price = 0.0_f64;
    let mut entry_index = 0_i64;
    let mut drawn = 0_usize;

    for index in 1..n {
        if in_position {
            let (hit_tp, hit_sl) = if short {
                let target = entry_price * (1.0 - tp / 100.0);
                let stop = entry_price * (1.0 + sl / 100.0);
                (tp > 0.0 && lows[index] <= target, sl > 0.0 && highs[index] >= stop)
            } else {
                let target = entry_price * (1.0 + tp / 100.0);
                let stop = entry_price * (1.0 - sl / 100.0);
                (tp > 0.0 && highs[index] >= target, sl > 0.0 && lows[index] <= stop)
            };
            if hit_tp
                || hit_sl
                || (max_hold > 0 && (index as i64) - entry_index >= max_hold)
            {
                in_position = false;
            }
        } else {
            let draw = if drawn < draws.len() {
                let value = draws[drawn];
                drawn += 1;
                value
            } else {
                1.0
            };
            if draw < chance {
                entries[index] = true;
                in_position = true;
                entry_price = closes[index];
                entry_index = index as i64;
            }
        }
    }
    Ok(entries)
}

#[pymodule]
fn lalala_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk, m)?)?;
    m.add_function(wrap_pyfunction!(random_entries, m)?)?;
    m.add("__version__", "0.1.0")?;
    Ok(())
}
