"""``python -m xrplayer …`` — thin delegator to ``vragent2.main``.

All command-line arguments are forwarded unchanged so existing scripts and
documentation that reference ``vragent2.main`` continue to work under the
``xrplayer`` namespace.
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from vragent2.main import main as _vragent_main
    except Exception as exc:  # pragma: no cover
        print(f"[xrplayer] cannot import vragent2.main: {exc}", file=sys.stderr)
        return 2
    return int(_vragent_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
