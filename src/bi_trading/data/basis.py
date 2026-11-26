"""How far the history the backtest runs on is from the venue it trades on.

The history is Binance spot BTCUSDT; the orders go to Hyperliquid perps (and
Polymarket). Prices, spreads and wicks differ, most on one-minute bars, so a fill
that worked on Binance can be impossible on the venue. The venue serves only its
latest few thousand candles, so a full-history swap is not possible; this measures
the gap over the window it does give and keeps the answer where the backtest shows it.

    uv run python -m bi_trading.data.basis        # fetch, compare, save

`compare` is pure (two sets of bars in, a report out); `fetch_venue` is the only
part that touches the network, and takes the poster as an argument.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

__all__ = ["compare", "fetch_venue", "latest_basis", "report_path", "run", "summary"]

INFO_URL = "https://api.hyperliquid.xyz/info"
MINUTE_MS = 60_000
VENUE_BARS = 5_000          # all the venue keeps at any interval
STALE_DAYS = 30             # a report older than this is shown as old


def report_path() -> Path:
    return Path(os.environ.get("BI_TRADING_BASIS", "~/.config/bi-trading/basis.json")).expanduser()


def compare(binance: dict, venue: dict) -> dict:
    """The gap between two sets of 1m bars, matched by their stamp.

    Each is `{"stamps", "open", "high", "low", "close"}` as arrays. Returns the
    number of bars matched, the venue's close minus Binance's in basis points
    (`mean_bps`), the typical and worst-5% size of that gap (`median_abs_bps`,
    `p95_abs_bps`), how wide the venue's bars are next to Binance's
    (`range_ratio`), and how often the two disagree about whether a level one
    typical bar range from the open was touched (`touch_disagree_up`: a target
    above; `touch_disagree_down`: a stop below).
    """
    common, ib, iv = np.intersect1d(
        np.asarray(binance["stamps"]), np.asarray(venue["stamps"]), return_indices=True
    )
    if len(common) < 30:
        return {"bars": int(len(common))}

    def pick(source, key, index):
        return np.asarray(source[key], dtype=float)[index]

    b_open, b_high, b_low, b_close = (pick(binance, k, ib) for k in ("open", "high", "low", "close"))
    v_open, v_high, v_low, v_close = (pick(venue, k, iv) for k in ("open", "high", "low", "close"))
    gap = (v_close / b_close - 1.0) * 1e4
    b_range = (b_high - b_low) / b_open
    v_range = (v_high - v_low) / v_open
    live = b_range > 0
    level = float(np.median(b_range[live])) if live.any() else 0.0
    up_b = b_high >= b_open * (1.0 + level)
    up_v = v_high >= v_open * (1.0 + level)
    down_b = b_low <= b_open * (1.0 - level)
    down_v = v_low <= v_open * (1.0 - level)
    return {
        "bars": int(len(common)),
        "first": int(common[0]),
        "last": int(common[-1]),
        "mean_bps": float(gap.mean()),
        "median_abs_bps": float(np.median(np.abs(gap))),
        "p95_abs_bps": float(np.percentile(np.abs(gap), 95)),
        "range_ratio": float(np.median(v_range[live] / b_range[live])) if live.any() else None,
        "level_pct": level * 100.0,
        "touch_disagree_up": float(np.mean(up_b != up_v)),
        "touch_disagree_down": float(np.mean(down_b != down_v)),
    }


def fetch_venue(
    post: Callable[[dict], list] | None = None, coin: str = "BTC", bars: int = VENUE_BARS
) -> dict:
    """The venue's latest 1m bars as arrays. `post` takes the request body."""
    now = int(time.time() * 1000)
    body = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin, "interval": "1m",
            "startTime": now - bars * MINUTE_MS, "endTime": now,
        },
    }
    if post is None:
        import httpx

        def post(payload: dict) -> list:
            response = httpx.post(INFO_URL, json=payload, timeout=20.0)
            response.raise_for_status()
            return response.json()

    rows = []
    for item in post(body):
        try:
            rows.append((int(item["t"]), float(item["o"]), float(item["h"]),
                         float(item["l"]), float(item["c"])))
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort()
    columns = np.array(rows, dtype=float).reshape(-1, 5)
    return {
        "stamps": columns[:, 0].astype(np.int64), "open": columns[:, 1],
        "high": columns[:, 2], "low": columns[:, 3], "close": columns[:, 4],
    }


def _store_bars(first: int, last: int) -> dict | None:
    """The stored Binance 1m bars from `first` to `last` (ms), or None."""
    from datetime import UTC, datetime

    from bi_trading.ui.strat.playback_data import load_span

    years = sorted({datetime.fromtimestamp(first / 1000, UTC).year,
                    datetime.fromtimestamp(last / 1000, UTC).year})
    span = load_span(years, "1m")
    if span is None or span.length == 0:
        return None
    keep = (span.stamps >= first) & (span.stamps <= last)
    return {
        "stamps": span.stamps[keep], "open": span.opens[keep], "high": span.highs[keep],
        "low": span.lows[keep], "close": span.closes[keep],
    }


def run(post: Callable[[dict], list] | None = None) -> dict:
    """Fetch the venue's bars, compare with the stored history, save, return."""
    venue = fetch_venue(post)
    if not len(venue["stamps"]):
        raise RuntimeError("the venue returned no candles")
    mine = _store_bars(int(venue["stamps"][0]), int(venue["stamps"][-1]))
    if mine is None or not len(mine["stamps"]):
        raise RuntimeError(
            "the stored history does not reach the venue's recent bars: download the "
            "current year in the Backtest view first"
        )
    report = compare(mine, venue)
    report["venue"] = "Hyperliquid BTC perp"
    report["history"] = "Binance spot BTCUSDT"
    report["made_at"] = time.time()
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def latest_basis() -> dict | None:
    """The saved report, or None when there is none."""
    try:
        report = json.loads(report_path().read_text())
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) and report.get("bars") else None


def summary(report: dict | None, now: float | None = None) -> str:
    """One line for the backtest's evidence row."""
    if not report:
        return "venue data: not compared (run python -m bi_trading.data.basis)"
    age = ((now if now is not None else time.time()) - float(report.get("made_at") or 0)) / 86400
    old = f", {age:.0f} days old" if age > STALE_DAYS else ""
    ratio = report.get("range_ratio")
    return (
        f"venue check ({report['bars']:,} bars{old}): close differs {report['median_abs_bps']:.1f} bps "
        f"typically, {report['p95_abs_bps']:.1f} at the 95th"
        + ("" if ratio is None else f", venue bars {ratio:.2f}x as wide")
        + f"; a target/stop one bar-range from the open is touched on one venue but not "
        f"the other {report['touch_disagree_up'] * 100:.0f}% / {report['touch_disagree_down'] * 100:.0f}% of bars"
    )


if __name__ == "__main__":  # pragma: no cover
    print(summary(run()))
