import { views, state, draw, normalize, tick } from "./views.js";
const I = (d) => `<svg viewBox="0 0 24 24">${d}</svg>`;
const rail = [
  ["home", "Home", I('<path d="M3 11l9-8 9 8M5 10v10h14V10"/>')],
  ["portfolio", "Portfolio", I('<path d="M3 7h18v13H3zM3 7l3-4h12l3 4M16 13h2"/>')],
  ["live", "Live", I('<path d="M3 12h4l3-8 4 16 3-8h4"/>')],
  ["builder", "Strategy builder", I('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>')],
  ["backtest", "Backtest", I('<path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2"/>')],
  ["ml", "ML", I('<circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="12" cy="12" r="2"/><path d="M7 12h3M14 12l3-6M14 12l3 6"/>')],
];
const tail = [
  ["logs", "Logs", I('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>')],
  ["settings", "Settings", I('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>')],
];
const keys = ["home", "portfolio", "live", "builder", "backtest", "ml", "logs", "settings"];
const titles = { home: "Home", portfolio: "Portfolio", live: "Live", builder: "Strategy builder", backtest: "Backtest engine", ml: "ML strategy builder", model: "Model builder", logs: "Logs", settings: "Settings" };
const $ = (s) => document.querySelector(s);
const link = ([k, t, i], key) => `<a href="#${k}" title="${t}" class="${k === key || (k === "ml" && key === "model") ? "on" : ""}">${i}</a>`;
const vs = [["Polymarket", "pm", "PM"], ["Hyperliquid", "hl", "HL"], ["Both", "", "⇄"]];
function render() {
  normalize();
  let key = location.hash.slice(1) || "home"; if (!views[key]) key = "home";
  const v = views[key];
  document.body.classList.toggle("hub", !!v.hub);
  document.body.classList.toggle("live-mode", !!state.live);
  document.body.dataset.venue = state.venue;
  $("#rail").innerHTML = `<div class="vsw">${vs.map(([n, c, t]) => `<a class="${c} ${state.venue === n ? "on" : ""}" data-set="venue=${n}" title="${n === "Both" ? "Both venues" : n}">${t}</a>`).join("")}</div><hr>${rail.map((r) => link(r, key)).join("")}<span class="sp"></span>${tail.map((r) => link(r, key)).join("")}<hr><div class="lat"><span class="pm" style="color:#5b82ff">PM</span>26ms<span style="color:#97fce4">HL</span>217ms</div><hr><a class="pw" title="Quit"><svg viewBox="0 0 24 24"><path d="M12 3v9M6.5 6.5a8 8 0 1 0 11 0"/></svg></a>`;
  const extra = v.topExtra ? v.topExtra() : "";
  $("#topbar").innerHTML = `<b style="font-size:12px">${titles[key]}</b><span class="vtag ${state.venue === "Polymarket" ? "pm" : state.venue === "Hyperliquid" ? "hl" : ""}">${state.venue === "Both" ? "PM + HL" : state.venue}</span><span style="flex:1"></span>${extra}<span class="modesw"><button class="paper ${state.live ? "" : "on"}" data-set="live=0">PAPER</button><button class="live ${state.live ? "on" : ""}" data-set="live=1">LIVE</button></span>`;
  const main = $("#main");
  main.style.gridTemplateColumns = v.grid; main.style.gridTemplateRows = v.rowsPx || v.rows;
  main.innerHTML = v.html();
  const f = $("#footer"); const foot = v.foot ? v.foot() : ""; f.style.display = foot ? "flex" : "none"; f.innerHTML = foot;
  requestAnimationFrame(draw);
}
document.addEventListener("click", (e) => {
  const s = e.target.closest("[data-set]"); if (!s) return;
  const [k, ...v] = s.dataset.set.split("="), val = v.join("="); state[k] = val !== "" && !isNaN(val) ? Number(val) : val; render();
});
document.addEventListener("change", (e) => { const f = e.target.dataset.flip; if (f) { state[f] = e.target.checked; render(); } });
addEventListener("hashchange", render); addEventListener("resize", draw);
addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && /^[1-8]$/.test(e.key)) { e.preventDefault(); location.hash = keys[e.key - 1]; }
  if (e.altKey && ["1", "2", "3"].includes(e.key)) { state.venue = ["Polymarket", "Hyperliquid", "Both"][e.key - 1]; render(); }
});
// The books tick so the portfolio reads as live.
setInterval(() => { if (location.hash === "#portfolio") { tick.n++; render(); } }, 1500);
render();
