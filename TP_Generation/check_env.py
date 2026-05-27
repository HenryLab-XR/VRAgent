#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

from dependency_guard import inspect_package


ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 8)
CORE_PACKAGES: Tuple[str, ...] = ("networkx", "openai", "jsonschema")
DEV_PACKAGES: Tuple[str, ...] = ("pytest",)
ANALYZERS: Tuple[Tuple[str, Path], ...] = (
    ("UnityDataAnalyzer.exe", ROOT / "UnityDataAnalyzer" / "UnityDataAnalyzer.exe"),
    ("CSharpAnalyzer.exe", ROOT / "CSharpScriptAnalyzer" / "CSharpAnalyzer.exe"),
    ("CodeStructureAnalyzer.exe", ROOT / "CodeStructureAnalyzer" / "CodeStructureAnalyzer.exe"),
)


def check_python() -> Tuple[bool, str]:
    current = sys.version_info[:3]
    if current >= MIN_PYTHON:
        return True, f"Python {current[0]}.{current[1]}.{current[2]}"
    return False, (
        f"Python {current[0]}.{current[1]}.{current[2]} is too old; "
        f"need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    )


def check_imports(packages: Iterable[str]) -> List[Tuple[str, bool, str]]:
    rows: List[Tuple[str, bool, str]] = []
    for package in packages:
        ok, detail = inspect_package(package)
        rows.append((package, ok, detail))
    return rows


def check_files(items: Iterable[Tuple[str, Path]]) -> List[Tuple[str, bool, str]]:
    rows: List[Tuple[str, bool, str]] = []
    for label, path in items:
        rows.append((label, path.exists(), str(path)))
    return rows


def print_rows(title: str, rows: Iterable[Tuple[str, bool, str]]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for name, ok, detail in rows:
        status = "OK" if ok else "MISSING"
        print(f"[{status}] {name}: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether TP_Generation can run on this machine."
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Also check development-only dependencies such as pytest.",
    )
    args = parser.parse_args()

    overall_ok = True

    python_ok, python_detail = check_python()
    print_rows("Python", [("interpreter", python_ok, f"{python_detail} | {sys.executable}")])
    overall_ok &= python_ok

    import_rows = check_imports(CORE_PACKAGES + (DEV_PACKAGES if args.dev else ()))
    print_rows("Python Packages", import_rows)
    overall_ok &= all(ok for _, ok, _ in import_rows)

    file_rows = check_files(ANALYZERS)
    print_rows("Bundled Analyzers", file_rows)
    overall_ok &= all(ok for _, ok, _ in file_rows)

    if overall_ok:
        print("\nEnvironment check passed.")
        return 0

    print("\nEnvironment check failed.")
    print(f"Install packages with: python -m pip install -r \"{ROOT / 'requirements.txt'}\"")
    print("If a package looks installed but still fails, force reinstall it, e.g.:")
    print("python -m pip install --force-reinstall --no-cache-dir networkx")
    if args.dev:
        print(f"Dev extras: python -m pip install -r \"{ROOT / 'requirements-dev.txt'}\"")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
