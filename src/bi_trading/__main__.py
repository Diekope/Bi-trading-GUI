from __future__ import annotations

import sys

from bi_trading.app import run


def main(argv: list[str] | None = None) -> int:
    """Entry point for both `bi-trading` and `python -m bi_trading`."""
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
