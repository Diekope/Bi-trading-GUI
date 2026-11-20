import test from "node:test";
import assert from "node:assert/strict";
import * as F from "../feeds.js";
import * as P from "../paper.js";

class FakeWS { constructor(url) { this.url = url; this.sent = []; this.readyState = 0; FakeWS.all.push(this); setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0); }
  send(m) { this.sent.push(JSON.parse(m)); } close() { this.readyState = 3; this.onclose?.(); } emit(o) { this.onmessage?.({ data: JSON.stringify(o) }); } }
FakeWS.all = [];
const wait = (ms = 20) => new Promise((r) => setTimeout(r, ms));
const env = (fetchImpl) => ({ ...F.defaultEnv(), WebSocket: FakeWS, fetch: fetchImpl });
const json = (o) => ({ ok: true, json: async () => o });

test("parsers", () => {
  assert.deepEqual(F.parseCandles([{ t: 2, o: "1", h: "2", l: "0.5", c: "1.5", v: "3" }, { t: 1, o: "1", h: "1", l: "1", c: "1" }, { bad: 1 }]).map((c) => c.t), [1, 2]);
  assert.deepEqual(F.parseMids({ mids: { BTC: "75000.5", X: "nope" } }), { BTC: 75000.5 });
  assert.deepEqual(F.parseBBO({ coin: "BTC", bbo: [{ px: "100" }, { px: "102" }] }), ["BTC", 101]);
  const b = F.parseHLBook({ coin: "HYPE", levels: [[{ px: "1", sz: "2", n: 1 }, { px: "2", sz: "1", n: 1 }], [{ px: "4", sz: "1" }, { px: "3", sz: "1" }]], time: 5 });
  assert.equal(b.bids[0].px, 2); assert.equal(b.asks[0].px, 3);
  assert.equal(F.marketSlug(1700000123456), "btc-updown-5m-1700000100");
  assert.deepEqual(F.slugWindow("btc-updown-5m-1699999800"), [1699999800000, 1700000100000]);
  const m = F.parseMarket([{ slug: "btc-updown-5m-1699999800", question: "Q", clobTokenIds: '["a","b"]', outcomes: '["Up","Down"]', outcomePrices: '["0.8","0.2"]', liquidity: "1000", endDate: "2023-11-14T22:15:00Z" }]);
  assert.equal(m.outcomes[1].token, "b"); assert.equal(m.liquidity, 1000); assert.equal(m.startMs, 1699999800000);
  assert.equal(F.resolvedSide({ closed: true, outcomes: '["Up","Down"]', outcomePrices: '["0","1"]' }), "down");
  assert.equal(F.resolvedSide({ closed: true, outcomes: '["Up","Down"]', outcomePrices: '["0.6","0.4"]' }), null);
  assert.equal(F.resolvedSide({ closed: false, outcomes: '["Up","Down"]', outcomePrices: '["1","0"]' }), null);
});

test("dispatch HL candle upsert and book", () => {
  const S = { coin: "HYPE", series: { "HYPE|1m": [{ t: 1, o: 1, h: 1, l: 1, c: 1, v: 0 }] }, mids: {}, book: null };
  F.dispatchHL(S, JSON.stringify({ channel: "candle", data: { s: "HYPE", i: "1m", t: 1, o: "1", h: "2", l: "1", c: "2", v: "5" } }));
  F.dispatchHL(S, JSON.stringify({ channel: "candle", data: { s: "HYPE", i: "1m", t: 2, o: "2", h: "2", l: "2", c: "2", v: "1" } }));
  assert.equal(S.series["HYPE|1m"].length, 2); assert.equal(S.series["HYPE|1m"][0].c, 2);
  F.dispatchHL(S, JSON.stringify({ channel: "l2Book", data: { coin: "HYPE", levels: [[{ px: "1", sz: "1" }], [{ px: "2", sz: "1" }]] } }));
  assert.equal(S.book.asks[0].px, 2);
});

test("dispatch PM book, change, trade", () => {
  const S = { books: {}, trades: [] };
  F.dispatchPM(S, [{ event_type: "book", asset_id: "a", bids: [{ price: "0.5", size: "10" }, { price: "0.6", size: "5" }], asks: [{ price: "0.9", size: "5" }, { price: "0.7", size: "5" }], timestamp: "1" }]);
  assert.equal(S.books.a.bids[0].price, 0.6); assert.equal(S.books.a.asks[0].price, 0.7);
  F.dispatchPM(S, { event_type: "price_change", timestamp: "2", price_changes: [{ asset_id: "a", price: "0.7", size: "0", side: "SELL" }, { asset_id: "a", price: "0.65", size: "3", side: "SELL" }] });
  assert.deepEqual(S.books.a.asks.map((x) => x.price), [0.65, 0.9]);
  F.dispatchPM(S, { event_type: "last_trade_price", asset_id: "a", price: "0.65", size: "2", side: "BUY", timestamp: "3" });
  assert.equal(S.trades[0].price, 0.65);
  assert.equal(F.dispatchPM(S, "PONG"), false);
});

test("startHL subscribes and loads candles", async () => {
  FakeWS.all.length = 0; const posts = [];
  const h = F.startHL(env(async (url, o) => { posts.push(JSON.parse(o.body)); return json([{ t: 1, o: "1", h: "1", l: "1", c: "1", v: "1" }]); }));
  await wait(); const ws = FakeWS.all[0];
  assert.equal(F.feed.hl.status, "live"); assert.equal(ws.url, F.HL_WS);
  assert.ok(ws.sent.some((m) => m.method === "subscribe" && m.subscription.type === "l2Book" && m.subscription.coin === "HYPE"));
  assert.ok(ws.sent.some((m) => m.subscription.type === "candle" && m.subscription.coin === "BTC"));
  assert.ok(posts.some((p) => p.type === "candleSnapshot" && p.req.coin === "HYPE"));
  assert.equal(F.feed.hl.series["HYPE|1m"].length, 1);
  h.setWatch("ETH", "5m");
  assert.ok(ws.sent.some((m) => m.method === "unsubscribe" && m.subscription.coin === "HYPE"));
  assert.ok(ws.sent.some((m) => m.method === "subscribe" && m.subscription.coin === "ETH" && m.subscription.interval === "5m"));
  h.stop();
});

let pmHandle;
test("startPM resolves the market and subscribes", async () => {
  FakeWS.all.length = 0; let slugAsked = "";
  const end = (Math.floor(Date.now() / 300000) + 1) * 300000;
  pmHandle = F.startPM(env(async (url) => {
    if (url.includes("gamma")) { slugAsked = new URL(url).searchParams.get("slug"); return json([{ slug: slugAsked, question: "BTC up?", clobTokenIds: '["tu","td"]', outcomes: '["Up","Down"]', outcomePrices: '["0.8","0.2"]', acceptingOrders: true, endDate: new Date(end).toISOString() }]); }
    return json([{ t: end - 300000, o: "75726", h: "1", l: "1", c: "1", v: "1" }]);
  }));
  await wait(60); const ws = FakeWS.all.find((w) => w.url === F.PM_WS);
  assert.ok(slugAsked.startsWith("btc-updown-5m-")); assert.deepEqual(ws.sent[0], { assets_ids: ["tu", "td"], type: "market" });
  assert.equal(F.feed.pm.status, "live"); assert.equal(F.feed.pm.target, 75726);
  ws.emit([{ event_type: "book", asset_id: "tu", bids: [{ price: "0.80", size: "100" }], asks: [{ price: "0.81", size: "100" }, { price: "0.83", size: "100" }] }]);
  assert.equal(F.feed.pm.books.tu.asks[0].price, 0.81);
});

test("paper: PM bet fills through the book and settles", async () => {
  const feed = F.feed; P.resetPaper();
  const r = P.placePM(feed, "UP", 100);
  assert.ok(r.ok, r.error); assert.ok(r.pos.entry > 0.81 && r.pos.entry < 0.83); assert.equal(P.P.cash.Polymarket, 900); const sh = r.pos.shares; assert.ok(Math.abs(sh * r.pos.entry - 100) < 1e-9);
  assert.ok(P.pnlOf(feed, r.pos) < 0); // marked at the 0.80 bid
  await P.settleBet(r.pos, "up", false);
  assert.equal(P.P.positions.length, 0); assert.ok(Math.abs(P.P.cash.Polymarket - (900 + sh)) < 1e-6);
  const big = P.placePM(feed, "UP", 900); assert.ok(!big.ok); assert.match(big.error, /depth/);
  assert.ok(!P.placePM(feed, "UP", 5000).ok);
});

test("read-only HL account", async () => {
  assert.deepEqual(F.parseHLAccount({ marginSummary: { accountValue: "13109.48", totalMarginUsed: "100", totalNtlPos: "500" } }), { value: 13109.48, marginUsed: 100, notional: 500 });
  assert.equal(F.parseHLAccount({}), null); assert.ok(F.validAddress("0x" + "a".repeat(40))); assert.ok(!F.validAddress("0x123"));
  const posts = []; const h = F.startHL(env(async (u, o) => { const b = JSON.parse(o.body); posts.push(b); return b.type === "clearinghouseState" ? json({ marginSummary: { accountValue: "42.5", totalMarginUsed: "1", totalNtlPos: "2" } }) : json([]); }));
  const bad = await h.setAddress("nope"); assert.ok(!bad.ok);
  const ok = await h.setAddress("0x" + "b".repeat(40)); assert.ok(ok.ok); assert.equal(F.feed.hl.account.value, 42.5);
  assert.ok(posts.some((p) => p.type === "clearinghouseState" && p.user === "0x" + "b".repeat(40)));
  await h.setAddress(""); assert.equal(F.feed.hl.account, null); h.stop();
});

test("paper: HL long fills on the ask, TP closes it, fees counted", () => {
  const feed = F.feed; P.resetPaper(); const S = feed.hl; S.status = "live"; S.coin = "HYPE";
  S.book = { coin: "HYPE", bids: [{ px: 99, sz: 100 }], asks: [{ px: 100, sz: 5 }, { px: 101, sz: 100 }] }; S.mids.HYPE = 100;
  const r = P.placeHL(feed, { coin: "HYPE", side: "Long", size: 1000, lev: 5, tp: 2, sl: 1 });
  assert.ok(r.ok, r.error); assert.ok(r.pos.entry > 100 && r.pos.entry < 101); // walked 500 at 100 then 500 at 101
  assert.ok(Math.abs(P.P.cash.Hyperliquid - (10000 - 200 - 0.6)) < 1e-9);
  S.book = { coin: "HYPE", bids: [{ px: 104, sz: 100 }], asks: [{ px: 105, sz: 100 }] };
  P.tick(feed); assert.equal(P.P.positions.length, 0);
  assert.equal(P.P.history[0].reason, "take profit"); assert.ok(P.P.history[0].pnl > 0);
  const eq = P.equity(feed, "Hyperliquid"); assert.ok(eq > 10000);
  // stop loss and liquidation
  S.book = { coin: "HYPE", bids: [{ px: 99, sz: 100 }], asks: [{ px: 100, sz: 100 }] };
  P.placeHL(feed, { coin: "HYPE", side: "Short", size: 1000, lev: 20, sl: 0 });
  S.book = { coin: "HYPE", bids: [{ px: 110, sz: 100 }], asks: [{ px: 111, sz: 100 }] };
  P.tick(feed); assert.equal(P.P.history[0].reason, "liquidated"); assert.ok(P.P.cash.Hyperliquid < 10000);
});

test.after(() => { pmHandle?.stop(); setTimeout(() => process.exit(0), 50); });
