from __future__ import annotations

import sys

from lalala.app import run


def main(argv: list[str] | None = None) -> int:
    """Entry point for both `lalala` and `python -m lalala`."""
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
