const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function fit(cv) { const d = devicePixelRatio || 1, r = cv.getBoundingClientRect(); cv.width = r.width * d; cv.height = r.height * d; const g = cv.getContext("2d"); g.scale(d, d); return [g, r.width, r.height]; }

export function drawCandles(cv, data, { volume = true, bands = false, markers = [] } = {}) {
  const [g, W, H] = fit(cv), axis = 56, vh = volume ? H * 0.15 : 0, ph = H - vh - 18, pw = W - axis;
  const hi = Math.max(...data.map((d) => d.h)), lo = Math.min(...data.map((d) => d.l)), y = (v) => ph - ((v - lo) / (hi - lo)) * (ph - 8) - 4;
  const bw = pw / data.length, vmax = Math.max(...data.map((d) => d.v));
  g.font = "11px sans-serif"; g.fillStyle = css("--faint"); g.strokeStyle = css("--border");
  for (let i = 0; i < 3; i++) { const v = lo + ((hi - lo) * i) / 2; g.beginPath(); g.moveTo(0, y(v)); g.lineTo(pw, y(v)); g.stroke(); g.fillText(v.toFixed(3), pw + 6, y(v) + 4); }
  data.forEach((d, i) => {
    const x = i * bw + bw / 2, col = d.c >= d.o ? css("--up") : css("--down");
    g.strokeStyle = g.fillStyle = col; g.beginPath(); g.moveTo(x, y(d.h)); g.lineTo(x, y(d.l)); g.stroke();
    g.fillRect(x - bw * 0.35, Math.min(y(d.o), y(d.c)), bw * 0.7, Math.max(1, Math.abs(y(d.o) - y(d.c))));
    if (volume) { g.globalAlpha = 0.5; g.fillRect(x - bw * 0.35, H - 18 - (d.v / vmax) * vh, bw * 0.7, (d.v / vmax) * vh); g.globalAlpha = 1; }
  });
  if (bands) {
    const n = 20; g.strokeStyle = css("--band");
    [1, -1].forEach((sgn) => { g.beginPath(); data.forEach((_, i) => { if (i < n) return; const w = data.slice(i - n, i).map((d) => d.c), m = w.reduce((a, b) => a + b) / n, sd = Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / n); const px = i * bw + bw / 2, py = y(m + sgn * 2 * sd); i === n ? g.moveTo(px, py) : g.lineTo(px, py); }); g.stroke(); });
  }
  markers.forEach((m) => { const d = data[m.i]; if (!d) return; const x = m.i * bw + bw / 2, buy = m.side === 'buy'; g.fillStyle = buy ? css('--faint') : css('--accent'); g.beginPath(); const yy = buy ? y(d.l) + 8 : y(d.h) - 8; g.moveTo(x, yy + (buy ? -5 : 5)); g.lineTo(x - 4, yy + (buy ? 4 : -4)); g.lineTo(x + 4, yy + (buy ? 4 : -4)); g.fill(); });
  const last = data.at(-1); g.setLineDash([3, 3]); g.strokeStyle = css("--text"); g.beginPath(); g.moveTo(0, y(last.c)); g.lineTo(pw, y(last.c)); g.stroke(); g.setLineDash([]);
  g.fillStyle = css("--accent"); g.fillText(last.c.toFixed(3), pw + 6, y(last.c) + 4);
}

export function drawLines(cv, series) {
  const [g, W, H] = fit(cv), all = series.flatMap((s) => s.v), hi = Math.max(...all), lo = Math.min(...all);
  series.forEach((s) => { g.strokeStyle = css(s.color); g.lineWidth = 1.5; g.setLineDash(s.dash || []); g.beginPath(); s.v.forEach((v, i) => { const x = (i / (s.v.length - 1)) * W, yy = H - ((v - lo) / (hi - lo)) * (H - 8) - 4; i ? g.lineTo(x, yy) : g.moveTo(x, yy); }); g.stroke(); });
}

// Filled area under a single series (drawdown, loss curves).
export function drawArea(cv, v, color = "--down") {
  const [g, W, H] = fit(cv), hi = Math.max(...v), lo = Math.min(...v), span = hi - lo || 1;
  g.beginPath(); v.forEach((x, i) => { const px = (i / (v.length - 1)) * W, py = H - ((x - lo) / span) * (H - 6) - 3; i ? g.lineTo(px, py) : g.moveTo(px, py); });
  g.strokeStyle = css(color); g.lineWidth = 1.5; g.stroke(); g.lineTo(W, H); g.lineTo(0, H); g.closePath(); g.fillStyle = css(color); g.globalAlpha = 0.15; g.fill(); g.globalAlpha = 1;
}
