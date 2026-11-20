const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const mono = () => `10px ${css("--mono")}`;
function fit(cv) { const d = devicePixelRatio || 1, r = cv.getBoundingClientRect(); cv.width = r.width * d; cv.height = r.height * d; const g = cv.getContext("2d"); g.scale(d, d); return [g, r.width, r.height]; }

export function drawCandles(cv, data, { volume = true, bands = false, markers = [], axis = 64 } = {}) {
  const [g, W, H] = fit(cv), vh = volume ? H * 0.16 : 0, ph = H - vh - 20, pw = W - axis;
  const hi = Math.max(...data.map((d) => d.h)), lo = Math.min(...data.map((d) => d.l)), y = (v) => ph - ((v - lo) / (hi - lo)) * (ph - 12) - 6;
  const bw = pw / data.length, vmax = Math.max(...data.map((d) => d.v));
  g.font = mono(); g.lineWidth = 1;
  [lo, (lo + hi) / 2, hi].forEach((v) => { g.strokeStyle = css("--border"); g.beginPath(); g.moveTo(0, y(v)); g.lineTo(pw, y(v)); g.stroke(); g.fillStyle = css("--muted"); g.fillText(v.toFixed(hi > 1000 ? 1 : hi > 100 ? 2 : 3), pw + 8, y(v) + 4); });
  data.forEach((d, i) => {
    const x = i * bw + bw / 2, col = d.c >= d.o ? css("--up") : css("--down");
    g.strokeStyle = g.fillStyle = col; g.beginPath(); g.moveTo(x, y(d.h)); g.lineTo(x, y(d.l)); g.stroke();
    g.fillRect(x - bw * 0.36, Math.min(y(d.o), y(d.c)), bw * 0.72, Math.max(1, Math.abs(y(d.o) - y(d.c))));
    if (volume) { g.globalAlpha = 0.55; g.fillRect(x - bw * 0.36, H - 20 - (d.v / vmax) * vh, bw * 0.72, (d.v / vmax) * vh); g.globalAlpha = 1; }
  });
  if (bands) { const n = 20; g.strokeStyle = css("--band"); [1, -1].forEach((s) => { g.beginPath(); data.forEach((_, i) => { if (i < n) return; const w = data.slice(i - n, i).map((d) => d.c), m = w.reduce((a, b) => a + b) / n, sd = Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / n); const px = i * bw + bw / 2, py = y(m + s * 2 * sd); i === n ? g.moveTo(px, py) : g.lineTo(px, py); }); g.stroke(); }); }
  markers.forEach((m) => { const d = data[m.i]; if (!d) return; const x = m.i * bw + bw / 2, buy = m.side === "buy", yy = buy ? y(d.l) + 10 : y(d.h) - 10; g.fillStyle = buy ? css("--muted") : css("--accent"); g.beginPath(); g.moveTo(x, yy + (buy ? -5 : 5)); g.lineTo(x - 4, yy + (buy ? 4 : -4)); g.lineTo(x + 4, yy + (buy ? 4 : -4)); g.fill(); });
  const last = data.at(-1); g.setLineDash([3, 3]); g.strokeStyle = css("--text"); g.beginPath(); g.moveTo(0, y(last.c)); g.lineTo(pw, y(last.c)); g.stroke(); g.setLineDash([]);
  g.fillStyle = css("--accent"); g.fillText(last.c.toFixed(hi > 1000 ? 1 : hi > 100 ? 2 : 3), pw + 8, y(last.c) + 4);
  g.fillStyle = css("--muted"); [0.15, 0.5, 0.85].forEach((f) => { const d = new Date(data[Math.floor(f * (data.length - 1))].t); g.fillText(d.toISOString().slice(11, 16), f * pw - 12, H - 4); });
}

// series: [{v, color, dash, fill}]. grid: show 3 guide lines labelled with fmt.
export function drawLines(cv, series, { grid = false, fmt = (v) => v.toFixed(2), pad = 0, lo: LO, hi: HI } = {}) {
  const [g, W, H] = fit(cv), all = series.flatMap((s) => s.v), hi = HI ?? Math.max(...all), lo = LO ?? Math.min(...all), L = grid ? 44 : 0, w = W - L - pad;
  const Y = (v) => H - ((v - lo) / (hi - lo || 1)) * (H - 10) - 5;
  g.font = mono();
  if (grid) [lo, (lo + hi) / 2, hi].forEach((v) => { g.strokeStyle = css("--border"); g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(W, Y(v)); g.stroke(); g.fillStyle = css("--muted"); g.fillText(fmt(v), 0, Y(v) < 12 ? Y(v) + 11 : Y(v) - 3); });
  series.forEach((s) => {
    g.beginPath(); s.v.forEach((v, i) => { const x = L + (i / (s.v.length - 1)) * w; i ? g.lineTo(x, Y(v)) : g.moveTo(x, Y(v)); });
    g.strokeStyle = css(s.color); g.lineWidth = 1.5; g.setLineDash(s.dash || []); g.stroke(); g.setLineDash([]);
    if (s.fill) { g.lineTo(L + w, H); g.lineTo(L, H); g.closePath(); g.fillStyle = css(s.color); g.globalAlpha = 0.14; g.fill(); g.globalAlpha = 1; }
  });
}
export const drawArea = (cv, v, color = "--down") => drawLines(cv, [{ v, color, fill: true }], { grid: false });
