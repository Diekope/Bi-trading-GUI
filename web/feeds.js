// Live public feeds for the sandbox, ported from src/bi_trading/data/{feed,polymarket_feed,polymarket_data}.py.
// Parsers and dispatchers are pure so they can be tested without a socket (see test/feeds.test.mjs).

export const HL_INFO = "https://api.hyperliquid.xyz/info";
export const HL_WS = "wss://api.hyperliquid.xyz/ws";
export const GAMMA = "https://gamma-api.polymarket.com";
export const CLOB = "https://clob.polymarket.com";
export const PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market";
export const SLUG_PREFIX = "btc-updown-5m";
export const WINDOW_MS = 300000;
export const INTERVAL_MS = { "1m": 60e3, "3m": 180e3, "5m": 300e3, "15m": 900e3, "30m": 1800e3, "1h": 3600e3 };
const CANDLE_COUNT = 300;

// -- shared state and a small event log -------------------------------------

export const feed = {
  hl: { status: "off", error: "", coin: "HYPE", interval: "1m", series: {}, mids: {}, book: null, btcMid: null, latency: null, latSrc: "", lastLat: 0, account: null },
  pm: { status: "off", error: "", market: null, books: {}, trades: [], target: null, latency: null },
};
export const events = [];
const listeners = new Set();
export const onChange = (f) => listeners.add(f);
export const emit = () => listeners.forEach((f) => f());
export function logEvent(level, source, origin, event, message, now = Date.now()) {
  events.unshift({ t: now, level, source, origin, event, message });
  if (events.length > 500) events.pop();
  emit();
}

// -- parsing ------------------------------------------------------------------

const num = (v) => { if (v === null || v === undefined || v === "") return null; const n = Number(v); return Number.isFinite(n) ? n : null; };

export function parseCandles(rows) {
  if (!Array.isArray(rows)) return [];
  const out = [];
  for (const r of rows) {
    const t = num(r?.t), o = num(r?.o), h = num(r?.h), l = num(r?.l), c = num(r?.c);
    if ([t, o, h, l, c].some((x) => x === null)) continue;
    out.push({ t, o, h, l, c, v: num(r.v) ?? 0 });
  }
  return out.sort((a, b) => a.t - b.t);
}

export function parseMids(data) {
  const mids = data && typeof data === "object" ? data.mids : null, out = {};
  if (mids && typeof mids === "object") for (const [k, v] of Object.entries(mids)) { const n = num(v); if (n !== null) out[k] = n; }
  return out;
}

export function parseBBO(data) {
  const coin = String(data?.coin || ""), lv = data?.bbo;
  if (!coin || !Array.isArray(lv) || lv.length < 2) return null;
  const bid = num(lv[0]?.px), ask = num(lv[1]?.px);
  if (!bid || !ask || bid <= 0 || ask <= 0) return null;
  return [coin, (bid + ask) / 2];
}

export function parseHLBook(data) {
  const levels = Array.isArray(data?.levels) ? data.levels : [[], []];
  const lv = (rows) => (Array.isArray(rows) ? rows : []).map((r) => ({ px: num(r?.px), sz: num(r?.sz), n: num(r?.n) ?? 0 })).filter((x) => x.px !== null && x.sz !== null);
  return { coin: String(data?.coin || ""), bids: lv(levels[0]).sort((a, b) => b.px - a.px), asks: lv(levels[1]).sort((a, b) => a.px - b.px), ts: num(data?.time) ?? 0 };
}

export function jsonList(v) {
  if (Array.isArray(v)) return v;
  if (typeof v === "string" && v.trim()) { try { const p = JSON.parse(v); return Array.isArray(p) ? p : []; } catch { return []; } }
  return [];
}
const isoMs = (v) => { if (!v) return null; const t = Date.parse(String(v).trim()); return Number.isNaN(t) ? null : t; };

export const marketSlug = (nowMs) => `${SLUG_PREFIX}-${Math.floor(nowMs / 1000 / 300) * 300}`;
export function slugWindow(slug) {
  const i = slug.lastIndexOf("-"), prefix = slug.slice(0, i), stamp = slug.slice(i + 1);
  if (prefix !== SLUG_PREFIX || !/^\d+$/.test(stamp)) return null;
  const s = Number(stamp) * 1000;
  return [s, s + WINDOW_MS];
}

export function parseMarket(payload) {
  if (Array.isArray(payload)) payload = payload[0];
  if (!payload || typeof payload !== "object") return null;
  const tokens = jsonList(payload.clobTokenIds), names = jsonList(payload.outcomes), prices = jsonList(payload.outcomePrices);
  if (!tokens.length) return null;
  const outcomes = tokens.map((t, i) => ({ name: String(names[i] ?? `Outcome ${i + 1}`), token: String(t), price: num(prices[i]) ?? 0 }));
  const slug = String(payload.slug || ""), w = slugWindow(slug), end = isoMs(payload.endDate);
  let startMs, endMs;
  if (w) { startMs = w[0]; endMs = end ?? w[1]; } else { startMs = isoMs(payload.startDate) ?? 0; endMs = end ?? startMs + WINDOW_MS; }
  return { slug, question: String(payload.question || slug || "Polymarket"), startMs, endMs, outcomes, liquidity: num(payload.liquidity) ?? 0, volume: num(payload.volume) ?? 0, spread: num(payload.spread) ?? 0, tickSize: num(payload.orderPriceMinTickSize) ?? 0.01, acceptingOrders: payload.acceptingOrders === undefined ? true : !!payload.acceptingOrders };
}

// "up" / "down" once Polymarket has settled the market, else null (never a guess).
export function resolvedSide(payload) {
  if (Array.isArray(payload)) payload = payload[0];
  if (!payload || typeof payload !== "object" || !payload.closed) return null;
  const names = jsonList(payload.outcomes).map((n) => String(n).trim().toLowerCase()), prices = jsonList(payload.outcomePrices).map(num);
  if (prices.length < 2 || prices.some((p) => p === null)) return null;
  const won = prices.map((p, i) => (p >= 0.99 ? i : -1)).filter((i) => i >= 0);
  if (won.length !== 1) return null;
  const name = names[won[0]] ?? "";
  if (name === "up" || name === "down") return name;
  return won[0] === 0 ? "up" : "down";
}

const levels = (raw, desc) => (Array.isArray(raw) ? raw : []).map((x) => ({ price: num(x?.price), size: num(x?.size) })).filter((x) => x.price !== null && x.size !== null && x.size > 0).sort((a, b) => (desc ? b.price - a.price : a.price - b.price));
export function parsePMBook(p) {
  if (!p || typeof p !== "object") return null;
  const token = String(p.asset_id || p.token_id || "");
  if (!token) return null;
  return { token, bids: levels(p.bids, true), asks: levels(p.asks, false), ts: num(p.timestamp) ?? 0 };
}
export function parseChanges(msg) {
  if (!msg || typeof msg !== "object") return [];
  const ts = num(msg.timestamp) ?? 0, out = [];
  for (const it of Array.isArray(msg.price_changes) ? msg.price_changes : []) {
    const token = it?.asset_id, price = num(it?.price), size = num(it?.size), side = String(it?.side || "").toUpperCase();
    if (!token || price === null || size === null || (side !== "BUY" && side !== "SELL")) continue;
    out.push({ token: String(token), price, size, side, ts });
  }
  return out;
}
export function applyChange(book, ch) {
  const buy = ch.side === "BUY", list = (buy ? book.bids : book.asks).map((x) => ({ ...x }));
  const i = list.findIndex((x) => x.price === ch.price);
  if (i >= 0) { if (ch.size <= 0) list.splice(i, 1); else list[i].size = ch.size; } else if (ch.size > 0) list.push({ price: ch.price, size: ch.size });
  list.sort((a, b) => (buy ? b.price - a.price : a.price - b.price));
  return { ...book, bids: buy ? list : book.bids, asks: buy ? book.asks : list, ts: ch.ts || book.ts };
}
export function parseTrade(msg) {
  const token = msg?.asset_id, price = num(msg?.price);
  if (!token || price === null) return null;
  return { token: String(token), price, size: num(msg.size) ?? 0, side: String(msg.side || "").toUpperCase(), ts: num(msg.timestamp) ?? 0 };
}

// -- dispatch (pure apart from the held state) --------------------------------

export function dispatchHL(S, raw) {
  let m; try { m = typeof raw === "string" ? JSON.parse(raw) : raw; } catch { return false; }
  if (!m || typeof m !== "object") return false;
  const d = m.data;
  switch (m.channel) {
    case "allMids": Object.assign(S.mids, parseMids(d)); return true;
    case "bbo": { const u = parseBBO(d); if (u) { S.mids[u[0]] = u[1]; if (u[0] === "BTC") S.btcMid = u[1]; } return !!u; }
    case "l2Book": { const b = parseHLBook(d); if (b.coin && b.coin === S.coin) { S.book = b; return true; } return false; }
    case "candle": {
      const key = `${d?.s}|${d?.i}`, c = parseCandles([d])[0], arr = S.series[key];
      if (!c || !arr) return false;
      const last = arr.at(-1);
      if (last && last.t === c.t) arr[arr.length - 1] = c; else if (!last || c.t > last.t) { arr.push(c); if (arr.length > CANDLE_COUNT) arr.shift(); } else { const i = arr.findIndex((x) => x.t === c.t); if (i >= 0) arr[i] = c; }
      return true;
    }
    case "pong": if (S._pingAt) { S.latency = Math.round(S._now() - S._pingAt); S.latSrc = "ws"; S.lastLat = S._now(); S._pingAt = 0; } return true;
    case "error": S.error = String(d); return true;
    default: return false;
  }
}

export function dispatchPM(S, raw) {
  let p; try { p = typeof raw === "string" ? JSON.parse(raw) : raw; } catch { return false; }
  let dirty = false;
  for (const ev of Array.isArray(p) ? p : [p]) {
    if (!ev || typeof ev !== "object") continue;
    if (ev.event_type === "book") { const b = parsePMBook(ev); if (b) { S.books[b.token] = b; dirty = true; } }
    else if (ev.event_type === "price_change") { for (const ch of parseChanges(ev)) { const held = S.books[ch.token]; if (held) { S.books[ch.token] = applyChange(held, ch); dirty = true; } } }
    else if (ev.event_type === "last_trade_price") { const t = parseTrade(ev); if (t) { S.trades.unshift(t); if (S.trades.length > 30) S.trades.pop(); dirty = true; } }
  }
  return dirty;
}

// Read-only account summary from a public address (no key): POST info {type:"clearinghouseState", user}.
export function parseHLAccount(j) {
  const m = j?.marginSummary, v = num(m?.accountValue);
  return v === null ? null : { value: v, marginUsed: num(m.totalMarginUsed) ?? 0, notional: num(m.totalNtlPos) ?? 0 };
}
export const validAddress = (a) => /^0x[0-9a-fA-F]{40}$/.test(String(a || "").trim());

// -- connections ----------------------------------------------------------------

export const defaultEnv = () => ({ fetch: (...a) => fetch(...a), WebSocket: globalThis.WebSocket, now: () => Date.now(), setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (t) => clearTimeout(t), setInterval: (f, ms) => setInterval(f, ms), clearInterval: (t) => clearInterval(t) });
const sleep = (env, ms) => new Promise((r) => env.setTimeout(r, ms));
const hlPost = async (env, body) => { const r = await env.fetch(HL_INFO, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); };

export function startHL(env = defaultEnv()) {
  const S = feed.hl; S._now = env.now;
  let ws = null, stopped = false, tries = 0; const timers = [];
  const key = (c, i) => `${c}|${i}`;
  const wanted = () => {
    const subs = [{ type: "allMids" }, { type: "l2Book", coin: S.coin }, { type: "candle", coin: S.coin, interval: S.interval }, { type: "bbo", coin: "BTC" }];
    if (!(S.coin === "BTC" && S.interval === "1m")) subs.push({ type: "candle", coin: "BTC", interval: "1m" });
    return subs;
  };
  const send = (method, subscription) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ method, subscription })); };
  async function snapshot(coin, interval) {
    const now = env.now();
    try {
      const rows = await hlPost(env, { type: "candleSnapshot", req: { coin, interval, startTime: now - INTERVAL_MS[interval] * CANDLE_COUNT, endTime: now } });
      S.series[key(coin, interval)] = parseCandles(rows); emit();
    } catch (e) { S.error = `candles: ${e.message}`; logEvent("warn", "Hyperliquid", "—", "FEED", `candles ${coin} ${interval}: ${e.message}`, env.now()); }
  }
  function connect() {
    if (stopped) return;
    S.status = tries ? "reconnecting" : "connecting"; emit();
    ws = new env.WebSocket(HL_WS);
    ws.onopen = () => {
      tries = 0; S.status = "live"; S.error = ""; logEvent("info", "System", "—", "CONNECTION", "Hyperliquid connected", env.now());
      wanted().forEach((s) => send("subscribe", s));
    };
    ws.onmessage = (e) => { if (dispatchHL(S, e.data)) S._dirty = true; };
    ws.onclose = () => { if (stopped) return; S.status = "reconnecting"; logEvent("warn", "System", "—", "CONNECTION", "Hyperliquid disconnected", env.now()); tries++; env.setTimeout(connect, Math.min(15000, 500 * 2 ** tries)); emit(); };
    ws.onerror = () => { S.error = "websocket error"; };
  }
  async function refreshAccount() {
    const a = S.account; if (!a?.address) return;
    try { const r = parseHLAccount(await hlPost(env, { type: "clearinghouseState", user: a.address })); if (!r) throw new Error("unexpected response"); S.account = { ...a, ...r, error: "", at: env.now() }; }
    catch (e) { S.account = { ...a, error: e.message, at: env.now() }; }
    emit();
  }
  snapshot(S.coin, S.interval); snapshot("BTC", "1m"); connect();
  timers.push(env.setInterval(refreshAccount, 10000));
  timers.push(env.setInterval(() => { if (S._dirty) { S._dirty = false; emit(); } }, 250));
  timers.push(env.setInterval(() => { if (ws && ws.readyState === 1) { S._pingAt = env.now(); ws.send(JSON.stringify({ method: "ping" })); } }, 2000));
  // HTTP round trip as a fallback latency (the browser cannot send protocol pings).
  const httpProbe = async () => {
    if (env.now() - S.lastLat < 6000) return;
    const t0 = env.now(); try { await hlPost(env, { type: "candleSnapshot", req: { coin: "BTC", interval: "1m", startTime: t0 - 120000, endTime: t0 } }); S.latency = Math.round(env.now() - t0); S.latSrc = "http"; emit(); } catch { /* keep last */ }
  };
  httpProbe(); timers.push(env.setInterval(httpProbe, 5000));
  return {
    async setAddress(address) {
      address = String(address || "").trim();
      if (!address) { S.account = null; emit(); return { ok: true }; }
      if (!validAddress(address)) return { ok: false, error: "That is not a 0x address (42 characters)." };
      S.account = { address, value: null, error: "", at: 0 }; await refreshAccount();
      return S.account.error ? { ok: false, error: S.account.error } : { ok: true };
    },
    setWatch(coin, interval) {
      if (coin === S.coin && interval === S.interval) return;
      const old = { coin: S.coin, interval: S.interval }; S.coin = coin; S.interval = interval; S.book = null;
      send("unsubscribe", { type: "l2Book", coin: old.coin });
      if (!(old.coin === "BTC" && old.interval === "1m")) send("unsubscribe", { type: "candle", coin: old.coin, interval: old.interval });
      send("subscribe", { type: "l2Book", coin }); if (!(coin === "BTC" && interval === "1m")) send("subscribe", { type: "candle", coin, interval });
      if (!S.series[key(coin, interval)]) snapshot(coin, interval); emit();
    },
    stop() { stopped = true; timers.forEach((t) => env.clearInterval(t)); try { ws && ws.close(); } catch { /* closed */ } },
  };
}

async function fetchTarget(env, startMs) {
  try {
    const rows = parseCandles(await hlPost(env, { type: "candleSnapshot", req: { coin: "BTC", interval: "1m", startTime: startMs - 60000, endTime: startMs + 120000 } }));
    return (rows.find((c) => c.t === startMs) || rows.find((c) => c.t >= startMs))?.o ?? null;
  } catch { return null; }
}

export async function fetchResolved(env, slug) {
  try { const r = await env.fetch(`${GAMMA}/markets?slug=${encodeURIComponent(slug)}`); return r.ok ? resolvedSide(await r.json()) : null; } catch { return null; }
}

export function startPM(env = defaultEnv()) {
  const S = feed.pm; let stopped = false, ws = null; const timers = [];
  const probe = async () => { const t0 = env.now(); try { const r = await env.fetch(`${CLOB}/time`); if (r.ok) { S.latency = Math.round(env.now() - t0); emit(); } } catch { /* keep last */ } };
  probe(); timers.push(env.setInterval(probe, 5000));
  timers.push(env.setInterval(() => { if (S._dirty) { S._dirty = false; emit(); } }, 250));
  async function session(m) {
    const tokens = m.outcomes.map((o) => o.token);
    while (!stopped && env.now() < m.endMs) {
      await new Promise((resolve) => {
        let done = false; const fin = () => { if (!done) { done = true; env.clearTimeout(t); resolve(); } };
        ws = new env.WebSocket(PM_WS);
        const t = env.setTimeout(() => { try { ws.close(); } catch { /* closed */ } fin(); }, Math.max(0, m.endMs - env.now()) + 1000);
        ws.onopen = () => { ws.send(JSON.stringify({ assets_ids: tokens, type: "market" })); S.status = "live"; S.error = ""; logEvent("info", "System", "—", "CONNECTION", "Polymarket connected", env.now()); };
        ws.onmessage = (e) => { if (dispatchPM(S, e.data)) S._dirty = true; };
        ws.onclose = () => { if (env.now() < m.endMs && !stopped) { S.status = "reconnecting"; logEvent("warn", "System", "—", "CONNECTION", "Polymarket reconnecting", env.now()); } fin(); };
        ws.onerror = () => { S.error = "websocket error"; };
      });
      if (!stopped && env.now() < m.endMs) await sleep(env, 1000);
    }
  }
  (async () => {
    while (!stopped) {
      const slug = marketSlug(env.now());
      try {
        S.status = "connecting"; emit();
        const r = await env.fetch(`${GAMMA}/markets?slug=${encodeURIComponent(slug)}`); if (!r.ok) throw new Error("HTTP " + r.status);
        const m = parseMarket(await r.json());
        if (!m) { S.error = "market not listed yet"; await sleep(env, 2000); continue; }
        S.market = m; S.books = {}; S.trades = []; S.target = null; emit();
        fetchTarget(env, m.startMs).then((t) => { S.target = t; emit(); });
        await session(m);
      } catch (e) {
        S.status = "error"; S.error = e.message || String(e); logEvent("error", "Polymarket", "—", "FEED", `market ${slug}: ${S.error}`, env.now()); emit();
        await sleep(env, 4000);
      }
    }
  })();
  return { stop() { stopped = true; timers.forEach((t) => env.clearInterval(t)); try { ws && ws.close(); } catch { /* closed */ } } };
}
