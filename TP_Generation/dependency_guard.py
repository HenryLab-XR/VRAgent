from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterable, List


def _requirements_hint() -> str:
    repo_dir = Path(__file__).resolve().parent
    req_file = repo_dir / "requirements.txt"
    if req_file.exists():
        return str(req_file)
    return r"TP_Generation\requirements.txt"


def ensure_packages(packages: Iterable[str], script_name: str) -> None:
    missing: List[str] = []

    for package in packages:
        try:
            importlib.import_module(package)
        except ModuleNotFoundError:
            missing.append(package)

    if not missing:
        return

    missing_text = ", ".join(sorted(missing))
    req_hint = _requirements_hint()

    print(f"[env] Missing Python package(s): {missing_text}", file=sys.stderr)
    print(f"[env] Interpreter: {sys.executable}", file=sys.stderr)
    print(f"[env] Before running {script_name}, install the project dependencies:", file=sys.stderr)
    print(f"[env]   python -m pip install -r \"{req_hint}\"", file=sys.stderr)
    print("[env] Recommended on a new machine:", file=sys.stderr)
    print("[env]   py -3.8 -m venv .venv", file=sys.stderr)
    print(r"[env]   .\.venv\Scripts\activate", file=sys.stderr)
    print(f"[env]   python -m pip install -r \"{req_hint}\"", file=sys.stderr)
    raise SystemExit(1)
