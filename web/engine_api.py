"""The engine behind the web sandbox: the same Qt-free code the desktop app runs.

`serve.py` routes `/api/...` here. Every answer is JSON; nothing places an order.

    GET  /api/status                 data on disk (candles, Polymarket prices), engine version
    GET  /api/strategies             the saved strategies (shared with the desktop app)
    POST /api/strategies             save one {name, timeframe, entry, exit, short_entry, venue}
    POST /api/parse                  check a rule {text, kind: entry|exit, venue}
    POST /api/backtest               Hyperliquid-style run over the Binance 1m candles
    POST /api/backtest/polymarket    the binary run over the past five-minute markets

The candle store is `BI_TRADING_DATA` (or the app's configured folder); `serve.py`
points it at the main checkout's `data/candles` when this worktree has none.
"""

from __future__ import annotations

import math
import time
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


def run_hyperliquid(body: dict) -> dict:
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
    if n > 400_000:
        raise ApiError(f"{n:,} bars is too many for one web run: shorten the span or pick a longer timeframe")
    bars = [
        {"timestamp": int(c["timestamp"][i]), "open": float(c["open"][i]), "high": float(c["high"][i]),
         "low": float(c["low"][i]), "close": float(c["close"][i]), "volume": float(c["volume"][i])}
        for i in range(n)
    ]
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


def run_polymarket(body: dict) -> dict:
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


ROUTES = {
    ("GET", "/api/status"): status,
    ("GET", "/api/strategies"): list_strategies,
    ("POST", "/api/strategies"): save_strategy,
    ("POST", "/api/parse"): check_rule,
    ("POST", "/api/backtest"): run_hyperliquid,
    ("POST", "/api/backtest/polymarket"): run_polymarket,
}
