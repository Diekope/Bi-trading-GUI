//! A native core for the backtest walk.
//!
//! The Python walk (`strat_playback.Playback`) is the reference; this mirrors
//! it exactly — one position at a time, take profit and stop loss read off a
//! candle's range, a fee each way, a hold limit — but runs the bar loop in
//! Rust, so a long span is walked without the Python-level cost.

use pyo3::prelude::*;

/// One closed trade: (entry index, entry price, exit index, exit price, result).
type Trade = (usize, f64, usize, f64, f64);

struct Settings {
    tp: f64,
    sl: f64,
    position: f64,
    fixed: bool,
    max_cash: f64,
    fee: f64,
    max_hold: i64,
}

fn budget(cash: f64, s: &Settings) -> f64 {
    let deployable = cash.min(s.max_cash);
    if s.fixed {
        s.position.clamp(0.0, deployable)
    } else {
        deployable * s.position.max(0.0) / 100.0
    }
}

/// Walk `closes` (with `highs`/`lows` for the exits), opening where `entries`
/// is true. Returns the trades and the realised equity per bar.
#[pyfunction]
#[pyo3(signature = (closes, highs, lows, entries, capital, tp, sl, position,
                    sizing, max_cash, fee, max_hold))]
#[allow(clippy::too_many_arguments)]
fn walk(
    closes: Vec<f64>,
    highs: Vec<f64>,
    lows: Vec<f64>,
    entries: Vec<bool>,
    capital: f64,
    tp: f64,
    sl: f64,
    position: f64,
    sizing: &str,
    max_cash: f64,
    fee: f64,
    max_hold: i64,
) -> PyResult<(Vec<Trade>, Vec<f64>)> {
    let n = closes.len();
    let s = Settings {
        tp,
        sl,
        position,
        fixed: sizing == "fixed",
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

    for index in 0..n {
        let close = closes[index];
        let high = highs[index];
        let low = lows[index];

        if qty > 0.0 {
            let target = entry_price * (1.0 + s.tp / 100.0);
            let stop = entry_price * (1.0 - s.sl / 100.0);
            let mut price: Option<f64> = None;
            if s.tp > 0.0 && high >= target {
                price = Some(target);
            } else if s.sl > 0.0 && low <= stop {
                price = Some(stop);
            } else if (index as i64) - (entry_index as i64) >= s.max_hold {
                price = Some(close);
            }
            if let Some(price) = price {
                let proceeds = qty * price;
                let cost = proceeds * s.fee;
                cash += proceeds - cost;
                let invested = entry_cost;
                let result = if invested > 0.0 {
                    (proceeds - cost) / invested - 1.0
                } else {
                    0.0
                };
                trades.push((entry_index, entry_price, index, price, result));
                qty = 0.0;
                entry_cost = 0.0;
            }
        } else if index != 0 && entries.get(index).copied().unwrap_or(false) {
            let notional = budget(cash, &s);
            if notional > 0.0 && close > 0.0 {
                let cost = notional * s.fee;
                qty = notional / close;
                cash -= notional + cost;
                entry_price = close;
                entry_index = index;
                entry_cost = notional + cost;
            }
        }

        // Realised book: an open position is carried at what it cost.
        equity_curve.push(cash + qty * entry_price);
    }

    Ok((trades, equity_curve))
}

#[pymodule]
fn lalala_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk, m)?)?;
    m.add("__version__", "0.1.0")?;
    Ok(())
}
