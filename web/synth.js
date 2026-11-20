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
