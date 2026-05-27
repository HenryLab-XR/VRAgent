from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def _requirements_hint() -> str:
    repo_dir = Path(__file__).resolve().parent
    req_file = repo_dir / "requirements.txt"
    if req_file.exists():
        return str(req_file)
    return r"TP_Generation\requirements.txt"


def _package_health_issue(package: str, module: object) -> Optional[str]:
    if package == "networkx" and not hasattr(module, "Graph"):
        return (
            "package imported, but 'Graph' is missing. "
            "This usually means the networkx installation is incomplete or corrupted."
        )
    if package == "jsonschema" and not hasattr(module, "Draft202012Validator"):
        return (
            "package imported, but 'Draft202012Validator' is missing. "
            "The jsonschema installation may be incomplete."
        )
    if package == "openai" and not (hasattr(module, "OpenAI") or hasattr(module, "__version__")):
        return (
            "package imported, but expected OpenAI client symbols are missing. "
            "The openai installation may be incomplete."
        )
    if package == "pytest" and not hasattr(module, "main"):
        return (
            "package imported, but 'main' is missing. "
            "The pytest installation may be incomplete."
        )
    return None


def inspect_package(package: str) -> Tuple[bool, str]:
    try:
        module = importlib.import_module(package)
    except ModuleNotFoundError:
        return False, "not installed"
    except Exception as exc:
        return False, f"import failed: {exc}"

    issue = _package_health_issue(package, module)
    if issue:
        return False, issue

    return True, "import ok"


def ensure_packages(packages: Iterable[str], script_name: str) -> None:
    issues: List[Tuple[str, str]] = []

    for package in packages:
        ok, detail = inspect_package(package)
        if not ok:
            issues.append((package, detail))

    if not issues:
        return

    issue_text = ", ".join(sorted(package for package, _ in issues))
    req_hint = _requirements_hint()

    print(f"[env] Missing or broken Python package(s): {issue_text}", file=sys.stderr)
    for package, detail in issues:
        print(f"[env]   - {package}: {detail}", file=sys.stderr)
    print(f"[env] Interpreter: {sys.executable}", file=sys.stderr)
    print(f"[env] Before running {script_name}, install the project dependencies:", file=sys.stderr)
    print(f"[env]   python -m pip install -r \"{req_hint}\"", file=sys.stderr)
    print("[env] If the package was already installed, force reinstall it:", file=sys.stderr)
    print("[env]   python -m pip install --force-reinstall --no-cache-dir networkx", file=sys.stderr)
    print("[env] Recommended on a new machine:", file=sys.stderr)
    print("[env]   py -3.8 -m venv .venv", file=sys.stderr)
    print(r"[env]   .\.venv\Scripts\activate", file=sys.stderr)
    print(f"[env]   python -m pip install -r \"{req_hint}\"", file=sys.stderr)
    raise SystemExit(1)
