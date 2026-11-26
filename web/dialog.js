// A small modal: a title, a line of text, an optional text field, and buttons.
// ask({ title, text, input, buttons: [{ label, value, cls }] }) resolves to { value, input } (Escape: value null).
export function ask({ title, text = "", input = null, buttons }) {
  return new Promise((resolve) => {
    const esc = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
    const wrap = document.createElement("div");
    wrap.className = "dialog-back";
    wrap.innerHTML = `<div class="card dialog" role="dialog" aria-modal="true"><b class="sec">${esc(title)}</b>${text ? `<span class="cap" style="line-height:1.5">${esc(text)}</span>` : ""}${input != null ? `<input type="text" class="dialog-input" value="${esc(input)}" style="font-family:var(--ui)">` : ""}<div class="row" style="justify-content:flex-end;gap:8px">${buttons.map((b, i) => `<button class="btn ${b.cls || ""}" data-i="${i}">${esc(b.label)}</button>`).join("")}</div></div>`;
    const field = wrap.querySelector(".dialog-input");
    const done = (value) => { wrap.remove(); removeEventListener("keydown", key, true); resolve({ value, input: field ? field.value.trim() : null }); };
    const key = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); done(null); }
      if (e.key === "Enter") { e.stopPropagation(); e.preventDefault(); const main = buttons.find((b) => b.cls?.includes("accent")) || buttons[0]; done(main.value); }
    };
    wrap.addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) { e.stopPropagation(); done(buttons[+b.dataset.i].value); } else if (e.target === wrap) done(null); });
    addEventListener("keydown", key, true);
    document.body.appendChild(wrap);
    (field || wrap.querySelector(".btn.accent") || wrap.querySelector(".btn"))?.focus();
    field?.select();
  });
}
