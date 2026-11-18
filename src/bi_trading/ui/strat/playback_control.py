"""What the playback tile does: run, pause, finish, restart and be pointed at a run.

Each function is a method of `PlaybackTile` (it takes `self`, and the class binds it
under its old name). `strat_playback.py` keeps the widgets and how they are laid out;
this file is the loop that drives them and the setters the other tiles call."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from bi_trading.ui.strat.playback_data import FRAME_MS, STEP_MS, strategy_label
from bi_trading.ui.strat.playback_session import build_session, walk_clamps

log = logging.getLogger("bi_trading.ui.strat.strat_playback")   # the tile's own logger

if TYPE_CHECKING:
    from bi_trading.ui.strat.strat_playback import PlaybackTile



def speed_changed(self: PlaybackTile, text: str) -> None:
    try:
        self._speed = max(1, int(text.lstrip("×x")))
    except ValueError:
        self._speed = 1


def tick(self: PlaybackTile) -> None:
    if self.playback.done:
        # It stops here. Starting over is a decision, not a loop.
        self.pause()
        self.note.setText(
            f"finished — {self.playback.trades:,} trades, "
            f"{self.playback.win_rate * 100:,.0f}% won, press Run to replay"
        )
        return
    self._elapsed += FRAME_MS
    if self._elapsed >= STEP_MS:
        self._elapsed -= STEP_MS
        for _ in range(self._speed):
            if self.playback.done:
                break
            if self.session is not None:
                self.session.advance()
            else:
                self.playback.advance()
        self._refresh_metrics()
        self._refresh_progress()
        self.advanced.emit()
    # Every frame, not every candle: this is what makes it scroll.
    self.player.set_offset(self._elapsed / STEP_MS)
    self.player.update()


def play(self: PlaybackTile) -> None:
    self.player.clear_view()  # back to the live tail
    self._timer.start()
    self.run_button.setText("Pause")


def pause(self: PlaybackTile) -> None:
    self._timer.stop()
    self.run_button.setText("Run" if self.playback.done else "Resume")


def playing(self: PlaybackTile) -> bool:
    return self._timer.isActive()


def on_run(self: PlaybackTile) -> None:
    """Run to start, then Pause and Resume; Run again once it is spent."""
    session = self.session
    if (
        session is not None
        and session.stream is not None
        and session.stream[3] is not None
    ):
        # A formula over a span too long to hold has no bar-by-bar form to play
        # (its signals come from the pieces); walk it whole, in pieces, instead.
        if not self._launched or self.playback.done:
            self.restart(autoplay=False)
        self.note.setText("a span this long is walked in pieces, not played…")
        self.finish()
        return
    if not self._launched or self.playback.done:
        self.restart()
    elif self.playing():
        self.pause()
    else:
        self.play()


def finish(self: PlaybackTile, wait: bool = False) -> None:
    """Walk straight to the end, so every result is there to look at.

    With the core ready the walk runs on a worker thread and the window
    stays alive meanwhile; `finished` fires when the result has landed.
    `wait=True` does it inline, for callers that need the answer now.
    """
    if self.session is None:
        return
    self.pause()
    session = self.session
    if not session._fast_ready():
        while not self.playback.done:
            session.advance()
        self._landed()
        return
    target = session.total
    if wait:
        session._core_apply(target, session._core_compute(target))
        self._landed()
        return
    self._finish_token += 1
    token = self._finish_token
    self.run_button.setEnabled(False)
    self.note.setText("walking the whole span…")

    def work() -> None:
        try:
            result = session._core_compute(target)
        except Exception as exc:  # handed to the main thread, not lost
            log.warning("the walk failed", exc_info=True)
            result = exc
        self._walk_ready.emit(token, session, target, result)

    threading.Thread(target=work, name="bi-trading-walk", daemon=True).start()


def show_saved(self: PlaybackTile, item) -> bool:
    """Put a saved run's own trades and curves on screen. False: walk it."""
    if self.session is None or not self.session._core_ready():
        return False
    self.pause()
    if not self.session.adopt_saved(
        item.trades, item.strategy_curve, item.random_curve
    ):
        return False
    self._landed()
    return True


def on_walk_ready(self: PlaybackTile, token: int, session, target: int, result) -> None:
    if token != self._finish_token or session is not self.session:
        return  # a restart or a newer finish got there first
    self.run_button.setEnabled(True)
    if isinstance(result, Exception):
        self.note.setText(f"the walk failed: {result}")
        return
    if self.session is not None:
        self.session._core_apply(target, result)
    self._landed()


def landed(self: PlaybackTile) -> None:
    self._elapsed = 0
    self.player.set_offset(0.0)
    self.player.reset_range()
    self._refresh_metrics()
    self._refresh_progress()
    self.player.update()
    self.run_button.setText("Run")
    self.note.setText(
        f"finished — {self.playback.trades:,} trades, "
        f"{self.playback.win_rate * 100:,.0f}% won, press Run to replay"
    )
    self.advanced.emit()
    self.finished.emit()


def restart(self: PlaybackTile, to: int = 0, autoplay: bool = True) -> None:
    """Adopt the controls and start the walk over. The only way it resets.

    `to` fast-forwards to a bar first, for the replay scrubber; `autoplay`
    keeps a seek paused so the chosen stretch can be studied.
    """
    self._finish_token += 1  # a walk still running is no longer wanted
    self.run_button.setEnabled(True)
    params = self._wanted_params or {
        "initial_capital": 10_000.0,
        "tp": 2.0,
        "sl": 1.0,
        "position": 10.0,
        "sizing": "balance",
        "cash": 2_000.0,
        "fee": 0.06,
    }
    self.session = build_session(
        self._wanted_years,
        params,
        self._wanted_rule,
        self._wanted_resolution,
        entry_formula=self._entry_formula,
        fields=self._entry_fields,
        exit_formula=self._exit_formula,
        side=self._wanted_side,
        short_entry_formula=self._short_formula,
    )
    self.playback = self.session.strategy
    self.player.playback = self.playback

    if self._wanted_years and self.session.total:
        played = self._wanted_years[-1] if self._wanted_years else 0
        self.source = f"{played} · {self._wanted_resolution}"
    else:
        self.source = "example"

    self._launched = True
    self._elapsed = 0
    # Fast-forward to the sought bar before anything is drawn.
    for _ in range(max(0, to)):
        if self.playback.done:
            break
        self.session.advance()
    self.player.set_offset(0.0)
    self.player.reset_range()
    self._describe()
    self._refresh_metrics()
    self._refresh_progress()
    self.player.update()
    self.restarted.emit(self.session)
    if autoplay:
        self.play()
    else:
        self.pause()
        self.run_button.setText("Run" if self.playback.done else "Resume")


def set_source(self: PlaybackTile, years: list[int], resolution: str) -> None:
    """Remember the span. Nothing changes until the next restart."""
    self._wanted_years = list(years)
    self._wanted_resolution = resolution
    self._describe()


def set_params(self: PlaybackTile, params: dict) -> None:
    """Remember the parameters. Nothing changes until the next restart."""
    self._wanted_params = dict(params)
    self._describe()


def set_strategy(self: PlaybackTile, rule: str) -> None:
    """Remember the strategy. Nothing changes until the next restart."""
    self._wanted_rule = rule
    self._entry_formula = None
    self._entry_fields = None
    self._saved_name = ""
    self._saved_entry = ""
    self._saved_exit = ""
    self._exit_formula = None
    self._wanted_side = "long"
    self._short_formula = None
    self._saved_short = ""
    self._describe()


def rule_key(self: PlaybackTile) -> str:
    return self._wanted_rule


def saved_entry(self: PlaybackTile) -> str:
    return self._saved_entry


def saved_name(self: PlaybackTile) -> str:
    return self._saved_name


def saved_exit(self: PlaybackTile) -> str:
    return self._saved_exit


def side(self: PlaybackTile) -> str:
    return self._wanted_side


def saved_short(self: PlaybackTile) -> str:
    return self._saved_short


def set_saved_strategy(self: PlaybackTile, name: str, entry: str, fields=None, exit: str = "",
    side: str = "long", short_entry: str = "",
) -> bool:
    """Point the run at a saved strategy: its rules and which way it goes.

    `side` is long, short or both. For both, `entry` opens longs and
    `short_entry` opens shorts.

    The rules are parsed once, here; a rule the language cannot read is
    refused and the built-in is kept. An empty exit rule leaves the
    parameters' take profit, stop loss and hold limit as the only exits.
    """
    from bi_trading.engine.formula import (
        ENTRY_FIELDS,
        EXIT_FIELDS,
        EXIT_FUNCTIONS,
        FUNCTIONS,
        FormulaError,
        parse,
    )

    try:
        formula = parse(entry, fields or ENTRY_FIELDS, FUNCTIONS)
        exit_formula = (
            parse(exit, EXIT_FIELDS, EXIT_FUNCTIONS) if exit.strip() else None
        )
        short_formula = (
            parse(short_entry, fields or ENTRY_FIELDS, FUNCTIONS)
            if side == "both" and short_entry.strip()
            else None
        )
    except FormulaError:
        self._describe()
        return False
    self._wanted_rule = "saved"
    self._exit_formula = exit_formula
    self._saved_exit = exit
    self._wanted_side = side if side in ("short", "both") else "long"
    self._short_formula = short_formula
    self._saved_short = short_entry
    self._entry_formula = formula
    self._entry_fields = tuple(fields or ENTRY_FIELDS)
    self._saved_name = name
    self._saved_entry = entry
    self._describe()
    return True


def describe(self: PlaybackTile) -> None:
    if not self._launched:
        self.note.setText("idle — press Run")
        return
    name = strategy_label(self._wanted_rule)
    if self._wanted_rule == "saved" and self._saved_name:
        name = self._saved_name
    stride = self.playback.stride
    pace = "" if stride <= 1 else f" · fast-forward ×{stride:,}"
    clamps = walk_clamps(self._wanted_params or {})
    pace += "".join(f" · {note}" for note in clamps)
    if self._wanted_years:
        span = f"{self._wanted_years[0]}–{self._wanted_years[-1]}"
        self.note.setText(
            f"{name} on {span} · {self._wanted_resolution}{pace}"
        )
    else:
        self.note.setText(f"{name} on the sample{pace}")
