import { views, state, draw } from "./views.js";
const rail = [["home", "⌂", "Home"], ["live", "◉", "Live"], ["builder", "ƒ", "Builder"], ["backtest", "⟲", "Backtest"], ["logs", "☰", "Logs"], ["ml", "✦", "ML"], ["settings", "⚙", "Settings"]];
const $ = (s) => document.querySelector(s);
function render() {
  let key = location.hash.slice(1) || "home"; if (!views[key]) key = "home";
  const v = views[key], main = $("#main");
  document.body.classList.toggle("hub", !!v.hub);
  $("#rail").innerHTML = `<span class="dot"></span>${rail.map(([k, i, t]) => `<a href="#${k}" title="${t}" class="${k === key || (k === "ml" && key === "model") ? "on" : ""}">${i}</a>`).join("")}<div class="lat"><span class="ok">PM<br>26ms</span><br><span class="warn">HL<br>217ms</span></div>`;
  $("#topbar").innerHTML = `<span>${v.title}</span><span class="spacer"></span>${v.extra ? v.extra() : ""}`;
  main.style.gridTemplateColumns = v.grid; main.style.gridTemplateRows = v.rows;
  main.innerHTML = v.html();
  $("#footer").style.display = v.foot ? "flex" : "none"; $("#footer").innerHTML = v.foot ? v.foot() : "";
  requestAnimationFrame(draw);
}
document.addEventListener("click", (e) => {
  const s = e.target.closest("[data-set]"), f = e.target.closest("[data-flip]");
  if (s) { const [k, ...v] = s.dataset.set.split("="); state[k] = isNaN(v.join("=")) ? v.join("=") : Number(v.join("=")); render(); }
  else if (f && f.type !== "checkbox") { state[f.dataset.flip] = !state[f.dataset.flip]; render(); }
});
document.addEventListener("change", (e) => { const f = e.target.dataset.flip; if (f) { state[f] = e.target.checked; render(); } });
addEventListener("hashchange", render); addEventListener("resize", draw);
addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && /^[1-7]$/.test(e.key)) { e.preventDefault(); location.hash = rail[e.key - 1][0]; } });
render();
