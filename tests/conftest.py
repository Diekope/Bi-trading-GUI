"""Test isolation: a throwaway settings file and no real display.

The panel reads its feel settings at import time. Pointing LALALA_SETTINGS at
an empty temporary path keeps a developer's own ~/.config file from changing
what the tests measure.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LALALA_SETTINGS"] = os.path.join(
    tempfile.mkdtemp(prefix="lalala-tests-"), "settings.json"
)
# And no test writes drafts into a developer's own config.
os.environ["LALALA_STRATEGIES"] = os.path.join(
    tempfile.mkdtemp(prefix="lalala-tests-"), "strategies.json"
)
# Secrets stay in the throwaway folder instead of the developer's keychain.
os.environ["LALALA_SECRETS"] = os.path.join(
    os.environ["LALALA_SETTINGS"].rsplit("/", 1)[0], "secrets.json"
)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_position_store():
    """The paper position is process-wide; never let it leak between tests.

    Only touched, never created: most tests are not GUI tests and a QObject
    made with no application around is one more thing Qt has to unwind at exit.
    """
    from lalala import positions

    if positions._store is not None:
        positions._store.clear()
    yield
    if positions._store is not None:
        positions._store.clear()
