import { candles, equity, tape, market, stats, strategies, palette, logs, features, layers, stack, heat, trades, histogram } from "./synth.js";
import { drawCandles, drawLines, drawArea } from "./chart.js";

export const state = { tf: "1m", vol: true, bb: false, strat: 3, ruleSide: "entry", mode: "formula", res: "overview", btTab: "overview", logSel: 0, logSrc: "All", sec: "Accounts", model: "Gradient boosting", horizon: 5, up: 0.6, down: 0.4, preset: "LSTM", autobet: false, playing: 0.62 };
const cs = candles(), eq = equity(), lg = logs(), hm = heat(), tr = trades();
const $ = (s) => document.querySelector(s);
const pills = (key, opts) => `<span class="toggle">${opts.map((o) => `<button class="pill ${state[key] === o ? "on" : ""}" data-set="${key}=${o}">${o}</button>`).join("")}</span>`;
const stat = (k, v, c = "") => `<span>${k}<b class="${c}">${v}</b></span>`;
const field = (l, v, t = "text") => `<label class="f">${l}<input type="${t}" value="${v}"></label>`;
const sel = (l, opts) => `<label class="f">${l}<select>${opts.map((o) => `<option>${o}</option>`).join("")}</select></label>`;
const toggle = (key) => `<span class="sw ${state[key] ? "on" : ""}" data-flip="${key}"></span>`;
const chip = (t, k) => `<span class="chip ${k}">⠿ ${t}</span>`;
const sc = (v) => (v >= 3 ? "rgba(61,220,132,.55)" : v >= 1 ? "rgba(61,220,132,.25)" : v > -1 ? "#26272b" : v > -3 ? "rgba(255,92,92,.28)" : "rgba(255,92,92,.5)");
const chartBar = () => `<span class="muted">${["Volume", "Bollinger"].map((n, i) => `<label style="margin-right:10px"><input type="checkbox" data-flip="${i ? "bb" : "vol"}" ${state[i ? "bb" : "vol"] ? "checked" : ""}> ${n}</label>`).join("")}</span>`;
const lat = `<span class="ok">PM ● 26 ms</span><span class="warn">HL ● 217 ms</span>`;
const topbar = (t, extra = "") => `<span>${t}</span><span class="spacer"></span>${extra}${lat}`;
const strat = () => strategies[state.strat];

const resultsCard = (grid = "") => `<section class="card" style="${grid}">
  <div class="row between"><h2>Results</h2><span class="toggle">${pills("res", ["overview", "compare"])}</span></div>
  <span class="faint">2026 · 1m · 1,400 bars · tp 2 / sl 1</span>
  <div class="stats">${stat("PnL", "+0.57%", "accent")}${stat("Sharpe", "0.01")}${stat("Max DD", "-2.52%", "down")}${stat("Trades", "10")}${stat("Win rate", "60%")}${stat("Fees", "$119")}</div>
  <div class="row grow" style="align-items:stretch;gap:16px">
    <canvas id="eq"></canvas>
    <div style="width:220px;display:grid;gap:8px;align-content:start">${state.res === "overview" ? `<h2>How trades end</h2>
      ${[["Time", 70, "--band"], ["Stop loss", 20, "--down"], ["Take profit", 10, "--up"]].map(([n, p, c]) => `<div class="hbar"><span style="width:70px" class="muted">${n}</span><span class="t"><i style="width:${p}%;background:var(${c})"></i></span>${p}%</div>`).join("")}`
      : `<div class="row between muted"><span>Walk-forward (4)</span><b>1 / 4 positive</b></div><h2>TP × SL sweep</h2><div class="heat">${hm.flat().map((v) => `<i style="background:${sc(v)}"></i>`).join("")}</div>`}</div>
  </div></section>`;

export const views = {
  home: {
    hub: 1, title: "Home",
    html: () => `<section class="card" style="grid-column:1/-1"><div class="big">Home</div><span class="muted">Pick a part to work on.</span></section>
      ${[["Active strategy", strat().name, strat().tf], ["Polymarket", "$412.30", "USDC · connected"], ["Hyperliquid", "$1,204.00", "USDC · connected"], ["Today", "+$18.40", "3 fills"]].map(([k, v, s]) => `<section class="card stat-card"><span class="sub">${k}</span><span class="v">${v}</span><span class="faint">${s}</span></section>`).join("")}
      <section class="card" style="grid-column:span 2"><h2>Live</h2><div>${market.title}</div><div class="row between"><span class="up big">${market.up}¢</span><span>closes in <b>${market.closesIn}</b></span></div><div class="row"><span class="muted">BTC</span><b>${market.btc.toLocaleString()}</b></div><a class="btn accent" href="#live" style="text-decoration:none;width:max-content">Open live</a></section>
      <section class="card" style="grid-column:span 2"><h2>Strategy builder</h2><div class="sub">Strategies</div>${strategies.map((s) => `<div class="row between"><span>${s.name}</span><span class="${s.pnl ? "up" : "faint"}">${s.pnl ? "+" + s.pnl + "%" : "draft"}</span></div>`).join("")}<div class="sub">Entry formula</div><pre class="code">band = bollinger_lower(close, 20, 2)\nclose &lt; band and volume &gt; 0</pre><a class="btn accent" href="#builder" style="text-decoration:none;width:max-content">Open builder</a></section>
      <section class="card" style="grid-column:span 2"><h2>Backtest engine</h2><div class="stats" style="grid-template-columns:repeat(3,1fr)">${stat("PnL", "-0.42%", "down")}${stat("Trades", "2,383")}${stat("Win rate", "44%")}</div><a class="btn accent" href="#backtest" style="text-decoration:none;width:max-content">Open backtest</a></section>`,
    grid: "repeat(4,1fr)", rows: "auto auto 1fr",
  },

  live: {
    title: "Live · BTC 5m · Polymarket + Hyperliquid",
    html: () => `<section class="card">
      <div class="row between"><h2>Polymarket <span class="pill">5m</span></h2><span class="up">● live</span></div>
      <div style="font-size:16px;font-weight:600">${market.title}</div>
      <div class="row between muted"><span>21:00–21:05 UTC</span><span>closes in <b class="big" style="color:var(--text)">${market.closesIn}</b></span></div>
      <div class="tiles"><div class="tile up"><span class="px up">${market.up}¢</span><b class="up">UP</b><div class="bar up"></div><span class="faint">bid 80¢ · ask 81¢</span></div>
      <div class="tile"><span class="px down">${market.down}¢</span><b class="down">DOWN</b><div class="bar down"></div><span class="faint">bid 19¢ · ask 20¢</span></div></div>
      <div class="kv"><span class="faint">SPREAD</span><b>${market.spread}</b><span class="faint">LIQUIDITY</span><b>${market.liquidity}</b><span class="faint">DEPTH</span><b>${market.depth}</b><span class="faint">TARGET</span><b>${market.target.toLocaleString()}</b></div>
      <h2>BTC / USD</h2><canvas id="btc"></canvas><h2>Tape</h2>
      <div class="tape">${tape().map((t) => `<div><span>${t.time}</span><span class="${t.side === "UP" ? "up" : "down"}">${t.side} ${t.px}¢</span><span>× ${t.size}</span></div>`).join("")}</div></section>
      <section class="card"><div class="row between"><h2 style="font-size:16px;letter-spacing:0">HYPE</h2><span class="big muted">${cs.at(-1).c.toFixed(3)}</span></div>
      <div class="row">${pills("tf", ["1m", "3m", "5m", "15m", "30m", "1h"])}</div><canvas id="hl"></canvas></section>`,
    grid: "1fr 1fr", rows: "1fr", extra: chartBar,
    foot: () => `<span class="muted">Strategy</span><b>${strat().name}</b><span class="btn accent">armed</span><span class="muted">signal</span><b class="down">FALSE</b><label><input type="checkbox" data-flip="autobet" ${state.autobet ? "checked" : ""}> Auto-bet</label><input type="number" value="20" style="width:80px"><span style="flex:1"></span><button class="btn up">Bet UP 82¢</button><button class="btn down">Bet DOWN 18¢</button>`,
  },

  builder: {
    title: "Create a strategy",
    html: () => `<section class="card" style="grid-row:1/3"><h2>Strategy</h2><div class="grid g2">${field("Name", strat().name)}${field("Timeframe", strat().tf)}</div>
      <div class="grow scroll" style="display:grid;gap:8px;align-content:start">${strategies.map((s, i) => `<div class="list-item ${i === state.strat ? "on" : ""}" data-set="strat=${i}"><span>${s.name}</span><span class="${s.pnl ? "up" : "faint"}">${s.pnl ? "+" + s.pnl + "%" : "draft"}</span></div>`).join("")}</div><button class="btn accent">Create a strategy</button></section>
      <section class="card"><div class="row between"><span class="toggle">${pills("ruleSide", ["entry", "exit"]).replace(/>(entry|exit)</g, (m, a) => `>${a.toUpperCase()} RULES<`)}</span>${pills("mode", ["rules", "formula", "code"])}</div>
      ${state.mode === "code" ? `<div class="well grow"><div class="sub">formula.txt · the code the tiles stand for — editable</div><pre class="code">band = bollinger_lower(close, 20, 2)\nclose &lt; band and volume &gt; 0</pre></div>`
      : state.mode === "rules" ? `<div class="grow scroll"><div class="sub">GROUP 1</div><div class="well grid g3" style="margin:6px 0">${sel("Left", ["close", "price", "volume"])}${sel("Operator", ["<", ">", "<=", ">="])}${sel("Right", ["band", "open", "0"])}</div><button class="btn">+ Add group</button></div>`
      : `<div class="grid grow" style="grid-template-columns:200px 1fr 200px;min-height:0">
        <div class="well scroll"><div class="sub">Blocks</div><input type="text" placeholder="search a block...">${Object.entries(palette).map(([g, a]) => `<div class="sub" style="margin-top:8px">${g}</div><div class="chips">${a.map((x) => chip(x, g === "Variables" ? "var" : g === "Data" ? "data" : g === "Indicators" ? "ind" : "math")).join("")}</div>`).join("")}</div>
        <div class="well scroll" style="display:grid;gap:8px;align-content:start"><div class="sub">Formula</div><div class="sub accent">Variables</div><div class="row">${chip("band", "var")} = ${chip("Boll low", "ind")}<span class="chip">20</span><span class="chip">2</span></div><button class="btn" style="width:max-content">+ Add variable</button>
        <div class="sub accent">${state.ruleSide === "entry" ? "Buy when" : "Sell when"}</div><div class="row chips">${chip("close", "data")}${chip("<", "math")}${chip("band", "var")}${chip("and", "math")}${chip("volume", "data")}${chip(">", "math")}${chip("0", "math")}</div><div class="row"><input type="text" value="band = bollinger_lower(close, 20, 2) close < band and volume > 0"><span class="valid">✓ valid</span></div></div>
        <div class="well"><div class="sub">Selected block</div><span class="faint">pick a block in a line to see it here</span><div class="sub" style="margin-top:12px">Live values</div><div class="kv" style="grid-template-columns:auto 1fr"><span class="muted">close</span><b>8.032e4</b><span class="muted">band</span><b>8.018e4</b><span class="muted">volume</span><b>5.05</b><span class="muted">result</span><b class="down">FALSE</b></div></div></div>`}</section>
      ${resultsCard("grid-column:2")}`,
    grid: "280px 1fr", rows: "1.1fr 1fr",
    foot: () => `<span class="muted">${strat().name} · unsaved</span><span style="flex:1"></span><button class="btn" disabled>Delete strategy</button><button class="btn">Reset</button><button class="btn accent">Save</button>`,
  },

  backtest: {
    title: "Backtest engine",
    html: () => `<section class="card"><div class="row between"><h2>Backtest</h2><span class="row"><button class="btn">Restart</button><input type="text" value="×1" style="width:60px"><button class="btn accent">Run</button></span></div>
      <span class="faint">finished — 2,383 trades, 44% won, press Run to replay</span><div class="progress"><i style="width:${state.playing * 100}%"></i></div>
      <div class="stats">${Object.entries(stats).map(([k, v]) => stat(k, v, v.startsWith("-") ? "down" : "")).join("")}</div><canvas id="hl"></canvas></section>
      <div class="grid" style="grid-template-rows:auto auto 1fr;gap:8px;min-height:0;overflow:auto">
        <section class="card"><h2>History</h2><div class="grid g2">${field("From", "2017")}${field("To", "2026")}</div><div class="row">${pills("tf", ["1m", "3m", "5m", "15m", "30m", "1h"])}</div><button class="btn accent">Download</button></section>
        <section class="card"><h2>Backtest value</h2><div class="grid g3">${field("Initial capital $", 10000, "number")}${sel("Sizing", ["Balance %", "Fixed $"])}${field("Position %", 10, "number")}${field("TP %", 2, "number")}${field("SL %", 1, "number")}${field("Max cash $", 2000, "number")}${field("Fee %", 0.06, "number")}<label class="f">Dynamic TP<span><input type="checkbox"> Enabled</span></label></div></section>
        <section class="card"><h2>Strategy</h2>${sel("Strategy", strategies.map((s) => s.name))}<span class="faint">${strat().note}</span><button class="btn accent">Create a strategy</button><div class="grid g2"><div class="well"><div class="sub">Save run</div><input type="text" placeholder="run name"> <button class="btn accent" style="margin-top:6px">Save run</button></div><div class="well"><div class="sub">Load run</div><span class="faint">no saved runs yet</span></div></div></section></div>
      <section class="card" style="grid-column:1/3"><div class="row between"><h2>Results</h2>${pills("btTab", ["overview", "trades"])}</div>
      ${state.btTab === "trades" ? `<div class="scroll grow"><table><tr><th>#</th><th>Side</th><th>Entry</th><th>PnL %</th><th>Exit</th></tr>${tr.map((t) => `<tr><td>${t.n}</td><td>${t.side}</td><td>${t.entry}</td><td class="${t.pnl >= 0 ? "up" : "down"}">${t.pnl}</td><td>${t.exit}</td></tr>`).join("")}</table></div>`
      : `<div class="row grow" style="align-items:stretch;gap:16px"><div style="flex:1;display:grid;grid-template-rows:3fr 1fr;gap:6px;min-width:0"><canvas id="eq"></canvas><canvas id="dd"></canvas></div><div style="width:240px;display:grid;gap:6px;align-content:start"><h2>How trades end</h2>${[["Take profit", 20, "--up"], ["Stop loss", 45, "--down"], ["Time", 35, "--band"]].map(([n, p, c]) => `<div class="hbar"><span style="width:70px" class="muted">${n}</span><span class="t"><i style="width:${p}%;background:var(${c})"></i></span>${p}%</div>`).join("")}<h2>PnL distribution</h2><div style="display:flex;align-items:end;height:90px;gap:1px">${histogram.map((h, i) => `<i style="flex:1;height:${Math.min(100, h)}%;background:${i < 20 ? "var(--down)" : "var(--up)"}"></i>`).join("")}</div></div></div>`}</section>`,
    grid: "1.7fr 1fr", rows: "1.2fr 1fr",
    foot: () => `<span class="muted">Playback</span><div class="progress" style="flex:1"><i style="width:${state.playing * 100}%"></i></div><span class="muted">${Math.round(state.playing * 196496).toLocaleString()} / 196,496 candles</span><button class="btn">⏸</button><button class="btn accent">×1</button>`,
  },

  logs: {
    hub: 1, title: "Logs",
    html: () => `<section class="card" style="grid-column:1/-1"><div class="stats" style="grid-template-columns:repeat(5,1fr)">${stat("Sent", 14)}${stat("Filled", 11)}${stat("Rejected", 2, "down")}${stat("Warnings", 3, "accent")}${stat("PnL today", "+$18.40", "up")}</div>
      <div class="row"><input type="text" placeholder="search">${pills("logSrc", ["All", "Polymarket", "Hyperliquid", "Strategy", "System"])}<span style="flex:1"></span><button class="btn">Pause</button><button class="btn">Clear</button><button class="btn">Export</button></div></section>
      <section class="card"><div class="scroll grow"><table><tr><th>Time</th><th>Level</th><th>Source</th><th>Origin</th><th>Event</th><th>Message</th></tr>${lg.filter((r) => state.logSrc === "All" || r.source === state.logSrc).map((r, i) => `<tr class="click ${i === state.logSel ? "sel" : ""}" data-set="logSel=${i}"><td>${r.time}</td><td class="${r.level === "error" ? "down" : r.level === "warn" ? "accent" : "muted"}">${r.level}</td><td>${r.source}</td><td>${r.origin}</td><td>${r.event}</td><td>${r.message}</td></tr>`).join("")}</table></div><div class="row between muted"><span>Auto-scroll <span class="sw on"></span></span><button class="btn">Load older</button></div></section>
      <section class="card"><h2>Details</h2>${(() => { const r = lg[state.logSel] || lg[0]; return `<div class="kv" style="grid-template-columns:auto 1fr"><span class="muted">Time</span><b>${r.time}</b><span class="muted">Source</span><b>${r.source}</b><span class="muted">Origin</span><b>${r.origin}</b><span class="muted">Latency</span><b>${r.latency} ms</b></div><div class="sub">Why it fired</div><div class="well"><pre class="code">close 8.018e4 < band 8.020e4\nvolume 5.05 > 0</pre></div><div class="sub">Request / response</div><div class="well"><pre class="code">POST /order {"side":"UP","size":5}\n→ 200 filled</pre></div><div class="row"><button class="btn">Copy</button><button class="btn accent">Open in Live</button></div>`; })()}</section>`,
    grid: "1.6fr 1fr", rows: "auto 1fr",
  },

  ml: {
    hub: 1, title: "ML strategy builder", extra: () => `<a class="btn" href="#model" style="text-decoration:none">Model builder →</a>`,
    html: () => `<section class="card"><h2>Data & features</h2><span class="faint">BTC candles · 60 / 20 / 20 time split</span>${features.map(([n, , on]) => `<label><input type="checkbox" ${on ? "checked" : ""}> ${n}</label>`).join("")}<button class="btn">+ Custom feature</button></section>
      <section class="card"><h2>Target & model</h2><div class="grid g2">${sel("Predict", ["Up / down", "Up / flat / down"])}${field("Horizon (bars)", state.horizon, "number")}${field("Min move %", 0.05, "number")}${sel("Model", ["Gradient boosting", "Random forest", "Logistic regression", "Neural net (MLP)"])}</div>
      <label><input type="checkbox"> Walk-forward retraining</label><div class="row"><button class="btn">Auto-tune</button><button class="btn accent">Train</button><button class="btn down">Stop</button></div>
      <h2>Trading rule</h2><div class="grid g2">${field("Bet UP / Long if P(up) ≥", state.up, "number")}${field("Bet DOWN / Short if P(up) ≤", state.down, "number")}</div>${field("Min edge vs market price", 0.03, "number")}<div class="row"><button class="btn">Edit exit rules</button><button class="btn">Open in formula</button></div></section>
      <section class="card"><h2>Results · test set</h2><table><tr><th></th><th>Train</th><th>Valid</th><th>Test</th></tr><tr><td>Accuracy</td><td>58.1%</td><td>53.0%</td><td>52.4%</td></tr><tr><td>AUC</td><td>0.61</td><td>0.54</td><td>0.53</td></tr><tr><td>Log loss</td><td>0.67</td><td>0.69</td><td>0.69</td></tr></table>
      <div class="warnbox">Train − test accuracy gap 5.7 pts: likely overfitting.</div><h2>Feature importance</h2>${features.slice(0, 7).map(([n, v]) => `<div class="hbar"><span style="width:110px" class="muted">${n}</span><span class="t"><i style="width:${v}%;background:var(--accent)"></i></span>${v}</div>`).join("")}</section>
      <section class="card" style="grid-column:1/-1"><div class="row between"><h2>Test curve vs buy & hold</h2><span class="muted">Signals 312 · Hit rate 47%</span></div><canvas id="eq"></canvas></section>`,
    grid: "1fr 1.2fr 1.2fr", rows: "1.4fr 1fr",
    foot: () => `<span class="muted">untitled model</span><span style="flex:1"></span><button class="btn">Save</button><button class="btn accent">Run full backtest</button>`,
  },

  model: {
    hub: 1, title: "Model builder", extra: () => `<a class="btn" href="#ml" style="text-decoration:none">← ML</a>`,
    html: () => `<section class="card"><h2>Layers</h2><div class="chips">${layers.map((l) => `<button class="btn">${l}</button>`).join("")}</div><label class="f">Start from${pills("preset", ["MLP", "LSTM", "Conv1D", "Blank"])}</label>
      <h2>Stack</h2><div class="muted">Input · last 30 bars × 8 features</div>${stack.map(([n, d]) => `<div class="list-item"><span>⠿ ${n}</span><span class="muted">${d}</span></div>`).join("")}</section>
      <section class="card"><h2>Layer guide</h2><span class="muted">LSTM keeps a memory across the 30 bars. Use after the input; follow with Dropout or Dense.</span><h2>Validator</h2><div class="valid">✓ shapes line up</div><div class="warnbox">A Dense after a sequence layer flattens the time axis.</div><h2>Code</h2><div class="well"><pre class="code">class Net(nn.Module):\n  def __init__(s):\n    s.lstm = nn.LSTM(8, 64)\n    s.drop = nn.Dropout(0.2)\n    s.fc = nn.Linear(64, 1)</pre></div></section>
      <section class="card"><h2>Training</h2><div class="grid g2">${sel("Loss", ["BCE", "Cross-entropy"])}${sel("Optimizer", ["Adam", "SGD"])}${field("Learning rate", 0.001, "number")}${field("Epochs", 30, "number")}${field("Batch size", 256, "number")}<label class="f">Early stopping<span><input type="checkbox" checked> patience 3</span></label></div><canvas id="loss"></canvas></section>`,
    grid: "1fr 1fr 1fr", rows: "1fr",
    foot: () => `<span style="flex:1"></span><button class="btn">Save to my models</button><button class="btn accent">Use in strategy</button>`,
  },

  settings: {
    hub: 1, title: "Settings",
    html: () => `<section class="card"><div class="grid" style="gap:4px">${["Accounts", "Backtest defaults", "Trading defaults", "General"].map((s) => `<div class="list-item ${state.sec === s ? "on" : ""}" data-set="sec=${s}">${s}</div>`).join("")}</div></section>
      <section class="card scroll">${{
        Accounts: `<h2>Hyperliquid</h2><div class="grid g2">${field("API wallet address", "0x…")}${field("Private key", "••••••••", "text")}</div><div class="row"><button class="btn">Test connection</button><button class="btn down">Disconnect</button><span class="ok">● connected · $1,204</span></div><h2>Polymarket</h2><div class="grid g2">${field("Key", "••••••••")}${field("Funder address", "0x…")}</div><div class="row"><button class="btn">Test connection</button><button class="btn down">Disconnect</button></div><div class="sub">SECURITY</div><span class="faint">Keys are stored in the macOS Keychain, never in settings.json.</span>`,
        "Backtest defaults": `<h2>Backtest defaults</h2><div class="grid g3">${field("Capital", 10000, "number")}${sel("Sizing", ["Balance %", "Fixed $"])}${field("TP %", 2, "number")}${field("SL %", 1, "number")}${field("Max cash", 2000, "number")}${field("Fee %", 0.06, "number")}</div>`,
        "Trading defaults": `<h2>Trading defaults</h2><div class="grid g3">${field("Size", 20, "number")}${field("Leverage", 3, "number")}${field("Max stake", 100, "number")}</div><div class="row"><span class="sw"></span> Place real orders (off by default)</div><div class="row"><span class="sw on"></span> Confirm before sending</div>`,
        General: `<h2>General</h2>${sel("Start page", ["Home", "Live", "Builder", "Backtest", "ML"])}${field("Candles folder", "~/.local/share/bi-trading/candles")}`,
      }[state.sec]}</section>`,
    grid: "220px 1fr", rows: "1fr",
    foot: () => `<span style="flex:1"></span><button class="btn">Reset</button><button class="btn accent">Save</button>`,
  },
};

export function draw() {
  const o = { volume: state.vol, bands: state.bb };
  const mk = [{ i: 8, side: "buy" }, { i: 25, side: "sell" }, { i: 49, side: "buy" }, { i: 70, side: "sell" }, { i: 92, side: "buy" }];
  const el = (id) => $(id);
  if (el("#hl")) drawCandles(el("#hl"), cs.slice(-120), { ...o, markers: location.hash === "#backtest" ? mk : [] });
  if (el("#btc")) drawLines(el("#btc"), [{ v: cs.map((c) => c.c), color: "--up" }]);
  if (el("#eq")) {
    const s = [{ v: eq.strategy, color: "--accent" }, { v: eq.random, color: "--band" }, { v: eq.hold, color: "--faint", dash: [3, 3] }];
    if (state.res === "compare" && location.hash === "#builder") s.push({ v: eq.hold.map((x, i) => x * 0.6 + eq.strategy[i]), color: "--up" });
    drawLines(el("#eq"), s);
  }
  if (el("#dd")) drawArea(el("#dd"), eq.strategy.map((x, i, a) => x - Math.max(...a.slice(0, i + 1))));
  if (el("#loss")) drawLines(el("#loss"), [{ v: Array.from({ length: 30 }, (_, i) => 0.9 - 0.2 * (1 - Math.exp(-i / 6)) + Math.sin(i) * 0.005), color: "--accent" }, { v: Array.from({ length: 30 }, (_, i) => 0.92 - 0.1 * (1 - Math.exp(-i / 4)) + i * 0.002), color: "--band" }]);
}
