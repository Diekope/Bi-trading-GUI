//! A native core for the backtest walk.
//!
//! The Python walk (`bi_trading.engine.core._python_walk`) is the reference; this
//! mirrors it exactly — one position at a time, long or short, take profit and
//! stop loss read off a candle's range (the stop wins when one candle holds
//! both), an optional trailing take profit, an optional exit rule, a fee each
//! way, a hold limit — but runs the bar loop in Rust, so a long span is walked
//! without the Python-level cost.
//!
//! An exit rule arrives as a small program (see `bi_trading.engine.core.compile_exit`)
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
    participation: f64,
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

/// What a walk carries from one bar to the next.
#[derive(Clone)]
struct State {
    cash: f64,
    qty: f64,
    short: bool,
    entry_price: f64,
    entry_index: usize,
    entry_cost: f64,
    entry_fee: f64,
    entry_notional: f64,
    best: f64,
}

impl State {
    fn fresh(capital: f64) -> State {
        State {
            cash: capital, qty: 0.0, short: false, entry_price: 0.0, entry_index: 0,
            entry_cost: 0.0, entry_fee: 0.0, entry_notional: 0.0, best: 0.0,
        }
    }
}

/// The state as Python holds it between chunks:
/// (cash, qty, short, entry price, entry index, entry cost, entry fee,
/// entry notional, best).
type PyState = (f64, f64, bool, f64, usize, f64, f64, f64, f64);

impl From<PyState> for State {
    fn from(t: PyState) -> State {
        State {
            cash: t.0, qty: t.1, short: t.2, entry_price: t.3, entry_index: t.4,
            entry_cost: t.5, entry_fee: t.6, entry_notional: t.7, best: t.8,
        }
    }
}

impl From<State> for PyState {
    fn from(t: State) -> PyState {
        (
            t.cash, t.qty, t.short, t.entry_price, t.entry_index, t.entry_cost,
            t.entry_fee, t.entry_notional, t.best,
        )
    }
}

/// The bar loop. `offset` is the index of the first bar in the whole span, so
/// trades carry whole-span indices when the span is walked in chunks.
#[allow(clippy::too_many_arguments)]
fn run_walk(
    closes: &[f64],
    highs: &[f64],
    lows: &[f64],
    longs: &[bool],
    shorts: &[bool],
    capital: f64,
    s: &Settings,
    rule: Option<&[(i64, f64)]>,
    slots: usize,
    offset: usize,
    state: Option<State>,
    gaps: Option<&[bool]>,
    volumes: Option<&[f64]>,
) -> (Vec<Trade>, Vec<f64>, State) {
    let n = closes.len();

    let mut trades: Vec<Trade> = Vec::new();
    let mut equity_curve: Vec<f64> = Vec::with_capacity(n);

    let mut vars = vec![0.0_f64; slots.max(6)];
    let mut stack: Vec<f64> = Vec::with_capacity(16);

    // The book as the walk leaves it, so a long span can be walked in chunks:
    // each chunk starts from the state the one before it ended in.
    let State {
        mut cash,
        mut qty,
        mut short,
        mut entry_price,
        mut entry_index,
        mut entry_cost,
        mut entry_fee,
        mut entry_notional,
        mut best,
    } = state.unwrap_or(State::fresh(capital));

    for local in 0..n {
        let index = offset + local;
        let close = closes[local];
        let high = highs[local];
        let low = lows[local];
        // True when the next bar is not the next minute-step: a hole in the data.
        let gap_after = gaps.map_or(false, |g| g[local]);

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
            } else if let Some(program) = rule {
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
            // The data stops after this bar: the position cannot be held
            // through a hole, so it is closed at the last known close.
            if price.is_none() && gap_after {
                price = Some(close);
                reason = "gap";
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
        } else if index != 0 && !gap_after && (longs[local] != shorts[local]) {
            let mut notional = budget(cash, s);
            // Take no more than a share of what the bar traded: a position the
            // market could not have absorbed is not a fill.
            if s.participation > 0.0 {
                if let Some(v) = volumes {
                    notional = notional.min(v[local] * close * s.participation);
                }
            }
            if notional > 0.0 && close > 0.0 {
                let cost = notional * s.fee;
                short = shorts[local];
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

        // Marked to market: an open long is worth qty at the close, an open
        // short its margin plus what the price has fallen (never below 0).
        let held = if qty > 0.0 {
            if short {
                (qty * (2.0 * entry_price - close)).max(0.0)
            } else {
                qty * close
            }
        } else {
            0.0
        };
        equity_curve.push(cash + held);
    }
    (trades, equity_curve, State {
        cash, qty, short, entry_price, entry_index, entry_cost, entry_fee,
        entry_notional, best,
    })
}

/// Walk `closes` (with `highs`/`lows` for the exits), opening a long where
/// `longs` is true and a short where `shorts` is. A bar that is both is left
/// alone. Returns the trades and the marked-to-market equity per bar.
///
/// The columns arrive as NumPy arrays, so a long span is not copied into a
/// Python list first.
#[pyfunction]
#[pyo3(signature = (closes, highs, lows, longs, shorts, capital, tp, sl, position,
                    sizing, max_cash, fee, max_hold, dynamic_tp=false, reverse=0.0,
                    rule=None, slots=0, slippage=0.0, gaps=None, volumes=None, participation=0.0))]
#[allow(clippy::too_many_arguments)]
fn walk(
    py: Python<'_>,
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
    gaps: Option<PyReadonlyArray1<bool>>,
    volumes: Option<PyReadonlyArray1<f64>>,
    participation: f64,
) -> PyResult<(Vec<Trade>, Vec<f64>)> {
    let (trades, equity, _) = walk_chunk(
        py, closes, highs, lows, longs, shorts, capital, tp, sl, position, sizing,
        max_cash, fee, max_hold, dynamic_tp, reverse, rule, slots, slippage, 0, None, gaps,
        volumes, participation,
    )?;
    Ok((trades, equity))
}

/// `walk` for one chunk of a longer span. `offset` is the chunk's first bar in
/// the whole span and `state` what the chunk before ended in (None to begin);
/// it returns the state to hand to the next. A trade can open in one chunk and
/// close in a later one, and trades carry whole-span indices.
#[pyfunction]
#[pyo3(signature = (closes, highs, lows, longs, shorts, capital, tp, sl, position,
                    sizing, max_cash, fee, max_hold, dynamic_tp=false, reverse=0.0,
                    rule=None, slots=0, slippage=0.0, offset=0, state=None, gaps=None,
                    volumes=None, participation=0.0))]
#[allow(clippy::too_many_arguments)]
fn walk_chunk(
    py: Python<'_>,
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
    offset: usize,
    state: Option<PyState>,
    gaps: Option<PyReadonlyArray1<bool>>,
    volumes: Option<PyReadonlyArray1<f64>>,
    participation: f64,
) -> PyResult<(Vec<Trade>, Vec<f64>, PyState)> {
    let closes = closes.as_slice()?;
    let highs = highs.as_slice()?;
    let lows = lows.as_slice()?;
    let longs = longs.as_slice()?;
    let shorts = shorts.as_slice()?;
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
        participation,
    };
    let state = state.map(State::from);
    let gaps = match &gaps {
        Some(g) => Some(g.as_slice()?),
        None => None,
    };
    let volumes = match &volumes {
        Some(v) => Some(v.as_slice()?),
        None => None,
    };
    // The bar loop touches no Python object, so let go of the GIL: a worker
    // thread can walk a long span while the window keeps painting.
    let (trades, equity, end) = py.allow_threads(|| {
        run_walk(
            closes, highs, lows, longs, shorts, capital, &s, rule.as_deref(), slots,
            offset, state, gaps, volumes,
        )
    });
    Ok((trades, equity, end.into()))
}

/// Where the coin-flip baseline stands between chunks: in a position, its entry
/// price and index, and how many draws the last piece used.
type RandomState = (bool, f64, i64, usize);

#[pyfunction]
#[pyo3(signature = (highs, lows, closes, draws, tp, sl, max_hold, chance, short=false, gaps=None))]
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
    gaps: Option<PyReadonlyArray1<bool>>,
) -> PyResult<Vec<bool>> {
    let gaps = match &gaps {
        Some(g) => Some(g.as_slice()?),
        None => None,
    };
    let (entries, _) = run_random(
        highs.as_slice()?,
        lows.as_slice()?,
        closes.as_slice()?,
        draws.as_slice()?,
        tp, sl, max_hold, chance, short, 0, (false, 0.0, 0, 0), gaps,
    );
    Ok(entries)
}

/// `random_entries` for one piece of a longer span: `offset` is its first bar's
/// index in the whole span and `state` what the piece before it ended in
/// (`None` to begin). `draws` holds the next uniforms in the stream, at least
/// as many as the piece has bars. Returns the entries and the state to go on from.
#[pyfunction]
#[pyo3(signature = (highs, lows, closes, draws, tp, sl, max_hold, chance, short=false, offset=0, state=None, gaps=None))]
#[allow(clippy::too_many_arguments)]
fn random_entries_chunk(
    highs: PyReadonlyArray1<f64>,
    lows: PyReadonlyArray1<f64>,
    closes: PyReadonlyArray1<f64>,
    draws: PyReadonlyArray1<f64>,
    tp: f64,
    sl: f64,
    max_hold: i64,
    chance: f64,
    short: bool,
    offset: i64,
    state: Option<RandomState>,
    gaps: Option<PyReadonlyArray1<bool>>,
) -> PyResult<(Vec<bool>, RandomState)> {
    let gaps = match &gaps {
        Some(g) => Some(g.as_slice()?),
        None => None,
    };
    Ok(run_random(
        highs.as_slice()?,
        lows.as_slice()?,
        closes.as_slice()?,
        draws.as_slice()?,
        tp, sl, max_hold, chance, short, offset,
        state.unwrap_or((false, 0.0, 0, 0)), gaps,
    ))
}

#[allow(clippy::too_many_arguments)]
fn run_random(
    highs: &[f64],
    lows: &[f64],
    closes: &[f64],
    draws: &[f64],
    tp: f64,
    sl: f64,
    max_hold: i64,
    chance: f64,
    short: bool,
    offset: i64,
    state: RandomState,
    gaps: Option<&[bool]>,
) -> (Vec<bool>, RandomState) {
    let n = closes.len();
    // `drawn` counts this piece's own draws; the caller adds them up.
    let (mut in_position, mut entry_price, mut entry_index) = (state.0, state.1, state.2);
    let mut drawn = 0_usize;

    // The coin-flip baseline: one position at a time, a draw on each bar that
    // is flat, exits the same as the walk. `draws` is one uniform per bar, so
    // this matches the Python version draw for draw.
    let mut entries = vec![false; n];
    for local in 0..n {
        let global = offset + local as i64;
        if global == 0 {
            continue;
        }
        let gap_after = gaps.map_or(false, |g| g[local]);
        if in_position {
            let (hit_tp, hit_sl) = if short {
                let target = entry_price * (1.0 - tp / 100.0);
                let stop = entry_price * (1.0 + sl / 100.0);
                (tp > 0.0 && lows[local] <= target, sl > 0.0 && highs[local] >= stop)
            } else {
                let target = entry_price * (1.0 + tp / 100.0);
                let stop = entry_price * (1.0 - sl / 100.0);
                (tp > 0.0 && highs[local] >= target, sl > 0.0 && lows[local] <= stop)
            };
            if hit_tp || hit_sl || gap_after || (max_hold > 0 && global - entry_index >= max_hold) {
                in_position = false;
            }
        } else if gap_after {
            // The walk will not open on the last bar before a hole.
        } else {
            let draw = if drawn < draws.len() {
                let value = draws[drawn];
                drawn += 1;
                value
            } else {
                1.0
            };
            if draw < chance {
                entries[local] = true;
                in_position = true;
                entry_price = closes[local];
                entry_index = global;
            }
        }
    }
    (entries, (in_position, entry_price, entry_index, drawn))
}

#[pymodule]
fn bi_trading_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk, m)?)?;
    m.add_function(wrap_pyfunction!(walk_chunk, m)?)?;
    m.add_function(wrap_pyfunction!(random_entries, m)?)?;
    m.add_function(wrap_pyfunction!(random_entries_chunk, m)?)?;
    m.add("__version__", "0.1.0")?;
    Ok(())
}
