//! A native core for the backtest walk.
//!
//! The Python walk (`strat_playback.Playback`) is the reference; this mirrors
//! it exactly — one position at a time, long or short, take profit and stop loss read off a
//! candle's range, a fee each way, a hold limit — but runs the bar loop in
//! Rust, so a long span is walked without the Python-level cost.

use numpy::PyReadonlyArray1;
use pyo3::prelude::*;

/// One closed trade:
/// (entry index, entry price, exit index, exit price, result, fees, notional, reason).
type Trade = (usize, f64, usize, f64, f64, f64, f64, &'static str);

struct Settings {
    tp: f64,
    sl: f64,
    position: f64,
    fixed: bool,
    risk: bool,
    short: bool,
    max_cash: f64,
    fee: f64,
    max_hold: i64,
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

/// Walk `closes` (with `highs`/`lows` for the exits), opening where `entries`
/// is true. Returns the trades and the realised equity per bar.
///
/// The columns arrive as NumPy arrays, so a long span is not copied into a
/// Python list first.
#[pyfunction]
#[pyo3(signature = (closes, highs, lows, entries, capital, tp, sl, position,
                    sizing, max_cash, fee, max_hold, short=false))]
#[allow(clippy::too_many_arguments)]
fn walk(
    closes: PyReadonlyArray1<f64>,
    highs: PyReadonlyArray1<f64>,
    lows: PyReadonlyArray1<f64>,
    entries: PyReadonlyArray1<bool>,
    capital: f64,
    tp: f64,
    sl: f64,
    position: f64,
    sizing: &str,
    max_cash: f64,
    fee: f64,
    max_hold: i64,
    short: bool,
) -> PyResult<(Vec<Trade>, Vec<f64>)> {
    let closes = closes.as_slice()?;
    let highs = highs.as_slice()?;
    let lows = lows.as_slice()?;
    let entries = entries.as_slice()?;
    let n = closes.len();
    let s = Settings {
        tp,
        sl,
        position,
        fixed: sizing == "fixed",
        risk: sizing == "risk",
        short,
        max_cash,
        fee,
        max_hold,
    };

    let mut trades: Vec<Trade> = Vec::new();
    let mut equity_curve: Vec<f64> = Vec::with_capacity(n);

    let mut cash = capital;
    let mut qty = 0.0_f64;
    let mut entry_price = 0.0_f64;
    let mut entry_index = 0_usize;
    let mut entry_cost = 0.0_f64;
    let mut entry_fee = 0.0_f64;
    let mut entry_notional = 0.0_f64;

    for index in 0..n {
        let close = closes[index];
        let high = highs[index];
        let low = lows[index];

        if qty > 0.0 {
            let (target, stop, hit_tp, hit_sl) = if s.short {
                let target = entry_price * (1.0 - s.tp / 100.0);
                let stop = entry_price * (1.0 + s.sl / 100.0);
                (target, stop, s.tp > 0.0 && low <= target, s.sl > 0.0 && high >= stop)
            } else {
                let target = entry_price * (1.0 + s.tp / 100.0);
                let stop = entry_price * (1.0 - s.sl / 100.0);
                (target, stop, s.tp > 0.0 && high >= target, s.sl > 0.0 && low <= stop)
            };
            let mut price: Option<f64> = None;
            let mut reason = "time";
            if hit_tp {
                price = Some(target);
                reason = "tp";
            } else if hit_sl {
                price = Some(stop);
                reason = "sl";
            } else if (index as i64) - (entry_index as i64) >= s.max_hold {
                price = Some(close);
                reason = "time";
            }
            if let Some(price) = price {
                // A long is worth qty * price; a short is its margin back plus
                // what the price fell, never less than nothing.
                let value = if s.short {
                    (qty * (2.0 * entry_price - price)).max(0.0)
                } else {
                    qty * price
                };
                let cost = qty * price * s.fee;
                cash += value - cost;
                let invested = entry_cost;
                let result = if invested > 0.0 {
                    (value - cost) / invested - 1.0
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
                ));
                qty = 0.0;
                entry_cost = 0.0;
            }
        } else if index != 0 && entries[index] {
            let notional = budget(cash, &s);
            if notional > 0.0 && close > 0.0 {
                let cost = notional * s.fee;
                qty = notional / close;
                cash -= notional + cost;
                entry_price = close;
                entry_index = index;
                entry_fee = cost;
                entry_notional = notional;
                entry_cost = notional + cost;
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
                || ((index as i64) - entry_index >= max_hold)
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
