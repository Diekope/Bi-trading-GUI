// The Builder's Formula (blocks) and Rules (rows) views. Both read the rule text and write it back,
// so Code, Formula and Rules always show the same rule.
import { toLines, fromLines, tokenize, kind, insertion, assigned, isAssign, toRows, fromRows, sayRule, FUNCS, EXIT_FUNCS, OPS } from "./rule.js";

// "BET UP WHEN" -> "Bet UP when"
const sentence = (w) => w.toLowerCase().replace(/^./, (c) => c.toUpperCase()).replace(/\b(up|down)\b/g, (m) => m.toUpperCase());
export const plain = (ctx, empty) => `<div class="nl">${sayRule(ctx.text, sentence(ctx.when), true) || `<span class="muted">${empty}</span>`}</div>`;

const esc = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const MATHS = ["+", "-", "*", "/", "(", ")", ",", "<", "<=", ">", ">=", "==", "!="];
const LOGIC = ["and", "or", "not"];

// ctx: { text, setText(t), groups: {title: [words]}, exit: bool, badge: html, key: "<strategy>|<field>" }
let C = null;
export const sel = { key: "", line: -1, i: -1 };   // the selected block
const drafts = {};                               // Rules rows being typed, by strategy and rule

// -- Formula: lines of draggable blocks ----------------------------------------------------

const block = (t, k, attrs = "") => `<span class="chip ${k}" draggable="true" ${attrs}>${esc(t)}</span>`;

export function formulaView(ctx) {
  C = ctx;
  if (sel.key !== ctx.key) Object.assign(sel, { key: ctx.key, line: -1, i: -1 });
  const ls = toLines(ctx.text), vars = assigned(ls);
  if (!ls.length || isAssign(ls[ls.length - 1])) ls.push([]);   // there is always a condition line to drop on
  const fns = ctx.exit ? EXIT_FUNCS : Object.keys(FUNCS);
  const groups = { ...(vars.length ? { Variables: vars } : {}), ...ctx.groups, Functions: fns, Maths: MATHS, Logic: LOGIC };
  const palette = Object.entries(groups).map(([g, a]) => `<div class="cap" style="margin:10px 0 4px;font-size:10px;letter-spacing:.1em">${g.toUpperCase()}</div><div class="chips">${a.map((x) => block(x, g === "Variables" ? "var" : g === "Functions" ? "ind" : g === "Logic" ? "kw" : g === "Maths" ? "math" : kind(x, vars), `data-ins='${esc(JSON.stringify(insertion(x)))}' title="drag into a line, or click to add it after the selected block"`)).join("")}</div>`).join("");
  const line = (toks, L) => {
    const cond = L === ls.length - 1 && !isAssign(toks);
    return `<div class="fline"><div class="row between"><b class="accent" style="font-size:10px">${cond ? ctx.when : "VARIABLE"}</b>${cond ? "" : `<button class="btn sm" data-act="f-delline-${L}" title="remove this line">×</button>`}</div>
      <div class="well chips dropline" data-line="${L}" style="background:var(--well);min-height:34px">${toks.map((t, i) => block(t, kind(t, vars) + (sel.line === L && sel.i === i ? " picked" : ""), `data-at="${L}:${i}"`)).join("") || `<span class="cap">drop blocks here</span>`}</div></div>`;
  };
  const cur = ls[sel.line]?.[sel.i];
  return `<div class="grid grow" style="grid-template-columns:200px 1fr 200px;min-height:0;gap:8px">
    <div class="well scroll" style="background:var(--inner)"><b class="sec" style="font-size:10px">Blocks</b>${palette}</div>
    <div class="well scroll" style="display:grid;gap:10px;align-content:start"><b class="sec" style="font-size:10px">Formula</b>
      ${ls.map(line).join("")}
      <div class="row"><button class="btn sm" data-act="f-addvar">+ Add variable</button><span class="sp"></span><input type="text" data-fnum placeholder="a number, e.g. 20 or 0.05" style="width:170px"><button class="btn sm" data-act="f-addnum">+ Add</button><button class="btn sm" data-act="f-clear" title="empty the condition line">⟲ Clear</button></div>
      <div class="well" style="background:var(--well);display:grid;gap:6px"><span class="cap" style="font-size:10px;letter-spacing:.1em">DESCRIPTION</span>${plain(ctx, "No rule yet: drag blocks into the lines above.")}${ctx.badge}</div></div>
    <div class="well" style="display:flex;flex-direction:column;gap:8px"><b class="sec" style="font-size:10px">Selected block</b>${cur == null ? `<div class="cap">click a block in a line to edit, move or remove it. Drag blocks to reorder them, or drop them on another line.</div>`
      : `<input type="text" data-fedit value="${esc(cur)}" style="font-family:var(--mono)"><span class="cap">${kind(cur, vars) === "ind" ? "a function" : kind(cur, vars) === "var" ? "your variable" : kind(cur, vars) === "math" ? "a number or an operator" : kind(cur, vars) === "kw" ? "logic" : "a value from the data"}</span><div class="row"><button class="btn sm" data-act="f-left" title="move left">←</button><button class="btn sm" data-act="f-right" title="move right">→</button><span class="sp"></span><button class="btn sm down" data-act="f-del">Remove</button></div>`}</div></div>`;
}

function edit(fn) {
  const ls = toLines(C.text);
  if (!ls.length || isAssign(ls[ls.length - 1])) ls.push([]);
  fn(ls);
  C.setText(fromLines(ls));
}

const at = (s) => s.split(":").map(Number);

// Clicks on blocks and buttons; true when handled.
export function formulaClick(el) {
  if (!C) return false;
  const chip = el.closest("[data-at],[data-ins]");
  if (chip?.dataset.at) { const [L, i] = at(chip.dataset.at); Object.assign(sel, { line: L, i }); return true; }
  if (chip?.dataset.ins) {
    const ins = JSON.parse(chip.dataset.ins);
    edit((ls) => { const L = sel.line >= 0 ? sel.line : ls.length - 1, i = sel.line >= 0 ? sel.i + 1 : ls[L].length; ls[L].splice(i, 0, ...ins); Object.assign(sel, { line: L, i: i + ins.length - 1 }); });
    return true;
  }
  const a = el.closest("[data-act]")?.dataset.act;
  if (!a?.startsWith("f-")) return false;
  if (a === "f-addvar") edit((ls) => { const used = new Set(assigned(ls)); let n = 1; while (used.has("v" + n)) n++; ls.splice(ls.length - 1, 0, ["v" + n, "=", "close"]); });
  else if (a.startsWith("f-delline-")) { const L = +a.slice(10); edit((ls) => ls.splice(L, 1)); Object.assign(sel, { line: -1, i: -1 }); }
  else if (a === "f-clear") { edit((ls) => { ls[ls.length - 1] = []; }); Object.assign(sel, { line: -1, i: -1 }); }
  else if (a === "f-addnum") {
    const box = document.querySelector("[data-fnum]"), v = box?.value.trim();
    if (!v) return true;
    edit((ls) => { const L = sel.line >= 0 ? sel.line : ls.length - 1, i = sel.line >= 0 ? sel.i + 1 : ls[L].length; ls[L].splice(i, 0, ...tokenize(v)); });
    box.value = "";
  } else if (sel.line >= 0) {
    edit((ls) => {
      const row = ls[sel.line];
      if (!row) return;
      if (a === "f-del") { row.splice(sel.i, 1); sel.i = Math.min(sel.i, row.length - 1); if (sel.i < 0) sel.line = -1; }
      if (a === "f-left" && sel.i > 0) { [row[sel.i - 1], row[sel.i]] = [row[sel.i], row[sel.i - 1]]; sel.i--; }
      if (a === "f-right" && sel.i < row.length - 1) { [row[sel.i + 1], row[sel.i]] = [row[sel.i], row[sel.i + 1]]; sel.i++; }
    });
  }
  return true;
}

export function formulaInput(el) {
  if (!C || !el.matches("[data-fedit]") || sel.line < 0) return false;
  const v = tokenize(el.value);
  edit((ls) => { if (ls[sel.line] && v.length === 1) ls[sel.line][sel.i] = v[0]; });   // one block stays one block
  return true;
}

// Drag and drop: from the palette (a copy) or from a line (a move), onto any line.
let marker = null;
function dropIndex(zone, x, y) {
  const chips = [...zone.querySelectorAll("[data-at]")];
  for (let k = 0; k < chips.length; k++) {
    const r = chips[k].getBoundingClientRect();
    if (y < r.top) return k;
    if (y <= r.bottom && x < r.left + r.width / 2) return k;
  }
  return chips.length;
}
function showMarker(zone, k) {
  marker?.classList.remove("drop-before", "drop-after");
  const chips = zone.querySelectorAll("[data-at]");
  marker = chips[k] || chips[chips.length - 1] || null;
  marker?.classList.add(chips[k] ? "drop-before" : "drop-after");
}
export function installDnD(render) {
  document.addEventListener("dragstart", (e) => {
    const c = e.target.closest?.("[data-at],[data-ins]");
    if (!c || !C) return;
    e.dataTransfer.setData("text/plain", JSON.stringify(c.dataset.at ? { from: at(c.dataset.at) } : { ins: JSON.parse(c.dataset.ins) }));
    e.dataTransfer.effectAllowed = c.dataset.at ? "move" : "copy";
  });
  document.addEventListener("dragover", (e) => {
    const zone = e.target.closest?.(".dropline");
    if (!zone) return;
    e.preventDefault();
    zone.classList.add("over");
    showMarker(zone, dropIndex(zone, e.clientX, e.clientY));
  });
  document.addEventListener("dragleave", (e) => { const zone = e.target.closest?.(".dropline"); if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove("over"); });
  document.addEventListener("dragend", () => { marker?.classList.remove("drop-before", "drop-after"); document.querySelectorAll(".dropline.over").forEach((z) => z.classList.remove("over")); });
  document.addEventListener("drop", (e) => {
    const zone = e.target.closest?.(".dropline");
    if (!zone || !C) return;
    e.preventDefault();
    let data;
    try { data = JSON.parse(e.dataTransfer.getData("text/plain")); } catch { return; }
    const L = +zone.dataset.line;
    let k = dropIndex(zone, e.clientX, e.clientY);
    edit((ls) => {
      if (!ls[L]) return;
      let moved = data.ins;
      if (data.from) {
        const [fl, fi] = data.from;
        moved = ls[fl].splice(fi, 1);
        if (fl === L && fi < k) k--;
      }
      ls[L].splice(k, 0, ...moved);
      Object.assign(sel, { line: L, i: k + moved.length - 1 });
    });
    marker?.classList.remove("drop-before", "drop-after");
    render();
  });
}

// -- Rules: let rows and condition rows ----------------------------------------------------

function draftOf(ctx) {
  const d = drafts[ctx.key];
  if (d && d.text === ctx.text) return d;           // keep half-typed rows while the text is ours
  const r = toRows(ctx.text);
  if (!r) return null;
  drafts[ctx.key] = { ...r, text: ctx.text };
  return drafts[ctx.key];
}
function commit(d) { d.text = fromRows(d); C.setText(d.text); }

export function rulesView(ctx) {
  C = ctx;
  const d = draftOf(ctx);
  const opt = (v, cur) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`;
  const words = Object.entries(ctx.groups);
  const fns = ctx.exit ? EXIT_FUNCS.map((f) => insertion(f)) : ["sma", "ema", "rsi", "highest", "lowest", "bollinger_lower", "bollinger_middle", "bollinger_upper", "change"].map(insertion);
  const side = `<div class="well scroll"><b class="sec" style="font-size:10px">Variables</b><div class="cap" style="font-size:10px;margin:4px 0 8px">click one to drop it into the box you are in</div><div style="display:grid;gap:7px;font-size:11px;padding-left:6px">${words.map(([g, a]) => `<span class="cap" style="font-size:10px;letter-spacing:.1em;margin-top:4px">${esc(g.toUpperCase())}</span>${a.map((v) => `<span class="pickword" data-word="${esc(v)}" style="cursor:pointer;${kind(v) === "pmv" ? "color:#7f9bff" : ""}">${esc(v)}</span>`).join("")}`).join("")}<span class="cap" style="font-size:10px;letter-spacing:.1em;margin-top:4px">FUNCTIONS</span>${fns.map((t) => `<span class="pickword" data-word="${esc(t.join("").replace(/,/g, ", "))}" style="cursor:pointer">${esc(t.join("").replace(/,/g, ", "))}</span>`).join("")}${d && d.vars.length ? `<span class="cap" style="font-size:10px;letter-spacing:.1em;margin-top:4px">YOURS</span>${d.vars.filter((v) => v.name).map((v) => `<span class="pickword accent" data-word="${esc(v.name)}" style="cursor:pointer">${esc(v.name)}</span>`).join("")}` : ""}</div></div>`;
  if (!d) {
    return `<div class="grid grow" style="grid-template-columns:1fr 250px;gap:8px;min-height:0"><div class="well scroll" style="display:flex;flex-direction:column;gap:8px"><b class="sec" style="font-size:10px">Conditions</b><div class="cap" style="line-height:1.5">This rule mixes <b>and</b> with <b>or</b>, or uses <b>not</b> or brackets around a comparison: rows cannot show it. Edit it in Formula or Code.</div><div class="well" style="background:var(--well);display:grid;gap:6px">${plain(ctx, "")}${ctx.badge}</div></div>${side}</div>`;
  }
  return `<div class="grid grow" style="grid-template-columns:1fr 250px;gap:8px;min-height:0"><div class="well scroll" style="display:flex;flex-direction:column;gap:8px">
    <b class="sec" style="font-size:10px">Let</b>
    ${d.vars.map((v, k) => `<div class="row"><input type="text" data-rvar="${k}:name" value="${esc(v.name)}" placeholder="name" style="width:110px;color:#e87aa6"><span class="muted">=</span><input type="text" data-rvar="${k}:expr" value="${esc(v.expr)}" placeholder="close - open"><button class="btn sm" data-act="r-delvar-${k}">×</button></div>`).join("")}
    <span><button class="btn sm" data-act="r-addvar">+ Add variable</button></span>
    <b class="sec" style="font-size:10px">Conditions</b>
    <div class="well" style="background:var(--well);border-style:dashed;display:grid;gap:8px"><div class="row"><b class="accent" style="font-size:11px;letter-spacing:.1em">${esc(ctx.when)}</b><select data-rjoin style="width:110px;font-family:var(--ui)">${opt("All (AND)", d.join === "and" ? "All (AND)" : "")}${opt("Any (OR)", d.join === "or" ? "Any (OR)" : "")}</select></div>
      ${d.rows.map((r, k) => `<div class="row"><input type="text" data-rrow="${k}:0" value="${esc(r[0])}" placeholder="close" style="font-family:var(--mono)"><select data-rrow="${k}:1" style="width:64px">${OPS.map((o) => opt(o, r[1])).join("")}</select><input type="text" data-rrow="${k}:2" value="${esc(r[2])}" placeholder="0" style="font-family:var(--mono)"><button class="btn sm" data-act="r-delrow-${k}">×</button></div>`).join("") || `<span class="cap">no condition yet</span>`}
      <span><button class="btn sm accent" data-act="r-addrow">+ Add condition</button></span></div>
    <span class="grow"></span>
    <div class="well" style="background:var(--well);display:grid;gap:6px"><span class="cap" style="font-size:10px;letter-spacing:.1em">DESCRIPTION</span>${plain(ctx, "No condition yet: add one above.")}${ctx.badge}</div></div>${side}</div>`;
}

let lastBox = null;
document.addEventListener("focusin", (e) => { if (e.target.matches?.("[data-rvar],[data-rrow]")) lastBox = e.target; });

export function rulesInput(el) {
  if (!C) return false;
  const d = drafts[C.key];
  if (!d) return false;
  if (el.matches("[data-rvar]")) { const [k, f] = el.dataset.rvar.split(":"); d.vars[+k][f] = el.value; commit(d); return true; }
  if (el.matches("[data-rrow]")) { const [k, f] = el.dataset.rrow.split(":").map(Number); d.rows[k][f] = el.value; commit(d); return true; }
  if (el.matches("[data-rjoin]")) { d.join = el.value.startsWith("Any") ? "or" : "and"; commit(d); return true; }
  return false;
}

export function rulesClick(el) {
  if (!C) return false;
  const w = el.closest("[data-word]");
  if (w) {
    const box = lastBox && document.contains(lastBox) ? lastBox : null;
    if (!box || box.tagName !== "INPUT") return true;
    const s = box.selectionStart ?? box.value.length, e2 = box.selectionEnd ?? s;
    box.value = box.value.slice(0, s) + w.dataset.word + box.value.slice(e2);
    box.focus(); box.setSelectionRange(s + w.dataset.word.length, s + w.dataset.word.length);
    box.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  }
  const a = el.closest("[data-act]")?.dataset.act;
  if (!a?.startsWith("r-")) return false;
  const d = drafts[C.key];
  if (!d) return true;
  if (a === "r-addvar") { const used = new Set(d.vars.map((v) => v.name)); let n = 1; while (used.has("v" + n)) n++; d.vars.push({ name: "v" + n, expr: "" }); }
  else if (a.startsWith("r-delvar-")) d.vars.splice(+a.slice(9), 1);
  else if (a === "r-addrow") d.rows.push(["", ">", ""]);
  else if (a.startsWith("r-delrow-")) d.rows.splice(+a.slice(9), 1);
  commit(d);
  return true;
}
