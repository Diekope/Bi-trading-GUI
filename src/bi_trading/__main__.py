from __future__ import annotations

import sys

from bi_trading.ui.hub.main_hub import run


def main(argv: list[str] | None = None) -> int:
    """Entry point for both `bi-trading` and `python -m bi_trading`: the whole app (the hub)."""
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
