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
