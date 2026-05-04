"""Backwards-compatibility entry point for the Jelly dashboard.

``python -m vragent2.jelly`` simply forwards to :mod:`xrplayer.jelly`.
"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    try:
        from xrplayer.jelly.__main__ import main as _jelly_main
    except Exception as exc:  # pragma: no cover
        print(f"[vragent2.jelly] cannot import xrplayer.jelly: {exc}", file=sys.stderr)
        return 2
    return _jelly_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
