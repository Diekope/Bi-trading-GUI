import { candles, equity, tape, market, stats } from "./synth.js";
import { drawCandles, drawLines } from "./chart.js";
const $ = (s) => document.querySelector(s), main = $("#main"), foot = $("#footer");
const cs = candles(), eq = equity();
let view = "terminal";

const views = {
  terminal() {
    main.style.gridTemplateColumns = "1fr 1fr"; main.style.gridTemplateRows = "1fr";
    main.innerHTML = `
    <section class="card">
      <div class="row between"><h2>Polymarket <span class="pill">5m</span></h2><span class="up">● live</span></div>
      <div style="font-size:16px;font-weight:600">${market.title}</div>
      <div class="row between muted"><span>21:00–21:05 UTC</span><span>closes in <b class="big" style="color:var(--text)">${market.closesIn}</b></span></div>
      <div class="tiles">
        <div class="tile up"><span class="px up">${market.up}¢</span><b class="up">UP</b><div class="bar up"></div><span class="faint">bid 80¢ · ask 81¢</span></div>
        <div class="tile"><span class="px down">${market.down}¢</span><b class="down">DOWN</b><div class="bar down"></div><span class="faint">bid 19¢ · ask 20¢</span></div>
      </div>
      <div class="kv"><span class="faint">SPREAD</span><b>${market.spread}</b><span class="faint">LIQUIDITY</span><b>${market.liquidity}</b><span class="faint">DEPTH</span><b>${market.depth}</b><span class="faint">TARGET</span><b>${market.target.toLocaleString()}</b></div>
      <h2>BTC / USD</h2><canvas id="btc"></canvas>
      <h2>Tape</h2><div class="tape">${tape().map((t) => `<div><span>${t.time}</span><span class="${t.side === "UP" ? "up" : "down"}">${t.side} ${t.px}¢</span><span>× ${t.size}</span></div>`).join("")}</div>
    </section>
    <section class="card">
      <div class="row between"><h2 style="font-size:16px;letter-spacing:0;color:var(--muted)">HYPE</h2><span class="big muted">${cs.at(-1).c.toFixed(3)}</span></div>
      <div class="row">${["1m", "3m", "5m", "15m", "30m", "1h"].map((t, i) => `<button class="pill ${i ? "" : "on"}">${t}</button>`).join("")}</div>
      <canvas id="hl"></canvas>
    </section>`;
    foot.innerHTML = `<span class="muted">Strategy</span><b>Bollinger reversion</b><span class="btn accent">armed</span><span class="muted">signal</span><b class="down">FALSE</b><span class="spacer" style="flex:1"></span><button class="btn up">Bet UP 82¢</button><button class="btn down">Bet DOWN 18¢</button>`;
    redraw();
  },
  backtest() {
    main.style.gridTemplateColumns = "2fr 1fr"; main.style.gridTemplateRows = "1fr 1fr";
    main.innerHTML = `
    <section class="card"><h2>Backtest</h2><div class="stats">${Object.entries(stats).map(([k, v]) => `<span>${k}<b>${v}</b></span>`).join("")}</div><canvas id="hl"></canvas></section>
    <section class="card"><h2>Backtest value</h2><span class="muted">Form fields go here.</span></section>
    <section class="card" style="grid-column:1/3"><h2>Results</h2><canvas id="eq"></canvas></section>`;
    foot.innerHTML = `<span class="muted">Run controls</span><button class="btn accent">Run</button>`;
    redraw();
  },
};
function redraw() {
  const o = { volume: $("#vol").checked, bands: $("#bb").checked };
  if ($("#hl")) drawCandles($("#hl"), cs.slice(-120), o);
  if ($("#btc")) drawLines($("#btc"), [{ v: cs.map((c) => c.c), color: "--up" }]);
  if ($("#eq")) drawLines($("#eq"), [{ v: eq.strategy, color: "--accent" }, { v: eq.hold, color: "--band" }, { v: eq.random, color: "--faint" }]);
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => { document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b)); views[(view = b.dataset.v)](); }));
$("#vol").onchange = $("#bb").onchange = redraw; addEventListener("resize", redraw);
views.terminal();
