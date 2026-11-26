// The engine, through serve.py's /api routes: the same Python backtests the desktop app runs.
// Without the server (file://, a static host) every call fails and the screens keep their demo numbers.
import { strategies } from "./synth.js";

export const E = {
  status: null,                                   // data on disk
  offline: false,                                 // the /api routes do not answer
  busy: "",                                       // the venue a run is going on
  err: "",
  res: { Hyperliquid: null, Polymarket: null },   // the last run per venue
  check: {},                                      // "<strategy>|<field>" -> { ok, error }
  path: "",                                       // where the strategies file lives
};

export async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  let j;
  try { j = await r.json(); } catch { j = { error: `HTTP ${r.status}` }; }
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

// A saved strategy joins the list (same name and venue: replaces the demo one).
export function mergeSaved(list) {
  for (const s of list) {
    const row = { venue: s.venue, name: s.name, tf: s.timeframe || "1m", saved: true, note: "saved strategy", entry: s.entry, exit: s.exit, short_entry: s.short_entry };
    const i = strategies.findIndex((x) => x.name === s.name && x.venue === s.venue);
    if (i >= 0) strategies[i] = { ...strategies[i], ...row }; else strategies.push({ pnl: null, ...row });
  }
}

export async function boot(update) {
  try { E.status = await api("/api/status"); } catch (e) { E.offline = true; E.err = `engine offline: ${e.message}`; update(); return; }
  try { const s = await api("/api/strategies"); E.path = s.path; mergeSaved(s.strategies); } catch (e) { E.err = e.message; }
  update();
}

// Which strategy field a builder tab edits.
export const ruleKey = (side) => (side === "down" ? "short_entry" : side === "exit" ? "exit" : "entry");

// Rule checks, debounced; the result lands in E.check and the screen re-renders.
const timers = {}, pending = new Set();
export function checkRule(s, field, venue, update, wait = 300) {
  const key = `${s.name}|${field}`;
  clearTimeout(timers[key]); pending.add(key);
  timers[key] = setTimeout(async () => {
    try { E.check[key] = await api("/api/parse", { text: s[field] ?? "", kind: field === "exit" ? "exit" : "entry", venue }); }
    catch (e) { E.check[key] = { ok: false, error: e.message, offline: true }; }
    pending.delete(key); update();
  }, wait);
}
export const checking = (key) => pending.has(key);
