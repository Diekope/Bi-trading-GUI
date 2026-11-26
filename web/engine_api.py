"""The engine behind the web sandbox: the same Qt-free code the desktop app runs.

`serve.py` routes `/api/...` here. Every answer is JSON; nothing places an order.

    GET  /api/status                 data on disk (candles, Polymarket prices), engine version
    GET  /api/strategies             the saved strategies (shared with the desktop app)
    POST /api/strategies             save one {name, timeframe, entry, exit, short_entry, venue}
    POST /api/parse                  check a rule {text, kind: entry|exit, venue}
    POST /api/backtest               Hyperliquid-style run over the Binance 1m candles ({days} or {year})
    POST /api/backtest/polymarket    the binary run over the past five-minute markets

The candle store is `BI_TRADING_DATA` (or the app's configured folder); `serve.py`
points it at the main checkout's `data/candles` when this worktree has none.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from bi_trading.data import candles
from bi_trading.engine import binary
from bi_trading.engine.formula import (
    ENTRY_FIELDS,
    EXIT_FIELDS,
    EXIT_FUNCTIONS,
    FUNCTIONS,
    PM_ENTRY_FIELDS,
    PM_EXIT_FIELDS,
    FormulaError,
    parse,
)
from bi_trading.engine.formula_eval import FEE, SLIPPAGE, _walk, backtest, entry_signals
from bi_trading.state import strategies

DAY_MS = 86_400_000
TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
MAX_POINTS = 600          # curves are thinned to this many points for the page
MAX_ROWS = 500            # trades / bets sent back
DEFAULT_EXIT = "pnl >= tp or pnl <= -sl"


class ApiError(Exception):
    """A 400: the request does not hold up (bad rule, no data, bad number)."""


# -- helpers ---------------------------------------------------------------------


def _num(body: dict, key: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
    raw = body.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ApiError(f"{key}: not a number ({raw!r})") from None
    if not math.isfinite(value):
        raise ApiError(f"{key}: not a finite number")
    if lo is not None and value < lo or hi is not None and value > hi:
        raise ApiError(f"{key}: {value} is outside {lo} to {hi}")
    return value


def _thin(values, n: int = MAX_POINTS) -> list[float]:
    values = list(values)
    if len(values) <= n:
        return [round(float(v), 4) for v in values]
    step = (len(values) - 1) / (n - 1)
    return [round(float(values[round(i * step)]), 4) for i in range(n)]


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def _span(body: dict, floor_ms: int = 0) -> tuple[int, int]:
    last = int(time.time() * 1000)
    if body.get("year") not in (None, ""):          # one calendar year
        body = {**body, "year_from": body["year"], "year_to": body["year"]}
    if body.get("year_from") not in (None, "") or body.get("year_to") not in (None, ""):
        y0 = int(_num(body, "year_from", 2017, 2009, 2100))
        y1 = int(_num(body, "year_to", y0, 2009, 2100))
        if y1 < y0:
            raise ApiError(f"the end year ({y1}) is before the start year ({y0})")
        first = int(datetime(y0, 1, 1, tzinfo=UTC).timestamp() * 1000)
        end = int(datetime(y1 + 1, 1, 1, tzinfo=UTC).timestamp() * 1000) - 1
        return max(first, floor_ms), min(end, last)
    days = _num(body, "days", 90, 0, 20 * 365)
    first = floor_ms if days == 0 else last - int(days * DAY_MS)
    return max(first, floor_ms), last


def _rule(text: str, fields, functions=FUNCTIONS, what: str = "rule"):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return parse(text, fields, functions)
    except FormulaError as exc:
        raise ApiError(f"{what}: {exc}") from None


def load_candles(first_ms: int, last_ms: int) -> dict[str, np.ndarray]:
    """The 1m Binance candles between two times (as `strat_pm.load_candles`)."""
    parts = []
    for year in range(datetime.fromtimestamp(first_ms / 1000, UTC).year,
                      datetime.fromtimestamp(last_ms / 1000, UTC).year + 1):
        data = candles.arrays(candles.candle_file(year))
        if data is not None:
            parts.append(data)
    names = ("timestamp", "open", "high", "low", "close", "volume")
    if not parts:
        return {name: np.array([]) for name in names}
    joined = [np.concatenate([p[i] for p in parts]) for i in range(6)]
    mask = (joined[0] >= first_ms) & (joined[0] <= last_ms)
    return {name: joined[i][mask] for i, name in enumerate(names)}


def resample(c: dict[str, np.ndarray], minutes: int) -> dict[str, np.ndarray]:
    """1m candles to `minutes`, on clock-aligned buckets; a partial bucket is kept."""
    if minutes <= 1 or not len(c["timestamp"]):
        return c
    size = minutes * 60_000
    bucket = (c["timestamp"] // size).astype(np.int64)
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(bucket)] - 1
    return {
        "timestamp": bucket[starts] * size,
        "open": c["open"][starts],
        "high": np.maximum.reduceat(c["high"], starts),
        "low": np.minimum.reduceat(c["low"], starts),
        "close": c["close"][ends],
        "volume": np.add.reduceat(c["volume"], starts),
    }


# -- endpoints ---------------------------------------------------------------------


def status(_body: dict | None = None) -> dict:
    years = []
    for path in sorted(candles.candles_dir().glob("BTC-*-1m.parquet")):
        years.append({"year": int(path.stem.split("-")[1]), "rows": candles.row_count(path)})
    pm = {"markets": 0, "missing": 0, "newest": None}
    try:
        from bi_trading.data import polymarket_history

        have, missing, newest = polymarket_history.coverage()
        pm = {"markets": have, "missing": missing, "newest": _iso(newest) if newest else None,
              "start": _iso(polymarket_history.HISTORY_START_MS)}
    except Exception as exc:  # the store is optional
        pm["error"] = f"{type(exc).__name__}: {exc}"
    return {"dataDir": str(candles.candles_dir()), "candles": years, "polymarket": pm}


def list_strategies(_body: dict | None = None) -> dict:
    return {"strategies": [
        {**s.as_dict(), "venue": "Polymarket" if _is_pm(s) else "Hyperliquid"}
        for s in strategies.load()
    ], "path": str(strategies.path())}


def _is_pm(s) -> bool:
    words = ("up_price", "down_price", "seconds_left", "minute")
    return any(w in f"{s.entry} {s.exit} {s.short_entry}" for w in words)


def save_strategy(body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    if not name:
        raise ApiError("name: a strategy needs a name")
    pm = body.get("venue") == "Polymarket"
    entry, exit_, short = (str(body.get(k) or "") for k in ("entry", "exit", "short_entry"))
    _rule(entry, PM_ENTRY_FIELDS if pm else ENTRY_FIELDS, what="entry")
    _rule(short, PM_ENTRY_FIELDS if pm else ENTRY_FIELDS, what="second entry")
    _rule(exit_, PM_EXIT_FIELDS if pm else EXIT_FIELDS, FUNCTIONS if pm else EXIT_FUNCTIONS, what="exit")
    saved = strategies.save(strategies.SavedStrategy(
        name=name, timeframe=str(body.get("timeframe") or "1m"), entry=entry, exit=exit_,
        side="long", short_entry=short,
    ))
    return {"saved": name, "count": len(saved)}


def check_rule(body: dict) -> dict:
    pm = body.get("venue") == "Polymarket"
    exit_ = body.get("kind") == "exit"
    fields = (PM_EXIT_FIELDS if exit_ else PM_ENTRY_FIELDS) if pm else (EXIT_FIELDS if exit_ else ENTRY_FIELDS)
    functions = EXIT_FUNCTIONS if exit_ and not pm else FUNCTIONS
    try:
        parse(str(body.get("text") or ""), fields, functions)
    except FormulaError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "fields": list(fields)}


def _hl_setup(body: dict):
    """Rules, money and bars of a Hyperliquid-style run, as both the run and the sweep need them."""
    tf = str(body.get("timeframe") or "1m")
    if tf not in TF_MINUTES:
        raise ApiError(f"timeframe: one of {', '.join(TF_MINUTES)}")
    entry = _rule(body.get("entry"), ENTRY_FIELDS, what="entry")
    if entry is None:
        raise ApiError("entry: write an entry rule first")
    # Without an exit rule the walk closes on the next bar; TP and SL only act through the rule,
    # so an empty one means "take profit or stop loss".
    exit_text = str(body.get("exit") or "").strip() or DEFAULT_EXIT
    exit_ = _rule(exit_text, EXIT_FIELDS, EXIT_FUNCTIONS, what="exit")
    short_entry = _rule(body.get("short_entry"), ENTRY_FIELDS, what="second entry")
    short = body.get("side") == "short"
    tp, sl = _num(body, "tp", 2.0, 0, 1000), _num(body, "sl", 1.0, 0, 100)
    capital = _num(body, "capital", 10_000, 1)
    fee = _num(body, "fee_pct", FEE * 100, 0, 10) / 100
    first, last = _span(body)
    c = resample(load_candles(first, last), TF_MINUTES[tf])
    n = len(c["timestamp"])
    if n < 2:
        raise ApiError(f"no candles on disk for that span (looked in {candles.candles_dir()})")
    if n > 1_200_000:
        raise ApiError(f"{n:,} bars is too many for one web run: shorten the span or pick a longer timeframe")
    bars = [
        {"timestamp": int(c["timestamp"][i]), "open": float(c["open"][i]), "high": float(c["high"][i]),
         "low": float(c["low"][i]), "close": float(c["close"][i]), "volume": float(c["volume"][i])}
        for i in range(n)
    ]
    return tf, entry, exit_text, exit_, short_entry, short, tp, sl, capital, fee, c, n, bars


def run_hyperliquid(body: dict) -> dict:
    tf, entry, exit_text, exit_, short_entry, short, tp, sl, capital, fee, c, n, bars = _hl_setup(body)
    report = backtest(bars, entry, exit_, tp=tp, sl=sl, capital=capital, fee=fee,
                      short=short, short_entry=short_entry)

    # The trade list: walk once more with the same entries, keeping each trade.
    closes = c["close"].tolist()
    signals = set(entry_signals(entry, bars, ENTRY_FIELDS))
    shorting = set(entry_signals(short_entry, bars, ENTRY_FIELDS)) if short_entry is not None and not short else None
    _, results, reasons, _ = _walk(closes, signals, exit_, tp, sl, capital, fee, short, shorting, SLIPPAGE)
    rows = [{"n": i + 1, "pnl": round(r * 100, 3), "reason": reasons[i] if i < len(reasons) else ""}
            for i, r in enumerate(results)]

    eq = report.strategy
    peak, dd = eq[0] if eq else capital, 0.0
    ddc = []
    for v in eq:
        peak = max(peak, v)
        d = (v / peak - 1) * 100 if peak else 0
        dd = min(dd, d)
        ddc.append(d)
    pct = lambda curve: [(v / capital - 1) * 100 for v in curve]  # noqa: E731
    final = eq[-1] if eq else capital
    hist = np.histogram([r["pnl"] for r in rows], bins=40)[0].tolist() if rows else []
    return {
        "exit": exit_text, "bars": n, "from": _iso(int(c["timestamp"][0])), "to": _iso(int(c["timestamp"][-1])), "timeframe": tf,
        "trades": report.trades, "wins": report.wins,
        "winRate": report.wins / report.trades if report.trades else 0.0,
        "pnlPct": (final / capital - 1) * 100, "final": final, "fees": report.fees, "maxDD": dd,
        "randomPct": (report.random[-1] / capital - 1) * 100 if report.random else 0.0,
        "holdPct": (report.hold[-1] / capital - 1) * 100 if report.hold else 0.0,
        "reasons": [{"label": lab, "count": cnt, "share": sh} for lab, cnt, sh in report.reason_shares],
        "curves": {"strategy": _thin(pct(eq)), "random": _thin(pct(report.random)),
                   "hold": _thin(pct(report.hold)), "drawdown": _thin(ddc)},
        "histogram": hist,
        "histRange": [min(r["pnl"] for r in rows), max(r["pnl"] for r in rows)] if rows else [0, 0],
        "tradeRows": rows[-MAX_ROWS:][::-1],
        "price": _thin(closes),
    }


def run_polymarket_inputs(body: dict):
    """Candles, Polymarket history, rules and bet values of a Polymarket run."""
    from bi_trading.data import polymarket_history

    entry = _rule(body.get("entry"), PM_ENTRY_FIELDS, what="bet UP rule")
    down = _rule(body.get("short_entry"), PM_ENTRY_FIELDS, what="bet DOWN rule")
    exit_ = _rule(body.get("exit"), PM_EXIT_FIELDS, what="cash-out rule")
    if entry is None and down is None:
        raise ApiError("write a bet UP or a bet DOWN rule first")
    side = "down" if body.get("side") == "down" else "up"
    if entry is None:              # only a DOWN rule: it is the one rule, betting DOWN
        entry, down, side = down, None, "down"
    params = binary.BinaryParams(
        capital=_num(body, "capital", 1000, 1), stake_pct=_num(body, "stake_pct", 5, 0, 100), side=side,
        first_minute=int(_num(body, "first_minute", 1, 1, 4)),
        half_spread=_num(body, "half_spread_cents", 1, 0, 50) / 100,
        fee_pct=_num(body, "fee_pct", 0, 0, 50), tp=_num(body, "tp", 0, 0, 10_000), sl=_num(body, "sl", 0, 0, 100),
    )
    first, last = _span(body, polymarket_history.HISTORY_START_MS)
    bars = load_candles(first, last)
    if not len(bars["timestamp"]):
        raise ApiError(f"no Binance candles on disk for that span (looked in {candles.candles_dir()})")
    history = polymarket_history.load_rows(first, last)
    return bars, history, entry, exit_, params, down


def run_polymarket(body: dict) -> dict:
    bars, history, entry, exit_, params, down = run_polymarket_inputs(body)
    first, last = int(bars["timestamp"][0]), int(bars["timestamp"][-1])
    result = binary.run_binary(bars, history, entry, exit_, params, down)
    base = {s: binary.always_side(bars, history, s, params) for s in ("up", "down")}
    cap = params.capital

    def figures(r) -> dict:
        return {"bets": len(r.trades), "winRate": r.win_rate, "roi": r.roi, "pnl": r.pnl,
                "final": r.final_equity, "maxDD": r.max_drawdown}

    reasons: dict[str, int] = {}
    for t in result.trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    total = len(result.trades) or 1
    pct = lambda curve: [(v / cap - 1) * 100 for v in curve]  # noqa: E731
    peak, ddc = cap, []
    for v in result.window_equity:
        peak = max(peak, v)
        ddc.append((v / peak - 1) * 100 if peak else 0)
    return {
        **figures(result), "markets": result.windows, "realMarkets": result.real_windows,
        "early": result.early, "settled": len(result.trades) - result.early,
        "realEntries": sum(t.real_price for t in result.trades),
        "estimated": sum(t.estimated_outcome for t in result.trades),
        "from": _iso(first), "to": _iso(last), "halfSpreadCents": params.half_spread * 100,
        "baselines": {s: figures(r) for s, r in base.items()},
        "reasons": sorted(({"label": k, "count": v, "share": v / total} for k, v in reasons.items()),
                          key=lambda x: -x["count"]),
        "curves": {"strategy": _thin(pct(result.window_equity)), "up": _thin(pct(base["up"].window_equity)),
                   "down": _thin(pct(base["down"].window_equity)), "drawdown": _thin(ddc)},
        "betRows": [
            {"at": _iso(t.start_ms), "side": t.side.upper(), "inM": f"m{t.entry_minute}",
             "buy": round(t.entry_price, 3), "outM": "settle" if t.exit_minute >= binary.STEPS else f"m{t.exit_minute}",
             "sold": round(t.exit_price, 3), "stake": round(t.stake, 2), "pnl": round(t.pnl, 2),
             "ended": t.reason, "prices": "real" if t.real_price else "sim"}
            for t in result.trades[-MAX_ROWS:][::-1]
        ],
    }


def _values(body: dict, key: str, default: list[float], hi: float) -> list[float]:
    raw = body.get(key, default)
    if isinstance(raw, str):
        raw = [x for x in raw.replace(";", ",").split(",") if x.strip()]
    try:
        vals = sorted({round(float(x), 6) for x in raw})
    except (TypeError, ValueError):
        raise ApiError(f"{key}: numbers separated by commas") from None
    if not vals or len(vals) > 8 or any(v < 0 or v > hi for v in vals):
        raise ApiError(f"{key}: 1 to 8 values between 0 and {hi:g}")
    return vals


def sweep(body: dict) -> dict:
    """The strategy under every take profit x stop loss pair: one cell per pair.

    TP and SL act through the exit rule (`pnl >= tp`, `pnl <= -sl`); a rule that never
    reads them gives the same result in every cell, which the answer says.
    """
    tps = _values(body, "tps", [1, 2, 3, 4, 5], 1000)
    sls = _values(body, "sls", [0.5, 1, 1.5, 2, 3], 100)
    pm = body.get("venue") == "Polymarket"
    cells = []
    if pm:
        exit_text = str(body.get("exit") or "")
        bars, history, entry, exit_, params, down = run_polymarket_inputs(body)
        for sl_v in sls:
            for tp_v in tps:
                r = binary.run_binary(bars, history, entry, exit_, replace(params, tp=tp_v, sl=sl_v), down)
                cells.append({"tp": tp_v, "sl": sl_v, "pnlPct": (r.final_equity / params.capital - 1) * 100,
                              "trades": len(r.trades), "winRate": r.win_rate, "maxDD": -r.max_drawdown * 100})
    else:
        tf, entry, exit_text, exit_, short_entry, short, _tp, _sl, capital, fee, c, n, bars = _hl_setup(body)
        closes = c["close"].tolist()
        signals = set(entry_signals(entry, bars, ENTRY_FIELDS))
        shorting = set(entry_signals(short_entry, bars, ENTRY_FIELDS)) if short_entry is not None and not short else None
        for sl_v in sls:
            for tp_v in tps:
                eq, results, _, _ = _walk(closes, signals, exit_, tp_v, sl_v, capital, fee, short, shorting, SLIPPAGE)
                peak, dd = capital, 0.0
                for v in eq:
                    peak = max(peak, v)
                    dd = min(dd, (v / peak - 1) * 100 if peak else 0)
                cells.append({"tp": tp_v, "sl": sl_v, "pnlPct": ((eq[-1] if eq else capital) / capital - 1) * 100,
                              "trades": len(results), "winRate": sum(r > 0 for r in results) / len(results) if results else 0.0,
                              "maxDD": dd})
    uses = any(w in exit_text for w in ("tp", "sl"))
    return {"tps": tps, "sls": sls, "cells": cells, "exit": exit_text, "usesTpSl": uses}


def delete_strategy(body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    if not name:
        raise ApiError("name: which strategy?")
    kept = strategies.remove(name)
    return {"deleted": name, "count": len(kept)}


# -- the live walk: the desktop app's playback, stepped from the page --------------------------
#
# A Hyperliquid backtest is not computed and then shown: the page starts a session here and asks
# for a few ticks at a time, exactly as the desktop's playback tile advances its `BacktestSession`.

PLAYS: dict[str, dict] = {}
MAX_PLAYS = 4
PLAY_TFS = ("1m", "3m", "5m", "15m", "30m", "1h")


def _play(body: dict) -> dict:
    p = PLAYS.get(str(body.get("id") or ""))
    if p is None:
        raise ApiError("this run is no longer held: start it again")
    p["used"] = time.time()
    return p


def _keep(entry: dict) -> str:
    import uuid

    while len(PLAYS) >= MAX_PLAYS:                      # forget the least recently used run
        old = PLAYS.pop(min(PLAYS, key=lambda k: PLAYS[k]["used"]))
        if old.get("cond") is not None:                 # let a parked Polymarket walk finish and exit
            with old["cond"]:
                old["stop"] = True
                old["cond"].notify_all()
    pid = uuid.uuid4().hex[:12]
    entry["used"] = time.time()
    PLAYS[pid] = entry          # the same dict the walk thread writes to
    return pid


def pm_play_start(body: dict) -> dict:
    """The Polymarket walk: `run_binary` itself, on a thread that waits for the page between markets."""
    import threading

    bars, history, entry, exit_, params, down = run_polymarket_inputs(body)
    base = {side: binary.always_side(bars, history, side, params) for side in ("up", "down")}
    p = {"pm": True, "cond": threading.Condition(), "budget": 0, "res": None, "n": 0, "done": False, "stop": False, "err": "",
         "base": base, "meta": {"capital": params.capital, "halfSpread": params.half_spread * 100,
                                "from": _iso(int(bars["timestamp"][0])), "to": _iso(int(bars["timestamp"][-1]))}}

    def paced(result) -> None:
        with p["cond"]:
            p["res"], p["n"] = result, p["n"] + 1
            p["budget"] -= 1
            p["cond"].notify_all()
            while p["budget"] <= 0 and not p["stop"]:
                p["cond"].wait()

    def walk() -> None:
        try:
            r = binary.run_binary(bars, history, entry, exit_, params, down, progress=paced)
            with p["cond"]:
                p["res"] = r
        except Exception as exc:  # shown on the page
            p["err"] = f"{type(exc).__name__}: {exc}"
        with p["cond"]:
            p["done"] = True
            p["cond"].notify_all()

    pid = _keep(p)
    threading.Thread(target=walk, daemon=True).start()
    return {"id": pid, **_pm_advance(p, 1, body)}


def _pm_advance(p: dict, ticks: float, body: dict) -> dict:
    with p["cond"]:
        p["budget"] += ticks
        p["cond"].notify_all()
        deadline = time.time() + 20
        while p["budget"] > 0 and not p["done"] and time.time() < deadline:
            p["cond"].wait(0.5)
        return _pm_snapshot(p, body)


def _pm_snapshot(p: dict, body: dict) -> dict:
    if p["err"]:
        raise ApiError(p["err"])
    r, meta, cap = p["res"], p["meta"], p["meta"]["capital"]
    if r is None:
        return {"pm": True, "index": 0, "total": 0, "done": p["done"], **meta}
    n = len(r.window_equity) - 1
    trades = list(r.trades)
    pct = lambda curve: [(v / cap - 1) * 100 for v in curve]  # noqa: E731
    eq = list(r.window_equity)
    peak, dd, ddc = cap, 0.0, []
    for v in eq:
        peak = max(peak, v)
        d = (v / peak - 1) * 100 if peak else 0
        dd = min(dd, d)
        ddc.append(d)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    staked = sum(t.stake for t in trades)
    pnl = sum(t.pnl for t in trades)
    rows = int(_num(body, "rows", 100, 0, MAX_ROWS))
    base = {side: list(b.window_equity[: n + 1]) for side, b in p["base"].items()}
    return {
        "pm": True, "index": n, "total": r.windows, "done": p["done"], **meta,
        "stats": {"bets": len(trades), "markets": n, "winRate": sum(t.won for t in trades) / len(trades) if trades else 0.0,
                  "roi": pnl / staked if staked else 0.0, "pnl": pnl, "equity": eq[-1], "maxDD": dd,
                  "early": sum(1 for t in trades if t.exit_minute < binary.STEPS),
                  "realEntries": sum(t.real_price for t in trades), "estimated": sum(t.estimated_outcome for t in trades)},
        "baselines": {side: {"roi": (b[-1] / cap - 1) * 100 if b else 0.0} for side, b in base.items()},
        "curves": {"strategy": _thin(pct(eq)), "up": _thin(pct(base["up"])), "down": _thin(pct(base["down"])), "drawdown": _thin(ddc)},
        "reasons": sorted(({"label": k, "count": v, "share": v / (len(trades) or 1)} for k, v in reasons.items()), key=lambda x: -x["count"]),
        "betRows": [
            {"at": _iso(t.start_ms), "side": t.side.upper(), "inM": f"m{t.entry_minute}", "buy": round(t.entry_price, 3),
             "outM": "settle" if t.exit_minute >= binary.STEPS else f"m{t.exit_minute}", "sold": round(t.exit_price, 3),
             "stake": round(t.stake, 2), "pnl": round(t.pnl, 2), "ended": t.reason, "prices": "real" if t.real_price else "sim"}
            for t in trades[-rows:][::-1]
        ],
    }


def play_start(body: dict) -> dict:
    import threading

    from bi_trading.ui.strat.playback_session import build_session

    if body.get("venue") == "Polymarket":
        return pm_play_start(body)

    tf = str(body.get("timeframe") or "1h")
    if tf not in PLAY_TFS:
        raise ApiError(f"timeframe: one of {', '.join(PLAY_TFS)}")
    entry = _rule(body.get("entry"), ENTRY_FIELDS, what="entry")
    if entry is None:
        raise ApiError("entry: write an entry rule first")
    exit_text = str(body.get("exit") or "").strip() or DEFAULT_EXIT
    exit_ = _rule(exit_text, EXIT_FIELDS, EXIT_FUNCTIONS, what="exit")
    short_entry = _rule(body.get("short_entry"), ENTRY_FIELDS, what="second entry")
    y0 = int(_num(body, "year_from", 2026, 2009, 2100))
    y1 = int(_num(body, "year_to", y0, 2009, 2100))
    if y1 < y0:
        raise ApiError(f"the end year ({y1}) is before the start year ({y0})")
    have = {int(p.stem.split("-")[1]) for p in candles.candles_dir().glob("BTC-*-1m.parquet")}
    years = [y for y in range(y0, y1 + 1) if y in have]
    if not years:
        raise ApiError(f"no candles on disk for {y0}–{y1} (looked in {candles.candles_dir()})")
    params = {
        "initial_capital": _num(body, "capital", 10_000, 1), "tp": _num(body, "tp", 2, 0, 1000),
        "sl": _num(body, "sl", 1, 0, 100), "position": _num(body, "position", 10, 0, 1e9),
        "sizing": "fixed" if body.get("sizing") == "fixed" else "balance",
        "cash": _num(body, "max_cash", 2000, 0, 1e12), "fee": _num(body, "fee_pct", 0.06, 0, 10),
    }
    side = "both" if short_entry is not None and body.get("side") != "short" else ("short" if body.get("side") == "short" else "long")
    session = build_session(years, params, "formula", tf, entry_formula=entry, exit_formula=exit_,
                            side=side, short_entry_formula=short_entry)
    pid = _keep({"s": session, "lock": threading.Lock(),
                 "meta": {"years": [y0, y1], "timeframe": tf, "exit": exit_text, "capital": params["initial_capital"]}})
    return {"id": pid, **_snapshot(PLAYS[pid], body)}


def play_step(body: dict) -> dict:
    p = _play(body)
    ticks = int(_num(body, "ticks", 1, 0, 5000))
    if p.get("pm"):
        return _pm_advance(p, ticks, body)
    with p["lock"]:
        s = p["s"]
        for _ in range(ticks):
            if s.strategy.done:
                break
            s.advance()
        return _snapshot(p, body)


def play_end(body: dict) -> dict:
    p = _play(body)
    if p.get("pm"):
        return _pm_advance(p, float("inf"), {**body, "rows": MAX_ROWS})
    with p["lock"]:
        p["s"].seek(p["s"].total)
        return _snapshot(p, {**body, "rows": MAX_ROWS})


def _snapshot(p: dict, body: dict) -> dict:
    s, meta = p["s"], p["meta"]
    play, cap = s.strategy, s.capital
    view = int(_num(body, "view", 160, 20, 1500))
    recent = play.recent()[-view:]
    first_index = play.index - len(recent)
    markers = [{"i": i - first_index - 1, "side": side, "px": px} for i, side, px in play.markers if i > first_index]
    pct = lambda curve: [(v / cap - 1) * 100 for v in curve]  # noqa: E731
    log = play.trades_log
    reasons: dict[str, int] = {}
    for t in log:
        reasons[t[9]] = reasons.get(t[9], 0) + 1
    words = {"tp": "Take profit", "sl": "Stop loss", "time": "Time", "rule": "Rule", "gap": "Data gap"}
    return {
        "index": play.index, "total": play.total, "stride": play.stride, "done": play.done,
        "years": meta["years"], "timeframe": meta["timeframe"], "exit": meta["exit"], "capital": cap,
        "candles": [[c.stamp, c.open, c.high, c.low, c.close, c.volume] for c in recent],
        "markers": markers,
        "stats": {
            "equity": play.equity, "pnlPct": (play.equity / cap - 1) * 100, "drawdown": play.drawdown() * 100,
            "maxDD": -abs(play.max_drawdown) * 100, "maxGain": play.max_gain * 100, "trades": play.trades,
            "winRate": play.win_rate, "fees": play.fees, "sharpe": play.sharpe, "exposure": play.exposure,
            "streak": play.streak, "bestWin": play.best_win, "worstLoss": play.worst_loss,
            "randomPct": (s.random.equity / cap - 1) * 100, "holdPct": (s.buy_and_hold() / cap - 1) * 100,
        },
        "curves": {"strategy": _thin(pct(s.strategy_curve)), "random": _thin(pct(s.random_curve)), "hold": _thin(pct(s.benchmark))},
        "reasons": sorted(({"label": words.get(k, k), "count": v, "share": v / (len(log) or 1)} for k, v in reasons.items()), key=lambda x: -x["count"]),
        "tradeRows": [{"n": len(log) - k, "in": _iso(t[0]), "out": _iso(t[3]), "side": t[12], "inPx": t[2], "outPx": t[5],
                       "pnl": round(t[6] * 100, 3), "usd": round(t[8], 2), "reason": words.get(t[9], t[9])}
                      for k, t in enumerate(reversed(log[-int(_num(body, "rows", 100, 0, MAX_ROWS)):]))],
    }


ROUTES = {
    ("GET", "/api/status"): status,
    ("GET", "/api/strategies"): list_strategies,
    ("POST", "/api/strategies"): save_strategy,
    ("POST", "/api/parse"): check_rule,
    ("POST", "/api/backtest"): run_hyperliquid,
    ("POST", "/api/backtest/polymarket"): run_polymarket,
    ("POST", "/api/sweep"): sweep,
    ("POST", "/api/play/start"): play_start,
    ("POST", "/api/play/step"): play_step,
    ("POST", "/api/play/end"): play_end,
    ("POST", "/api/strategies/delete"): delete_strategy,
}
