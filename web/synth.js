// Synthetic data only: seeded so every reload shows the same thing.
export function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }

export function candles(n = 300, start = 76.3, seed = 7, stepMs = 60000, t0 = Date.UTC(2026, 10, 8, 16, 0)) {
  const r = rng(seed), out = []; let p = start;
  for (let i = 0; i < n; i++) {
    const o = p, drift = (r() - 0.5) * 0.12, c = o + drift;
    const h = Math.max(o, c) + r() * 0.05, l = Math.min(o, c) - r() * 0.05;
    out.push({ t: t0 + i * stepMs, o, h, l, c, v: 20 + r() * 80 * (r() > 0.97 ? 6 : 1) });
    p = c;
  }
  return out;
}

export function equity(n = 800, seed = 3) {
  const r = rng(seed); const s = [0], b = [0], rnd = [0];
  for (let i = 1; i < n; i++) {
    s.push(s[i - 1] + (r() - 0.48) * 0.12);
    b.push(b[i - 1] + (r() - 0.45) * 0.4);
    rnd.push(rnd[i - 1] + (r() - 0.52) * 0.1);
  }
  return { strategy: s, hold: b, random: rnd };
}

export function tape(seed = 11, n = 4) {
  const r = rng(seed);
  return Array.from({ length: n }, (_, i) => {
    const up = r() > 0.4;
    return { time: `21:00:${String(26 - i).padStart(2, "0")}`, side: up ? "UP" : "DOWN", px: up ? 82 : 19, size: +(1 + r() * 5).toFixed(2) };
  });
}

export const market = { title: "Bitcoin Up or Down - November 8, 4:00PM-4:05PM ET", up: 80.5, down: 19.5, btc: 75759.5, target: 75726.0, closesIn: "04:27", liquidity: "$11.4k", depth: "$6.3k", spread: "1¢" };
export const stats = { PnL: "-0.42%", Equity: "$9,958", Sharpe: "-0.00", Drawdown: "-2.65%", "Max DD": "-2.72%", "Max gain": "+2.29%", Streak: "L4", "Best W": "10", "Worst L": "19", Trades: "2,383", "Win rate": "44%", Fees: "$572" };

export const strategies = [
  { name: "Volume spike", tf: "1m", pnl: null, draft: true, note: "Buys when the close falls below the lower band on volume." },
  { name: "Edge vs model", tf: "5m", pnl: 3.01, note: "model_p above 0.60 against the market price." },
  { name: "Late favorite", tf: "5m", pnl: 3.35, note: "Backs the favorite in the last minute." },
  { name: "Bollinger reversion", tf: "1m", pnl: 0.57, note: "Buys when the close falls below the lower band (20 bars, 2σ)." },
];

export const palette = {
  Variables: ["band"],
  Data: ["close", "price", "open", "high", "low", "volume", "model_p", "spread", "liquidity", "days_left"],
  Indicators: ["SMA", "EMA", "RSI", "Highest", "Lowest", "Change", "Shift", "Boll low", "Boll mid", "Boll up", "σ", "zscore"],
  Maths: ["+", "−", "×", "÷", "%", "^", "(", ")", ",", "=", "<", "<=", ">", ">="],
};

export function logs(n = 40, seed = 5) {
  const r = rng(seed), src = ["Polymarket", "Hyperliquid", "Strategy", "System"], ev = ["ORDER", "FILL", "SIGNAL", "REJECT", "CONNECTION", "CLOSE"], lv = ["info", "info", "info", "warn", "error"];
  return Array.from({ length: n }, (_, i) => {
    const e = ev[Math.floor(r() * ev.length)], s = src[Math.floor(r() * src.length)], l = e === "REJECT" ? "error" : lv[Math.floor(r() * lv.length)];
    const sec = 3600 * 21 - i * 47;
    return { time: `${String(Math.floor(sec / 3600)).padStart(2, "0")}:${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`, level: l, source: s, origin: s === "Strategy" ? "Auto" : "Manual", event: e, message: `${e === "SIGNAL" ? "entry formula true" : e === "REJECT" ? "insufficient balance" : "UP 82¢ × " + (1 + Math.floor(r() * 9))}`, latency: Math.round(40 + r() * 260) };
  });
}

export const features = [
  ["Return 1", 100, true], ["Return 5", 71, true], ["Return 15", 44, true], ["Volatility σ(20)", 38, true], ["ATR(14)", 27, true],
  ["EMA 20/50 ratio", 19, true], ["z-score(20)", 12, true], ["Bollinger %B", 9, true], ["RSI(14)", 6, false], ["Volume z-score", 3, false],
];

export const layers = ["Dense", "Dropout", "BatchNorm", "Activation", "LSTM", "GRU", "Conv1D", "Attention"];
export const stack = [["LSTM", "64 units"], ["Dropout", "0.2"], ["Dense", "32 units · ReLU"], ["Output", "1 · sigmoid"]];

export function heat(seed = 9) { const r = rng(seed); return Array.from({ length: 5 }, (_, y) => Array.from({ length: 5 }, (_, x) => +((r() - 0.5) * 6 + (x - y) * 0.4).toFixed(1))); }
export function trades(n = 12, seed = 21) { const r = rng(seed); return Array.from({ length: n }, (_, i) => { const pnl = (r() - 0.45) * 3, ex = ["Take profit", "Stop loss", "Time"][Math.floor(r() * 3)]; return { n: i + 1, side: r() > 0.5 ? "Long" : "Short", entry: (76 + r()).toFixed(3), pnl: +pnl.toFixed(2), exit: ex }; }); }
export const histogram = Array.from({ length: 40 }, (_, i) => Math.round(2 + 30 * Math.exp(-((i - 18) ** 2) / 60) + (i === 0 ? 90 : 0) + (i === 39 ? 50 : 0)));
