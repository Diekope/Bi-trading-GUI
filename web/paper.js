// Paper trading against the live books. Nothing here ever talks to a venue's trading API.
import { logEvent, fetchResolved, defaultEnv, emit } from "./feeds.js";

const KEY = "bi-trading-sandbox-paper-v1";
export const FEE = 0.0006; // 0.06 %, the Backtest default fee. Applied per side on Hyperliquid; Polymarket bets carry none.
const fresh = () => ({ cash: { Polymarket: 1000, Hyperliquid: 10000 }, start: { Polymarket: 1000, Hyperliquid: 10000 }, positions: [], history: [], curve: [], seq: 1 });
const store = () => { try { return typeof localStorage === "undefined" ? null : localStorage; } catch { return null; } };
function load() { try { const j = JSON.parse(store()?.getItem(KEY) || "null"); if (j && j.cash && Array.isArray(j.positions)) return j; } catch { /* corrupt: start over */ } return fresh(); }
export const P = load();
export const save = () => { try { store()?.setItem(KEY, JSON.stringify(P)); } catch { /* storage blocked */ } };
export function resetPaper() { Object.assign(P, fresh()); save(); logEvent("info", "System", "Manual", "PAPER", "Paper account reset"); }

// -- marks ------------------------------------------------------------------------

const tokenBook = (feed, token) => feed.pm.books[token];
const outcomeOf = (feed, pos) => feed.pm.market?.slug === pos.slug ? feed.pm.market.outcomes.find((o) => o.token === pos.token) : null;
export function markOf(feed, pos) {
  if (pos.kind === "bet") {
    const b = tokenBook(feed, pos.token)?.bids[0]?.price;
    return b ?? outcomeOf(feed, pos)?.price ?? pos.entry;
  }
  const S = feed.hl, book = S.book?.coin === pos.coin ? S.book : null;
  const px = pos.side === "Long" ? book?.bids[0]?.px : book?.asks[0]?.px;
  return px ?? S.mids[pos.coin] ?? pos.entry;
}
export function pnlOf(feed, pos) {
  const mark = markOf(feed, pos);
  if (pos.kind === "bet") return pos.shares * mark - pos.stake;
  return (mark - pos.entry) * pos.qty * (pos.side === "Long" ? 1 : -1);
}
const valueOf = (feed, pos) => (pos.kind === "bet" ? pos.shares * markOf(feed, pos) : pos.margin + pnlOf(feed, pos));
export const equity = (feed, venue) => {
  const vs = venue ? [venue] : ["Polymarket", "Hyperliquid"];
  return vs.reduce((a, v) => a + P.cash[v] + P.positions.filter((p) => p.venue === v).reduce((s, p) => s + valueOf(feed, p), 0), 0);
};
export const startEquity = (venue) => (venue ? P.start[venue] : P.start.Polymarket + P.start.Hyperliquid);
export function dayPnl(feed, venue) {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  const realized = P.history.filter((h) => (!venue || h.venue === venue) && h.closedAt >= d.getTime()).reduce((a, h) => a + h.pnl, 0);
  const open = P.positions.filter((p) => !venue || p.venue === venue).reduce((a, p) => a + pnlOf(feed, p), 0);
  return realized + open;
}

// -- fills ------------------------------------------------------------------------

// Average price paying `usd` of notional through book levels [{px, sz}] (sz in base units).
export function walkUsd(levels, usd) {
  let left = usd, qty = 0;
  for (const l of levels) { const take = Math.min(left, l.px * l.sz); qty += take / l.px; left -= take; if (left <= 1e-9) break; }
  return left > 1e-6 ? null : usd / qty;
}
const walkShares = (asks, stake) => { let left = stake, shares = 0; for (const a of asks) { const take = Math.min(left, a.price * a.size); shares += take / a.price; left -= take; if (left <= 1e-9) break; } return left > 1e-6 ? null : shares; };

export function placePM(feed, side, stake, now = Date.now()) {
  const S = feed.pm, m = S.market;
  if (!m || S.status !== "live") return { ok: false, error: "Polymarket feed is not live, so there is no price to fill against." };
  if (!(stake > 0)) return { ok: false, error: "Enter a stake above 0." };
  if (stake > P.cash.Polymarket) return { ok: false, error: `Stake exceeds the paper cash ($${P.cash.Polymarket.toFixed(2)}).` };
  if (!m.acceptingOrders || now >= m.endMs - 3000) return { ok: false, error: "This market is closed to orders; wait for the next window." };
  const o = m.outcomes.find((x) => x.name.toLowerCase() === side.toLowerCase()) ?? m.outcomes[side === "UP" ? 0 : 1];
  const asks = tokenBook(feed, o.token)?.asks ?? [];
  let shares = asks.length ? walkShares(asks, stake) : o.price > 0 ? stake / o.price : null;
  if (!shares) return { ok: false, error: "Not enough depth on the ask side for that stake." };
  const pos = { id: P.seq++, venue: "Polymarket", kind: "bet", market: "BTC 5m", slug: m.slug, side, token: o.token, shares, entry: stake / shares, stake, endMs: m.endMs, target: S.target, openedAt: now };
  P.cash.Polymarket -= stake; P.positions.push(pos); save();
  logEvent("info", "Polymarket", "Manual", "ORDER", `PAPER ${side} $${stake} @ ${(pos.entry * 100).toFixed(1)}¢ (${shares.toFixed(2)} sh)`, now);
  return { ok: true, pos };
}

export function placeHL(feed, { coin, side, size, lev, tp = 0, sl = 0 }, now = Date.now()) {
  const S = feed.hl;
  if (S.status !== "live") return { ok: false, error: "Hyperliquid feed is not live, so there is no price to fill against." };
  if (!(size > 0) || !(lev >= 1 && lev <= 50)) return { ok: false, error: "Size must be above 0 and leverage between 1 and 50." };
  const book = S.book?.coin === coin ? S.book : null, long = side === "Long";
  let entry = book ? walkUsd(long ? book.asks : book.bids, size) : null;
  entry ??= S.mids[coin] ?? null;
  if (!entry) return { ok: false, error: `No price for ${coin} yet.` };
  const fee = size * FEE, margin = size / lev;
  if (margin + fee > P.cash.Hyperliquid) return { ok: false, error: `Margin $${(margin + fee).toFixed(2)} exceeds the paper cash ($${P.cash.Hyperliquid.toFixed(2)}).` };
  const pos = { id: P.seq++, venue: "Hyperliquid", kind: "perp", market: coin, coin, side, size, lev, entry, qty: size / entry, margin, tp, sl, fee, openedAt: now };
  P.cash.Hyperliquid -= margin + fee; P.positions.push(pos); save();
  logEvent("info", "Hyperliquid", "Manual", "ORDER", `PAPER ${side} ${coin} $${size} x${lev} @ ${entry}`, now);
  return { ok: true, pos };
}

function closeOut(pos, exitPx, pnl, reason, cashBack, now) {
  P.positions = P.positions.filter((p) => p.id !== pos.id);
  P.cash[pos.venue] += cashBack;
  P.history.unshift({ ...pos, exitPx, pnl, reason, closedAt: now });
  if (P.history.length > 500) P.history.pop();
  save();
  logEvent(pnl >= 0 ? "info" : "warn", pos.venue, "Manual", "CLOSE", `PAPER ${pos.market} ${pos.side} closed (${reason}) ${pnl >= 0 ? "+" : "-"}$${Math.abs(pnl).toFixed(2)}`, now);
}

export function closePosition(feed, id, reason = "manual", now = Date.now()) {
  const pos = P.positions.find((p) => p.id === id);
  if (!pos) return { ok: false, error: "Position not found." };
  if (pos.kind === "bet") {
    if (now >= pos.endMs) return { ok: false, error: "The market has ended; it settles on its own." };
    const px = markOf(feed, pos), pnl = pos.shares * px - pos.stake;
    closeOut(pos, px, pnl, reason, pos.shares * px, now); return { ok: true };
  }
  const px = markOf(feed, pos), fee = pos.size * FEE, pnl = pnlOf(feed, pos) - pos.fee - fee;
  closeOut(pos, px, pnl, reason, pos.margin + pnlOf(feed, pos) - fee, now); return { ok: true };
}

// -- the loop ---------------------------------------------------------------------

export async function settleBet(pos, side, estimated, now = Date.now()) {
  if (!P.positions.some((p) => p.id === pos.id)) return;
  const won = pos.side.toLowerCase() === side, payout = won ? pos.shares : 0;
  closeOut(pos, won ? 1 : 0, payout - pos.stake, `resolved ${side.toUpperCase()}${estimated ? " (est. from BTC price)" : ""}`, payout, now);
}

export function tick(feed, env = defaultEnv()) {
  const now = env.now(); let changed = false;
  for (const pos of [...P.positions]) {
    if (pos.kind === "perp") {
      const pnl = pnlOf(feed, pos), pct = (pnl / pos.size) * 100;
      if (pnl <= -0.9 * pos.margin) { closeOut(pos, markOf(feed, pos), -pos.margin - pos.fee, "liquidated", 0, now); changed = true; }
      else if (pos.tp && pct >= pos.tp) { closePosition(feed, pos.id, "take profit", now); changed = true; }
      else if (pos.sl && pct <= -pos.sl) { closePosition(feed, pos.id, "stop loss", now); changed = true; }
    } else if (now >= pos.endMs && !pos.settling) {
      pos.settling = true;
      (async () => {
        const side = await fetchResolved(env, pos.slug);
        if (side) return settleBet(pos, side, false, env.now());
        if (env.now() < pos.endMs + 30000) { pos.settling = false; return; } // give Gamma time to settle
        const btc = feed.hl.btcMid ?? feed.hl.mids.BTC;
        if (pos.target && btc) return settleBet(pos, btc >= pos.target ? "up" : "down", true, env.now());
        pos.settling = false;
      })().then(() => emit());
    }
  }
  const last = P.curve.at(-1);
  if (!last || now - last.t >= 5000) { P.curve.push({ t: now, e: equity(feed), Polymarket: equity(feed, "Polymarket"), Hyperliquid: equity(feed, "Hyperliquid") }); if (P.curve.length > 3000) P.curve.shift(); changed = true; }
  if (changed) { save(); emit(); }
}
