// The rule model the Builder's three views share: node --test test/rule.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { tokenize, join, toLines, fromLines, toRows, fromRows, insertion, kind, sayRule } from "../rule.js";

test("tokenize and join round-trip the engine's syntax", () => {
  const src = "band = bollinger_lower(close, 20, 2)\nclose < band and volume > 0";
  assert.deepEqual(tokenize("sma(close,20)>=1.5"), ["sma", "(", "close", ",", "20", ")", ">=", "1.5"]);
  assert.equal(fromLines(toLines(src)), src);
  assert.equal(join(tokenize("pnl <= -30 or x>-1")), "pnl <= -30 or x > -1");
  assert.equal(join(tokenize("close - open")), "close - open");
});

test("rows read a flat and/or rule and write it back", () => {
  const r = toRows("body = close - open\nminute >= 2 and up_price < 0.4 and body > 0");
  assert.deepEqual(r.vars, [{ name: "body", expr: "close - open" }]);
  assert.equal(r.join, "and");
  assert.deepEqual(r.rows[1], ["up_price", "<", "0.4"]);
  assert.equal(fromRows(r), "body = close - open\nminute >= 2 and up_price < 0.4 and body > 0");
  assert.equal(toRows("pnl >= 25 or pnl <= -30").join, "or");
  assert.deepEqual(toRows("sma(close, 20) > close").rows[0], ["sma(close, 20)", ">", "close"]);
});

test("rows refuse what they cannot show", () => {
  assert.equal(toRows("a > 1 and b > 2 or c > 3"), null);
  assert.equal(toRows("not close > open"), null);
  assert.ok(toRows("(a > 1 or b > 2) and c > 3") === null);
});

test("half-typed rows are left out of the text", () => {
  assert.equal(fromRows({ vars: [{ name: "v1", expr: "" }], join: "and", rows: [["close", ">", "open"], ["", ">", ""]] }), "close > open");
});

test("blocks", () => {
  assert.deepEqual(insertion("bollinger_upper"), ["bollinger_upper", "(", "close", ",", "20", ",", "2", ")"]);
  assert.equal(kind("up_price"), "pmv");
  assert.equal(kind("band", ["band"]), "var");
  assert.equal(kind("or"), "kw");
});

test("a rule in plain words", () => {
  assert.equal(sayRule("body = close - open\nminute >= 2 and body > 0", "Bet UP when"), "Let body be the close − the open. Bet UP when the minute is at least 2 and body is above 0.");
  assert.equal(sayRule("close < bollinger_lower(close, 20, 2)", "Buy when"), "Buy when the close is below the lower Bollinger band of the close (20 bars, 2σ).");
  assert.equal(sayRule("pnl <= -sl or pnl <= -30", "Sell when"), "Sell when the trade's gain (%) is at most minus the stop loss or the trade's gain (%) is at most -30.");
  assert.equal(sayRule("", "When"), "");
});
