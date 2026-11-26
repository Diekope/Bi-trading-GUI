import { views, state, draw, normalize, latency, balances, paintAll, engAct, setSField, setRerender, setAutoRun, pan } from "./views.js";
import { boot } from "./engine.js";
import { formulaClick, formulaInput, rulesClick, rulesInput, installDnD } from "./builder.js";
import { feed, onChange, startHL, startPM, logEvent, detectProxy, endpoints, health } from "./feeds.js";
import { P, placePM, placeHL, closePosition, resetPaper, tick as paperTick } from "./paper.js";
const I = (d) => `<svg viewBox="0 0 24 24">${d}</svg>`;
const rail = [
  ["home", "Home", I('<path d="M3 11l9-8 9 8M5 10v10h14V10"/>')],
  ["portfolio", "Portfolio", I('<path d="M3 7h18v13H3zM3 7l3-4h12l3 4M16 13h2"/>')],
  ["live", "Live", I('<path d="M3 12h4l3-8 4 16 3-8h4"/>')],
  ["builder", "Strategy builder", I('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>')],
  ["backtest", "Backtest", I('<path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2"/>')],
  ["ml", "ML", I('<circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="12" cy="12" r="2"/><path d="M7 12h3M14 12l3-6M14 12l3 6"/>')],
];
const tail = [
  ["logs", "Logs", I('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>')],
  ["settings", "Settings", I('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>')],
];
const venueOnly = new Set(["builder", "backtest", "ml", "model"]); // strategy work exists per venue, not in "general"
const shown = (k) => state.venue !== "Both" || !venueOnly.has(k);
const keys = () => ["home", "portfolio", "live", "builder", "backtest", "ml", "logs", "settings"].filter(shown);
const titles = { home: "Home", portfolio: "Portfolio", live: "Live", builder: "Strategy builder", backtest: "Backtest engine", ml: "ML strategy builder", model: "Model builder", logs: "Logs", settings: "Settings" };
const ADDR_KEY = "bi-trading-sandbox-hl-address", PM_ADDR_KEY = "bi-trading-sandbox-pm-address";
const liveViews = new Set(["home", "portfolio", "live", "logs"]);
const $ = (s) => document.querySelector(s);
const link = ([k, t, i], key) => `<a href="#${k}" title="${t}" class="${k === key || (k === "ml" && key === "model") ? "on" : ""}">${i}</a>`;
const vs = [["Polymarket", "pm", "pm"], ["Hyperliquid", "hl", "hl"], ["Both", "", "⇄"]];
const curKey = () => { const k = location.hash.slice(1) || "home"; return views[k] ? k : "home"; };

function chrome(key) {
  const v = views[key], L = latency(), cls = (ms) => L.cls(ms), fmt = (ms) => (ms == null ? "—" : ms + "ms");
  document.body.classList.toggle("hub", !!v.hub);
  document.body.classList.toggle("live-mode", !!state.live);
  document.body.dataset.venue = state.venue;
  morph($("#rail"), `<div class="vsw">${vs.map(([n, c, t]) => { const ms = t === "pm" ? L.pm : t === "hl" ? L.hl : null; return `<a class="${c} ${state.venue === n ? "on" : ""}" data-set="venue=${n}" title="${n === "Both" ? "Both venues" : `${n} · ${fmt(ms)} delay`}">${t === "pm" || t === "hl" ? `<i class="vlogo ${t}"></i><span class="vlat ${cls(ms)}">${fmt(ms)}</span>` : t}</a>`; }).join("")}</div><hr>${rail.filter((r) => shown(r[0])).map((r) => link(r, key)).join("")}<span class="sp"></span>${tail.map((r) => link(r, key)).join("")}<hr><a class="pw" title="Quit"><svg viewBox="0 0 24 24"><path d="M12 3v9M6.5 6.5a8 8 0 1 0 11 0"/></svg></a>`);
  const extra = v.topExtra ? v.topExtra() : "";
  morph($("#topbar"), `<b style="font-size:12px">${titles[key]}</b><span class="vtag ${state.venue === "Polymarket" ? "pm" : state.venue === "Hyperliquid" ? "hl" : ""}">${state.venue === "Both" ? "PM + HL" : state.venue}</span><span style="flex:1"></span>${extra}${feedChips()}${balChips()}<span class="modesw"><button class="paper ${state.live ? "" : "on"}" data-set="live=0">PAPER</button><button class="live ${state.live ? "on" : ""}" data-set="live=1">LIVE</button></span>`);
}
const usd = (n) => `<span class="${n >= 0 ? "up" : "down"}">${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}</span>`;
const money = (n) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
function balChips() {
  const b = balances();
  return `<a class="bal" href="#portfolio" title="Paper account, marked to the live books"><span class="mode paper">PAPER</span> <b>${money(b.paper)}</b> ${usd(b.paperPnl)} <span class="${b.paperPct >= 0 ? "up" : "down"}">${b.paperPct >= 0 ? "+" : ""}${b.paperPct.toFixed(2)}%</span></a><a class="bal" href="#portfolio" title="Live balance: Hyperliquid account value, read-only. Add an address in Settings."><span class="mode live">LIVE</span> <b>${b.live != null ? money(b.live) : "—"}</b>${b.liveNote === "error" ? ` <span class="down">!</span>` : ""}</a>`;
}
// Patch the DOM in place instead of replacing it: hover, focus, scroll and canvases survive a live repaint
// (replacing every node each 400 ms is what made the UP/DOWN tiles blink under the pointer).
function syncAttrs(o, n) {
  const keep = o.tagName === "CANVAS" ? new Set(["width", "height"]) : null; // the painter owns the bitmap size
  for (const at of [...o.attributes]) if (!n.hasAttribute(at.name) && !keep?.has(at.name)) o.removeAttribute(at.name);
  for (const at of n.attributes) if (!keep?.has(at.name) && o.getAttribute(at.name) !== at.value) o.setAttribute(at.name, at.value);
}
function patch(o, n) {
  if (o.nodeType === 3) { if (o.nodeValue !== n.nodeValue) o.nodeValue = n.nodeValue; return; }
  syncAttrs(o, n);
  if (o.tagName === "CANVAS") return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(o.tagName)) {
    if (o === document.activeElement) return;
    if (o.type === "checkbox" || o.type === "radio") o.checked = n.checked;
    else if (o.tagName === "TEXTAREA") { if (o.value !== n.value) o.value = n.value; }
    else if (o.tagName === "SELECT") { o.innerHTML = n.innerHTML; o.selectedIndex = n.selectedIndex; } // the options change with the venue
    else o.value = n.getAttribute("value") ?? "";
    return;
  }
  const oc = [...o.childNodes], nc = [...n.childNodes], same = (x, y) => x.nodeType === y.nodeType && (x.nodeType === 3 || x.tagName === y.tagName);
  nc.forEach((c, i) => { if (!oc[i]) o.appendChild(c); else if (same(oc[i], c)) patch(oc[i], c); else o.replaceChild(c, oc[i]); });
  for (let i = oc.length - 1; i >= nc.length; i--) o.removeChild(oc[i]);
}
function morph(el, html, full) {
  if (full) { el.innerHTML = html; return; }
  const t = document.createElement(el.tagName); t.innerHTML = html;
  const oc = [...el.childNodes], nc = [...t.childNodes];
  nc.forEach((c, i) => { if (!oc[i]) el.appendChild(c); else if (oc[i].nodeType === c.nodeType && (c.nodeType === 3 || oc[i].tagName === c.tagName)) patch(oc[i], c); else el.replaceChild(c, oc[i]); });
  for (let i = oc.length - 1; i >= nc.length; i--) el.removeChild(oc[i]);
}
let lastKey = "";
function feedChips() {
  const chip = (name, S) => { const h = health(S); return h.ok ? "" : `<a class="bal" href="#logs" title="${h.why || h.label}"><span class="mode paper">${name} ${h.label.toUpperCase()}</span> <span class="muted">demo data</span></a>`; };
  return chip("PM", feed.pm) + chip("HL", feed.hl);
}
let hlHandle = null, pmHandle = null;
function render() {
  normalize();
  if (!shown(curKey())) { location.hash = "#home"; return; } // a strategy screen while on "general": go home (hashchange re-renders)
  const key = curKey(), v = views[key];
  hlHandle?.setWatch(state.venue === "Polymarket" ? "BTC" : state.coin, state.tf); // Polymarket's chart is BTC
  chrome(key);
  const full = key !== lastKey; lastKey = key;
  const main = $("#main");
  main.style.gridTemplateColumns = v.grid; main.style.gridTemplateRows = v.rowsPx || v.rows;
  morph(main, v.html(), full);
  const f = $("#footer"); const foot = v.foot ? v.foot() : ""; f.style.display = foot ? "flex" : "none"; morph(f, foot, full);
  requestAnimationFrame(draw);
}
// Live data repaints the screens that show it, but never while the user is typing.
let timer = null;
let lastInput = 0;
const typing = () => false; // inputs are preserved by the in-place patch, so repainting is safe while typing
function schedule() {
  if (timer) return;
  timer = setTimeout(() => { timer = null; const key = curKey(); if (liveViews.has(key) && !typing()) render(); else chrome(key); }, 400);
}
function toast(msg, err = false) { const t = $("#toast"); t.textContent = msg; t.className = err ? "err show" : "show"; clearTimeout(toast.h); toast.h = setTimeout(() => (t.className = ""), 3500); }
function act(a) {
  const f = state.form;
  if (a === "pan-latest") { pan.off = 0; render(); return; }
  if (a.startsWith("eng-") || a.startsWith("run-show-")) { engAct(a, render, toast); return; } // backtests and saves: never an order
  if (a === "reset-paper") { resetPaper(); toast("Paper account reset."); return; }
  if (a === "hl-connect") { const addr = (f.hlAddr ?? feed.hl.account?.address ?? "").trim(); hlHandle.setAddress(addr).then((r) => { if (r.ok) { try { localStorage.setItem(ADDR_KEY, addr); } catch { /* storage blocked */ } } toast(r.ok ? "Live balance connected (read-only)." : r.error, !r.ok); render(); }); toast("Checking the address…"); return; }
  if (a === "pm-connect") { const addr = (f.pmAddr ?? feed.pm.account?.address ?? "").trim(); pmHandle.setAddress(addr).then((r) => { if (r.ok) { try { localStorage.setItem(PM_ADDR_KEY, addr); } catch { /* storage blocked */ } } toast(r.ok ? "Polymarket positions value connected (read-only)." : r.error, !r.ok); render(); }); toast("Checking the address…"); return; }
  if (a === "pm-disconnect") { pmHandle.setAddress(""); try { localStorage.removeItem(PM_ADDR_KEY); } catch { /* storage blocked */ } state.form.pmAddr = ""; toast("Polymarket wallet disconnected."); render(); return; }
  if (a === "hl-disconnect") { hlHandle.setAddress(""); try { localStorage.removeItem(ADDR_KEY); } catch { /* storage blocked */ } state.form.hlAddr = ""; toast("Live balance disconnected."); render(); return; }
  if (state.live && !a.startsWith("close-")) { toast("Live trading is not available in this sandbox. Switch to PAPER to place orders.", true); return; }
  // Paper orders wait out a round trip, then fill against the book as it is then.
  const delay = Math.max(0, Number(f.paperDelay ?? 400) || 0);
  if (!state.live && delay > 0 && (a.startsWith("pm-") || a.startsWith("hl-")) && !act.waiting) {
    toast(`Order sent: fills in ${delay} ms (paper delay, Settings).`);
    setTimeout(() => { act.waiting = true; try { act(a); } finally { act.waiting = false; } }, delay);
    return;
  }
  let r;
  if (a.startsWith("pm-")) r = placePM(feed, a.slice(3), Number(f.pmStake ?? 20));
  else if (a.startsWith("hl-")) r = placeHL(feed, { coin: feed.hl.coin, side: a.slice(3), margin: Number(f.hlSize ?? 100), lev: Number(f.hlLev ?? 5), tp: Number(f.hlTp ?? 2) || 0, sl: Number(f.hlSl ?? 1) || 0 });
  else if (a.startsWith("close-")) r = closePosition(feed, Number(a.slice(6)));
  if (!r) return;
  if (!r.ok) { logEvent("warn", a.startsWith("pm-") ? "Polymarket" : "Hyperliquid", "Manual", "REJECT", r.error); toast(r.error, true); } else toast(a.startsWith("close-") ? "Position closed." : "Paper order filled.");
  render();
}
document.addEventListener("click", (e) => {
  if (location.hash === "#builder" && (state.mode === "Formula" ? formulaClick(e.target) : state.mode === "Rules" ? rulesClick(e.target) : false)) { render(); return; }
  const x = e.target.closest("[data-act]"); if (x) { act(x.dataset.act); return; }
  const s = e.target.closest("[data-set]"); if (!s) return;
  const [k, ...v] = s.dataset.set.split("="), val = v.join("="); state[k] = val !== "" && !isNaN(val) ? Number(val) : val; render();
});
document.addEventListener("change", (e) => { const f = e.target.dataset.flip; if (f) { state[f] = e.target.checked; render(); } const k = e.target.dataset.pick; if (k) { state[k] = Number(e.target.value); render(); } });
document.addEventListener("input", (e) => {
  lastInput = Date.now(); const d = e.target.dataset || {};
  if (d.bind) state.form[d.bind] = e.target.value;
  if (d.sfield) setSField(d.sfield, e.target.value); // the builder edits the selected strategy; checks re-render when they land
  if (location.hash === "#builder" && (formulaInput(e.target) || rulesInput(e.target))) render();
});
// Always to scale: below the 1280 x 860 the screens were laid out for, the whole app shrinks evenly
// instead of cutting cards off; above it, the layout just grows.
const BASE_W = 1280, BASE_H = 860;
function fitScale() {
  const z = Math.min(1, innerWidth / BASE_W, innerHeight / BASE_H), b = document.body.style;
  b.zoom = z; b.boxSizing = "border-box"; b.width = `${innerWidth / z}px`; b.height = `${innerHeight / z}px`;
}
fitScale();
addEventListener("hashchange", render); addEventListener("resize", () => { fitScale(); draw(); });
addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && /^[1-8]$/.test(e.key)) { e.preventDefault(); const k = keys()[e.key - 1]; if (k) location.hash = k; }
  if (e.altKey && ["1", "2", "3"].includes(e.key)) { state.venue = ["Polymarket", "Hyperliquid", "Both"][e.key - 1]; render(); }
});
onChange(schedule);
(function frame() { paintAll(); requestAnimationFrame(frame); })();
(async () => {
  const proxied = await detectProxy();
  logEvent("info", "System", "—", "FEED", proxied ? "Using the local relay (serve.py) for REST and the Polymarket socket" : "Calling the venues directly from the browser (run web/serve.py if Polymarket stays on demo data)");
  hlHandle = startHL(); pmHandle = startPM();
  try { const saved = localStorage.getItem(ADDR_KEY); if (saved) hlHandle.setAddress(saved); const p = localStorage.getItem(PM_ADDR_KEY); if (p) pmHandle.setAddress(p); } catch { /* storage blocked */ }
  render();
})();
setInterval(() => { paperTick(feed); schedule(); }, 1000);
render();
setRerender(render);
installDnD(render);
setAutoRun(() => engAct("eng-run", render, (msg, err) => { if (err) toast(msg, err); }));
boot(render);
// The order book's height: drag the handle under it, double-click to let it fit again.
document.addEventListener("mousedown", (e) => {
  const h = e.target.closest?.("[data-split]"); if (!h) return;
  e.preventDefault();
  const col = h.parentElement, top = col.getBoundingClientRect().top, max = col.getBoundingClientRect().height - 140;
  h.classList.add("drag");
  const rows = (px) => { col.style.gridTemplateRows = `${px}px 6px minmax(0,1fr) auto`; }; // same rows as hlView with a set height
  const move = (ev) => { state.bookH = Math.round(Math.min(max, Math.max(90, ev.clientY - top))); rows(state.bookH); };
  const up = () => { h.classList.remove("drag"); removeEventListener("mousemove", move); removeEventListener("mouseup", up); render(); };
  addEventListener("mousemove", move); addEventListener("mouseup", up);
});
document.addEventListener("dblclick", (e) => { if (e.target.closest?.("[data-split]")) { state.bookH = 0; render(); } });
// Live candles: drag to move through time, scroll to zoom (around the pointer), double-click for the latest.
const plotW = (cv) => cv.getBoundingClientRect().width - 64; // the price axis takes 64 px on the right
document.addEventListener("mousedown", (e) => {
  const cv = e.target.closest?.("canvas.pannable"); if (!cv || e.button !== 0) return;
  e.preventDefault();
  let x0 = e.clientX; const off0 = pan.off, per = plotW(cv) / pan.n, wasOff = pan.off > 0;
  cv.classList.add("grabbing");
  const move = (ev) => { pan.off = off0 + (ev.clientX - x0) / per; requestAnimationFrame(draw); };
  const up = () => { cv.classList.remove("grabbing"); removeEventListener("mousemove", move); removeEventListener("mouseup", up); if ((pan.off > 0) !== wasOff) render(); };
  addEventListener("mousemove", move); addEventListener("mouseup", up);
});
document.addEventListener("wheel", (e) => {
  const cv = e.target.closest?.("canvas.pannable"); if (!cv) return;
  e.preventDefault();
  const wasOff = pan.off > 0;
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) { pan.off += e.deltaX / (plotW(cv) / pan.n); }
  else {
    const r = cv.getBoundingClientRect(), fromRight = Math.min(1, Math.max(0, 1 - (e.clientX - r.left) / plotW(cv)));
    const at = pan.off + fromRight * pan.n, n = Math.max(15, Math.min(1000, pan.n * (e.deltaY > 0 ? 1.12 : 1 / 1.12)));
    pan.n = n; pan.off = Math.max(0, at - fromRight * n);
  }
  requestAnimationFrame(draw);
  if ((pan.off > 0) !== wasOff) render();
}, { passive: false });
document.addEventListener("dblclick", (e) => { if (e.target.closest?.("canvas.pannable")) { pan.off = 0; render(); } });
