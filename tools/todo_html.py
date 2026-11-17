"""Render TODO.md as a light, tickable HTML page: docs/todo.html.

    uv run python tools/todo_html.py
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


LABELS = {"high": "High", "med": "Medium", "low": "Low"}


def split_priority(bullet: str) -> tuple[str, str]:
    match = re.match(r"\[(high|med|low)\]\s*", bullet)
    if not match:
        return "low", bullet
    return match.group(1), bullet[match.end():]


def parse(source: str) -> tuple[str, list[tuple[str, list[str]]]]:
    intro: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in source.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif not sections:
            if not line.startswith("# ") and line.strip():
                intro.append(line.strip())
        elif line.startswith("- "):
            sections[-1][1].append(line[2:].strip())
        elif line.strip() and sections[-1][1]:
            sections[-1][1][-1] += " " + line.strip()
    return " ".join(intro), sections


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bi-trading · to-do</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1b1f27; --mute:#6b7280; --line:#e4e7ec; --accent:#2563eb }
  * { box-sizing:border-box }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.5 -apple-system, "Inter", system-ui, sans-serif }
  main { max-width:860px; margin:0 auto; padding:32px 16px 64px }
  h1 { font-size:24px; margin:0 0 4px }
  .sub { color:var(--mute); margin:0 0 8px }
  .count { color:var(--mute); margin:0 0 24px; font-size:13px }
  section { background:var(--card); border:1px solid var(--line); border-radius:12px;
            padding:16px 20px; margin-bottom:16px }
  h2 { font-size:13px; margin:0 0 8px; text-transform:uppercase; letter-spacing:.05em; color:var(--mute) }
  ul { list-style:none; margin:0; padding:0 }
  li { display:flex; gap:10px; padding:8px 0; border-top:1px solid var(--line) }
  li:first-child { border-top:0 }
  li.done span { text-decoration:line-through; color:var(--mute) }
  input { margin-top:5px; accent-color:var(--accent) }
  .bar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:24px }
  .bar button { border:1px solid var(--line); background:var(--card); color:var(--ink);
                padding:6px 12px; border-radius:999px; cursor:pointer; font:inherit }
  .bar button[aria-pressed="true"] { background:var(--accent); border-color:var(--accent); color:#fff }
  .tag { font-size:11px; font-weight:600; padding:1px 8px; border-radius:999px; border:1px solid currentColor;
         white-space:nowrap; margin-left:auto; align-self:center }
  .tag.high { color:#d92d20 } .tag.med { color:#b54708 } .tag.low { color:#475467 }
  .hide { display:none }
  code { background:#eef0f4; padding:1px 5px; border-radius:4px; font-size:13px }
</style>
</head>
<body>
<main>
  <h1>bi-trading · to-do</h1>
  <p class="sub">%(intro)s</p>
  <p class="count" id="count"></p>
  <div class="bar" id="bar">
    <button data-f="all" aria-pressed="true">All</button>
    <button data-f="high" aria-pressed="false">High</button>
    <button data-f="med" aria-pressed="false">Medium</button>
    <button data-f="low" aria-pressed="false">Low</button>
    <button data-f="open" aria-pressed="false">Open only</button>
  </div>
%(sections)s
</main>
<script>
const KEY = "bt-todo-md";
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const items = [...document.querySelectorAll("li")];
function count() {
  const done = items.filter(li => li.classList.contains("done")).length;
  document.getElementById("count").textContent = done + " of " + items.length + " ticked";
}
items.forEach(li => {
  const cb = li.querySelector("input"), id = li.dataset.id;
  cb.checked = !!state[id]; li.classList.toggle("done", cb.checked);
  cb.onchange = () => {
    state[id] = cb.checked; li.classList.toggle("done", cb.checked);
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
    count();
  };
});
count();
let filter = "all";
function apply() {
  items.forEach(li => {
    const ok = filter === "all" || (filter === "open" ? !li.classList.contains("done") : li.dataset.p === filter);
    li.classList.toggle("hide", !ok);
  });
  document.querySelectorAll("section").forEach(s =>
    s.classList.toggle("hide", !s.querySelector("li:not(.hide)")));
}
items.forEach(li => li.querySelector("input").addEventListener("change", apply));
document.getElementById("bar").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  filter = b.dataset.f;
  document.querySelectorAll("#bar button").forEach(x => x.setAttribute("aria-pressed", x === b));
  apply();
};
</script>
</body>
</html>
"""


def main() -> None:
    intro, sections = parse((ROOT / "TODO.md").read_text())
    parts = []
    for title, bullets in sections:
        rows = "\n".join(
            f'    <li data-p="{p}" data-id={json.dumps(re.sub(r"[^a-z0-9]+", "-", t[:48].lower()))}>'
            f'<input type="checkbox"><span>{inline(t)}</span>'
            f'<span class="tag {p}">{LABELS[p]}</span></li>'
            for p, t in map(split_priority, bullets)
        )
        parts.append(f"  <section>\n    <h2>{html.escape(title)}</h2>\n    <ul>\n{rows}\n    </ul>\n  </section>")
    (ROOT / "docs" / "todo.html").write_text(
        PAGE % {"intro": inline(intro), "sections": "\n".join(parts)}
    )
    print(f"docs/todo.html: {sum(len(b) for _, b in sections)} items")


if __name__ == "__main__":
    main()
