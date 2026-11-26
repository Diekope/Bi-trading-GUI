import { candles, equity as equity_, tape, market, stats, pmStats, pmBets, pmRun, dataFor, dataGroups, strategies, palette, features, heat, trades, histogram, rng } from "./synth.js";
import { drawCandles, drawLines, drawArea } from "./chart.js";
import { feed, events, health } from "./feeds.js";
import { paintBtc } from "./btcchart.js";
import { E, api, ruleKey, checkRule, checking } from "./engine.js";
import { formulaView, rulesView } from "./builder.js";
import { ask } from "./dialog.js";
import { P, equity, startEquity, dayPnl, markOf, pnlOf, FEE } from "./paper.js";

export const state = { tf: "1m", btTf: "1m", vol: true, bb: false, strat: 3, ruleSide: "entry", mode: "Formula", res: "Overview", btTab: "Overview", logSel: -1, logSrc: "All", model: "Gradient boosting", autobet: false, mlSel: 0, view: "Visual", sec: "x", venue: "Both", focus: "Hyperliquid", live: 0, side: "Long", pfTab: "All", coin: "HYPE", form: {}, pmSel: "UP", btcSpan: "1m" };

const p2 = (n, w = 2) => String(n).padStart(w, "0");
const lgRows = () => events.map((e) => { const d = new Date(e.t); return { time: `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}.${p2(d.getMilliseconds(), 3)}`, level: e.level.toUpperCase(), source: e.source, origin: e.origin, event: e.event, message: e.message }; }).filter((r) => (state.logSrc === "All" || r.source === state.logSrc) && (state.venue === "Both" || r.source === state.venue || r.source === "System" || r.source === "Strategy"));
const cs = candles(), eq = equity_(), hm = heat(), tr = trades();
const $ = (s) => document.querySelector(s);
const pills = (key, opts) => `<span class="toggle">${opts.map((o) => `<button class="pill ${state[key] === o ? "on" : ""}" data-set="${key}=${o}">${o}</button>`).join("")}</span>`;
const stat = (k, v, c = "") => `<span>${k}<b class="${c}">${v}</b></span>`;
const field = (l, v, t = "number") => `<label class="f">${l}<input type="text" value="${v}" ${t === "number" ? 'style="text-align:right"' : ""}></label>`;
const sel = (l, v, opts = [v]) => `<label class="f">${l}<select>${opts.map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
const ck = (l, on = false, key = "") => `<label class="ck"><input type="checkbox" ${on ? "checked" : ""} ${key ? `data-flip="${key}"` : ""}>${l}</label>`;
const chip = (t, k) => `<span class="chip ${k}">⠿ ${t}</span>`;
const strat = () => strategies[state.strat];
export const V = () => (state.venue === "Both" ? state.focus : state.venue);
const isPM = () => V() === "Polymarket";
export function normalize() {
  if (state.venue !== "Both") state.focus = state.venue;
  if (strategies[state.strat].venue !== V()) state.strat = strategies.findIndex((x) => x.venue === V());
}
const hl = (x) => `<div class="c hl-only">${x}</div>`, pm = (x) => `<div class="c pm-only">${x}</div>`;
const focusPills = () => (state.venue === "Both" ? `<span class="toggle">${["Polymarket", "Hyperliquid"].map((o) => `<button class="pill ${state.focus === o ? "on" : ""}" data-set="focus=${o}">${o === "Polymarket" ? "PM" : "HL"}</button>`).join("")}</span>` : "");
const modeBadge = () => `<span class="mode ${state.live ? "live" : "paper"}">${state.live ? "LIVE" : "PAPER"}</span>`;
const vtag = (v) => `<span class="vtag ${v === "Polymarket" ? "pm" : "hl"}">${v === "Polymarket" ? "PM" : "HL"}</span>`;
const pmRules = {
  entry: { text: "body = close - open\nminute >= 2 and up_price < 0.4 and body > 0", conds: [["minute", ">=", "2"], ["up_price", "<", "0.4"], ["body", ">", "0"]], live: [["up_price", "0.806"], ["body", "12.4"], ["minute", "2"], ["result", "FALSE"]] },
  down: { text: "body = close - open\nminute >= 2 and up_price > 0.6 and body < 0", conds: [["minute", ">=", "2"], ["up_price", ">", "0.6"], ["body", "<", "0"]], live: [["up_price", "0.806"], ["body", "12.4"], ["minute", "2"], ["result", "FALSE"]] },
  exit: { join: "or", text: "pnl >= 25 or pnl <= -30 or seconds_left < 30", conds: [["pnl", ">=", "25"], ["pnl", "<=", "-30"], ["seconds_left", "<", "30"]], live: [["pnl", "+4.2"], ["price", "0.31"], ["seconds_left", "148"], ["result", "FALSE"]], noVar: true },
};
const pmKind = (w) => (["up_price", "down_price", "minute", "seconds_left"].includes(w) ? "pmv" : ["pnl", "price", "entry", "tp", "sl", "bars"].includes(w) ? "data" : /^\d/.test(w) || /^-?\d/.test(w) ? "math" : w === "body" ? "var" : "data");
const pmTok = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\b(and|or)\b/g, '<span style="color:var(--accent)">$1</span>').replace(/\b(up_price|down_price|minute|seconds_left)\b/g, '<span style="color:#7f9bff">$1</span>').replace(/\bbody\b/g, '<span style="color:#e87aa6">body</span>').replace(/\b(close|open|pnl|price)\b/g, '<span style="color:#8ab4ff">$1</span>').replace(/(?<![\w#>])(-?\d+(\.\d+)?)\b/g, '<span style="color:#5fd6d0">$1</span>');
const F0 = () => (isPM()
  ? (() => { const r = pmRules[state.ruleSide] || pmRules.entry; return { v: r.noVar ? "" : "body", expr: "close - open", rhs: [["close", "data"], ["−", "math"], ["open", "data"]], cond: r.conds.flatMap(([a, o, b], n) => [...(n ? [[r.join || "and", "kw"]] : []), [a, pmKind(a)], [o, "math"], [b, pmKind(b)]]), conds: r.conds, text: r.text, live: r.live, tok: pmTok(r.text), noVar: r.noVar }; })()
  : { v: "band", expr: "bollinger_lower(close, 20, 2)", rhs: [["Boll low", "ind"]], cond: [["close", "data"], ["<", "math"], ["band", "var"], ["and", "kw"], ["volume", "data"], [">", "math"], ["0", "math"]], conds: [["close", "<", "band"], ["volume", ">", "0"]], text: "band = bollinger_lower(close, 20, 2)\nclose < band and volume > 0", live: [["close", "8.032e4"], ["band", "8.018e4"], ["volume", "5.05"], ["result", "FALSE"]], tok: null });
// The rule being edited is the selected strategy's own text; the tiles around it stay illustrative.
const ruleText = () => { const v = strat()?.[ruleKey(state.ruleSide)]; return typeof v === "string" ? v : null; };
const F = () => { const f = F0(), t = ruleText(); return t == null ? f : { ...f, text: t, tok: isPM() ? pmTok(t) : null }; };
const esc = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
let rerender = () => {}, autoRun = () => {}, autoTimer = 0;
export const setRerender = (f) => { rerender = f; };
export const setAutoRun = (f) => { autoRun = f; };
// The check badge: asks the engine once per text, then shows its verdict.
const validBadge = (field = ruleKey(state.ruleSide)) => {
  const s = strat(), key = `${s.name}|${field}`, c = E.check[key];
  if (E.offline) return `<span class="cap">not checked: engine offline</span>`;
  if (!c || c.text !== (s[field] ?? "")) { if (!checking(key)) { checkRule(s, field, V(), () => { if (E.check[key]) E.check[key].text = s[field] ?? ""; rerender(); }, 0); } return `<span class="cap">checking…</span>`; }
  return c.ok ? `<span class="valid">✓ valid</span>` : `<span class="down" style="font-size:11px">${esc(c.error)}</span>`;
};
export function setSField(field, value) {
  const s = strat();
  if (!s._orig) s._orig = { name: s.name, tf: s.tf, entry: s.entry, exit: s.exit, short_entry: s.short_entry };
  s[field] = value; s.dirty = true;
  if (["entry", "exit", "short_entry"].includes(field)) {
    const key = `${s.name}|${field}`;
    checkRule(s, field, V(), () => {
      if (E.check[key]) E.check[key].text = value;
      rerender();
      // The Builder's results follow the rule: a valid edit runs the backtest again, quietly.
    });
  }
}
// Variables, grouped: a Polymarket rule keeps the Binance candle and the market apart; a cash-out rule also sees the open bet.
const varGroups = () => (isPM() && state.ruleSide === "exit"
  ? { "Open bet": ["price", "entry", "pnl", "tp", "sl", "bars"], ...dataGroups(V()) }
  : dataGroups(V()));
const noIndicators = () => isPM() && state.ruleSide === "exit"; // a cash-out rule reads the bet and the market, no indicators
const whenLabel = () => (isPM() ? (state.ruleSide === "entry" ? "BET UP WHEN" : state.ruleSide === "down" ? "BET DOWN WHEN" : "CASH OUT WHEN") : state.ruleSide === "entry" ? "BUY WHEN" : "SELL WHEN");
const sc = (v) => (v >= 3 ? "rgba(61,220,132,.55)" : v >= 1 ? "rgba(61,220,132,.25)" : v > -1 ? "#26272b" : v > -3 ? "rgba(255,92,92,.3)" : "rgba(255,92,92,.5)");
const pmIcon = `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M2 3l12 2-12 4zM2 9l12 2-12 3z"/></svg>`;
const hlIcon = `<svg viewBox="0 0 16 16" width="14" height="14" fill="#97fce4"><circle cx="4" cy="8" r="2.5"/><circle cx="12" cy="8" r="2.5"/><rect x="4" y="7" width="8" height="2"/></svg>`;
const hubHead = (t, sub, right = "") => `<section class="card" style="grid-column:1/-1;flex-direction:row;align-items:center;justify-content:space-between;padding:12px 16px"><div><div class="h1">${t}</div><div class="cap">${sub}</div></div>${right}</section>`;
const link = (h, t, cls = "accent") => `<a class="btn ${cls}" href="#${h}">${t}</a>`;

const resultsCard = (grid = "") => { const R = E.res[V()], pm = isPM();
  return `<section class="card" style="${grid}">
  <div class="row between"><h2 class="sec">Preview</h2><span class="row">${pills("res", ["Overview", "Compare"])}</span></div>
  <span class="cap">${runNote()}</span>
  ${previewLater()}${!R || R.sig !== sigOf(strat()) ? empty(previewHint()) : `<div class="stats" style="grid-template-columns:repeat(6,1fr);max-width:640px">${pm ? `${stat("ROI", pctS(R.roi * 100), cls(R.roi))}${stat("PnL", cash(R.pnl), cls(R.pnl))}${stat("Max DD", "-" + (R.maxDD * 100).toFixed(1) + "%", "down")}${stat("Bets", n0(R.bets))}${stat("Win rate", (R.winRate * 100).toFixed(1) + "%")}${stat("Markets", n0(R.markets))}` : `${stat("PnL", pctS(R.pnlPct), cls(R.pnlPct))}${stat("Max DD", pctS(R.maxDD), "down")}${stat("Trades", n0(R.trades))}${stat("Win rate", (R.winRate * 100).toFixed(1) + "%")}${stat("Fees", money(R.fees))}${stat("Bars", n0(R.bars))}`}</div>
  <div class="row grow" style="align-items:stretch;gap:20px;min-height:0">
    <div style="flex:1;display:flex;flex-direction:column;min-width:0"><canvas id="eq"></canvas>
      <div class="row" style="gap:16px;font-weight:600;font-size:12px">${pm ? `<span class="accent">strategy</span><span style="color:var(--indigo)">always UP ${pctS(R.baselines.up.roi * 100)}</span><span class="muted">always DOWN ${pctS(R.baselines.down.roi * 100)}</span>` : `<span class="accent">strategy ${pctS(R.pnlPct)}</span><span style="color:var(--indigo)">random buy ${pctS(R.randomPct)}</span><span class="muted">buy &amp; hold ${pctS(R.holdPct)}</span>`}</div></div>
    <div style="width:250px;display:grid;gap:10px;align-content:start">${state.res === "Overview" ? `<b style="font-size:11px">How ${pm ? "bets" : "trades"} end</b>${reasonBars(R.reasons)}`
      : `<span class="cap">Compare (walk-forward, TP × SL sweep) is not wired to the engine yet: demo grid</span><b style="font-size:11px">TP × SL sweep</b><div class="heat">${hm.flat().map((v) => `<i style="background:${sc(v)}"></i>`).join("")}</div>`}</div>
  </div>`}</section>`; };

const stratList = () => `<section class="card" style="gap:10px;padding:12px"><div class="grow scroll" style="display:grid;gap:8px;align-content:start">${strategies.map((s, i) => s.venue !== V() ? "" : `<div class="list-item ${i === state.strat ? "on" : ""}" data-set="strat=${i}"><span>${s.name}</span><span class="${s.pnl == null ? "muted" : s.pnl >= 0 ? "up" : "down"}">${s.pnl == null ? (s.saved ? "saved" : "draft") : (s.pnl >= 0 ? "+" : "") + s.pnl + "%"}</span></div>`).join("")}</div><button class="btn accent" style="width:100%" data-act="eng-new">Create a strategy</button></section>`;


export function balances() {
  const v = state.venue === "Both" ? null : state.venue, eq = equity(feed, v), st = startEquity(v), h = feed.hl.account, p = feed.pm.account;
  const hv = h?.value ?? null, pv = p?.value ?? null;
  const live = v === "Polymarket" ? pv : v === "Hyperliquid" ? hv : hv == null && pv == null ? null : (hv ?? 0) + (pv ?? 0);
  const err = v === "Polymarket" ? p?.error : v === "Hyperliquid" ? h?.error : h?.error || p?.error;
  return { paper: eq, paperPnl: eq - st, paperPct: st > 0 ? ((eq - st) / st) * 100 : 0, live, liveNote: err ? "error" : live == null ? "—" : "" };
}
const cents = (p) => (p == null ? "—" : Math.abs(p * 100 - Math.round(p * 100)) < 0.05 ? `${Math.round(p * 100)}¢` : `${(p * 100).toFixed(1)}¢`);
const compact = (n) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${(n / 1e3).toFixed(1)}k` : `$${Math.round(n)}`);
const clock = (ms) => { const s = Math.max(0, Math.round(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
const hhmm = (ms) => new Date(ms).toISOString().slice(11, 16);
const pxFmt = (v) => (v == null ? "—" : v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 1 }) : v >= 100 ? v.toFixed(2) : v.toFixed(3));
const money = (n) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const latCls = (ms) => (ms == null ? "muted" : ms <= 120 ? "up" : ms <= 300 ? "accent" : "down");
export const latency = () => ({ pm: feed.pm.latency, hl: feed.hl.latency, cls: latCls });

function pmData() {
  const S = feed.pm, m = S.market;
  if (!(health(S).ok && m)) return { live: false, why: S.error || S.status, title: market.title, win: "21:00–21:05 UTC", closes: market.closesIn, up: { bid: 0.8, ask: 0.81, mid: 0.805 }, down: { bid: 0.19, ask: 0.2, mid: 0.195 }, spread: market.spread, liquidity: market.liquidity, depth: market.depth, target: market.target, btc: market.btc, tape: tape().map((t) => ({ time: t.time, side: t.side, px: t.px / 100, size: t.size })) };
  const pick = (n, i) => m.outcomes.find((o) => o.name.toLowerCase() === n) ?? m.outcomes[i];
  const u = pick("up", 0), d = pick("down", 1);
  const side = (o) => { const b = S.books[o.token], bid = b?.bids[0]?.price ?? null, ask = b?.asks[0]?.price ?? null; return { bid, ask, mid: bid != null && ask != null ? (bid + ask) / 2 : (bid ?? ask ?? o.price) }; };
  const U = side(u), D = side(d), ub = S.books[u.token];
  const depth = ub ? [...ub.bids.slice(0, 5), ...ub.asks.slice(0, 5)].reduce((a, l) => a + l.price * l.size, 0) : null;
  const btc = feed.hl.btcMid ?? feed.hl.mids.BTC ?? null;
  const t2 = (ts) => new Date(ts).toISOString().slice(11, 19);
  return { live: true, title: m.question, win: `${hhmm(m.startMs)}–${hhmm(m.endMs)} UTC`, closes: clock(m.endMs - Date.now()), up: U, down: D, spread: U.bid != null && U.ask != null ? `${Math.round((U.ask - U.bid) * 100)}¢` : "—", liquidity: compact(m.liquidity), depth: depth == null ? "—" : compact(depth), target: S.target, btc, tape: S.trades.slice(0, 5).map((t) => ({ time: t2(t.ts || Date.now()), side: t.token === d.token ? "DOWN" : "UP", px: t.price, size: t.size })) };
}
function hlData() {
  const S = feed.hl, c = S.series[`${S.coin}|${S.interval}`];
  return c && c.length >= 2 && health(S).ok ? { live: true, candles: c, price: S.mids[S.coin] ?? c.at(-1).c } : { live: false, candles: cs, price: cs.at(-1).c };
}
const statusChip = (S) => { const h = health(S); return h.ok ? `<span class="up" style="font-size:11px">● live</span>` : `<span class="accent" style="font-size:11px" title="${h.why}">○ ${h.label} · demo data${h.why ? " · " + h.why : ""}</span>`; };

const pmCard = () => { const d = pmData(), pl = feed.pm.latency, sel = state.pmSel === "DOWN" ? d.down : d.up, ret = sel.ask ? (1 / sel.ask - 1) * 100 : null, delta = d.btc && d.target ? ((d.btc - d.target) / d.target) * 100 : null;
  const tile = (n, o) => `<div class="tile ${state.pmSel === n ? (n === "UP" ? "up" : "down") : ""}" data-set="pmSel=${n}" style="cursor:pointer" title="Show ${n} details"><div class="row between"><b class="${n === "UP" ? "up" : "down"}">${n}</b><span class="${n === "UP" ? "up" : "down"}" style="font-size:24px;font-weight:700">${(o.mid * 100).toFixed(1)}¢</span></div><div style="height:3px;background:var(--${n === "UP" ? "up" : "down"});width:${Math.min(100, o.mid * 100)}%;margin:4px 0 8px;border-radius:2px"></div><div class="row between" style="font-size:11px"><span class="faint">bid ${cents(o.bid)} · ask ${cents(o.ask)}</span><b class="${n === "UP" ? "muted" : "down"}">${o.ask ? "×" + (1 / o.ask).toFixed(2) : ""}</b></div></div>`;
  return `<section class="card" style="padding:16px 18px;gap:6px">
      <div class="row between"><div class="row"><b class="sec" style="color:var(--muted)">Polymarket</b><span class="pill">5m</span></div>${statusChip(feed.pm)}</div>
      <div style="font-size:17px;font-weight:600;margin-top:4px">${d.title}</div>
      <div class="row between muted" style="font-size:11px"><span>${d.win}</span><span>closes in <b style="font-size:20px;color:var(--text);margin-left:6px">${d.closes}</b></span></div>
      <span class="${latCls(pl)}" style="font-size:11px;font-weight:700;letter-spacing:.1em">PM DELAY ● ${pl ?? "—"} ms</span>
      <div class="grid g2" style="gap:8px">${tile("UP", d.up)}${tile("DOWN", d.down)}</div>
      <div class="grid g2" style="font-size:11px;gap:2px 20px">${[["SPREAD", sel.bid != null && sel.ask != null ? `${Math.round((sel.ask - sel.bid) * 100)}¢` : d.spread, "LIQUIDITY", d.liquidity], ["DEPTH", d.depth, "TARGET", d.target ? pxFmt(d.target) : "—"], ["BTC", d.btc ? pxFmt(d.btc) : "—", "Δ OPEN", delta == null ? "—" : (delta >= 0 ? "+" : "") + delta.toFixed(2) + "%"], ["RETURN", ret == null ? "—" : "+" + ret.toFixed(0) + "%", "PER $100", sel.ask ? "$" + (100 / sel.ask).toFixed(0) : "—"]].map(([a, b, c, e]) => `<div class="row"><span class="faint" style="width:56px">${a}</span><b>${b}</b></div><div class="row"><span class="faint" style="width:70px">${c}</span><b class="${c === "Δ OPEN" && delta != null ? (delta >= 0 ? "up" : "down") : ""}">${e}</b></div>`).join("")}</div>
      <div class="cap" style="padding:2px 0"><b class="${state.pmSel === "UP" ? "up" : "down"}">${state.pmSel}</b> selected: ${state.pmSel} at ${cents(sel.ask)} pays ${sel.ask ? "$" + (100 / sel.ask).toFixed(0) : "—"} per $100 if it wins. Click a tile to switch.</div>
      <div class="row between" style="margin-top:6px"><b class="sec" style="color:var(--muted)">BTC / USD${health(feed.hl).ok ? "" : " · demo"}</b><b class="${delta == null ? "muted" : delta >= 0 ? "up" : "down"}" style="font-size:11px">${delta == null ? "" : (delta >= 0 ? "ABOVE " : "BELOW ") + (delta >= 0 ? "+" : "") + delta.toFixed(2) + "%"}</b></div><canvas id="btc"></canvas>
      <b class="sec" style="color:var(--muted)">Tape</b><div class="mono" style="font-size:11px;color:var(--muted);display:grid;gap:1px">${d.tape.map((t) => `<div style="display:grid;grid-template-columns:80px 70px 1fr auto"><span>${t.time}</span><span class="${t.side === "UP" ? "up" : "down"}">${t.side}</span><span style="text-align:right;padding-right:30px">${cents(t.px)}</span><span>× ${(+t.size).toFixed(2)}</span></div>`).join("") || `<div>waiting for trades…</div>`}</div>${posStrip("Polymarket")}</section>`; };

const COINS = ["HYPE", "BTC", "ETH", "SOL"];
const hlCard = () => { const h = hlData(), S = feed.hl;
  return `<section class="card" style="padding:14px 16px"><div class="row between"><div class="row"><b style="font-size:17px;color:var(--muted)">${state.coin}</b>${statusChip(S)}</div><div class="row"><b style="font-size:19px;color:var(--muted)">${pxFmt(h.price)}</b></div></div>
      <div class="row between"><div class="row">${pills("coin", COINS)}</div>${pills("tf", ["1m", "3m", "5m", "15m", "30m", "1h"])}</div><canvas id="hl"></canvas>${posStrip("Hyperliquid")}</section>`; };

const bookRows = (side, n) => {
  const S = feed.hl, b = S.status === "live" && S.book?.coin === S.coin ? S.book : null;
  if (b) { const lv = (side === "ask" ? b.asks : b.bids).slice(0, n), mx = Math.max(...lv.map((l) => l.sz), 1e-9), rows = lv.map((l) => `<div class="book-row mono"><span></span><span class="${side === "ask" ? "down" : "up"}">${pxFmt(l.px)}</span><span class="muted">${l.sz >= 1000 ? l.sz.toFixed(0) : l.sz.toFixed(2)}</span><span class="faint">${compact(l.px * l.sz)}</span><i style="width:${(l.sz / mx) * 100}%;background:var(--${side === "ask" ? "down" : "up"})"></i></div>`); return (side === "ask" ? rows.reverse() : rows).join(""); }
  return Array.from({ length: n }, (_, i) => { const r = rng(40 + i + (side === "ask" ? 0 : 9)), w = 20 + r() * 80, px = side === "ask" ? 76.4 + (n - i) * 0.01 : 76.26 - i * 0.01; return `<div class="book-row mono"><span></span><span class="${side === "ask" ? "down" : "up"}">${px.toFixed(3)}</span><span class="muted">${(200 + r() * 4000).toFixed(0)}</span><span class="faint">${(1 + r() * 30).toFixed(1)}k</span><i style="width:${w}%;background:var(--${side === "ask" ? "down" : "up"})"></i></div>`; }).join("");
};
const posStrip = (venue) => { const rows = P.positions.filter((p) => p.venue === venue); if (state.venue !== "Both") return "";
  return `<div style="border-top:1px solid var(--border);padding-top:6px;display:grid;gap:4px"><span class="cap">Paper positions</span>${rows.map((r) => `<div class="row between mono" style="font-size:11px"><span>${r.market} ${r.kind === "bet" ? r.side : r.side + " " + r.lev + "x"} <span class="muted">${r.kind === "bet" ? "$" + r.stake.toFixed(0) + " @ " + cents(r.entry) : "$" + r.size.toFixed(0) + " @ " + pxFmt(r.entry)}</span></span><span class="row">${pnlCell(pnlOf(feed, r), baseOf(r))}<button class="btn sm" data-act="close-${r.id}">Close</button></span></div>`).join("") || `<span class="cap">none open</span>`}</div>`; };
const DEMO_MIDS = { HYPE: 76.2, BTC: 75760, ETH: 3100, SOL: 165 };
const midOf = (c) => feed.hl.mids[c] ?? DEMO_MIDS[c];
const homePM = () => { const d = pmData(); return `<div style="display:grid;gap:10px;align-content:start"><b class="sec" style="font-size:10px;color:var(--muted)">Polymarket · BTC 5m</b><div class="grid g2"><div class="tile up" style="display:flex;justify-content:space-between;align-items:center"><span class="up mono" style="font-size:10px">UP</span><b class="up mono" style="font-size:17px">${(d.up.mid * 100).toFixed(1)}¢</b></div><div class="tile down" style="display:flex;justify-content:space-between;align-items:center"><span class="down mono" style="font-size:10px">DOWN</span><b class="down mono" style="font-size:17px">${(d.down.mid * 100).toFixed(1)}¢</b></div></div><div class="row between mono" style="font-size:11px"><span class="muted">closes in</span><b>${d.closes}</b></div><div class="progress"><i style="width:30%"></i></div><div class="row between mono" style="font-size:11px;border-top:1px solid var(--border);padding-top:10px"><span>BTC</span><span>${d.btc ? pxFmt(d.btc) : "—"}</span></div></div>`; };
const homeHL = () => { const S = feed.hl, bk = S.book?.coin === state.coin && health(S).ok ? S.book : null, mid = midOf(state.coin);
  const bid = bk?.bids[0]?.px ?? (mid ? mid * 0.99995 : null), ask = bk?.asks[0]?.px ?? (mid ? mid * 1.00005 : null);
  return `<div style="display:grid;gap:10px;align-content:start"><b class="sec" style="font-size:10px;color:var(--muted)">Hyperliquid · ${state.coin} perp</b>
  <div class="grid g2"><div class="tile up" style="display:flex;justify-content:space-between;align-items:center"><span class="up mono" style="font-size:10px">BID</span><b class="up mono" style="font-size:17px">${bid != null ? pxFmt(bid) : "—"}</b></div><div class="tile down" style="display:flex;justify-content:space-between;align-items:center"><span class="down mono" style="font-size:10px">ASK</span><b class="down mono" style="font-size:17px">${ask != null ? pxFmt(ask) : "—"}</b></div></div>
  <div class="row between mono" style="font-size:11px"><span class="muted">spread</span><b>${bid != null && ask != null ? pxFmt(ask - bid) : "—"}</b></div>
  <div style="display:grid;gap:6px">${["HYPE", "BTC", "ETH", "SOL"].map((c) => `<a class="stile wide ${state.coin === c ? "on" : ""}" data-set="coin=${c}"><span class="mono">${c}</span><b class="mono">${pxFmt(midOf(c))}</b></a>`).join("")}</div>
  <canvas id="hlmini" style="max-height:80px;min-height:50px"></canvas></div>`; };
const MODELS = [{ venue: "Hyperliquid", name: "BTC direction", kind: "Gradient boosting", tf: "5m", val: "52.4%", unit: "accuracy" }, { venue: "Polymarket", name: "Edge vs model", kind: "Gradient boosting", tf: "5m", val: "+3.01%", unit: "backtest" }];
const bind = (k, d) => `value="${state.form[k] ?? d}" data-bind="${k}"`;
const posRows = (list, closable) => list.map((r) => { const pnl = pnlOf(feed, r), mark = markOf(feed, r); return `<tr><td>${vtag(r.venue)}</td><td>${r.market}</td><td>${r.kind === "bet" ? r.side : r.side + " " + r.lev + "x"}</td><td>$${(r.kind === "bet" ? r.stake : r.size).toFixed(0)}</td><td>${r.kind === "bet" ? cents(r.entry) : pxFmt(r.entry)}</td><td>${r.kind === "bet" ? cents(mark) : pxFmt(mark)}</td><td style="text-align:right" title="PnL and % of margin (perp) or stake (bet)">${pnlCell(pnl, baseOf(r))}</td>${closable ? `<td style="text-align:right"><button class="btn sm" data-act="close-${r.id}">${r.kind === "bet" && Date.now() >= r.endMs ? "settling" : "Close"}</button></td>` : ""}</tr>`; }).join("");
const usd = (n) => `<span class="${n >= 0 ? "up" : "down"}">${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}</span>`;
// PnL as a percentage of what is at risk: margin for a perp (return on margin), stake for a bet, start equity for the account.
const pct = (n, base) => (base > 0 ? `<span class="${n >= 0 ? "up" : "down"}" style="font-size:.92em">${n >= 0 ? "+" : ""}${((n / base) * 100).toFixed(2)}%</span>` : "");
const pnlCell = (n, base, stack = false) => `<span style="white-space:nowrap">${usd(n)}${stack ? "<br>" : " "}${pct(n, base)}</span>`;
const baseOf = (p) => (p.kind === "bet" ? p.stake : p.margin);

const bothBars = () => { const d = pmData(), cp = "padding:5px 8px;width:58px;text-align:right";
  const pm = `<div class="bar-foot row" style="flex:1"><span class="vtag pm">PM</span><b class="${state.pmSel === "UP" ? "up" : "down"}">${state.pmSel}</b><span style="flex:1"></span><label class="cap">Stake <input type="text" ${bind("pmStake", 20)} style="${cp}"></label>${modeBadge()}<button class="btn up ${state.pmSel === "UP" ? "sel" : ""}" data-act="pm-UP">Bet UP ${cents(d.up.ask)}</button><button class="btn down ${state.pmSel === "DOWN" ? "sel" : ""}" data-act="pm-DOWN">Bet DOWN ${cents(d.down.ask)}</button></div>`;
  const hl = `<div class="bar-foot row" style="flex:1"><span class="vtag hl">HL</span><b>${state.coin}</b><span style="flex:1"></span><label class="cap">Size $ <input type="text" ${bind("hlSize", 500)} style="${cp}"></label><label class="cap">x <input type="text" ${bind("hlLev", 5)} style="${cp};width:42px"></label><label class="cap">TP% <input type="text" ${bind("hlTp", 2)} style="${cp};width:42px"></label><label class="cap">SL% <input type="text" ${bind("hlSl", 1)} style="${cp};width:42px"></label>${modeBadge()}<button class="btn up" data-act="hl-Long">Buy / Long</button><button class="btn down" data-act="hl-Short">Sell / Short</button></div>`;
  return pm + hl; };
const pmView = () => { const d = pmData(), edge = d.up.ask != null ? 0.64 - d.up.ask : null, mine = [...P.positions.filter((p) => p.venue === "Polymarket").map((p) => ({ ...p, open: true })), ...P.history.filter((h) => h.venue === "Polymarket").slice(0, 4)];
  return pmCard() + `<section class="card"><div class="row between"><div class="row"><b class="sec">BTC / USD</b>${statusChip(feed.hl)}<b class="mono" style="font-size:15px">${pxFmt(hlData().price)}</b></div>${pills("tf", ["1m", "3m", "5m", "15m", "30m", "1h"])}</div><div class="row between cap"><span>Hyperliquid BTC perp candles, live</span><span>${d.target ? "window target " + pxFmt(d.target) : "target loading…"}</span></div><canvas id="hl"></canvas>
  <div class="grid g3" style="gap:8px"><div class="well"><div class="cap">Model P(up) · demo</div><b class="mono" style="font-size:18px">0.64</b></div><div class="well"><div class="cap">Market UP ask</div><b class="mono" style="font-size:18px">${cents(d.up.ask)}</b></div><div class="well"><div class="cap">Edge</div><b class="mono ${edge != null && edge >= 0 ? "up" : "down"}" style="font-size:18px">${edge == null ? "—" : (edge >= 0 ? "+" : "") + (edge * 100).toFixed(1) + "¢"}</b></div></div>
  <b class="sec" style="color:var(--muted)">Your paper bets</b>
  <table><tr><th>Side</th><th>Stake</th><th>Entry</th><th>Now / result</th><th></th></tr>${mine.map((p) => `<tr><td>${p.side}</td><td>$${p.stake.toFixed(0)}</td><td>${cents(p.entry)}</td><td>${p.open ? `${cents(markOf(feed, p))} ${pnlCell(pnlOf(feed, p), p.stake)}` : `${pnlCell(p.pnl, p.stake)} <span class="muted">${p.reason}</span>`}</td><td style="text-align:right">${p.open ? `<button class="btn sm" data-act="close-${p.id}">Close</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">no bets yet: place one with the buttons below</td></tr>`}</table></section>`; };

const hlView = () => { const h = hlData(), S = feed.hl, f = state.form, size = +(f.hlSize ?? 500) || 0, lev = +(f.hlLev ?? 5) || 1, mid = h.price, liq = mid * (1 - 0.9 / lev), liqS = mid * (1 + 0.9 / lev);
  const bookH = state.bookH ? `${state.bookH}px` : "minmax(120px,1fr)";
  return hlCard() + `<div id="hlcol" style="display:grid;grid-template-rows:${bookH} 6px ${state.bookH ? "minmax(0,1fr)" : "minmax(0,auto)"} auto;gap:4px;min-height:0">
  <section class="card" style="padding:10px 14px;gap:2px;min-height:0;display:flex;flex-direction:column"><div class="row between"><b class="sec">Order book</b><span class="cap mono">${S.latency != null ? S.latency + " ms" : ""}</span></div>
    <div style="flex:1;min-height:0;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden">${bookRows("ask", 20)}</div>
    <div class="row between mono" style="padding:4px 0;border-block:1px solid var(--border);font-size:12px"><b>${pxFmt(h.price)}</b><span class="muted">${S.book && S.book.asks[0] && S.book.bids[0] ? "spread " + pxFmt(S.book.asks[0].px - S.book.bids[0].px) : ""}</span></div>
    <div style="flex:1;min-height:0;overflow:hidden">${bookRows("bid", 20)}</div></section>
  <div class="splitter" data-split="bookH" title="drag to resize the order book, double-click to fit it again"></div>
  <section class="card scroll" style="gap:4px;padding:10px 14px;min-height:0"><div class="row between"><b class="sec">Paper positions</b><span class="cap">${money(equity(feed, "Hyperliquid"))}</span></div><table>${P.positions.filter((p) => p.venue === "Hyperliquid").map((r) => `<tr><td>${r.coin} ${r.side} ${r.lev}x<br><span class="muted">$${r.size.toFixed(0)} @ ${pxFmt(r.entry)}</span></td><td style="text-align:right" title="PnL and % of margin">${pnlCell(pnlOf(feed, r), r.margin, true)}</td><td style="text-align:right"><button class="btn sm" data-act="close-${r.id}">Close</button></td></tr>`).join("") || `<tr><td class="muted">none open</td></tr>`}</table></section>
  <section class="card" style="gap:8px;padding:12px 14px"><div class="row between"><b class="sec">Trade ${state.coin}</b>${modeBadge()}</div>
  <div class="grid g2" style="gap:8px"><label class="f">Size (USD)<input type="text" ${bind("hlSize", 500)} style="text-align:right"></label><label class="f">Leverage ×<input type="text" ${bind("hlLev", 5)} style="text-align:right"></label><label class="f">TP %<input type="text" ${bind("hlTp", 2)} style="text-align:right"></label><label class="f">SL %<input type="text" ${bind("hlSl", 1)} style="text-align:right"></label></div>
  <span class="cap mono">Margin ${money(size / lev)} · Liq. long ${pxFmt(liq)} / short ${pxFmt(liqS)} · Fee ~${(FEE * 100).toFixed(2)}%</span><div class="grid g2" style="gap:8px"><button class="btn up" data-act="hl-Long">Buy / Long</button><button class="btn down" data-act="hl-Short">Sell / Short</button></div></section></div>`; };

const portfolio = () => { const A = feed.hl.account, V1 = state.venue === "Both" ? null : state.venue, eqv = equity(feed, V1), st = startEquity(V1), dp = dayPnl(feed, V1), rows = P.positions.filter((p) => !V1 || p.venue === V1), hist = P.history.filter((p) => !V1 || p.venue === V1).slice(0, 5), live = !!state.live;
  const card = (isLive) => { const armed = live === isLive;
    return `<section class="card ${armed ? "armed" : ""} ${isLive ? "livebook" : ""}"><div class="row between"><div class="row"><b class="sec">${isLive ? "Live book" : "Paper book"}</b><span class="mode ${isLive ? "live" : "paper"}">${isLive ? "LIVE" : "PAPER"}</span>${armed ? `<span class="cap">orders go here</span>` : ""}</div>${isLive ? `<b class="mono muted">—</b>` : `<b class="mono">${pnlCell(rows.reduce((a, r) => a + pnlOf(feed, r), 0), rows.reduce((a, r) => a + baseOf(r), 0))}</b>`}</div>
    ${isLive ? (A || feed.pm.account ? `${feed.pm.account && state.venue !== "Hyperliquid" ? `<div class="well" style="display:grid;gap:6px"><div class="row between"><span class="cap">Polymarket wallet</span><span class="mono" style="font-size:11px">${feed.pm.account.address.slice(0, 6)}…${feed.pm.account.address.slice(-4)}</span></div><div class="row between"><span class="cap">Positions value</span><b class="mono">${feed.pm.account.value != null ? money(feed.pm.account.value) : "…"}</b></div>${feed.pm.account.error ? `<span class="down" style="font-size:11px">${feed.pm.account.error}</span>` : ""}</div>` : ""}${A && state.venue !== "Polymarket" ? `<div class="well" style="display:grid;gap:6px"><div class="row between"><span class="cap">Hyperliquid account</span><span class="mono" style="font-size:11px">${A.address.slice(0, 6)}…${A.address.slice(-4)}</span></div><div class="row between"><span class="cap">Account value</span><b class="mono">${A.value != null ? money(A.value) : "…"}</b></div><div class="row between"><span class="cap">Margin used</span><span class="mono">${A.marginUsed != null ? money(A.marginUsed) : "—"}</span></div><div class="row between"><span class="cap">Open notional</span><span class="mono">${A.notional != null ? money(A.notional) : "—"}</span></div>${A.error ? `<span class="down" style="font-size:11px">${A.error}</span>` : ""}</div>` : ""}<span class="cap" style="line-height:1.5">Read-only: values come from public addresses. This sandbox never places a real order. Polymarket cash needs API credentials, so only the value of its positions is shown.</span>` : `<div class="well cap" style="line-height:1.5">No live account is connected. Add a wallet address in Settings to read its balance (Hyperliquid) or positions value (Polymarket); public data, no key. This sandbox never places a real order.</div>`)
      : `<table><tr><th></th><th>Market</th><th>Side</th><th>Size</th><th>Entry</th><th>Mark</th><th style="text-align:right">PnL</th><th></th></tr>${posRows(rows, true) || `<tr><td colspan="8" class="muted">no open position</td></tr>`}</table>
      <b class="sec" style="font-size:10px;color:var(--muted)">Closed</b>${hist.map((h) => `<div class="row between mono" style="font-size:11px"><span>${vtag(h.venue)} ${h.market} ${h.side}</span><span class="muted">${h.reason}</span>${pnlCell(h.pnl, baseOf(h))}</div>`).join("") || `<span class="cap">nothing closed yet</span>`}<span class="grow"></span><div class="row between"><span class="cap">Cash: PM ${money(P.cash.Polymarket)} · HL ${money(P.cash.Hyperliquid)}</span><button class="btn sm" data-act="reset-paper">Reset paper account</button></div>`}</section>`; };
  const series = P.curve.map((c) => ((V1 ? c[V1] : c.e) / st - 1) * 100);
  return `${hubHead("Portfolio", "Paper book marked to the live books" + (V1 ? " (" + V1 + ")" : "") + ".", `<span class="row">${modeBadge()}<span class="cap">orders go to the ${state.live ? "live" : "paper"} book</span></span>`)}
  <div class="grid g4" style="grid-column:1/-1;gap:8px">${[["Live equity", balances().live != null ? money(balances().live) : "—", "live", state.venue === "Polymarket" ? "positions value, read-only" : state.venue === "Hyperliquid" ? "account value, read-only" : balances().live != null ? "HL account + PM positions, read-only" : "add a wallet address in Settings"], ["Paper equity", money(eqv), "paper", `${((eqv / st - 1) * 100).toFixed(2)}% since start`], ["Day PnL live", "—", "live", "not tracked"], ["Day PnL paper", pnlCell(dp, st), "paper", "closed + open, % of start equity"]].map(([k, v, m, sub]) => `<section class="card" style="padding:12px 14px;gap:3px"><span class="cap row">${k}<span class="mode ${m}" style="padding:0 5px">${m.toUpperCase()}</span></span><b style="font-size:19px" class="mono">${v}</b><span class="cap">${sub}</span></section>`).join("")}</div>
  ${card(true)}${card(false)}
  <section class="card" style="grid-column:1/-1"><div class="row between"><b class="sec">Paper return since start</b><span class="cap">sampled every 5 s</span></div>${series.length >= 2 ? `<canvas id="pf" data-series='${JSON.stringify(series.slice(-600))}'></canvas>` : `<div class="cap" style="margin:auto">Collecting samples…</div>`}</section>`; };

// -- engine results ---------------------------------------------------------------------
// Engine figures can run away (compounding with no liquidity cap): past a billion they print in exponent form.
const big = (v, f) => (Math.abs(v) >= 1e9 ? Number(v).toExponential(2) : f(Number(v)));
const pctS = (v, d = 2) => (v >= 0 ? "+" : "") + big(v, (x) => x.toFixed(d)) + "%";
const cash = (v) => (v >= 0 ? "+$" : "-$") + big(Math.abs(v), (x) => x.toFixed(2));
const n0 = (v) => Number(v).toLocaleString("en-US");
const cls = (v) => (v >= 0 ? "up" : "down");
const lastPct = (venue) => { const R = E.res[venue]; return !R ? 0 : venue === "Polymarket" ? (R.final / R.capital - 1) * 100 : R.pnlPct; };
const reasonColor = (l) => (/profit|win/i.test(l) ? "--up" : /stop|loss/i.test(l) ? "--down" : "--indigo");
const reasonBars = (rs) => rs.map((r) => `<div class="hbar"><span class="l">${esc(r.label)}</span><span class="t"><i style="width:${(r.share * 100).toFixed(0)}%;background:var(${reasonColor(r.label)})"></i></span>${(r.share * 100).toFixed(0)}%</div>`).join("") || `<span class="cap">no trades</span>`;
const fieldB = (l, k, d) => `<label class="f">${l}<input type="text" ${bind(k, d)} style="text-align:right"></label>`;
const selB = (l, k, d, opts) => `<label class="f">${l}<select data-bind="${k}">${opts.map((o) => `<option ${(state.form[k] ?? d) === o ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
export const SPANS = { "All history": 0, "Last year": 365, "Last 90 days": 90, "Last 30 days": 30, "Last 7 days": 7 };
const runBtn = (sm = "sm") => { const busy = E.busy === V(); return `<button class="btn ${sm} accent" data-act="eng-run" ${busy || E.offline ? "disabled" : ""}>${busy ? "Running…" : "Run backtest"}</button>`; };
const runNote = () => { const R = E.res[V()], busy = E.busy === V();
  return E.offline ? `<span class="down">engine offline: start web/serve.py with uv run</span>` : busy ? "running in the engine…" : E.err ? `<span class="down">${esc(E.err)}</span>` : R ? `${esc(R.strategy)} · ${R.from} → ${R.to} UTC · ${R.ms} ms` : "press Run: the engine walks the data on disk"; };
const empty = (t) => `<div class="cap" style="margin:auto;text-align:center;padding:20px">${t}</div>`;
const stratPick = () => `<select data-pick="strat" style="font-family:var(--ui)">${strategies.map((x, i) => (x.venue !== V() ? "" : `<option value="${i}" ${i === state.strat ? "selected" : ""}>${esc(x.name)}${x.saved ? "" : " (demo)"}</option>`)).join("")}</select>`;
const rulesNote = () => { const x = strat(), L = isPM() ? [["bet UP when", x.entry], ["bet DOWN when", x.short_entry], ["cash out when", x.exit]] : [["enter when", x.entry], ["short when", x.short_entry], ["exit when", x.exit || "pnl >= tp or pnl <= -sl (default)"]];
  return L.filter(([, t]) => t && t.trim()).map(([k, t]) => `${k}: <span class="mono">${esc(t.replace(/\n/g, "; "))}</span>`).join("<br>") || "no rule yet: write one in the Builder"; };

// Polymarket backtest (mirrors ui/strat/strat_pm.py): result figures, baselines, equity curve, and the bets table.
const pmResultCard = () => { const R = E.res.Polymarket;
  return `<section class="card" style="grid-row:1"><div class="row between"><div><b class="sec">Result</b><div class="cap">${runNote()}</div></div><span class="row">${runBtn()}</span></div>
  ${R ? `<div class="stats" style="gap:6px 18px">${stat("Bets", n0(R.bets))}${stat("Markets", n0(R.markets))}${stat("Win rate", (R.winRate * 100).toFixed(1) + "%")}${stat("ROI on stake", pctS(R.roi * 100), cls(R.roi))}${stat("PnL", cash(R.pnl), cls(R.pnl))}${stat("Final", big(R.final, money))}${stat("Max DD", "-" + (R.maxDD * 100).toFixed(1) + "%", "down")}</div>
  <div class="cap">Cashed out early: ${n0(R.early)} · held to settlement: ${n0(R.settled)} · entry at a real price: ${n0(R.realEntries)} of ${n0(R.bets)} (the rest simulated) · outcome estimated from Binance: ${n0(R.estimated)}</div>
  <canvas id="eq"></canvas>
  <div class="row" style="gap:16px;font-weight:600;font-size:12px"><span class="accent">strategy</span><span style="color:var(--indigo)">always UP</span><span class="muted">always DOWN</span></div>
  <div class="cap">Baselines at minute 1, held to settlement. Always UP: ${n0(R.baselines.up.bets)} bets, win ${(R.baselines.up.winRate * 100).toFixed(1)}%, ROI ${pctS(R.baselines.up.roi * 100)}. Always DOWN: ${n0(R.baselines.down.bets)} bets, win ${(R.baselines.down.winRate * 100).toFixed(1)}%, ROI ${pctS(R.baselines.down.roi * 100)}. Prices carry an assumed ${R.halfSpreadCents} cent half spread: no order book history exists.</div>` : empty("No run yet. Pick a strategy and the bet values on the right, then Run.")}</section>`; };
const pmBetsCard = () => { const R = E.res.Polymarket;
  return `<section class="card" style="grid-column:1/3"><div class="row between"><b class="sec">Bets</b><span class="cap">${R ? `the last ${Math.min(500, R.bets)} of ${n0(R.bets)}, newest first` : ""}</span></div>
  ${R ? `<div class="row grow" style="align-items:stretch;gap:20px;min-height:0"><div class="scroll grow" style="flex:1"><table><tr><th>Market (UTC)</th><th>Side</th><th>In</th><th>Buy</th><th>Out</th><th>Sold</th><th>Stake $</th><th>PnL $</th><th>Ended</th><th>Prices</th></tr>${R.betRows.map((t) => `<tr><td>${t.at}</td><td>${t.side}</td><td>${t.inM}</td><td>${t.buy.toFixed(2)}</td><td>${t.outM}</td><td>${t.sold.toFixed(2)}</td><td>${big(t.stake, (x) => x.toFixed(2))}</td><td class="${cls(t.pnl)}">${t.pnl >= 0 ? "+" : ""}${big(t.pnl, (x) => x.toFixed(2))}</td><td>${esc(t.ended)}</td><td class="muted">${t.prices}</td></tr>`).join("") || `<tr><td colspan="10" class="muted">the rule never fired</td></tr>`}</table></div>
  <div style="width:250px;display:grid;gap:8px;align-content:start"><b style="font-size:11px">How bets end</b>${reasonBars(R.reasons)}<b style="font-size:11px;margin-top:6px">Drawdown</b><canvas id="dd" style="height:90px"></canvas></div></div>` : empty("The bets of the last run show here.")}</section>`; };
const hlTopCard = () => { const R = E.res.Hyperliquid;
  return `<section class="card" style="grid-row:1"><div class="row between"><div><b class="sec">Backtest</b><div class="cap">${runNote()}</div></div><span class="row">${focusPills()}${runBtn()}</span></div>
  ${R ? `<div class="stats" style="gap:6px 12px">${stat("PnL", pctS(R.pnlPct), cls(R.pnlPct))}${stat("Final", money(R.final))}${stat("Max DD", pctS(R.maxDD), "down")}${stat("Trades", n0(R.trades))}${stat("Win rate", (R.winRate * 100).toFixed(1) + "%")}${stat("Fees", money(R.fees))}${stat("Random buy", pctS(R.randomPct), cls(R.randomPct))}${stat("Buy & hold", pctS(R.holdPct), cls(R.holdPct))}${stat("Bars", n0(R.bars) + " · " + R.timeframe)}</div><canvas id="hl"></canvas>` : empty("No run yet. Pick a strategy, a span and a timeframe on the right, then Run.")}</section>`; };
const hlResultsCard = () => { const R = E.res.Hyperliquid;
  return `<section class="card" style="grid-column:1/3"><div class="row between"><b class="sec">Results</b>${pills("btTab", ["Overview", "Trades"])}</div>
  ${!R ? empty("The curves and trades of the last run show here.") : state.btTab === "Trades" ? `<span class="cap">the last ${Math.min(500, R.trades)} of ${n0(R.trades)} closed trades, newest first</span><div class="scroll grow"><table><tr><th>#</th><th>PnL %</th><th>Ended</th></tr>${R.tradeRows.map((t) => `<tr><td>${t.n}</td><td class="${cls(t.pnl)}">${pctS(t.pnl, 3)}</td><td>${esc(t.reason)}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">the rule never fired</td></tr>`}</table></div>`
  : `<span class="cap">return since the start: strategy, random buy with the same exits, buy and hold</span><div class="row grow" style="align-items:stretch;gap:20px;min-height:0"><div style="flex:1;display:grid;grid-template-rows:minmax(0,4fr) auto minmax(0,1fr);gap:6px;min-width:0"><canvas id="eq"></canvas><div class="row" style="gap:16px;font-weight:600;font-size:12px"><span class="accent">strategy ${pctS(R.pnlPct)}</span><span style="color:var(--indigo)">random buy ${pctS(R.randomPct)}</span><span class="muted">buy &amp; hold ${pctS(R.holdPct)}</span></div><canvas id="dd"></canvas></div><div style="width:250px;display:grid;gap:8px;align-content:start"><b style="font-size:11px">How trades end</b>${reasonBars(R.reasons)}<b style="font-size:11px;margin-top:6px">PnL distribution</b><div style="display:flex;align-items:end;height:100px;gap:1px">${(() => { const m = Math.max(1, ...R.histogram), [lo, hi] = R.histRange; return R.histogram.map((h, i) => `<i style="flex:1;height:${(h / m) * 100}%;background:${lo + ((hi - lo) * (i + 0.5)) / R.histogram.length < 0 ? "var(--down)" : "var(--up)"}"></i>`).join(""); })()}</div><div class="row between muted mono" style="font-size:10px"><span>${pctS(R.histRange[0])}</span><span>${pctS(R.histRange[1])}</span></div></div></div>`}</section>`; };
const historyCard = () => { const S = E.status, pm = isPM();
  const yrs = S?.candles || [], rows = yrs.reduce((a, y) => a + y.rows, 0), cy = yrs.find((y) => y.year === new Date().getUTCFullYear());
  const disk = !S ? (E.offline ? "engine offline: nothing read from disk" : "reading the data folder…") : pm ? `Polymarket prices: ${n0(S.polymarket.markets)} markets on disk (${n0(S.polymarket.missing)} not on Polymarket)${S.polymarket.newest ? `, newest ${S.polymarket.newest} UTC` : ""}.<br>Binance 1m candles ${cy ? cy.year + ": " + n0(cy.rows) + " rows" : ": none this year"}.` : yrs.length ? `Binance 1m candles ${yrs[0].year} → ${yrs[yrs.length - 1].year}: ${n0(rows)} rows.` : "No candles on disk.";
  return `<section class="card"><b class="sec">History</b><span class="cap">${disk}</span>${selB("Span", pm ? "btSpanPM" : "btSpanHL", pm ? "All history" : "Last 90 days", pm ? ["All history", "Last 90 days", "Last 30 days", "Last 7 days"] : ["Last 7 days", "Last 30 days", "Last 90 days", "Last year", "All history", ...yrs.map((y) => String(y.year)).reverse()])}
  ${pm ? "" : `<div class="grid" style="grid-template-columns:repeat(7,1fr);gap:6px">${["1m", "3m", "5m", "15m", "30m", "1h", "4h"].map((t) => `<button class="pill ${state.btTf === t ? "on" : ""}" style="padding:6px 0" data-set="btTf=${t}">${t}</button>`).join("")}</div>`}
  <span class="cap">${S ? `Data folder: <span class="mono">${esc(S.dataDir)}</span>. Download new history from the desktop app (Backtest → Download).` : ""}</span></section>`; };
const valueCard = () => (isPM()
  ? `<section class="card"><b class="sec">Bet value</b><div class="grid g3" style="gap:8px">${selB("Side (one rule)", "pmSide", "Bet UP", ["Bet UP", "Bet DOWN"])}${fieldB("Start capital $", "pmCap", 1000)}${fieldB("Stake % of equity", "pmStake", 5)}${fieldB("First decision minute", "pmMin", 1)}${fieldB("Half spread (cents)", "pmSpread", 1)}${fieldB("Fee %", "pmFee", 0)}${fieldB("TP % (share price)", "pmTp", 0)}${fieldB("SL % (share price)", "pmSl", 0)}</div><span class="cap">A share pays $1 if its side won, $0 if not. With both a bet UP and a bet DOWN rule, each bets its own side. No order-book history exists: the spread is an assumption.</span></section>`
  : `<section class="card"><b class="sec">Backtest value</b><div class="grid g3" style="gap:8px">${fieldB("Initial capital $", "hlCap", 10000)}${selB("Side", "hlSideB", "Long", ["Long", "Short"])}${fieldB("Fee % per side", "hlFee", 0.06)}${fieldB("TP %", "hlTpB", 2)}${fieldB("SL %", "hlSlB", 1)}</div><span class="cap">BTC only, one position at a time, the whole book per trade. The exit rule reads pnl, tp and sl.</span></section>`);
const stratCard = () => `<section class="card"><b class="sec">Strategy</b><div class="row">${stratPick()}<a class="btn" href="#builder" style="white-space:nowrap">Edit in builder</a></div><span class="cap" style="line-height:1.5">${rulesNote()}</span></section>`;

export const views = {
  portfolio: {
    hub: 1, html: portfolio, grid: "1fr 1fr", rows: "auto auto auto 1fr",
  },

  home: {
    hub: 1,
    html: () => `${hubHead("Home", "Pick a part to work on.", `<span class="row">${link("portfolio", "Portfolio", "")}<span class="c venue-only">${`<a class="btn accent" href="#builder" data-act="eng-new">Create a strategy</a>`}</span></span>`)}
      <div class="statrow">${[["Active strategy", strat().name, strat().tf + " · armed"], ["Last backtest", E.res[V()] ? pctS(lastPct(V())) : "—", E.res[V()] ? `${E.res[V()].strategy} · ${E.res[V()].from.slice(0, 10)} → ${E.res[V()].to.slice(0, 10)}` : "no run yet"], ["Open position", "—", "no position"], ["Next market", pmData().closes, "Polymarket BTC 5m"], [hlIcon + " Hyperliquid balance", money(equity(feed, "Hyperliquid")), "paper · USDC"], [pmIcon + " Polymarket balance", money(equity(feed, "Polymarket")), "paper · USDC"]].map(([k, v, s]) => `<section class="card ${/Hyperliquid/.test(k) ? "hl-only" : /Polymarket|Next market/.test(k) ? "pm-only" : /Active strategy|Last backtest/.test(k) ? "venue-only" : ""}" style="padding:12px 14px;gap:4px"><span class="cap" style="display:flex;gap:6px;align-items:center">${k}</span><b style="font-size:17px">${v}</b><span class="cap">${s}</span></section>`).join("")}</div>
      <section class="card live-card" style="grid-column:span 3"><h2 class="sec">Live</h2><span style="color:var(--soft);line-height:1.5">${state.venue === "Polymarket" ? "Watch the Polymarket 5m market and the BTC chart, and place bets." : state.venue === "Hyperliquid" ? "Watch the Hyperliquid markets and the order book, and place trades." : "Watch both venues and place bets or trades."}</span>
        <div class="well grow" style="display:grid;gap:12px;align-content:start;background:var(--well);${state.venue === "Both" ? "grid-template-columns:1fr 1fr" : ""}">${state.venue !== "Hyperliquid" ? homePM() : ""}${state.venue !== "Polymarket" ? homeHL() : ""}</div>${link("live", "Open live")}</section>
      <section class="card both-only" style="grid-column:span 6"><h2 class="sec">Portfolio</h2><span style="color:var(--soft);line-height:1.5">Both venues in one place: the paper book marked to the live prices, and the live account balance when connected.</span>
        <div class="well grow" style="background:var(--well);display:grid;gap:10px;align-content:start"><div class="row between mono" style="font-size:12px"><span>Paper equity</span><b>${money(equity(feed))}</b></div><div class="row between mono" style="font-size:12px"><span>Paper PnL</span>${pnlCell(equity(feed) - startEquity(null), startEquity(null))}</div><div class="row between mono" style="font-size:12px"><span>Open positions</span><b>${P.positions.length}</b></div><div class="row between mono" style="font-size:12px"><span>Live balance (HL, read-only)</span><b>${feed.hl.account?.value != null ? money(feed.hl.account.value) : "—"}</b></div></div>${link("portfolio", "Open portfolio")}</section>
      <section class="card venue-only" style="grid-column:span 3"><h2 class="sec">Strategy builder</h2><span style="color:var(--soft);line-height:1.5">Create strategies with blocks, formulas or code, and set their entry and exit rules.</span>
        <div class="well grow scroll" style="background:var(--well);display:grid;gap:8px;align-content:start"><span class="cap mono" style="letter-spacing:.1em">STRATEGIES</span><div class="grid g2" style="gap:8px">${strategies.map((s, i) => (s.venue !== V() ? "" : `<a class="stile ${i === state.strat ? "on" : ""}" href="#builder" data-set="strat=${i}"><b>${s.name}</b><span class="cap">${s.tf} · ${s.venue === "Polymarket" ? "PM" : "HL"}${i === state.strat ? " · selected" : ""}</span><span class="mono ${s.pnl == null ? "muted" : s.pnl >= 0 ? "up" : "down"}">${s.pnl == null ? (s.saved ? "saved" : "draft") : (s.pnl >= 0 ? "+" : "") + s.pnl + "%"}</span></a>`)).join("")}<a class="stile new" href="#builder" data-act="eng-new">+ New strategy</a></div><span class="cap mono" style="letter-spacing:.1em;border-top:1px solid var(--border);padding-top:8px">ENTRY FORMULA · ${strat().name}</span><pre class="code" style="background:var(--canvas);padding:8px;border-radius:6px">${F().text.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre><span style="width:max-content">${validBadge("entry")}</span></div><div class="row">${link("builder", "Open builder")}</div></section>
      <section class="card venue-only" style="grid-column:span 3"><h2 class="sec">Backtest engine</h2><span style="color:var(--soft);line-height:1.5">Replay a strategy on history, candle by candle, then review every result.</span>
        <div class="well grow" style="background:var(--well);display:flex;flex-direction:column;gap:8px"><canvas id="mini" style="max-height:130px"></canvas><span class="cap mono">2017 → 2026 · 1m · 196,496 bars</span><div style="border-top:1px solid var(--border);padding-top:8px;display:grid;gap:10px" class="mono"><div class="row between" style="font-size:12px"><span>PnL</span><span><i style="color:var(--amber)">●</i> -0.42%</span></div><div class="row between" style="font-size:12px"><span>Win rate</span><span><i style="color:var(--amber)">●</i> 44%</span></div><div class="row between" style="font-size:12px"><span>Max DD</span><span><i class="up">▲</i> -2.72%</span></div></div></div><div class="row">${link("backtest", "Open engine")}<a class="btn" href="#backtest">Run</a></div></section>
      <section class="card venue-only" style="grid-column:span 3"><h2 class="sec">ML strategies</h2><span style="color:var(--soft);line-height:1.5">Train a model on the candles, then trade what it predicts.</span>
        <div class="well grow scroll" style="background:var(--well);display:grid;gap:8px;align-content:start"><span class="cap mono" style="letter-spacing:.1em">MODELS</span><div class="grid g2" style="gap:8px">${MODELS.map((m) => (m.venue !== V() ? "" : `<a class="stile" href="#ml"><b>${m.name}</b><span class="cap">${m.kind} · ${m.tf}</span><span class="mono up">${m.val} <span class="cap">${m.unit}</span></span></a>`)).join("")}<a class="stile new" href="#ml">+ New model</a></div></div>${link("ml", "Open ML builder")}</section>`,
    grid: "repeat(12,1fr)", rows: "auto auto 1fr",
  },

  live: {
    html: () => (state.venue === "Polymarket" ? pmView() : state.venue === "Hyperliquid" ? hlView() : pmCard() + hlCard()),
    get grid() { return state.venue === "Polymarket" ? "1.1fr 1fr" : state.venue === "Hyperliquid" ? "minmax(0,1fr) 330px" : "1fr 1fr"; },
    rows: "1fr",
    topExtra: () => `<span class="muted" style="font-size:11px">${ck("Volume", state.vol, "vol")}${ck("Bollinger", state.bb, "bb")}</span>`,
    foot: () => (state.venue === "Both" ? bothBars() : state.venue === "Hyperliquid"
      ? `<div class="bar-foot row" style="flex:1"><span class="tag">Strategy</span><div class="field" style="width:170px;font:12px var(--ui)">${strategies.find((x) => x.venue === "Hyperliquid" && x === strat())?.name || "Bollinger reversion"}</div><span class="valid" style="border-radius:12px;padding:4px 14px">armed</span><span class="tag">close</span><b>76.3</b><span class="tag">band</span><b>76.2</b><span class="tag">signal</span><b class="down">FALSE</b><div class="field" style="flex:1;font:12px var(--ui);color:var(--muted)">Position : none</div>${ck("Auto-trade", state.autobet, "autobet")}${modeBadge()}</div>`
      : `<div class="bar-foot row" style="flex:1"><span class="tag">Strategy</span><div class="field" style="width:150px;font:12px var(--ui)">${strat().name}</div><span class="valid" style="border-radius:12px;padding:4px 14px">armed</span><span style="flex:1"></span>${ck("Auto-bet", state.autobet, "autobet")}<input type="text" ${bind("pmStake", 20)} style="width:70px;text-align:right">${modeBadge()}<button class="btn up ${state.pmSel === "UP" ? "sel" : ""}" data-act="pm-UP">Bet UP ${cents(pmData().up.ask)}</button><button class="btn down ${state.pmSel === "DOWN" ? "sel" : ""}" data-act="pm-DOWN">Bet DOWN ${cents(pmData().down.ask)}</button></div>`),
  },

  builder: {
    html: () => `<div style="display:grid;grid-template-rows:auto 1fr;gap:8px;min-height:0"><section class="card" style="gap:6px;padding:12px"><b class="sec">Strategy</b><div class="row"><input type="text" value="${esc(strat().name)}" data-sfield="name" style="font-family:var(--ui)"><input type="text" value="${esc(strat().tf)}" data-sfield="tf" style="width:70px;font-family:var(--ui)"></div><div class="row between">${focusPills()}${vtag(V())}</div></section>${stratList()}</div>
      <div style="display:grid;grid-template-rows:1.6fr 1fr;gap:8px;min-height:0"><section class="card" style="gap:6px;padding:10px 12px"><div class="row between"><span class="row">${(isPM() ? [["entry", "BET UP RULES"], ["down", "BET DOWN RULES"], ["exit", "CASH OUT RULES"]] : [["entry", "ENTRY RULES"], ["exit", "EXIT RULES"]]).map(([k, l]) => `<button class="pill ${state.ruleSide === k ? "on" : ""}" style="font-weight:700;letter-spacing:.1em;padding:5px 10px" data-set="ruleSide=${k}">${l}</button>`).join("")}</span>${pills("mode", ["Rules", "Formula", "Code"])}</div>
      ${state.mode === "Code" ? codeMode() : state.mode === "Rules" ? rulesMode() : formulaMode()}</section>
      ${resultsCard()}</div>`,
    grid: "280px 1fr", rows: "1fr",
    foot: () => `<span class="cap">${esc(strat().name)} · ${strat().dirty || !strat().saved ? "unsaved" : "saved"}${E.path ? ` · ${esc(E.path)}` : ""}</span><span class="sp"></span><button class="btn" disabled>Delete strategy</button><button class="btn" data-act="eng-runbt" title="open the Backtest and run this strategy">Run backtest</button><button class="btn accent" data-act="eng-save">Save</button>`,
  },

  backtest: {
    html: () => `${isPM() ? pmResultCard() : hlTopCard()}
      <div class="dense" style="display:grid;gap:8px;grid-template-rows:auto auto auto;align-content:start;overflow:auto">${historyCard()}${stratCard()}${valueCard()}</div>
      ${isPM() ? pmBetsCard() : hlResultsCard()}`,
    grid: "1.65fr 1fr", rows: "1.85fr 1fr",
  },

  logs: {
    hub: 1,
    html: () => `<div class="row" style="grid-column:1/-1;gap:34px;padding:4px 8px;align-items:flex-start">${[["Orders", events.filter((e) => e.event === "ORDER").length], ["Filled", events.filter((e) => e.event === "ORDER").length], ["Rejected", events.filter((e) => e.event === "REJECT").length], ["Warnings", `<span style="color:var(--amber)">⚠ ${events.filter((e) => e.level === "warn").length}</span>`], ["Day PnL", pnlCell(dayPnl(feed), startEquity(null))]].map(([k, v]) => `<div class="cap">${k}<div class="mono" style="font-size:13px;color:var(--text);font-weight:600;margin-top:4px">${v}</div></div>`).join("")}</div>
      <div class="row" style="grid-column:1/-1"><input type="text" placeholder="Search logs..." style="width:200px;font-family:var(--ui)">${pills("logSrc", ["All", "Polymarket", "Hyperliquid", "Strategy", "System"])}<span class="field" style="width:94px;font:12px var(--ui)">Origin: all</span><span class="field" style="width:92px;font:12px var(--ui)">Level: all</span><span class="field" style="width:108px;font:12px var(--ui)">Strategy: all</span><span style="flex:1"></span><button class="btn">Pause</button><button class="btn">Clear</button><button class="btn">Export</button></div>
      <section class="card scroll" style="padding:0 6px"><table><tr><th style="padding-left:16px">Time</th><th>Level</th><th>Source</th><th>Origin</th><th>Event</th><th>Message</th></tr>${lgRows().map((r, i) => `<tr class="click ${i === state.logSel ? "sel" : ""}" data-set="logSel=${i}"><td style="padding-left:16px">${r.time}</td><td style="color:${r.level === "WARN" ? "var(--amber)" : "var(--muted)"};font-weight:${r.level === "WARN" ? 700 : 400}">${r.level === "WARN" ? "⚠ " : ""}${r.level}</td><td>${r.source === "Polymarket" ? pmIcon : r.source === "Hyperliquid" ? hlIcon : "ⓘ"} ${r.source}</td><td class="muted">${r.origin}</td><td>${r.event}</td><td>${r.message}</td></tr>`).join("") || `<tr><td colspan="6" class="muted" style="padding-left:16px">no events yet</td></tr>`}</table></section>
      <section class="card"><b class="sec">Details</b>${state.logSel < 0 ? `<div class="cap" style="text-align:center">Select an event</div>` : (() => { const r = lgRows()[state.logSel]; return `<div class="cap" style="text-align:center">${r ? r.event + " · " + r.message : ""}</div>`; })()}${["Time", "Source", "Origin", "Latency"].map((k, i) => { const r = lgRows()[state.logSel]; const v = r ? [r.time, r.source, r.origin, "—"][i] : ""; return `<div class="row between mono" style="border-top:1px solid var(--border);padding:8px 0;font-size:11px"><span class="muted">${k}</span><span>${v}</span></div>`; }).join("")}<span class="grow"></span><div class="grid g2"><button class="btn">Copy</button>${link("live", "Open in Live")}</div></section>
      <div class="row between cap" style="grid-column:1/-1;padding:0 8px"><span>Showing ${lgRows().length} of ${events.length} events</span><label class="ck"><input type="checkbox" checked>Auto-scroll</label></div>`,
    grid: "1fr 310px", rows: "auto auto 1fr auto",
  },

  ml: {
    hub: 1,
    html: () => `<section class="card" style="gap:10px"><b class="sec">Data &amp; features</b>
        <div class="row between cap"><span>Market</span><b class="mono" style="color:var(--text)">BTC</b></div><div class="row between cap"><span>Candles</span><span class="row"><input type="text" value="5m" style="width:80px"><b class="mono" style="color:var(--text)">2017 → 2026</b></span></div><div class="row between cap"><span>Source</span><b class="mono" style="color:var(--text)">Local store (Binance)</b></div>
        <span class="cap">Split by time (no shuffling)</span><div class="seg"><span style="flex:6;background:#8d93f0">Train 60%</span><span style="flex:2;background:var(--accent)">Valid 20%</span><span style="flex:2;background:var(--up)">Test 20%</span></div><span class="cap">The test set stays untouched until the final run.</span>
        <b class="sec" style="color:var(--muted);font-size:10px;margin-top:4px">Features</b><span class="cap" style="margin-top:-6px;text-align:right">8 of 10 selected</span><div class="chk">${features.map(([n, , on]) => ck(n.replace("Return ", "Return ").replace(/^Return (\d+)$/, (m, a) => "Return " + a + (a === "1" ? " bar" : " bars")), on)).join("")}</div><span class="grow"></span><button class="btn dash" style="align-self:flex-start">+ Custom feature (formula)</button></section>
      <section class="card" style="gap:8px"><b class="sec">Target &amp; model</b>${sel("Predict", "Direction (up / down)", ["Direction (up / down)", "Up / flat / down"])}<div class="grid g2" style="gap:8px">${field("Horizon (bars)", 5)}${field("Min move %", 0.1)}</div><span class="cap">Looks 25 min ahead. Live auto-bet needs 5 min (5m x 1 or 1m x 5); this one backtests only.</span>
        <div class="row between cap"><b class="sec" style="font-size:10px;color:var(--muted)">Model</b><span>Pick one, or build your own</span></div>${[["Gradient boosting", "Recommended"], ["Random forest", "Tabular"], ["Logistic regression", "Baseline"], ["Neural net (MLP)", "Deep"]].map(([n, t]) => `<div class="model-row ${state.model === n ? "on" : ""}" data-set="model=${n}"><i></i><span style="flex:1">${n}</span><span class="tag">${t}</span></div>`).join("")}<a class="btn dash" href="#model" style="border-style:dashed">+ Build my own model</a>
        <div class="grid g3" style="gap:8px">${field("Trees", 300)}${field("Max depth", 4)}${field("Learning rate", 0.05)}</div><div class="row">${ck("Auto-tune")}<button class="btn accent" style="flex:1">Train model</button><button class="btn" disabled>Stop</button></div></section>
      <section class="card" style="gap:8px"><b class="sec">Trading rule</b><span class="cap">The model outputs <span class="chip" style="color:#8d93f0;cursor:default">model_p</span> = P(up). It also appears as a block in the Formula builder.</span><div class="grid g2" style="gap:8px">${field("Bet UP / Long if P(up) ≥", "0.60")}${field("Bet DOWN / Short if P(up) ≤", "0.40")}${isPM() ? field("Min edge vs market price", "0.05") : field("Leverage ×", 3)}${field("Retrain every (days)", 7)}</div>${ck("Walk-forward retraining")}<b class="sec" style="font-size:10px;color:var(--muted);border-top:1px solid var(--border);padding-top:8px">On the test set</b>${["Signals", "Hit rate", "Period"].map((k) => `<div class="row between cap"><span>${k}</span><span>—</span></div>`).join("")}<span class="grow"></span><div class="grid g2"><button class="btn">Edit exit rules</button><button class="btn">Open in formula</button></div></section>
      <section class="card" style="grid-column:1/-1"><div class="row between"><b class="sec">Results · test set</b><span class="row"><input type="text" value="BTC direction · gradient boosting" style="width:260px;font-family:var(--ui)"><button class="btn">Open</button><button class="btn">Save strategy</button><button class="btn accent">Run full backtest</button></span></div>
        <div class="grid" style="grid-template-columns:1fr 1fr 1fr;gap:20px;flex:1;min-height:0"><table><tr><th style="text-align:center">Metric</th><th style="text-align:center">Train</th><th style="text-align:center">Valid</th><th style="text-align:center">Test</th></tr>${[["Accuracy", "58.1%", "53.0%", "52.4%"], ["AUC", "0.61", "0.54", "0.53"], ["Log loss", "0.67", "0.69", "0.69"]].map((r) => `<tr>${r.map((c, i) => `<td style="${i ? "text-align:center" : "font-size:12px"}">${c}</td>`).join("")}</tr>`).join("")}</table>
        <div><span class="cap">Feature importance</span>${features.slice(0, 6).map(([n, v]) => `<div class="hbar" style="margin-top:6px"><span class="l" style="width:110px;font-size:11px">${n}</span><span class="t"><i style="width:${v}%;background:var(--accent)"></i></span></div>`).join("")}</div>
        <div style="display:flex;flex-direction:column"><span class="cap">Strategy on the test period</span><canvas id="eq"></canvas></div></div></section>`,
    grid: "1fr 1fr 1.1fr", rows: "auto 1fr", rowsPx: "minmax(0,1.9fr) minmax(0,1fr)",
  },

  model: {
    hub: 1,
    html: () => `<div class="row" style="grid-column:1/-1;align-items:flex-end;gap:12px"><label class="f" style="width:260px">Model name<input type="text" value="My model" style="font-family:var(--ui)"></label><label class="f" style="width:130px">Start from<select style="font-family:var(--ui)"><option>Neural net (MLP)</option></select></label><span style="flex:1"></span>${pills("view", ["Visual", "Code"])}</div>
      <section class="card" style="gap:6px"><b class="sec">Layers</b><span class="cap sec" style="font-size:10px;color:var(--muted);margin-top:6px">Core</span><div class="grid g2" style="gap:8px">${["Dense", "Dropout", "BatchNorm", "Activation"].map((l) => `<button class="btn mono" style="font-size:11px;padding:6px">${l}</button>`).join("")}</div><span class="cap sec" style="font-size:10px;color:var(--muted);margin-top:8px">Sequence</span><div class="grid g2" style="gap:8px">${["LSTM", "GRU", "Conv1D", "Attention"].map((l) => `<button class="btn mono" style="font-size:11px;padding:6px">${l}</button>`).join("")}</div><span class="cap" style="margin-top:8px;line-height:1.5">Click a layer to add it to the stack, or drag it by its handle to move it.</span></section>
      <section class="card scroll" style="gap:5px"><div class="row between"><b class="sec">Architecture</b><span class="cap mono">17,537 parameters</span></div>
        <div class="stack"><span class="muted mono" style="width:56px">Input</span><span class="muted mono" style="font-size:11px">30 bars × 8 features</span></div><div class="arrow">▼</div>
        ${[["Dense", "units", 64, "ReLU"], ["Dropout", "rate", 0.2], ["Dense", "units", 32, "ReLU"]].map(([n, k, v, a]) => `<div class="stack"><span class="faint">⋮⋮</span><b style="width:70px">${n}</b><span class="muted" style="font-size:11px">${k}</span><input type="text" value="${v}" style="width:70px;padding:5px 8px;text-align:right">${a ? `<input type="text" value="${a}" style="width:90px;padding:5px 8px">` : ""}<span style="flex:1"></span><span class="btn sm">×</span></div><div class="arrow">▼</div>`).join("")}
        <div class="stack"><span class="muted mono" style="width:56px">Output</span><span class="muted mono" style="font-size:11px">Dense 1 · sigmoid → model_p = P(up)</span></div><button class="btn dash" style="border-style:dashed;margin-top:2px">+ Add layer</button>
        <b class="sec" style="font-size:10px;color:var(--muted);margin-top:8px">Training</b><div class="grid g2" style="gap:8px">${sel("Loss", "Binary cross-entropy")}${sel("Optimizer", "Adam")}</div><div class="grid g3" style="gap:8px">${field("Learning rate", "0.001")}${field("Epochs", 30)}${field("Batch size", 256)}</div>${ck("Early stopping", true)}</section>
      <div style="display:grid;gap:8px;grid-template-rows:auto 1fr;min-height:0"><section class="card"><b class="sec">Layer guide</b><div class="row" style="gap:6px">${["Input", "Dense", "Dropout", "Output"].map((l, i) => `<span class="pill ${i ? "" : "on"}">${l}</span>`).join("")}</div><div class="row"><b class="accent mono" style="font-size:15px">Input</b><span class="tag">Data</span></div>${[["What it does", "Hands the model the last 30 bars, each described by the features you picked."], ["Main setting", "The number of features comes from the ML builder, the 30 bars are fixed."], ["Watch out", "Features are standardised on the training period only, so nothing leaks from the future."]].map(([a, b]) => `<b class="sec" style="font-size:10px;color:var(--muted)">${a}</b><span style="color:var(--soft);line-height:1.45">${b}</span>`).join("")}</section>
        <section class="card scroll" style="gap:6px"><b class="sec">Validator</b><div class="row between valid" style="padding:8px 12px;font-size:12px"><b>✓ Model is valid</b><span class="muted" style="font-size:11px">0 errors · 2 warnings</span></div>${[["✓", "Shapes line up: (30, 8) → Dense 64 → Dropout 0.2 → Dense 32 → 1"], ["✓", "Output: 1 unit + sigmoid matches “up / down”"], ["✓", "Layer order: sequence layers come before Dense"], ["✓", "Values in range: learning rate 0.001, dropout 0.2"], ["✓", "Data: 581k training samples, batch size 256"], ["●", "Dense flattens the 30 bars × 8 features into one vector"], ["●", "Capacity: 17,537 parameters for 8 features. Fewer units may overfit less."]].map(([i, t]) => `<div class="well" style="background:var(--well);padding:9px 12px;display:flex;gap:10px;font-size:12px"><span class="${i === "✓" ? "up" : ""}" style="color:${i === "●" ? "var(--amber)" : ""}">${i}</span>${t}</div>`).join("")}</section></div>`,
    grid: "270px 1fr 380px", rows: "auto 1fr",
    foot: () => `<span class="cap"><span class="up">✓</span> Valid · 2 warnings · saved models appear in the ML strategy builder</span><span class="sp"></span><button class="btn">Cancel</button><button class="btn">Save to my models</button><button class="btn accent">Use in strategy</button>`,
  },

  settings: {
    hub: 1,
    html: () => `${hubHead("Settings", "Accounts, defaults and safety limits.", `<span class="mono" style="font-size:11px;color:var(--soft)">${pmIcon} Polymarket — &nbsp; ${hlIcon} Hyperliquid — <span class="down">· lent</span></span>`)}
      <div style="display:grid;gap:8px;align-content:start;overflow:auto;grid-auto-rows:max-content">
        <section class="card" style="gap:10px"><b class="sec">${pmIcon} &nbsp;Polymarket</b><span class="cap mono">○ Credentials saved</span><div class="grid g2" style="gap:10px">${[["Private key", "●●●●●●●●●●●●", 1], ["Wallet address (read-only value)", "0x…"], ["Wallet type", "EOA / wallet"], ["Builder key", "optional — …", 1], ["Builder secret", "", 1], ["Builder passphrase", "", 1]].map(([l, v, s]) => `<label class="f">${l}<span class="row">${l.startsWith("Wallet address") ? `<input type="text" ${bind("pmAddr", feed.pm.account?.address ?? "")} placeholder="0x…">` : `<input type="text" value="${v}" style="${v.startsWith("●") ? "" : v ? "color:var(--muted)" : ""}">`}${s ? `<button class="btn sm">Show</button>` : ""}</span></label>`).join("")}</div><div class="row" style="flex-wrap:wrap"><button class="btn accent" data-act="pm-connect">Test connection</button><button class="btn">Create builder key</button><button class="btn" data-act="pm-disconnect">Disconnect</button><span class="mono" style="font-size:11px">${feed.pm.account ? (feed.pm.account.error ? `<span class="down">${feed.pm.account.error}</span>` : feed.pm.account.value != null ? `<span class="up">● ${money(feed.pm.account.value)} in positions</span>` : "checking…") : `<span class="muted">○ not connected</span>`}</span></div><span class="cap" style="line-height:1.5">Reads the value of the open positions of a public address (Polymarket Data API). The USDC cash balance needs API credentials, so it is not shown.</span></section>
        <section class="card" style="gap:10px"><b class="sec">${hlIcon} &nbsp;Hyperliquid</b><span class="cap mono">○ Not configured</span><div class="grid g2" style="gap:10px"><label class="f">Wallet address (read-only balance)<input type="text" ${bind("hlAddr", feed.hl.account?.address ?? "")} placeholder="0x…"></label><label class="f">API wallet private key<span class="row"><input type="text" value="●●●●●●●●●●●●●●●●●●"><button class="btn sm">Show</button></span></label></div>${sel("Network", "Mainnet")}<div class="row" style="flex-wrap:wrap"><button class="btn accent" data-act="hl-connect">Test connection</button><button class="btn" data-act="hl-disconnect">Disconnect</button><span class="mono" style="font-size:11px">${feed.hl.account ? (feed.hl.account.error ? `<span class="down">${feed.hl.account.error}</span>` : feed.hl.account.value != null ? `<span class="up">● ${money(feed.hl.account.value)} account value</span>` : "checking…") : `<span class="muted">○ not connected</span>`}</span></div><span class="cap" style="line-height:1.5">Reads the perps account value from the public address (no key). Accounts in unified or portfolio-margin mode keep balances in spot, so the value can show 0.</span></section>
        <section class="card" style="gap:6px"><b class="cap mono" style="letter-spacing:.1em">SECURITY</b><span style="line-height:1.45">Use an API wallet that can trade but not withdraw. Private keys are kept in your system keychain, never in strategy or settings files.</span></section></div>
      <div style="display:grid;gap:8px;align-content:start;overflow:auto">
        <section class="card" style="gap:12px"><b class="sec">Backtest defaults</b><div class="grid g3">${field("Initial capital $", 10000)}${sel("Sizing", "Balance %")}${field("Position %", 10)}${field("TP %", 2)}${field("SL %", 1)}${field("Max cash $", 2000)}${sel("Timeframe", "1m")}${field("From", 2017)}${field("To", 2026)}${field("Fees %", 0.06)}${field("Reverse % to close", 0.5)}<label class="f"><span>&nbsp;</span>${ck("Dynamic TP on by default")}</label>${hl(field("Hold (candles, 0 = no limit)", 7))}${field("Slippage %", 0.01)}${field("Warm-up (bars, 0 = off)", 100)}</div></section>
        <section class="card" style="gap:12px"><b class="sec">Trading defaults</b><div class="grid g3">${hl(field("Leverage ×", 5) + sel("Margin mode", "Isolated") + field("Default size (USD)", 3780))}${pm(field("Polymarket stake $", 20))}${field("Max stake per bet $", 100)}${field("Daily loss limit $", 200)}<label class="f">Paper fill delay (ms)<input type="text" ${bind("paperDelay", 400)} style="text-align:right"></label></div><span class="cap">A paper order waits this long, then fills against the book as it is then, like a real order's round trip. 0 fills at once.</span><div class="grid g3">${ck("Confirm before placing an order", true)}${ck("Auto-bet when a strategy is armed")}${ck("Place real orders (off = dry run)")}</div></section>
        <section class="card" style="gap:12px"><b class="sec">General</b><div class="grid" style="grid-template-columns:1fr 2fr auto">${sel("Start page", "Home")}${field("Data folder", "…/bi-trading/data/candles", "text")}<label class="f"><span>&nbsp;</span><button class="btn">Browse</button></label></div></section></div>`,
    grid: "minmax(0,1fr) minmax(0,1.5fr)", rows: "auto 1fr", settingsFix: true,
    foot: () => `<span class="cap">All changes saved</span><span class="sp"></span><button class="btn">Reset to defaults</button><button class="btn">Cancel</button><button class="btn accent">Save</button>`,
  },
};

// Formula and Rules edit the same text as Code (see builder.js and rule.js).
const bctx = () => { const field = ruleKey(state.ruleSide), sn = strat();
  return { key: `${sn.name}|${field}`, field, text: sn[field] ?? "", setText: (t) => setSField(field, t), groups: varGroups(), exit: state.ruleSide === "exit", when: whenLabel(), badge: validBadge(field) }; };
function formulaMode() { return formulaView(bctx()); }
function rulesMode() { return rulesView(bctx()); }
function codeMode() {
  const tok = F().tok || `<span style="color:#e87aa6">band</span> = <span style="color:var(--up)">bollinger_lower</span>(<span style="color:#8ab4ff">close</span>, <span style="color:#5fd6d0">20</span>, <span style="color:#5fd6d0">2</span>)\n<span style="color:#8ab4ff">close</span> &lt; <span style="color:#e87aa6">band</span> <span style="color:var(--accent)">and</span> <span style="color:#8ab4ff">volume</span> &gt; <span style="color:#5fd6d0">0</span>`;
  return `<div class="grid grow" style="grid-template-columns:1fr 250px;gap:8px;min-height:0"><div class="well" style="display:flex;flex-direction:column;gap:6px"><div class="row between"><b class="mono" style="font-size:11px">formula.txt</b><span class="cap" style="font-size:10px">the code the tiles stand for — editable</span></div><textarea class="code grow" data-sfield="${ruleKey(state.ruleSide)}" spellcheck="false" style="background:var(--well);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px;font:12px/1.6 var(--mono);resize:none;min-height:120px">${esc(F().text)}</textarea><div class="row between"><span class="cap" style="font-size:10px">checked by the engine as you type</span>${validBadge()}</div></div>
  <div style="display:grid;gap:8px;grid-template-rows:auto 1fr;min-height:0"><div class="well"><b class="sec" style="font-size:10px">Variables</b><div style="display:grid;gap:4px;font-size:11px;margin-top:6px">${Object.entries(varGroups()).map(([g, a]) => `<span class="cap" style="font-size:10px;letter-spacing:.1em;margin-top:4px">${g.toUpperCase()}</span>${a.map((d) => `<div class="row between" style="${g.startsWith("Polymarket") ? "color:#7f9bff" : ""}"><span>${d}</span><span class="muted">float</span></div>`).join("")}`).join("")}<span class="cap" style="font-size:10px;letter-spacing:.1em;margin-top:4px">FUNCTIONS</span>${[["abs()", "function"], ["bollinger_lower()", "function"], ["bollinger_middle()", "function"], ["bollinger_upper()", "function"]].map(([a, b]) => `<div class="row between"><span>${a}</span><span class="muted">${b}</span></div>`).join("")}</div></div><div class="well"><b class="sec" style="font-size:10px">Values</b><div class="row between" style="font-size:11px;margin-top:6px"><span>close</span><span class="muted">float</span></div><div class="cap">the bar's closing price</div><div class="row between" style="font-size:11px;margin-top:6px"><span>value</span><span class="muted mono">8.032e+04</span></div><div class="row between" style="font-size:11px"><span>result</span><b class="down">FALSE</b></div></div></div></div>`;
}

export function draw() {
  const o = { volume: state.vol, bands: state.bb }, bt = location.hash === "#backtest", R = (bt || location.hash === "#builder") ? E.res[V()] : null;
  const fmtP = (v) => pctS(v, 1);
  if ($("#hl")) {
    if (bt && R && R.price) drawLines($("#hl"), [{ v: R.price, color: "--accent" }], { grid: true, fmt: (v) => v.toFixed(0) });
    else drawCandles($("#hl"), (location.hash === "#live" ? hlData().candles : cs).slice(-120), { ...o, markers: [], axis: bt ? 0 : 64 });
  }
  if ($("#hlmini")) { const c = hlData().candles.slice(-60).map((x) => x.c); drawLines($("#hlmini"), [{ v: c, color: "--accent", fill: true }]); }
  if ($("#pf")) drawLines($("#pf"), [{ v: JSON.parse($("#pf").dataset.series), color: "--indigo" }], { grid: true, fmt: (v) => (v >= 0 ? "+" : "") + v.toFixed(2) + "%" });
  paintAll();
  if ($("#eq")) {
    if (R) {
      const c = R.curves, s = isPM() ? [{ v: c.strategy, color: "--accent" }, { v: c.up, color: "--indigo" }, { v: c.down, color: "--muted", dash: [3, 3] }] : [{ v: c.strategy, color: "--accent" }, { v: c.random, color: "--indigo" }, { v: c.hold, color: "--muted", dash: [3, 3] }];
      drawLines($("#eq"), s, { grid: true, fmt: fmtP });
    } else if (location.hash === "#ml") {
      drawLines($("#eq"), [{ v: eq.strategy, color: "--accent" }, { v: eq.random, color: "--indigo" }, { v: eq.hold.map((x) => x * 0.3), color: "--muted", dash: [3, 3] }], { grid: false, fmt: fmtP });
    }
  }
  if ($("#dd") && R) drawArea($("#dd"), R.curves.drawdown);
  if ($("#mini")) { const H = E.res[V()]; drawLines($("#mini"), H ? [{ v: H.curves.strategy, color: "--accent" }, { v: isPM() ? H.curves.up : H.curves.random, color: "--indigo" }] : [{ v: [0, 0], color: "--muted" }]); }
}

// The Builder's preview: the selected strategy's run, started on its own when the rules or the strategy change.
const sigOf = (s) => JSON.stringify([V(), s.name, s.entry ?? "", s.short_entry ?? "", s.exit ?? "", isPM() ? "" : state.btTf]);
const hasRule = (s) => !!((s.entry ?? "").trim() || (isPM() && (s.short_entry ?? "").trim()));
const badRule = (s) => ["entry", "short_entry", "exit"].some((f) => { const c = E.check[`${s.name}|${f}`]; return c && c.ok === false && c.text === (s[f] ?? ""); });
let tried = "";
const previewHint = () => { const s = strat(); return E.offline ? "engine offline" : !hasRule(s) ? (isPM() ? "Write a bet UP or a bet DOWN rule to see its preview." : "Write an entry rule to see its preview.") : badRule(s) ? "Fix the rule to see its preview." : E.busy ? "computing the preview…" : E.err && tried === sigOf(s) ? "" : "computing the preview…"; };
function previewLater() {
  const s = strat(), sig = sigOf(s);
  if (location.hash !== "#builder" || E.offline || E.busy || !hasRule(s) || badRule(s) || E.res[V()]?.sig === sig || tried === sig) return "";
  tried = sig; clearTimeout(autoTimer); autoTimer = setTimeout(() => autoRun(), 350);
  return "";
}

async function saveStrategy(s, venue) {
  await api("/api/strategies", { name: s.name, timeframe: s.tf, venue, entry: s.entry ?? "", exit: s.exit ?? "", short_entry: s.short_entry ?? "" });
  s.saved = true; s.dirty = false; delete s._orig;
}
const freshName = (base) => { let n = 1, name = base; while (strategies.some((x) => x.name === name && x.venue === V())) name = `${base} ${++n}`; return name; };

// The engine's actions: run a backtest, save the strategy.
export async function engAct(a, render, toast) {
  const s = strat(), venue = V(), pm = isPM(), f = state.form, n = (k, d) => (f[k] === undefined || f[k] === "" ? d : Number(f[k]));
  const rules = { entry: s.entry ?? "", short_entry: s.short_entry ?? "", exit: s.exit ?? "" };
  if (a === "eng-run") {
    if (E.busy) { E.again = true; return; }   // a run is going: run once more after it, on the newest rule
    const span = f[pm ? "btSpanPM" : "btSpanHL"] ?? (pm ? "All history" : "Last 90 days"), year = /^\d{4}$/.test(span) ? Number(span) : null;
    const days = SPANS[span] ?? 30;
    const body = pm
      ? { ...rules, days, capital: n("pmCap", 1000), stake_pct: n("pmStake", 5), first_minute: n("pmMin", 1), half_spread_cents: n("pmSpread", 1), fee_pct: n("pmFee", 0), tp: n("pmTp", 0), sl: n("pmSl", 0), side: f.pmSide === "Bet DOWN" ? "down" : "up" }
      : { ...rules, days, ...(year ? { year } : {}), timeframe: state.btTf, capital: n("hlCap", 10000), fee_pct: n("hlFee", 0.06), tp: n("hlTpB", 2), sl: n("hlSlB", 1), side: f.hlSideB === "Short" ? "short" : "long" };
    E.busy = venue; E.err = ""; render();
    const t0 = performance.now();
    try {
      const r = await api(pm ? "/api/backtest/polymarket" : "/api/backtest", body);
      Object.assign(r, { strategy: s.name, ms: Math.round(performance.now() - t0), capital: body.capital, sig: sigOf(s) });
      E.res[venue] = r; s.pnl = +lastPct(venue).toFixed(2);
      toast(`${s.name}: ${pctS(lastPct(venue))} over ${pm ? n0(r.bets) + " bets" : n0(r.trades) + " trades"}.`);
    } catch (e) { E.err = e.message; toast(e.message, true); }
    E.busy = ""; render();
    if (E.again) { E.again = false; engAct(a, render, toast); }
    return;
  }
  if (a === "eng-new") {
    if (s.dirty) {
      const { value } = await ask({ title: `Save "${s.name}" first?`, text: "You changed this strategy since it was last saved. A new strategy starts from a blank page.", buttons: [{ label: "Cancel", value: null }, { label: "Discard changes", value: "discard" }, { label: "Save", value: "save", cls: "accent" }] });
      if (!value) return;
      if (value === "save") { try { await saveStrategy(s, venue); toast(`Saved "${s.name}".`); } catch (e) { toast(e.message, true); return; } }
      else if (s._orig) { Object.assign(s, s._orig); delete s._orig; s.dirty = false; }
    }
    strategies.push({ venue, name: freshName("New strategy"), tf: pm ? "5m" : "1m", entry: "", exit: "", short_entry: "", pnl: null, note: "new strategy" });
    state.strat = strategies.length - 1; state.ruleSide = "entry";
    if (location.hash !== "#builder") location.hash = "#builder";
    render(); return;
  }
  if (a === "eng-runbt") {
    if (!s.saved || s.dirty) {
      const { value, input } = await ask({ title: "Save the strategy to backtest it", text: "The backtest runs a saved strategy. Give it a name:", input: s.saved || !/^New strategy/.test(s.name) ? s.name : freshName(pm ? "Polymarket strategy" : "Hyperliquid strategy"), buttons: [{ label: "Cancel", value: null }, { label: "Save and run", value: "go", cls: "accent" }] });
      if (!value) return;
      if (input) s.name = input;
      try { await saveStrategy(s, venue); } catch (e) { toast(e.message, true); return; }
    }
    location.hash = "#backtest";
    E.res[venue] = null; render();
    return engAct("eng-run", render, toast);
  }
  if (a === "eng-save") {
    try { await saveStrategy(s, venue); toast(`Saved "${s.name}". The desktop app sees it too.`); }
    catch (e) { toast(e.message, true); }
    render();
  }
}

// The Polymarket BTC chart: live samples when the feeds are up, otherwise a synthetic walk so the animation still shows.
const demo = { t: 0, pts: [], p: 75740 };
function btcFeed() {
  const m = feed.pm.market, ticks = feed.hl.btcTicks || [], live = health(feed.hl).ok && ticks.length > 1, now = Date.now();
  if (live) {
    const c = feed.hl.series["BTC|1m"] || [], first = ticks[0].t, back = c.filter((x) => x.t + 60000 < first && x.t + 60000 > now - 16 * 60e3).flatMap((x) => [{ t: x.t, p: x.o }, { t: x.t + 60000, p: x.c }]);
    return { points: [...back, ...ticks], target: feed.pm.target, startMs: m?.startMs, endMs: m?.endMs, windows: feed.pm.windows, key: `${location.hash}|btc`, mode: "1m" };
  }
  if (!demo.t) { demo.t = now - 16 * 60e3; }
  const r = rng(Math.floor(now / 500));
  while (demo.t < now) { demo.t += 500; demo.p += (r() - 0.5) * 14 + (75740 - demo.p) * 0.01; demo.pts.push({ t: demo.t, p: demo.p }); }
  while (demo.pts.length && demo.pts[0].t < now - 16 * 60e3) demo.pts.shift();
  const start = Math.floor(now / 300e3) * 300e3, at = (s) => demo.pts.find((x) => x.t >= s)?.p ?? demo.pts[0].p;
  const windows = [0, 1, 2].map((k) => ({ start: start - k * 300e3, end: start - k * 300e3 + 300e3, target: at(start - k * 300e3) }));
  return { points: demo.pts, target: windows[0].target, startMs: start, endMs: start + 300e3, windows, key: `${location.hash}|btc`, mode: "1m" };
}
export function paintAll() {
  const els = ["#btc", "#btc2"].map((s) => $(s)).filter(Boolean);
  if (!els.length) return;
  const f = btcFeed(); els.forEach((cv) => paintBtc(cv, f));
}
