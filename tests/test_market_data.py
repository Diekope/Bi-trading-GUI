"""Pure market-data logic: parsing, formatting, search ranking."""

from __future__ import annotations

import pytest

from lalala.market_data import (
    Book,
    Candle,
    CandleSeries,
    Level,
    Market,
    bollinger_bands,
    candle_window_ms,
    format_bps,
    format_price,
    format_size,
    parse_all_mids,
    parse_book,
    parse_candles,
    parse_universe,
    search_markets,
)


def test_format_price_respects_hyperliquid_rules() -> None:
    # 5 significant figures, capped by 6 - szDecimals decimals.
    assert format_price(84.4945, 5) == "84.5"
    assert format_price(97.369, 3) == "97.369"
    assert format_price(3080.0, 3) == "3,080.0"
    assert format_price(0.00012345, 0) == "0.000123"


def test_format_price_handles_missing() -> None:
    assert format_price(None) == "—"
    assert format_price(0.0) == "—"


def test_format_size_and_bps() -> None:
    assert format_size(1234.5678, 2) == "1,234.57"
    assert format_bps(1.234) == "1.2 bps"
    assert format_bps(None) == ""


def test_parse_universe_main_and_hip3() -> None:
    payload = {
        "universe": [
            {"name": "HYPE", "szDecimals": 2, "maxLeverage": 10},
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
        ]
    }
    markets = parse_universe(payload)
    assert [m.coin for m in markets] == ["HYPE", "BTC"]
    assert markets[1].sz_decimals == 5
    assert markets[0].is_hip3 is False

    xyz = parse_universe({"universe": [{"name": "xyz:CL", "szDecimals": 3}]}, "xyz")
    assert xyz[0].is_hip3 is True
    assert xyz[0].display == "CL"


def test_parse_all_mids_skips_junk() -> None:
    payload = {"dex": "xyz", "mids": {"xyz:CL": "97.369", "BAD": "n/a"}}
    assert parse_all_mids(payload) == {"xyz:CL": 97.369}


def test_parse_book_sorts_sides_and_computes_spread() -> None:
    payload = {
        "coin": "xyz:CL",
        "time": 1700000000000,
        "levels": [
            [{"px": "97.30", "sz": "5", "n": 1}, {"px": "97.35", "sz": "2", "n": 1}],
            [{"px": "97.45", "sz": "3", "n": 1}, {"px": "97.40", "sz": "1", "n": 1}],
        ],
    }
    book = parse_book(payload)
    assert [lv.px for lv in book.bids] == [97.35, 97.30]
    assert [lv.px for lv in book.asks] == [97.40, 97.45]
    assert book.best_bid == Level(97.35, 2.0, 1)
    assert book.best_ask == Level(97.40, 1.0, 1)
    assert round(book.mid or 0, 4) == 97.375
    assert round(book.spread_bps or 0, 1) == 5.1


def test_empty_book_is_safe() -> None:
    book = Book("BTC", (), ())
    assert book.mid is None
    assert book.spread_bps is None


def _pool() -> dict[str, Market]:
    names = [
        "HYPE",
        "BTC",
        "ETH",
        "xyz:CL",
        "xyz:BRENTOIL",
        "xyz:GOLD",
        "xyz:NATGAS",
        "xyz:XYZ100",
        "xyz:SP500",
        "xyz:SMH",
        "xyz:TLT",
        "xyz:AAPL",
        "xyz:NVDA",
    ]
    return {name: Market(name, "xyz" if name.startswith("xyz:") else "") for name in names}


def test_search_ranks_exact_before_substring() -> None:
    results = search_markets(_pool(), "HYPE")
    assert results[0].coin == "HYPE"


def test_search_plain_language_hits_commodities() -> None:
    results = search_markets(_pool(), "oil")
    assert [m.coin for m in results[:2]] == ["xyz:CL", "xyz:BRENTOIL"]
    assert search_markets(_pool(), "gold")[0].coin == "xyz:GOLD"
    assert search_markets(_pool(), "s&p")[0].coin == "xyz:SP500"


def test_search_requires_a_query_and_caps_results() -> None:
    assert search_markets(_pool(), "   ") == []
    assert len(search_markets({f"COIN{i}": Market(f"COIN{i}") for i in range(50)}, "COIN", limit=8)) == 8


def test_search_unknown_returns_nothing() -> None:
    assert search_markets(_pool(), "zzzz") == []


# -- candles ---------------------------------------------------------------


def test_parse_candles_sorts_and_skips_junk() -> None:
    payload = [
        {"t": 2000, "o": "1", "h": "3", "l": "0.5", "c": "2", "v": "10"},
        {"t": 1000, "o": "1", "h": "2", "l": "1", "c": "1.5"},
        {"t": "bad"},
    ]
    candles = parse_candles(payload)
    assert [c.t for c in candles] == [1000, 2000]
    assert candles[1].h == 3.0
    assert candles[1].is_up is True
    assert parse_candles("nope") == ()


def test_candle_series_last_price() -> None:
    series = CandleSeries("HYPE", "1m", (Candle(1, 1.0, 2.0, 1.0, 1.8),))
    assert series.last_price == 1.8
    assert CandleSeries("HYPE", "1m", ()).last_price is None


def test_candle_window_covers_the_requested_count() -> None:
    assert candle_window_ms("1m", 120) == 120 * 60_000
    assert candle_window_ms("1h", 120) == 120 * 3_600_000
    # Unknown interval falls back to 1m rather than raising.
    assert candle_window_ms("7m", 1) == 60_000


def test_downtrend_candle_is_not_up() -> None:
    assert Candle(1, 10.0, 11.0, 9.0, 9.5).is_up is False


def test_classic_etf_names_map_to_what_is_listed() -> None:
    # SPY/QQQ themselves are not on Hyperliquid; the index products are.
    assert search_markets(_pool(), "spy")[0].coin == "xyz:SP500"
    assert search_markets(_pool(), "qqq")[0].coin == "xyz:XYZ100"
    assert search_markets(_pool(), "bonds")[0].coin == "xyz:TLT"
    assert search_markets(_pool(), "semis")[0].coin == "xyz:SMH"


def test_company_names_map_to_tickers() -> None:
    assert search_markets(_pool(), "apple")[0].coin == "xyz:AAPL"
    assert search_markets(_pool(), "nvidia")[0].coin == "xyz:NVDA"


def test_etf_query_returns_a_basket() -> None:
    results = search_markets(_pool(), "etf", limit=10)
    assert len(results) > 1
    assert {m.coin for m in results} <= {m.coin for m in _pool().values()}


def test_unknown_ticker_suffix_still_matches() -> None:
    assert search_markets(_pool(), "AAPL")[0].coin == "xyz:AAPL"


# -- Bollinger bands -------------------------------------------------------

def test_bollinger_needs_a_full_period() -> None:
    candles = [Candle(i, 1.0, 1.0, 1.0, 1.0) for i in range(19)]
    assert bollinger_bands(candles, period=20) == (None,) * 19

    candles.append(Candle(19, 1.0, 1.0, 1.0, 1.0))
    bands = bollinger_bands(candles, period=20)
    assert bands[-1] is not None


def test_bollinger_on_a_flat_series_collapses_to_the_price() -> None:
    candles = [Candle(i, 5.0, 5.0, 5.0, 5.0) for i in range(30)]
    middle, upper, lower = bollinger_bands(candles, period=20)[-1]
    assert middle == upper == lower == 5.0


def test_bollinger_matches_the_textbook_formula() -> None:
    candles = [Candle(i, c, c, c, c) for i, c in enumerate((1.0, 2.0, 3.0))]
    middle, upper, lower = bollinger_bands(candles, period=3, deviations=2.0)[-1]
    assert middle == 2.0
    spread = ((1 + 4 + 9) / 3 - 4) ** 0.5 * 2
    assert upper == pytest.approx(2.0 + spread)
    assert lower == pytest.approx(2.0 - spread)


def test_bollinger_is_aligned_with_the_candles() -> None:
    candles = [Candle(i, 1.0 + i, 1.0 + i, 1.0 + i, 1.0 + i) for i in range(25)]
    bands = bollinger_bands(candles, period=20)
    assert len(bands) == len(candles)
    assert bands[18] is None and bands[19] is not None


def test_bollinger_rejects_a_zero_period() -> None:
    with pytest.raises(ValueError):
        bollinger_bands([], period=0)
