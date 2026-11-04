"""The tunable file: defaults, overrides, and the clamps that keep it sane."""

from __future__ import annotations

import json
from dataclasses import fields

import pytest

from lalala.settings import Settings, ensure_file, settings_path


def test_the_shipped_window_and_focus_slice_are_consistent() -> None:
    """The shipped feel may be tuned; the geometry has to stay drawable.

    These numbers are meant to be edited (they are the chart's feel), so the
    test checks the relationships that make the design work rather than
    pinning today's values.
    """
    settings = Settings.load(path="/nonexistent/settings.json", environ={})

    assert settings.view_ms == 15 * 60_000
    assert 0 < settings.focus_ms < settings.view_ms
    assert 0.0 < settings.focus_share < 1.0
    # The focus slice exists to make the live edge outrun a plain 15-min
    # axis; if this ever collapses, the tip is back to crawling.
    linear_px_per_s = 580.0 / (settings.view_ms / 1000.0)
    assert settings.edge_px_per_s(580.0) > 2.0 * linear_px_per_s


def test_the_file_overrides_the_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"focus_share": 0.5, "smooth": 0.2}))

    settings = Settings.load(path=path, environ={})

    assert settings.focus_share == pytest.approx(0.5)
    assert settings.smooth == pytest.approx(0.2)
    assert settings.view_ms == Settings().view_ms  # untouched keys keep defaults


def test_the_environment_overrides_the_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"focus_ms": 60_000}))

    settings = Settings.load(path=path, environ={"LALALA_FOCUS_MS": "45000"})

    assert settings.focus_ms == 45_000


def test_a_broken_file_falls_back_to_the_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json at all")

    assert Settings.load(path=path, environ={}) == Settings()


def test_values_are_clamped_to_what_the_chart_can_draw(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "focus_share": 4.0,   # more than the whole plot
                "smooth": 0.0,        # no damping at all
                "lag_ms": 100,        # shorter than the sample interval
                "frame_ms": 5,        # faster than the screen
            }
        )
    )

    settings = Settings.load(path=path, environ={})

    assert settings.focus_share == pytest.approx(0.9)
    assert settings.smooth == pytest.approx(0.01)
    assert settings.lag_ms > settings.sample_every_ms
    assert settings.frame_ms == 16


def test_the_first_launch_leaves_a_file_to_edit(tmp_path) -> None:
    path = tmp_path / "nested" / "settings.json"

    written = ensure_file(path)

    assert written == path
    assert path.exists()
    # The file is a complete, valid starting point: every key the loader knows
    # is present and loading it reproduces exactly what was written.
    values = json.loads(path.read_text())
    loaded = Settings.load(path=path, environ={})
    for field in fields(Settings):
        assert field.name in values
        assert getattr(loaded, field.name) == pytest.approx(values[field.name])


def test_the_path_can_be_redirected(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LALALA_SETTINGS", str(tmp_path / "elsewhere.json"))

    assert settings_path() == tmp_path / "elsewhere.json"
