"""Jelly — local web dashboard for XRPlayer runs.

Run via::

    python -m xrplayer.jelly --port 2000 --results-dir <output_root>

The dashboard is served from the local network only by default and uses
nothing beyond the Python standard library, so it works on any machine where
XRPlayer itself runs.
"""
from __future__ import annotations

DEFAULT_PORT = 2000
DEFAULT_HOST = "127.0.0.1"

__all__ = ["DEFAULT_PORT", "DEFAULT_HOST"]
