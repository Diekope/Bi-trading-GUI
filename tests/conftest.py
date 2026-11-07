"""Test isolation: a throwaway settings file and no real display.

The panel reads its feel settings at import time. Pointing LALALA_SETTINGS at
an empty temporary path keeps a developer's own ~/.config file from changing
what the tests measure.
"""

from __future__ import annotations

import os
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LALALA_SETTINGS"] = os.path.join(
    tempfile.mkdtemp(prefix="lalala-tests-"), "settings.json"
)
# And no test writes drafts into a developer's own config.
os.environ["LALALA_STRATEGIES"] = os.path.join(
    tempfile.mkdtemp(prefix="lalala-tests-"), "strategies.json"
)
