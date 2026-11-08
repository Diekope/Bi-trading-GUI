"""The silent log: a file on disk, nothing on the console."""

from __future__ import annotations

import logging
import os

import pytest

from lalala import logs


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    """A fresh log path and a fresh configuration for every test."""
    monkeypatch.setenv("LALALA_LOG", str(tmp_path / "lalala.log"))
    monkeypatch.delenv("LALALA_LOG_LEVEL", raising=False)
    logs.reset()
    root = logging.getLogger()
    original = list(root.handlers), root.level, {
        name: logging.getLogger(name).level for name in logs.NOISY
    }
    yield
    for handler in list(root.handlers):
        if handler not in original[0]:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(original[1])
    for name, level in original[2].items():
        logging.getLogger(name).setLevel(level)
    logs.reset()


def test_records_land_in_the_file(tmp_path) -> None:
    logs.setup()

    logging.getLogger("lalala.test").warning("something happened")
    for handler in logging.getLogger().handlers:
        handler.flush()

    text = (tmp_path / "lalala.log").read_text()
    assert "something happened" in text
    assert "lalala.test" in text
    assert "WARNING" in text


def test_nothing_is_written_to_the_console() -> None:
    logs.setup()

    # Every handler is a file handler or a do-nothing NullHandler: a console
    # handler would scribble over the terminal the app was launched from.
    handlers = logging.getLogger().handlers
    assert all(
        isinstance(handler, (logging.NullHandler, logging.FileHandler))
        for handler in handlers
    )
    assert not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in handlers
    )


def test_setup_is_idempotent(tmp_path) -> None:
    first = logs.setup()
    second = logs.setup()

    assert first == second
    file_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert len(file_handlers) == 1


def test_a_console_handler_left_behind_is_dropped() -> None:
    root = logging.getLogger()
    stray = logging.StreamHandler()
    root.addHandler(stray)

    logs.setup()

    assert stray not in root.handlers


def test_logging_is_on_without_being_asked(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LALALA_LOG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    logs.reset()

    # Unset means "use the default path", not "off".
    assert logs.logging_enabled() is True
    assert logs.log_path().name == "lalala.log"


def test_logging_can_be_turned_off(monkeypatch) -> None:
    monkeypatch.setenv("LALALA_LOG", "off")
    logs.reset()

    assert logs.setup() is None
    assert logs.logging_enabled() is False
    assert not any(
        isinstance(handler, logging.FileHandler)
        for handler in logging.getLogger().handlers
    )


def test_the_level_comes_from_the_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LALALA_LOG", str(tmp_path / "lalala.log"))
    monkeypatch.setenv("LALALA_LOG_LEVEL", "DEBUG")
    logs.reset()

    logs.setup()
    logging.getLogger("lalala.test").debug("a detail")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "a detail" in (tmp_path / "lalala.log").read_text()


def test_third_party_chatter_is_held_back() -> None:
    logs.setup()

    # httpx at INFO is a wall of connection noise and rarely what is wanted.
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("websockets").level == logging.WARNING


def test_a_read_only_home_does_not_stop_the_app(monkeypatch, tmp_path) -> None:
    # A path whose parent cannot be created: setup gives up quietly.
    monkeypatch.setenv("LALALA_LOG", str(tmp_path / "afile" / "nested.log"))
    (tmp_path / "afile").write_text("not a directory")
    logs.reset()

    assert logs.setup() is None
    assert os.path.exists(tmp_path / "afile")  # untouched
