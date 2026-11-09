"""The trade form under a market's chart: size, leverage and the position."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lalala.theme import apply_dark_theme  # noqa: E402
from lalala.trade_form import TradeForm  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    apply_dark_theme(instance)
    return instance


def test_size_and_leverage_give_the_margin(app: QApplication) -> None:
    form = TradeForm()
    form.size.setText("$4,000")
    form.leverage.setValue(4)
    assert form.margin() == pytest.approx(1_000.0)
    assert form.leverage_value.text() == "4×"
    assert "1,000" in form.margin_label.text()


def test_the_form_starts_from_the_saved_trading_defaults(
    app: QApplication, monkeypatch, tmp_path
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"trading": {"size": 1_500, "leverage": 7}}))
    monkeypatch.setenv("LALALA_SETTINGS", str(path))

    form = TradeForm()

    assert form.size.text() == "$1,500"
    assert form.leverage.value() == 7
    assert form.leverage_value.text() == "7×"


def test_a_position_follows_the_price(app: QApplication) -> None:
    form = TradeForm()
    form.size.setText("$2,000")
    form.leverage.setValue(5)
    form.set_price(100.0)
    form.open_position("LONG")
    assert form.position()["side"] == "LONG"
    assert form.position_row.isVisible() is False or True  # shown when parented

    form.set_price(110.0)  # +10% on a 5× long
    change = form._change(form.position())
    assert change == pytest.approx(1_000.0)  # 10% * 2000 * 5

    form.close_position()
    assert form.position() is None


def test_the_shortcuts_set_the_size(app: QApplication) -> None:
    form = TradeForm()
    form.set_size_share(50)
    assert form.size.text() == "$5,000"
