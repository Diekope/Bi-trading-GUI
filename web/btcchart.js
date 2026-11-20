// The Polymarket BTC line, animated like the Qt PriceChart: a rolling 15-minute axis that ends a
// fraction of a second behind live (so it scrolls continuously), a smoothed curve, an eased y-range,
// a tip that glides to each new price, and the window's target growing from the window start.
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
export const SPAN = 15 * 60e3, LAG = 300, REVEAL_MS = 900;
export const anim = { key: "", t0: 0, lo: null, hi: null, tip: null };

export const fmtPx = (v) => v.toLocaleString("en-US", { maximumFractionDigits: v > 1000 ? 0 : 2 });

// Pure helper (tested): where a timestamp lands on the plot, 0..1 across the rolling window.
export const xFrac = (t, wall) => (t - (wall - SPAN)) / SPAN;

export function paintBtc(cv, { points, target, startMs, endMs, key }, nowPerf = performance.now(), wall = Date.now() - LAG) {
  if (anim.key !== key) Object.assign(anim, { key, t0: nowPerf, lo: null, hi: null, tip: null });
  const r = cv.getBoundingClientRect(), d = devicePixelRatio || 1, w = Math.round(r.width * d), h = Math.round(r.height * d);
  if (!w || !h) return;
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const g = cv.getContext("2d"); g.setTransform(d, 0, 0, d, 0, 0); g.clearRect(0, 0, r.width, r.height);
  const W = r.width, H = r.height, L = 56, B = 18, pw = W - L - 8, ph = H - B, t0 = wall - SPAN;
  const vis = points.filter((p) => p.t >= t0 - 90e3 && p.t <= wall + 1000);
  if (vis.length < 2) return;
  const last = vis.at(-1).p;
  anim.tip = anim.tip == null ? last : anim.tip + (last - anim.tip) * 0.12;
  const inView = vis.filter((p) => p.t >= t0), vals = [...inView.map((p) => p.p), anim.tip, ...(target ? [target] : [])];
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo || 1) * 0.12; lo -= pad; hi += pad;
  anim.lo = anim.lo == null ? lo : anim.lo + (lo - anim.lo) * 0.08; anim.hi = anim.hi == null ? hi : anim.hi + (hi - anim.hi) * 0.08;
  const X = (t) => L + xFrac(t, wall) * pw, Y = (v) => ph - ((v - anim.lo) / (anim.hi - anim.lo)) * (ph - 8) - 4;
  g.font = `10px ${css("--mono")}`;
  // grid and time ticks (every 5 min, UTC)
  g.lineWidth = 1;
  [0, 0.5, 1].forEach((f) => { const v = anim.lo + (anim.hi - anim.lo) * f, y = Y(v); g.strokeStyle = css("--border"); g.beginPath(); g.moveTo(L, y); g.lineTo(L + pw, y); g.stroke(); g.fillStyle = css("--muted"); g.fillText(fmtPx(v), 2, Math.min(H - B - 2, Math.max(10, y + 3))); });
  for (let t = Math.ceil(t0 / 300e3) * 300e3; t <= wall; t += 300e3) { const x = X(t); g.strokeStyle = css("--border"); g.globalAlpha = 0.5; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, ph); g.stroke(); g.globalAlpha = 1; g.fillStyle = css("--faint"); g.fillText(new Date(t).toISOString().slice(11, 16), x - 14, H - 4); }
  // reveal sweep on entry, then the live scroll
  const reveal = Math.min(1, (nowPerf - anim.t0) / REVEAL_MS), e = 1 - (1 - reveal) ** 3;
  g.save(); if (reveal < 1) { g.beginPath(); g.rect(0, 0, L + pw * e + 1, H); g.clip(); }
  // current window band
  if (startMs && X(startMs) < L + pw) { const x0 = Math.max(L, X(startMs)); g.fillStyle = css("--accent"); g.globalAlpha = 0.04; g.fillRect(x0, 0, Math.min(L + pw, X(Math.min(endMs || wall, wall + 1))) - x0, ph); g.globalAlpha = 1; g.strokeStyle = css("--accent"); g.globalAlpha = 0.35; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(x0, 0); g.lineTo(x0, ph); g.stroke(); g.setLineDash([]); g.globalAlpha = 1; }
  // target segment grows from the window start
  const above = !target || anim.tip >= target, col = css(above ? "--up" : "--down");
  if (target && startMs) { const x0 = Math.max(L, X(startMs)), y = Y(target); g.strokeStyle = css("--accent"); g.setLineDash([4, 3]); g.beginPath(); g.moveTo(x0, y); g.lineTo(X(wall), y); g.stroke(); g.setLineDash([]); g.fillStyle = css("--accent"); const lbl = `open ${target.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`; g.fillText(lbl, L + pw - g.measureText(lbl).width - 2, y - 4); }
  // smoothed curve through the samples, ending at the eased tip
  const pts = [...vis.map((p) => [X(p.t), Y(p.p)]), [X(wall), Y(anim.tip)]];
  const path = () => { g.beginPath(); g.moveTo(pts[0][0], pts[0][1]); for (let i = 1; i < pts.length - 1; i++) { const mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2; g.quadraticCurveTo(pts[i][0], pts[i][1], mx, my); } g.lineTo(pts.at(-1)[0], pts.at(-1)[1]); };
  g.save(); g.beginPath(); g.rect(L, 0, pw + 8, ph); g.clip();
  path(); g.lineTo(pts.at(-1)[0], ph); g.lineTo(pts[0][0], ph); g.closePath(); const gr = g.createLinearGradient(0, 0, 0, ph); gr.addColorStop(0, col); gr.addColorStop(1, "transparent"); g.fillStyle = gr; g.globalAlpha = 0.22; g.fill(); g.globalAlpha = 1;
  path(); g.strokeStyle = col; g.lineWidth = 1.8; g.lineJoin = "round"; g.stroke();
  g.restore();
  // pulsing head
  const hx = X(wall), hy = Y(anim.tip), pulse = (Math.sin(nowPerf / 280) + 1) / 2;
  g.fillStyle = col; g.globalAlpha = 0.28 * (1 - pulse * 0.6); g.beginPath(); g.arc(hx, hy, 4 + pulse * 5, 0, 7); g.fill(); g.globalAlpha = 1; g.beginPath(); g.arc(hx, hy, 3, 0, 7); g.fill();
  g.restore();
}
