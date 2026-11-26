"""A saved model's live call and the bet it leads to."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from bi_trading.ml.live import MIN_BARS, Decision, decide, horizon_note, live_call
from tests.ml_data import make_market


@dataclass
class Bar:
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float


def bars_of(columns, stamps, count=None):
    count = count or len(stamps)
    return [
        Bar(int(stamps[i]), columns["open"][i], columns["high"][i], columns["low"][i],
            columns["close"][i], columns["volume"][i])
        for i in range(count)
    ]


# -- the decision -------------------------------------------------------------------


def test_the_thresholds_pick_the_side() -> None:
    assert decide(0.7, 0.6, 0.4, 0.0, 0.5, 0.5).side == "up"
    assert decide(0.3, 0.6, 0.4, 0.0, 0.5, 0.5).side == "down"
    between = decide(0.5, 0.6, 0.4, 0.0, 0.5, 0.5)
    assert between.side is None and "between" in between.reason


def test_the_edge_is_the_probability_over_the_ask() -> None:
    assert decide(0.70, 0.6, 0.4, 0.05, 0.60, 0.42).side == "up"          # +0.10
    low = decide(0.70, 0.6, 0.4, 0.05, 0.68, 0.34)
    assert low.side is None and "below" in low.reason and low.edge == pytest.approx(0.02)
    assert decide(0.30, 0.6, 0.4, 0.05, 0.66, 0.55).side == "down"        # 0.70 - 0.55
    assert decide(0.30, 0.6, 0.4, 0.05, 0.30, 0.68).side is None          # 0.70 - 0.68


def test_no_price_means_no_bet_when_an_edge_is_asked_for() -> None:
    assert decide(0.7, 0.6, 0.4, 0.05, None, 0.5).side is None
    assert decide(0.7, 0.6, 0.4, 0.0, None, None).side == "up"
    assert decide(None, 0.6, 0.4, 0.0, 0.5, 0.5) == Decision(reason="no call yet")


# -- the call -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def trained():
    pytest.importorskip("sklearn")
    pytest.importorskip("scipy")
    from bi_trading.ml.features import default_features
    from bi_trading.ml.spec import ModelSpec
    from bi_trading.ml.train import TrainConfig, train

    columns, stamps = make_market(4000)
    model = train(
        columns, stamps,
        TrainConfig(spec=ModelSpec("t", "logistic"), features=default_features(), horizon=1, min_move=0.0),
    )
    return model, columns, stamps


def test_the_forming_bar_is_left_out(trained) -> None:
    model, columns, stamps = trained
    bars = bars_of(columns, stamps, 500)
    now = int(stamps[499]) + 30_000                      # half way through the last bar
    call = live_call(model, bars, now)
    assert call.p is not None and call.stamp == int(stamps[498])
    closed = live_call(model, bars, int(stamps[499]) + 60_000)
    assert closed.stamp == int(stamps[499])


def test_the_call_is_the_models_own_prediction_on_that_bar(trained) -> None:
    from bi_trading.ml.features import feature_matrix

    model, columns, stamps = trained
    call = live_call(model, bars_of(columns, stamps, 600), int(stamps[599]) + 60_000)
    matrix = feature_matrix({k: v[:600] for k, v in columns.items()}, model.config.features)
    expected = model.predictor.predict_up(matrix, np.array([599]))[0]
    assert call.p == pytest.approx(expected)


def test_the_live_call_is_the_call_a_backtest_would_have_made(trained) -> None:
    """No train/serve skew: scoring a short tail of bars equals scoring the whole span."""
    from bi_trading.ml.train import predict_series

    model, columns, stamps = trained
    full = predict_series(model, columns, stamps, "1m", in_sample=True)
    bars = bars_of(columns, stamps)
    for end in (700, 1500, 3000, 3999):
        call = live_call(model, bars[: end + 1], int(stamps[end]) + 60_000)
        assert call.p == pytest.approx(full[end], abs=1e-6)


def test_too_few_bars_says_it_is_warming_up(trained) -> None:
    model, columns, stamps = trained
    call = live_call(model, bars_of(columns, stamps, MIN_BARS - 5), int(stamps[MIN_BARS]) + 10**9)
    assert call.p is None and "warming up" in call.reason


def test_a_hole_in_the_recent_bars_gives_no_call(trained) -> None:
    model, columns, stamps = trained
    bars = bars_of(columns, stamps, 400)
    for bar in bars[350:]:
        bar.t += 10 * 60_000                             # ten minutes missing before bar 350
    call = live_call(model, bars, bars[-1].t + 60_000)
    assert call.p is None and "gap" in call.reason


def test_the_horizon_note_warns_when_it_is_not_five_minutes(trained) -> None:
    model, _, _ = trained
    assert "1 min ahead" in horizon_note(model)
    model.config.timeframe, model.config.horizon = "5m", 1
    try:
        assert horizon_note(model) == ""
    finally:
        model.config.timeframe = "1m"


# -- on the terminal ------------------------------------------------------------------

from tests.test_polymarket import app, auto_window, window  # noqa: E402,F401  (fixtures)


@pytest.fixture
def ml_window(auto_window, trained, monkeypatch, tmp_path):  # noqa: F811
    """The terminal with a saved ML strategy listed and 600 bars on its chart."""
    from bi_trading.ml import store
    from bi_trading.state import strategies
    from bi_trading.state.strategies import SavedStrategy

    monkeypatch.setenv("BI_TRADING_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("BI_TRADING_STRATEGIES", str(tmp_path / "strategies.json"))
    model, columns, stamps = trained
    model.config.up, model.config.down, model.config.min_edge = 0.6, 0.4, 0.0
    model.config.timeframe, model.config.horizon = "5m", 1    # a model that looks at the window
    store.save_model(model, "live ml")
    strategies.save(SavedStrategy("live ml", "5m", "model_p >= 0.6", "", "both", "model_p <= 0.4", "live ml"))
    bars = bars_of(columns, stamps, 600)
    auto_window.main_card.chart._candles = tuple(bars)
    auto_window.main_card.interval = "5m"
    _WINDOW["start"] = auto_window.polymarket.market.start_ms
    auto_window.strategy_bar.auto.setChecked(True)
    auto_window._refresh_ml_choices()
    auto_window.strategy_bar.picker.setCurrentText("ML · live ml")
    auto_window.bars = bars
    return auto_window


_WINDOW: dict = {}


def call_with(monkeypatch, p):
    """A call on the bar that closed as the live window opened."""
    from bi_trading.ml import live

    stamp = _WINDOW["start"] - 300_000
    monkeypatch.setattr(live, "live_call", lambda *a, **k: live.LiveCall(p=p, stamp=stamp))


def test_saved_ml_strategies_join_the_picker(ml_window) -> None:
    labels = [ml_window.strategy_bar.picker.itemText(i) for i in range(ml_window.strategy_bar.picker.count())]
    assert labels[-1] == "ML · live ml" and labels[0] == "Bollinger reversion"
    assert ml_window.strategy_bar.ml_name() == "live ml"


def test_picking_one_moves_the_chart_to_its_timeframe_and_warns_about_the_horizon(ml_window) -> None:
    from bi_trading.ml import store

    model = store.load_model("live ml")
    model.config.timeframe, model.config.horizon = "1m", 5
    store.save_model(model, "live ml")
    ml_window.strategy_bar.picker.setCurrentText("Random buy")
    ml_window.strategy_bar.picker.setCurrentText("ML · live ml")
    assert ml_window.main_card.interval == "1m"
    assert "reading 1m bars" in ml_window.strategy_bar.status.text()
    model.config.horizon = 2                      # 2 minutes: not the window
    store.save_model(model, "live ml")
    ml_window.strategy_bar.picker.setCurrentText("Random buy")
    ml_window.strategy_bar.picker.setCurrentText("ML · live ml")
    assert "2 min ahead" in ml_window.strategy_bar.status.text() and "no bets" in ml_window.strategy_bar.status.text()


def test_a_call_over_the_threshold_bets_up_on_paper(ml_window, monkeypatch) -> None:
    call_with(monkeypatch, 0.9)
    ml_window._refresh_strategy_bar()
    assert ml_window.strategy_bar.signal_label.text() == "UP"
    assert ml_window.strategy_bar.band_label.text() == "0.90"
    (bet,) = ml_window._autobet.open
    assert (bet.side, bet.paper) == ("up", True) and ml_window.sent == []
    assert any(e.kind == "SIGNAL" and "P(up) 0.90" in e.message for e in ml_window.log.events())


def test_a_call_under_the_low_threshold_bets_down(ml_window, monkeypatch) -> None:
    call_with(monkeypatch, 0.1)
    ml_window._refresh_strategy_bar()
    assert ml_window.strategy_bar.signal_label.text() == "DOWN"
    (bet,) = ml_window._autobet.open
    assert bet.side == "down"
    assert bet.token == ml_window.polymarket.market.outcomes[1].token_id


def test_a_call_in_between_does_not_bet(ml_window, monkeypatch) -> None:
    call_with(monkeypatch, 0.5)
    ml_window._refresh_strategy_bar()
    assert ml_window._autobet.open == [] and ml_window.strategy_bar.signal_label.text() == "FALSE"
    assert "between" in ml_window.strategy_bar.status.text()


def test_the_edge_over_the_market_price_gates_the_bet(ml_window, monkeypatch) -> None:
    from bi_trading.ml import store

    model = store.load_model("live ml")
    model.config.min_edge = 0.30
    store.save_model(model, "live ml")
    call_with(monkeypatch, 0.9)             # the market asks about 0.5: edge 0.4 passes
    ml_window._refresh_strategy_bar()
    assert len(ml_window._autobet.open) == 1
    model.config.min_edge = 0.60
    store.save_model(model, "live ml")
    ml_window._autobet.open.clear()
    ml_window._autobet.last_window = ""
    ml_window._ml_cache = None
    ml_window._ml_side = None
    ml_window._refresh_strategy_bar()
    assert ml_window._autobet.open == [] and "below" in ml_window.strategy_bar.status.text()


def test_a_long_only_strategy_never_bets_down(ml_window, monkeypatch) -> None:
    from dataclasses import replace

    from bi_trading.state import strategies

    item = strategies.load()[0]
    strategies.save(replace(item, side="long"))
    ml_window._refresh_ml_choices()
    call_with(monkeypatch, 0.1)
    ml_window._refresh_strategy_bar()
    assert ml_window._autobet.open == [] and "long strategy" in ml_window.strategy_bar.status.text()


def test_one_bet_a_window_even_when_every_bar_calls_it(ml_window, monkeypatch) -> None:
    call_with(monkeypatch, 0.9)
    ml_window._refresh_strategy_bar()
    ml_window._ml_cache = None              # the next bar closed: a fresh call, same side
    ml_window._refresh_strategy_bar()
    assert len(ml_window._autobet.open) == 1


def test_without_auto_bet_the_call_shows_but_nothing_is_bet(ml_window, monkeypatch) -> None:
    ml_window.strategy_bar.auto.setChecked(False)
    call_with(monkeypatch, 0.9)
    ml_window._refresh_strategy_bar()
    assert ml_window.strategy_bar.signal_label.text() == "UP" and ml_window._autobet.open == []


def test_the_wrong_timeframe_is_said_not_guessed(ml_window, monkeypatch) -> None:
    ml_window.main_card.interval = "15m"
    ml_window._refresh_strategy_bar()
    assert ml_window._autobet.open == []
    assert "reads 5m bars" in ml_window.strategy_bar.status.text()


def test_a_real_call_on_the_real_model_runs_end_to_end(ml_window) -> None:
    """No stub: the saved model scores the chart's closed bars."""
    ml_window._refresh_strategy_bar()
    reading = ml_window.strategy_bar.band_label.text()
    assert reading == "—" or 0.0 <= float(reading) <= 1.0


def test_a_built_in_strategy_still_reads_the_band(ml_window) -> None:
    ml_window.strategy_bar.picker.setCurrentText("Bollinger reversion")
    ml_window._refresh_strategy_bar()
    assert ml_window.strategy_bar.band_caption.text() == "band"


# -- the horizon against the Polymarket window -------------------------------------------

def _model(trained, timeframe, horizon):
    model, _, _ = trained
    model.config.timeframe, model.config.horizon = timeframe, horizon
    return model


def test_a_five_minute_horizon_is_a_call_on_the_window_it_closed_into(trained) -> None:
    from bi_trading.ml.live import window_reason

    five = _model(trained, "5m", 1)
    start = 1_700_000_100_000
    assert window_reason(five, start - 300_000, start) == ""          # the bar that closed at the open
    assert "no call for this window yet" in window_reason(five, start - 600_000, start)
    assert "5 min into the window" in window_reason(five, start, start)   # a bar that closes after the open


def test_a_call_from_an_earlier_bar_is_not_a_call_on_this_window(trained) -> None:
    from bi_trading.ml.live import window_reason

    one = _model(trained, "1m", 5)                                    # 5 minutes ahead too
    start = 1_700_000_100_000
    assert window_reason(one, start - 60_000, start) == ""            # the first minute
    late = window_reason(one, start + 120_000, start)                 # made two minutes in
    assert "3 min into the window" in late
    assert "no call for this window yet" in window_reason(one, start - 180_000, start)


def test_any_other_horizon_never_bets(trained) -> None:
    from bi_trading.ml.live import horizon_note, window_reason

    for timeframe, horizon in (("1m", 1), ("5m", 3), ("15m", 1), ("1m", 20)):
        model = _model(trained, timeframe, horizon)
        assert "no bets" in horizon_note(model)
        assert "no bets" in window_reason(model, 0, 300_000)
    _model(trained, "1m", 1)


def test_the_terminal_does_not_bet_on_a_model_whose_horizon_is_not_the_window(ml_window, monkeypatch) -> None:
    from bi_trading.ml import store

    model = store.load_model("live ml")
    model.config.timeframe, model.config.horizon = "1m", 3   # 3 minutes ahead
    ml_window.main_card.interval = "1m"
    store.save_model(model, "live ml")
    call_with(monkeypatch, 0.9)
    ml_window._refresh_strategy_bar()
    assert ml_window._autobet.open == []
    assert "no bets" in ml_window.strategy_bar.status.text()
    assert ml_window.strategy_bar.band_label.text() == "0.90"         # still shown


def test_the_terminal_bets_only_on_the_call_made_as_the_window_opened(ml_window, monkeypatch) -> None:
    import dataclasses

    from bi_trading.ml import live

    start = ml_window.polymarket.market.start_ms
    monkeypatch.setattr(live, "live_call", lambda *a, **k: live.LiveCall(p=0.9, stamp=start - 300_000))
    ml_window._refresh_strategy_bar()
    assert len(ml_window._autobet.open) == 1                          # the call is on this window

    ml_window._autobet.open.clear()
    ml_window._autobet.last_window = ""
    ml_window._ml_cache = None
    ml_window._ml_side = None
    monkeypatch.setattr(live, "live_call", lambda *a, **k: live.LiveCall(p=0.9, stamp=start - 600_000))
    ml_window._refresh_strategy_bar()
    assert ml_window._autobet.open == []
    assert "no call for this window yet" in ml_window.strategy_bar.status.text()
    del dataclasses


def test_a_manual_bets_fill_is_tracked_and_its_window_books_the_pnl(ml_window) -> None:
    market = ml_window.polymarket.market
    token = market.outcomes[0].token_id
    ml_window._manual_orders[token] = (market.slug, "up", market.end_ms)

    ml_window._on_filled("polymarket", token, "buy", 20.0, 10.0)      # the venue's fill
    (bet,) = ml_window._autobet.open
    assert (bet.origin, bet.side, bet.stake, bet.filled) == ("manual", "up", 10.0, True)
    assert ml_window._autobet.last_window == ""         # auto-bets keep their window

    ml_window._on_filled("polymarket", token, "sell", 10.0, 7.0)      # half sold early
    assert any(e.pnl == 2.0 and "Sold early" in e.message for e in ml_window.log.events())

    # A fill nobody asked for (no order of ours behind it) is not made into a bet.
    ml_window._on_filled("polymarket", "unknown-token", "buy", 5.0, 2.0)
    assert [b.token for b in ml_window._autobet.open] == [token]

    ml_window._official[market.slug] = "up"
    ml_window._resolve_bets("a-later-window")
    assert ml_window._autobet.open == []
    assert any(e.pnl == 5.0 and e.origin == "manual" for e in ml_window.log.events())
