// A rule as the engine reads it (src/bi_trading/engine/formula.py): `name = expr` lines, then one condition.
// The text is the one source of truth; Formula (blocks) and Rules (rows) are views of it that write it back.

export const FUNCS = { abs: 1, sqrt: 1, log: 1, min: 2, max: 2, sma: 2, ema: 2, rsi: 2, highest: 2, lowest: 2, stdev: 2, zscore: 2, change: 2, shift: 2, bollinger_lower: 3, bollinger_middle: 3, bollinger_upper: 3 };
export const EXIT_FUNCS = ["abs", "sqrt", "min", "max"];
export const OPS = ["<", "<=", ">", ">=", "==", "!="];
export const PM_WORDS = ["up_price", "down_price", "minute", "seconds_left"];
const COMPARE = new Set(OPS);
const NAME = /^[A-Za-z_]\w*$/;
const TOK = /(#[^\n]*)|(\d+\.\d*|\.\d+|\d+)|([A-Za-z_]\w*)|(<=|>=|==|!=|[<>+\-*/%^=(),])/y;

export function tokenize(line) {
  const out = [];
  let i = 0;
  while (i < line.length) {
    if (/\s/.test(line[i])) { i++; continue; }
    TOK.lastIndex = i;
    const m = TOK.exec(line);
    if (!m) { out.push(line[i]); i++; continue; }   // a character the engine will refuse: kept so it shows
    if (!m[1]) out.push(m[0]);
    i = TOK.lastIndex;
  }
  return out;
}

const opener = (p) => p === undefined || COMPARE.has(p) || ["+", "-", "*", "/", "%", "^", "=", "(", ",", "and", "or", "not"].includes(p);
export function join(t) {
  let s = "";
  t.forEach((x, i) => {
    const p = t[i - 1];
    const tight = i === 0 || x === ")" || x === "," || p === "(" || (x === "(" && p in FUNCS) || (p === "-" && opener(t[i - 2]));
    s += (tight ? "" : " ") + x;
  });
  return s;
}

export const lines = (text) => String(text ?? "").split(/\n|;/).map((l) => l.trim()).filter(Boolean);
export const toLines = (text) => lines(text).map(tokenize);
export const fromLines = (ls) => ls.map(join).filter(Boolean).join("\n");
export const isAssign = (toks) => toks.length >= 2 && NAME.test(toks[0]) && toks[1] === "=";
export const assigned = (ls) => ls.filter(isAssign).map((t) => t[0]);

export function kind(tok, vars = []) {
  if (["and", "or", "not"].includes(tok)) return "kw";
  if (/^[\d.]/.test(tok)) return "math";
  if (tok in FUNCS) return "ind";
  if (vars.includes(tok)) return "var";
  if (PM_WORDS.includes(tok)) return "pmv";
  if (NAME.test(tok)) return "data";
  return "math";
}

// What a palette block drops: a function brings its brackets and sensible arguments.
export function insertion(word) {
  const n = FUNCS[word];
  if (!n) return [word];
  return n === 1 ? [word, "(", "close", ")"] : n === 2 ? [word, "(", "close", ",", "20", ")"] : [word, "(", "close", ",", "20", ",", "2", ")"];
}

// -- the Rules view: variables, and conditions all joined by `and` or all by `or` --------

function splitTop(toks, words) {
  const parts = [[]], seps = [];
  let depth = 0;
  for (const t of toks) {
    if (t === "(") depth++;
    if (t === ")") depth--;
    if (depth === 0 && words.includes(t)) { seps.push(t); parts.push([]); } else parts[parts.length - 1].push(t);
  }
  return { parts, seps };
}

// null when the condition does not fit rows (mixed and/or, `not`, brackets around a comparison...).
export function toRows(text) {
  const ls = toLines(text);
  const condLine = ls.length && !isAssign(ls[ls.length - 1]) ? ls[ls.length - 1] : [];
  const vars = ls.filter(isAssign).map((t) => ({ name: t[0], expr: join(t.slice(2)) }));
  if (ls.filter((t) => !isAssign(t)).length > 1) return null;
  if (!condLine.length) return { vars, join: "and", rows: [] };
  const { parts, seps } = splitTop(condLine, ["and", "or"]);
  if (new Set(seps).size > 1) return null;
  const rows = [];
  for (const p of parts) {
    if (p.includes("not")) return null;
    const { parts: sides, seps: ops } = splitTop(p, OPS);
    if (ops.length !== 1 || !sides[0].length || !sides[1].length) return null;
    rows.push([join(sides[0]), ops[0], join(sides[1])]);
  }
  return { vars, join: seps[0] || "and", rows };
}

export function fromRows({ vars, join: j, rows }) {
  const out = vars.filter((v) => v.name.trim() && v.expr.trim()).map((v) => `${v.name.trim()} = ${v.expr.trim()}`);
  const cond = rows.filter((r) => r[0].trim() && r[2].trim()).map((r) => `${r[0].trim()} ${r[1]} ${r[2].trim()}`).join(` ${j} `);
  if (cond) out.push(cond);
  return out.join("\n");
}

// -- the rule in plain words ---------------------------------------------------------------

const WORDS = {
  open: "the open", high: "the high", low: "the low", close: "the close", volume: "the volume", price: "the price",
  up_price: "the UP price", down_price: "the DOWN price", minute: "the minute", seconds_left: "the seconds left",
  pnl: "the trade's gain (%)", entry: "the entry price", tp: "the take profit", sl: "the stop loss", bars: "the bars held",
  model_p: "the model's P(up)", funding: "the funding", oi: "the open interest", spread: "the spread", liquidity: "the liquidity", days_left: "the days left",
};
const SAY_OP = { "<": "is below", "<=": "is at most", ">": "is above", ">=": "is at least", "==": "equals", "!=": "is not", "+": "+", "-": "−", "*": "×", "/": "÷", "%": "mod", "^": "to the power" };
const SAY_FN = {
  sma: ([x, n]) => `the ${n}-bar average of ${x}`, ema: ([x, n]) => `the ${n}-bar exponential average of ${x}`, rsi: ([x, n]) => `the ${n}-bar RSI of ${x}`,
  highest: ([x, n]) => `the highest ${x.replace(/^the /, "")} of the last ${n} bars`, lowest: ([x, n]) => `the lowest ${x.replace(/^the /, "")} of the last ${n} bars`,
  stdev: ([x, n]) => `the ${n}-bar deviation of ${x}`, zscore: ([x, n]) => `the ${n}-bar z-score of ${x}`, change: ([x, n]) => `the change in ${x.replace(/^the /, "")} over ${n} bars`,
  shift: ([x, n]) => `${x} ${n} bars ago`, abs: ([x]) => `the size of ${x}`, sqrt: ([x]) => `the square root of ${x}`, log: ([x]) => `the log of ${x}`,
  min: ([a, b]) => `the smaller of ${a} and ${b}`, max: ([a, b]) => `the larger of ${a} and ${b}`,
  bollinger_lower: ([x, n, d]) => `the lower Bollinger band of ${x} (${n} bars, ${d}σ)`, bollinger_middle: ([x, n, d]) => `the middle Bollinger band of ${x} (${n} bars, ${d}σ)`, bollinger_upper: ([x, n, d]) => `the upper Bollinger band of ${x} (${n} bars, ${d}σ)`,
};
const tag = (k, t, html) => (html ? `<span class="nl-${k}">${t}</span>` : t);

// One line of tokens as words; `vars` are the user's own names, shown as they are.
export function sayTokens(toks, vars = [], html = false) {
  let i = 0;
  const expr = (stop = []) => {
    const out = [];
    while (i < toks.length && !stop.includes(toks[i])) {
      const t = toks[i];
      if (t in FUNCS && toks[i + 1] === "(") {
        i += 2; const args = [];
        while (i < toks.length && toks[i] !== ")") { args.push(expr([",", ")"])); if (toks[i] === ",") i++; }
        i++; out.push(tag("fn", (SAY_FN[t] || ((a) => `${t}(${a.join(", ")})`))(args), html));
      } else if (t === "(") { i++; out.push(`(${expr([")"])})`); i++; }
      else if (t === "-" && opener(toks[i - 1])) {   // a sign, not a subtraction
        if (/^[\d.]/.test(toks[i + 1] ?? "")) { out.push(tag("num", "-" + toks[i + 1], html)); i += 2; } else { out.push("minus"); i++; }
      }
      else if (["and", "or", "not"].includes(t)) { out.push(tag("kw", t, html)); i++; }
      else if (t in SAY_OP) { out.push(tag(COMPARE.has(t) ? "op" : "math", SAY_OP[t], html)); i++; }
      else if (vars.includes(t)) { out.push(tag("var", t, html)); i++; }
      else if (t in WORDS) { out.push(tag(PM_WORDS.includes(t) ? "pm" : "data", WORDS[t], html)); i++; }
      else { const safe = html ? t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") : t; out.push(tag(/^[\d.]/.test(t) ? "num" : "data", safe, html)); i++; }
    }
    return out.join(" ");
  };
  return expr();
}

// The whole rule: "Let body be the close − the open. Bet UP when ..."
export function sayRule(text, when = "When", html = false) {
  const ls = toLines(text), vars = assigned(ls);
  if (!ls.length) return "";
  return ls.map((t) => (isAssign(t) ? `Let ${tag("var", t[0], html)} be ${sayTokens(t.slice(2), vars, html)}.` : `${when} ${sayTokens(t, vars, html)}.`)).join(html ? "<br>" : " ");
}
