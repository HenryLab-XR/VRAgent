"""Jelly CLI entry point.

``python -m xrplayer.jelly --port 2000 --results-dir <output_root>``

The server scans ``--results-dir`` for the standard XRPlayer artefacts
(``jelly_status.json``, ``agent_decisions.json``, ``summary.json``,
``gate_graph.json``, ``iteration_logs.json``, ``scene_understanding.json``)
and exposes them through small JSON endpoints consumed by the bundled
single-page dashboard.
"""
from __future__ import annotations

import argparse
import sys

from . import DEFAULT_HOST, DEFAULT_PORT
from .server import serve


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m xrplayer.jelly",
        description="Jelly — local dashboard for XRPlayer runs.",
    )
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"Bind host (default {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"Bind port (default {DEFAULT_PORT})")
    p.add_argument("--results-dir", default=".",
                   help="Directory containing run artefacts (json files).")
    p.add_argument("--auto-open", action="store_true",
                   help="Open the dashboard in the default browser on start.")
    args = p.parse_args(argv)

    try:
        serve(host=args.host, port=args.port,
              results_dir=args.results_dir,
              auto_open=args.auto_open)
    except KeyboardInterrupt:
        print("\n[jelly] interrupted — shutting down")
        return 0
    except OSError as exc:
        print(f"[jelly] failed to bind {args.host}:{args.port} — {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
