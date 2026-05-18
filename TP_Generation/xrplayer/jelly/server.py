"""Jelly stdlib HTTP server.

Implementation notes
--------------------
* Only Python standard library — no FastAPI / Flask / Tornado.
* Multi-threaded so the polling dashboard never blocks a slow read.
* Endpoints return small JSON payloads; heavy artefacts live on disk.
* POST endpoints allow workflow control (project management, run start/stop,
  file editing) in addition to the original read-only GET endpoints.

Read-only GET endpoints
~~~~~~~~~~~~~~~~~~~~~~~
* ``GET /``                          → dashboard HTML
* ``GET /api/health``                → ``{"ok": true}``
* ``GET /api/runs``                  → list available run dirs
* ``GET /api/status``                → ``jelly_status.json``
* ``GET /api/scene_understanding``   → scene understanding output
* ``GET /api/agent_trace``           → ``agent_decisions.json`` tail
* ``GET /api/coverage``              → ``summary.json``
* ``GET /api/gate_graph``            → ``gate_graph.json``
* ``GET /api/iterations``            → ``iteration_logs.json`` tail
* ``GET /api/test_plan``             → ``test_plan.json``

Workflow control endpoints
~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``GET  /api/projects``             → project list config
* ``POST /api/projects``             → add / remove / global-config
* ``GET  /api/scenes``               → discover .unity files in a project
* ``GET  /api/run/status``           → subprocess state + log line count
* ``GET  /api/run/log``              → rolling log slice (polling)
* ``POST /api/run/start``            → launch ``python -m vragent2``
* ``POST /api/run/stop``             → terminate running process
* ``GET  /api/file``                 → read a file under results_root
* ``POST /api/file``                 → write a file under results_root (.json/.md/.txt)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
import webbrowser
from collections import deque
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from vragent2.utils.path_layout import get_step2_results_dir, resolve_gobj_hierarchy_path, resolve_scene_meta_dir


# ---------------------------------------------------------------------------
# Process manager (run vragent2 as subprocess)
# ---------------------------------------------------------------------------

class _RunManager:
    """Manage a single vragent2 subprocess with a rolling log buffer."""

    MAX_LINES = 5000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._log: deque = deque(maxlen=self.MAX_LINES)
        self._state = "idle"   # idle | running | finished | error
        self._start_time = 0.0
        self._returncode: Optional[int] = None
        self._params: Dict[str, Any] = {}
        self._env: Optional[Dict[str, str]] = None

    def start(self, cmd: List[str], cwd: str, params: Dict[str, Any],
              env: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            if self._state == "running":
                raise ValueError("A run is already in progress. Stop it first.")
            self._log.clear()
            self._start_time = time.time()
            self._returncode = None
            self._params = params
            self._env = env
            self._proc = None
        proc_env = os.environ.copy()
        # Force unbuffered output so log lines appear even if process exits immediately
        proc_env["PYTHONUNBUFFERED"] = "1"
        proc_env["PYTHONIOENCODING"] = "utf-8"
        if env:
            proc_env.update(env)
        # On Windows, prevent subprocess from opening a console window
        _extra: Dict[str, Any] = {}
        if sys.platform == "win32":
            _extra["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                env=proc_env, **_extra,
            )
        except Exception as exc:
            with self._lock:
                self._state = "error"
                self._log.append(f"[jelly] failed to start process: {exc}")
                self._log.append(f"[jelly] cmd: {' '.join(cmd)}")
            raise
        with self._lock:
            self._proc = proc
            self._state = "running"
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()

    def _reader(self) -> None:
        try:
            assert self._proc is not None
            for raw in self._proc.stdout:  # type: ignore[union-attr]
                line = raw.rstrip("\n")
                with self._lock:
                    self._log.append(line)
        except Exception as exc:
            with self._lock:
                self._log.append(f"[jelly] reader error: {exc}")
        finally:
            rc = self._proc.wait() if self._proc else -1
            with self._lock:
                self._state = "finished" if rc == 0 else "error"
                self._returncode = rc
                self._log.append(f"[jelly] process exited with code {rc}")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        else:
            with self._lock:
                if self._state == "running":
                    self._state = "error"
                    self._log.append("[jelly] stopped stale running state")

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            elapsed = round(time.time() - self._start_time, 1) if self._state == "running" else None
            return {
                "state": self._state,
                "pid": self._proc.pid if self._proc else None,
                "lines": len(self._log),
                "start_time": self._start_time,
                "elapsed_s": elapsed,
                "returncode": self._returncode,
                "params": self._params,
            }

    def get_log_slice(self, from_idx: int) -> List[str]:
        with self._lock:
            lines = list(self._log)
        return lines[max(0, from_idx):]

    def total_lines(self) -> int:
        with self._lock:
            return len(self._log)


# ---------------------------------------------------------------------------
# Project config  (results_root/projects.json)
# ---------------------------------------------------------------------------

class _UiSettingsConfig:
    """Local-only UI settings (API key etc.) stored in .ui_settings.json.

    This file is gitignored and never served to the browser as plaintext.
    The GET route returns only ``has_api_key`` so the key never leaves the server.
    """

    def __init__(self, results_root: Path) -> None:
        self._path = results_root / ".ui_settings.json"
        self._lock = threading.Lock()

    def load(self) -> Dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def save(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get_api_key(self) -> str:
        return self.load().get("api_key", "")


class _ProjectsConfig:

    _DEFAULT: Dict[str, Any] = {
        "projects": [],
        "python_exe": "",
        "work_dir": "",
        "default_model": "gpt-4o",
    }

    def __init__(self, results_root: Path) -> None:
        self._path = results_root / "projects.json"
        self._results_root = results_root
        self._lock = threading.Lock()

    def _resolve_config_path(self, value: Any) -> Path:
        return _resolve_user_path(value, self._results_root)

    def _sanitize_optional_path(self, value: Any, *, want_file: bool = False, want_dir: bool = False) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        p = self._resolve_config_path(raw)
        if want_file and not p.is_file():
            return ""
        if want_dir and not p.is_dir():
            return ""
        return raw

    def _sanitize_loaded(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(data)
        cleaned["python_exe"] = self._sanitize_optional_path(cleaned.get("python_exe"), want_file=True)
        cleaned["work_dir"] = self._sanitize_optional_path(cleaned.get("work_dir"), want_dir=True)

        projects: List[Dict[str, Any]] = []
        for raw_project in cleaned.get("projects", []) or []:
            if not isinstance(raw_project, dict):
                continue
            project = dict(raw_project)
            project["python_exe"] = self._sanitize_optional_path(project.get("python_exe"), want_file=True)
            project["work_dir"] = self._sanitize_optional_path(project.get("work_dir"), want_dir=True)
            project["assets_path"] = self._sanitize_optional_path(project.get("assets_path"), want_dir=True)
            projects.append(project)
        cleaned["projects"] = projects
        return cleaned

    def load(self) -> Dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            # Merge with defaults so new keys are always present
            merged = dict(self._DEFAULT)
            merged.update(data)
            return self._sanitize_loaded(merged)
        except FileNotFoundError:
            return dict(self._DEFAULT)
        except (OSError, json.JSONDecodeError) as exc:
            return {**self._DEFAULT, "_error": str(exc)}

    def save(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def _repo_root_from_results(results_root: Path) -> Path:
    if results_root.name == "TP_Generation":
        return results_root.parent
    return results_root


_PATH_TOKENS = ("{repo}", "{repo_root}", "{tp_generation}")


def _has_path_token(path_value: Any) -> bool:
    raw = str(path_value or "")
    return any(token in raw for token in _PATH_TOKENS)


def _resolve_user_path(path_value: Any, results_root: Path) -> Path:
    raw = str(path_value or "").strip()
    if not raw:
        return Path("")
    repo_root = _repo_root_from_results(results_root)
    expanded = os.path.expandvars(os.path.expanduser(raw))
    expanded = (
        expanded
        .replace("{repo}", str(repo_root))
        .replace("{repo_root}", str(repo_root))
        .replace("{tp_generation}", str(results_root))
    )
    p = Path(expanded)
    if p.is_absolute():
        return p
    for base in (repo_root, results_root):
        candidate = base / p
        if candidate.exists():
            return candidate
    return repo_root / p


def _default_python(results_root: Path) -> str:
    repo_root = _repo_root_from_results(results_root)
    candidates = (
        os.environ.get("XRPLAYER_JELLY_PYTHON", ""),
        str(repo_root / ".venv" / "Scripts" / "python.exe"),
        sys.executable,
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return sys.executable


def _resolve_python(path_value: Any, results_root: Path) -> str:
    p = _resolve_user_path(path_value, results_root)
    if str(p) and p.is_file():
        return str(p)
    return _default_python(results_root)


def _resolve_work_dir(path_value: Any, results_root: Path) -> str:
    raw = str(path_value or "").strip()
    if not raw or raw in (".", "./", ".\\"):
        return str(results_root)
    p = _resolve_user_path(path_value, results_root)
    if str(p) and p.is_dir():
        return str(p)
    return str(results_root)


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------

def _find_scenes(project_path: str, max_results: int = 200) -> List[Dict[str, Any]]:
    """Discover .unity scene files inside a Unity project directory."""
    base = Path(project_path)
    if not base.is_dir():
        return []
    search_root = base / "Assets" if (base / "Assets").is_dir() else base
    scenes: List[Dict[str, Any]] = []
    try:
        for p in search_root.rglob("*.unity"):
            try:
                rel = str(p.relative_to(base)).replace("\\", "/")
                scenes.append({"name": p.stem, "path": rel, "full_path": str(p)})
            except ValueError:
                pass
            if len(scenes) >= max_results:
                break
    except Exception:
        pass
    return sorted(scenes, key=lambda s: s["name"].lower())


def _read_file_safe(results_root: Path, rel: str) -> Optional[Dict[str, Any]]:
    """Read a file inside results_root. Returns None on path-escape or not-found."""
    try:
        p = (results_root / rel).resolve()
        rr = results_root.resolve()
        if not str(p).startswith(str(rr)):
            return None
        if not p.is_file():
            return None
        content = p.read_text(encoding="utf-8", errors="replace")
        return {"path": rel, "content": content, "size": p.stat().st_size}
    except Exception:
        return None


def _write_file_safe(results_root: Path, rel: str, content: str) -> Optional[str]:
    """Write a file inside results_root. Returns error string or None on success."""
    try:
        p = (results_root / rel).resolve()
        rr = results_root.resolve()
        if not str(p).startswith(str(rr)):
            return "path escape not allowed"
        if p.suffix.lower() not in (".json", ".md", ".txt"):
            return "only .json / .md / .txt files can be edited via Jelly"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return None
    except Exception as exc:
        return str(exc)


def _list_result_files(results_root: Path, run_dir: Optional[str]) -> List[Dict[str, Any]]:
    """List editable/viewable artefact files for a given run."""
    if run_dir:
        safe = Path(run_dir.replace("\\", "/"))
        if any(p in ("..", "") for p in safe.parts):
            base = results_root
        else:
            base = results_root / safe
    else:
        base = results_root
    if not base.is_dir():
        return []
    files = []
    for ext in ("*.json", "*.md", "*.txt"):
        for p in base.glob(ext):
            rel = str(p.relative_to(results_root)).replace("\\", "/")
            files.append({
                "name": p.name,
                "path": rel,
                "size": p.stat().st_size,
                "mtime": p.stat().st_mtime,
            })
    files.sort(key=lambda f: f["name"])
    return files


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _read_static(name: str) -> Optional[bytes]:
    p = _STATIC_DIR / name
    if not p.is_file():
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Artefact loading helpers (read-only, defensive)
# ---------------------------------------------------------------------------

_ARTEFACT_NAMES = {
    "status":              "jelly_status.json",
    "scene":               "scene_understanding.json",
    "decisions":           "agent_decisions.json",
    "summary":             "summary.json",
    "gate_graph":          "gate_graph.json",
    "iterations":          "iteration_logs.json",
    "test_plan":           "test_plan.json",
    "all_actions":         "all_actions.json",
    "oracle_bugs":         "oracle_bugs.json",
    "coverage_snapshot":   "coverage_snapshot.json",
    "run_metadata":        "run_metadata.json",
}


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        return {"_jelly_error": f"failed to read {path.name}: {exc}"}


def _resolve_artefact(results_root: Path, run_dir: Optional[str], key: str) -> Path:
    """Resolve <results_root>[/<run_dir>]/<file>.

    ``run_dir`` may be a relative path like ``Home/qwen3-coder-30b-a3b-instruct``
    so the same Jelly server can browse multiple scenes.  When omitted, the
    artefact is read directly from ``results_root``.
    """
    name = _ARTEFACT_NAMES[key]
    if run_dir:
        # Disallow path escape.
        safe = Path(run_dir.replace("\\", "/"))
        if any(p in ("..", "") for p in safe.parts):
            return results_root / name
        return results_root / safe / name
    return results_root / name


def _list_runs(results_root: Path, max_depth: int = 3) -> List[Dict[str, Any]]:
    """Discover sub-directories that look like XRPlayer run outputs."""
    runs: List[Dict[str, Any]] = []
    if not results_root.is_dir():
        return runs

    seen: set = set()
    for marker_name in ("jelly_status.json", "summary.json", "agent_decisions.json"):
        for marker in results_root.rglob(marker_name):
            try:
                rel = marker.parent.relative_to(results_root)
            except ValueError:
                continue
            if len(rel.parts) > max_depth:
                continue
            key = str(rel).replace("\\", "/")
            if key in seen:
                continue
            seen.add(key)
            runs.append({
                "run_dir": key or ".",
                "scene": rel.parts[0] if rel.parts else "",
                "model": rel.parts[1] if len(rel.parts) > 1 else "",
                "has_status": (marker.parent / "jelly_status.json").is_file(),
                "has_decisions": (marker.parent / "agent_decisions.json").is_file(),
                "mtime": marker.stat().st_mtime,
            })
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs


# ---------------------------------------------------------------------------
# New helpers: replay options, Unity coverage XML, benchmark aggregation
# ---------------------------------------------------------------------------

def _scan_results_for_models(root: Path) -> List[Dict[str, Any]]:
    """Scan results root for <scene>/<model>/test_plan.json patterns."""
    options: List[Dict[str, Any]] = []
    if not root.is_dir():
        return options
    try:
        for scene_dir in sorted(root.iterdir()):
            if not scene_dir.is_dir():
                continue
            for model_dir in sorted(scene_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                test_plan = model_dir / "test_plan.json"
                if test_plan.exists():
                    options.append({
                        "scene": scene_dir.name,
                        "model": model_dir.name,
                        "path": str(test_plan),
                        "label": f"{scene_dir.name}/{model_dir.name}",
                    })
    except Exception:
        pass
    return options


def _parse_unity_coverage_xml(xml_path: Path) -> Dict[str, Any]:
    """Parse a Unity/OpenCover Summary.xml and return structured coverage data."""
    import xml.etree.ElementTree as ET  # stdlib
    if not xml_path.exists():
        return {"error": f"Summary.xml not found: {xml_path}", "found": False}
    try:
        tree = ET.parse(str(xml_path))
        root_el = tree.getroot()
        summary = root_el.find("Summary")
        if summary is None:
            return {"error": "No Summary element in XML", "found": False}

        def _f(k: str) -> float:
            try:
                return float(summary.get(k, 0) or 0)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0.0

        def _i(k: str) -> int:
            try:
                return int(summary.get(k, 0) or 0)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0

        result: Dict[str, Any] = {
            "found": True,
            "xml_path": str(xml_path),
            "sequence_coverage": _f("sequenceCoverage"),
            "branch_coverage": _f("branchCoverage"),
            "visited_sequence_points": _i("visitedSequencePoints"),
            "num_sequence_points": _i("numSequencePoints"),
            "visited_branch_points": _i("visitedBranchPoints"),
            "num_branch_points": _i("numBranchPoints"),
            "visited_classes": _i("visitedClasses"),
            "num_classes": _i("numClasses"),
            "visited_methods": _i("visitedMethods"),
            "num_methods": _i("numMethods"),
        }
        modules: List[Dict[str, Any]] = []
        mods_el = root_el.find("Modules")
        if mods_el is not None:
            for mod in mods_el:
                ms = mod.find("Summary")
                if ms is None:
                    continue
                mod_name = mod.get("moduleName") or mod.get("ModuleName") or ""
                try:
                    seq = float(ms.get("sequenceCoverage", 0) or 0)
                    brn = float(ms.get("branchCoverage", 0) or 0)
                except (TypeError, ValueError):
                    seq, brn = 0.0, 0.0
                modules.append({"name": mod_name, "sequence_coverage": seq, "branch_coverage": brn})
                if len(modules) >= 20:
                    break
        result["modules"] = modules
        return result
    except Exception as exc:
        return {"error": str(exc), "found": False}


def _parse_coverage_report_dir(report_dir: Path) -> Dict[str, Any]:
    """Parse Unity CodeCoverage report directory.

    Tries ``Summary.json`` first (ReportGenerator JSON output).  Falls back to
    parsing ``Summary.xml`` (legacy OpenCover format) via
    ``_parse_unity_coverage_xml``.
    """
    if not report_dir.is_dir():
        return {"found": False, "error": f"Report directory not found: {report_dir}"}

    result: Dict[str, Any] = {"found": True, "report_dir": str(report_dir)}

    # Provide path to interactive HTML report if it exists
    for htm_name in ("index.htm", "index.html"):
        htm_p = report_dir / htm_name
        if htm_p.exists():
            result["index_htm_path"] = str(htm_p)
            break

    # ── Try Summary.json first (richest data, no XML needed) ────────────
    summary_json_p = report_dir / "Summary.json"
    if summary_json_p.exists():
        try:
            raw = json.loads(summary_json_p.read_text(encoding="utf-8"))
            s = raw.get("summary", {})
            result["generated_on"]    = s.get("generatedon", "")
            result["line_coverage"]   = float(s.get("linecoverage", 0) or 0)
            result["method_coverage"] = float(s.get("methodcoverage", 0) or 0)
            result["covered_lines"]   = int(s.get("coveredlines", 0) or 0)
            result["coverable_lines"] = int(s.get("coverablelines", 0) or 0)
            result["total_lines"]     = int(s.get("totallines", 0) or 0)
            result["uncovered_lines"] = int(s.get("uncoveredlines", 0) or 0)
            result["covered_methods"] = int(s.get("coveredmethods", 0) or 0)
            result["total_methods"]   = int(s.get("totalmethods", 0) or 0)
            result["covered_branches"]= int(s.get("coveredbranches", 0) or 0)
            result["total_branches"]  = int(s.get("totalbranches", 0) or 0)
            result["num_classes"]     = int(s.get("classes", 0) or 0)
            classes: List[Dict[str, Any]] = []
            for asm in raw.get("coverage", {}).get("assemblies", []):
                for cls in asm.get("classesinassembly", []):
                    classes.append({
                        "name":            cls.get("name", ""),
                        "coverage":        float(cls.get("coverage", 0) or 0),
                        "covered_lines":   int(cls.get("coveredlines", 0) or 0),
                        "coverable_lines": int(cls.get("coverablelines", 0) or 0),
                        "total_lines":     int(cls.get("totallines", 0) or 0),
                        "method_coverage": float(cls.get("methodcoverage", 0) or 0),
                        "covered_methods": int(cls.get("coveredmethods", 0) or 0),
                        "total_methods":   int(cls.get("totalmethods", 0) or 0),
                    })
            result["classes"] = classes
            return result
        except Exception:
            pass  # fall through to XML

    # ── Fallback: parse Summary.xml (OpenCover attribute format) ────────
    xml_p2 = report_dir / "Summary.xml"
    if xml_p2.exists():
        xml_data = _parse_unity_coverage_xml(xml_p2)
        if xml_data.get("found"):
            result["generated_on"]    = ""
            result["line_coverage"]   = xml_data.get("sequence_coverage", 0.0)
            result["method_coverage"] = 0.0
            result["covered_lines"]   = xml_data.get("visited_sequence_points", 0)
            result["coverable_lines"] = xml_data.get("num_sequence_points", 0)
            result["total_lines"]     = xml_data.get("num_sequence_points", 0)
            result["uncovered_lines"] = xml_data.get("num_sequence_points", 0) - xml_data.get("visited_sequence_points", 0)
            result["covered_methods"] = xml_data.get("visited_methods", 0)
            result["total_methods"]   = xml_data.get("num_methods", 0)
            result["covered_branches"]= xml_data.get("visited_branch_points", 0)
            result["total_branches"]  = xml_data.get("num_branch_points", 0)
            result["num_classes"]     = xml_data.get("visited_classes", 0)
            result["classes"]         = []
        return result

    return {"found": False, "error": "No Summary.json or Summary.xml in report dir",
            "report_dir": str(report_dir)}


def _parse_time_value(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] if text.endswith("Z") else text
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d - %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def _format_time_value(value: Optional[datetime], fallback: str = "") -> str:
    if value is None:
        return fallback
    return value.isoformat(timespec="seconds") + "Z"


def _resolve_unity_project_root(project_path: str, results_root: Optional[Path] = None) -> Optional[Path]:
    if not project_path:
        return None
    current = (_resolve_user_path(project_path, results_root) if results_root is not None else Path(project_path)).resolve()
    for _ in range(12):
        if (current / "Assets").is_dir() and (current / "ProjectSettings").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _resolve_coverage_report_dir(project_path: str, metadata: Dict[str, Any], results_root: Optional[Path] = None) -> Optional[Path]:
    candidates: List[Path] = []

    metadata_report_dir = str(metadata.get("coverage_report_dir", "") or "").strip()
    if metadata_report_dir:
        try:
            if results_root is not None:
                candidates.append(_resolve_user_path(metadata_report_dir, results_root).resolve())
            else:
                candidates.append(Path(metadata_report_dir).resolve())
        except OSError:
            pass

    unity_root = _resolve_unity_project_root(project_path, results_root)
    if unity_root is not None:
        candidates.extend([
            unity_root / "CodeCoverage" / "Report",
            unity_root / "CodeCoverage",
            unity_root / "Coverage" / "Report",
        ])

    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if any((candidate / name).is_file() for name in ("Summary.json", "Summary.xml", "index.htm", "index.html")):
            return candidate
    return None


def _parse_report_history_nodes(report_dir: Path) -> List[Dict[str, Any]]:
    index_path: Optional[Path] = None
    for name in ("index.htm", "index.html"):
        candidate = report_dir / name
        if candidate.is_file():
            index_path = candidate
            break
    if index_path is None:
        return []

    try:
        html_text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    match = re.search(
        r'var\s+historyChartData[0-9a-fA-F]+\s*=\s*\{(?P<body>[\s\S]*?)\};',
        html_text,
    )
    if match is None:
        return []

    body = match.group("body")
    tooltip_match = re.search(r'"tooltips"\s*:\s*\[(?P<tooltips>[\s\S]*?)\]\s*', body)
    if tooltip_match is None:
        return []

    nodes: List[Dict[str, Any]] = []
    for index, raw_tooltip in enumerate(re.findall(r"'([^']*)'", tooltip_match.group("tooltips"))):
        tooltip = raw_tooltip.replace("\\'", "'")
        time_match = re.search(r"<h3>([^<]+)</h3>", tooltip)
        coverage_match = re.search(r"Line coverage:\s*([0-9.]+)%\s*\((\d+)/(\d+)\)", tooltip)
        total_match = re.search(r"Total lines:\s*(\d+)", tooltip)
        time_text = time_match.group(1).strip() if time_match else ""
        node_time = _parse_time_value(time_text)
        nodes.append({
            "index": index,
            "time": time_text,
            "time_iso": _format_time_value(node_time, time_text),
            "line_coverage": float(coverage_match.group(1)) if coverage_match else 0.0,
            "covered_lines": int(coverage_match.group(2)) if coverage_match else 0,
            "coverable_lines": int(coverage_match.group(3)) if coverage_match else 0,
            "total_lines": int(total_match.group(1)) if total_match else 0,
        })
    return nodes


def _load_run_metadata(results_root: Path, run_dir: Optional[str]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    raw = _read_json(_resolve_artefact(results_root, run_dir, "run_metadata"))
    if isinstance(raw, dict) and not raw.get("_jelly_error"):
        metadata.update(raw)

    safe_dir = Path(run_dir.replace("\\", "/")) if run_dir else Path()
    parts = safe_dir.parts
    if parts:
        metadata.setdefault("scene", parts[0])
        metadata.setdefault("model", parts[1] if len(parts) > 1 else parts[0])
        metadata.setdefault("run_id", parts[-1])
        metadata.setdefault("result_dir", str((results_root / safe_dir).resolve()))

    if not metadata.get("start_time") or not metadata.get("end_time"):
        iteration_logs = _read_json(_resolve_artefact(results_root, run_dir, "iterations"))
        if isinstance(iteration_logs, list):
            timestamps = [
                str(item.get("timestamp", "")).strip()
                for item in iteration_logs
                if isinstance(item, dict) and str(item.get("timestamp", "")).strip()
            ]
            if timestamps:
                timestamps.sort()
                metadata.setdefault("start_time", timestamps[0])
                metadata.setdefault("end_time", timestamps[-1])

    test_plan_name = str(metadata.get("test_plan_name", "") or "").strip()
    if not test_plan_name:
        scene = str(metadata.get("scene", "") or "").strip()
        model = str(metadata.get("model", "") or "").strip()
        test_plan_name = f"{scene}_{model}".strip("_")
        metadata["test_plan_name"] = test_plan_name

    metadata.setdefault("test_plan_id", metadata.get("test_plan_name") or metadata.get("run_id") or "")
    return metadata


def _match_history_nodes_to_run(
    history_nodes: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    tolerance_seconds: int = 180,
) -> List[Dict[str, Any]]:
    start_time = _parse_time_value(metadata.get("start_time"))
    end_time = _parse_time_value(metadata.get("end_time"))
    if start_time is None or end_time is None:
        return []
    if end_time < start_time:
        end_time = start_time

    lower = start_time - timedelta(seconds=tolerance_seconds)
    upper = end_time + timedelta(seconds=tolerance_seconds)
    matched: List[Dict[str, Any]] = []
    for node in history_nodes:
        node_time = _parse_time_value(node.get("time") or node.get("time_iso"))
        if node_time is None:
            continue
        if lower <= node_time <= upper:
            matched.append(node)
    return matched


def _build_run_coverage_diagnosis(
    results_root: Path,
    run_dir: Optional[str],
    project_path: str = "",
) -> Dict[str, Any]:
    metadata = _load_run_metadata(results_root, run_dir)
    report_dir = _resolve_coverage_report_dir(project_path, metadata, results_root)
    diagnosis: Dict[str, Any] = {
        "found": False,
        "coverage_source": "unity_summary_report",
        "is_real_report": False,
        "mapping_status": "missing",
        "metadata": metadata,
        "report_dir": str(report_dir) if report_dir is not None else str(metadata.get("coverage_report_dir", "") or ""),
        "history_nodes": [],
        "matched_history_nodes": [],
        "history_node_count": 0,
        "matched_history_node_count": 0,
        "highest_code_coverage": None,
    }
    if report_dir is None:
        diagnosis["mapping_status"] = "no_report"
        diagnosis["error"] = "Unity Code Coverage report not found"
        return diagnosis

    parsed = _parse_coverage_report_dir(report_dir)
    if not parsed.get("found"):
        diagnosis.update(parsed)
        diagnosis["mapping_status"] = "no_report"
        return diagnosis

    history_nodes = _parse_report_history_nodes(report_dir)
    if not history_nodes and parsed.get("generated_on"):
        history_nodes = [{
            "index": 0,
            "time": str(parsed.get("generated_on", "")),
            "time_iso": _format_time_value(_parse_time_value(parsed.get("generated_on")), str(parsed.get("generated_on", ""))),
            "line_coverage": float(parsed.get("line_coverage", 0) or 0),
            "covered_lines": int(parsed.get("covered_lines", 0) or 0),
            "coverable_lines": int(parsed.get("coverable_lines", 0) or 0),
            "total_lines": int(parsed.get("total_lines", 0) or 0),
        }]

    matched_nodes = _match_history_nodes_to_run(history_nodes, metadata)
    has_time_window = _parse_time_value(metadata.get("start_time")) is not None and _parse_time_value(metadata.get("end_time")) is not None
    if matched_nodes:
        mapping_status = "mapped"
    elif history_nodes and has_time_window:
        mapping_status = "unmapped"
    else:
        mapping_status = "missing"

    highest_code_coverage = None
    if matched_nodes:
        highest_code_coverage = max(float(node.get("line_coverage", 0) or 0) for node in matched_nodes)

    diagnosis.update(parsed)
    diagnosis.update({
        "found": True,
        "is_real_report": True,
        "mapping_status": mapping_status,
        "metadata": metadata,
        "report_dir": str(report_dir),
        "report_path": str(report_dir / ("index.htm" if (report_dir / "index.htm").is_file() else "index.html")),
        "history_nodes": history_nodes,
        "matched_history_nodes": matched_nodes,
        "history_node_count": len(history_nodes),
        "matched_history_node_count": len(matched_nodes),
        "highest_code_coverage": highest_code_coverage,
    })
    return diagnosis


def _resolve_benchmark_scan_root(root: Path) -> Tuple[Path, str]:
    if not root.is_dir():
        return root, ""
    nested_results = root / "Results"
    if nested_results.is_dir():
        return nested_results, "Results/"
    return root, ""


def _scan_benchmark_data(root: Path) -> List[Dict[str, Any]]:
    """Scan results root for all <scene>/<model>/summary.json entries."""
    entries: List[Dict[str, Any]] = []
    scan_root, run_prefix = _resolve_benchmark_scan_root(root)
    if not scan_root.is_dir():
        return entries
    try:
        for scene_dir in sorted(scan_root.iterdir()):
            if not scene_dir.is_dir():
                continue
            for model_dir in sorted(scene_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                summary = _read_json(model_dir / "summary.json")
                if summary is None:
                    continue
                oracle = _read_json(model_dir / "oracle_bugs.json")
                status = _read_json(model_dir / "jelly_status.json")
                run_dir = f"{run_prefix}{scene_dir.name}/{model_dir.name}"
                entries.append({
                    "scene": scene_dir.name,
                    "model": model_dir.name,
                    "run_dir": run_dir,
                    "summary": summary,
                    "oracle": oracle,
                    "status": status,
                    "code_coverage": _build_run_coverage_diagnosis(root, run_dir),
                })
    except Exception:
        pass
    return entries


def _normalize_preprocess_dir(path_value: str, results_root: Optional[Path] = None) -> Optional[Path]:
    if not path_value:
        return None
    try:
        path = _resolve_user_path(path_value, results_root) if results_root is not None else Path(path_value)
        return path.resolve()
    except OSError:
        return None


def _infer_scene_name_from_dir(results_dir: Optional[Path]) -> str:
    if results_dir is None or not results_dir.is_dir():
        return ""

    scene_meta_dir = resolve_scene_meta_dir(results_dir)
    if scene_meta_dir.is_dir():
        suffixes = (
            ".unity.json_graph.gml",
            ".unity.json_database.json",
            ".unity.json",
        )
        for suffix in suffixes:
            for path in sorted(scene_meta_dir.glob(f"*{suffix}")):
                return path.name[: -len(suffix)]

    hierarchy_suffix = "_gobj_hierarchy.json"
    for candidate_dir in (get_step2_results_dir(results_dir), results_dir):
        if not candidate_dir.is_dir():
            continue
        for path in sorted(candidate_dir.glob(f"*{hierarchy_suffix}")):
            return path.name[: -len(hierarchy_suffix)]

    return ""


def _contains_sorted_logic_markers(data: Any) -> bool:
    stack: List[Any] = [data]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if "sorted_target_logic_info" in current or "sorted_layer_logic_info" in current:
                return True
            for value in current.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            for value in current:
                if isinstance(value, (dict, list)):
                    stack.append(value)
    return False


def _build_preprocess_status(results_dir1: Optional[Path], results_dir2: Optional[Path],
                             results_dir3: Optional[Path], scene_name: str) -> Dict[str, Any]:
    scene_name = (scene_name or "").strip()
    if not scene_name:
        for candidate_dir in (results_dir1, results_dir2, results_dir3):
            scene_name = _infer_scene_name_from_dir(candidate_dir)
            if scene_name:
                break

    step1_dir = results_dir1 or results_dir2 or results_dir3
    step2_dir = results_dir2 or results_dir1 or results_dir3
    step3_dir = results_dir3 or results_dir2 or results_dir1

    graph_path = None
    database_path = None
    scene_json_path = None
    if step1_dir is not None and scene_name:
        scene_meta_dir = resolve_scene_meta_dir(step1_dir)
        graph_path = scene_meta_dir / f"{scene_name}.unity.json_graph.gml"
        database_path = scene_meta_dir / f"{scene_name}.unity.json_database.json"
        scene_json_path = scene_meta_dir / f"{scene_name}.unity.json"

    hierarchy_path2 = resolve_gobj_hierarchy_path(step2_dir, scene_name) if step2_dir is not None and scene_name else None
    hierarchy_path3 = resolve_gobj_hierarchy_path(step3_dir, scene_name) if step3_dir is not None and scene_name else None

    step1_done = any(path is not None and path.is_file() for path in (graph_path, database_path, scene_json_path))
    step2_done = hierarchy_path2 is not None and hierarchy_path2.is_file()

    step3_done = False
    step3_error = ""
    if hierarchy_path3 is not None and hierarchy_path3.is_file():
        data = _read_json(hierarchy_path3)
        if isinstance(data, dict) and data.get("_jelly_error"):
            step3_error = data["_jelly_error"]
        elif data is not None:
            step3_done = _contains_sorted_logic_markers(data)

    if step2_done or step3_done:
        step1_done = True
    if step3_done:
        step2_done = True

    return {
        "scene_name": scene_name,
        "step1": {
            "state": "done" if step1_done else "idle",
            "results_dir": str(step1_dir) if step1_dir is not None else "",
            "exists": bool(step1_dir and step1_dir.is_dir()),
            "graph_path": str(graph_path) if graph_path is not None and graph_path.is_file() else "",
            "database_path": str(database_path) if database_path is not None and database_path.is_file() else "",
            "scene_json_path": str(scene_json_path) if scene_json_path is not None and scene_json_path.is_file() else "",
        },
        "step2": {
            "state": "done" if step2_done else "idle",
            "results_dir": str(step2_dir) if step2_dir is not None else "",
            "exists": bool(step2_dir and step2_dir.is_dir()),
            "hierarchy_path": str(hierarchy_path2) if hierarchy_path2 is not None and hierarchy_path2.is_file() else "",
        },
        "step3": {
            "state": "done" if step3_done else "idle",
            "results_dir": str(step3_dir) if step3_dir is not None else "",
            "exists": bool(step3_dir and step3_dir.is_dir()),
            "hierarchy_path": str(hierarchy_path3) if hierarchy_path3 is not None and hierarchy_path3.is_file() else "",
            "error": step3_error,
        },
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _JellyHandler(BaseHTTPRequestHandler):
    server_version = "JellyXRPlayer/0.1"

    # The HTTPServer subclass below stamps ``results_root`` onto the server
    # instance; we read it via ``self.server`` here.
    @property
    def _root(self) -> Path:
        return self.server.results_root  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # Quieter than the default per-request stderr spam.
        if "/api/health" in (args[0] if args else ""):
            return
        print("[jelly] " + (fmt % args))

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str,
                    status: int = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self, msg: str = "not found") -> None:
        self._send_json({"error": msg}, status=HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        url = urlsplit(self.path)
        path = url.path
        qs = parse_qs(url.query)
        run_dir = (qs.get("run") or [None])[0]
        limit = _safe_int((qs.get("limit") or ["100"])[0], default=100, lo=1, hi=2000)

        if path in ("/", "/index.html"):
            html = _read_static("index.html")
            if html is None:
                self._send_bytes(_FALLBACK_HTML.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send_bytes(html, "text/html; charset=utf-8")
            return

        # ── Serve Unity CodeCoverage HTML report files ─────────────────────
        if path.startswith("/coverage_report/"):
            sub = path[len("/coverage_report/"):]
            if not sub or sub == "/":
                sub = "index.htm"
            pp_cr = (qs.get("project_path") or qs.get("assets_path") or [""])[0].strip()
            report_dir_cr: Optional[Path] = None
            if pp_cr:
                p_cr = _resolve_user_path(pp_cr, self._root).resolve()
                for _ in range(12):
                    if (p_cr / "Assets").is_dir() and (p_cr / "ProjectSettings").is_dir():
                        for _cov_sub in ("CodeCoverage/Report", "Coverage/Report", "CodeCoverage"):
                            _rd_cand = p_cr
                            for _seg in _cov_sub.split("/"):
                                _rd_cand = _rd_cand / _seg
                            if _rd_cand.is_dir() and (any(_rd_cand.glob("index.htm*"))):
                                report_dir_cr = _rd_cand
                                self.server.coverage_report_dir = _rd_cand
                                break
                        break
                    _nxt_cr = p_cr.parent
                    if _nxt_cr == p_cr:
                        break
                    p_cr = _nxt_cr
            if report_dir_cr is None:
                report_dir_cr = getattr(self.server, "coverage_report_dir", None)
            if report_dir_cr is None:
                _heur = self._root.parent / "VRAgent" / "CodeCoverage" / "Report"
                if _heur.is_dir():
                    report_dir_cr = _heur
            if report_dir_cr is None:
                self._send_json({"error": "Coverage report dir not found. Provide ?project_path= param."}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                _target_cr = (report_dir_cr / sub).resolve()
                _resolved_rd = report_dir_cr.resolve()
                if not str(_target_cr).startswith(str(_resolved_rd)):
                    self._send_json({"error": "Access denied"}, status=HTTPStatus.FORBIDDEN)
                    return
            except Exception:
                self._send_json({"error": "Invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not _target_cr.is_file():
                self._send_json({"error": f"File not found: {sub}"}, status=HTTPStatus.NOT_FOUND)
                return
            _MIME_CR = {
                ".htm": "text/html; charset=utf-8", ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml", ".png": "image/png", ".gif": "image/gif",
                ".json": "application/json; charset=utf-8", ".xml": "application/xml; charset=utf-8",
                ".woff": "font/woff", ".woff2": "font/woff2",
            }
            self._send_bytes(_target_cr.read_bytes(), _MIME_CR.get(_target_cr.suffix.lower(), "application/octet-stream"))
            return

        if path == "/api/health":
            repo_root = _repo_root_from_results(self._root)
            self._send_json({
                "ok": True,
                "results_root": str(self._root),
                "repo_root": str(repo_root),
                "default_python": _default_python(self._root),
                "default_work_dir": str(self._root),
                "venv_python": str(repo_root / ".venv" / "Scripts" / "python.exe"),
            })
            return

        # ── Serve archived snapshot HTML report files ─────────────────────────
        if path.startswith("/coverage_archive_report/"):
            sub_sar = path[len("/coverage_archive_report/"):] or "index.htm"
            _run_sar = (qs.get("run") or [None])[0]
            _ts_sar  = (qs.get("ts")  or [None])[0]
            if _run_sar and _ts_sar:
                _snap_sar = self._root / _run_sar.replace("\\", "/") / "coverage_snapshots" / _ts_sar
                if _snap_sar.is_dir():
                    self.server.active_snap_dir = _snap_sar  # type: ignore[attr-defined]
            _active_sar: Optional[Path] = getattr(self.server, "active_snap_dir", None)
            if _active_sar is None or not _active_sar.is_dir():
                self._send_json({"error": "Snapshot dir not found. Provide ?run= and ?ts= params."},
                                status=HTTPStatus.NOT_FOUND)
                return
            try:
                _tgt_sar = (_active_sar / sub_sar).resolve()
                if not str(_tgt_sar).startswith(str(_active_sar.resolve())):
                    self._send_json({"error": "Access denied"}, status=HTTPStatus.FORBIDDEN)
                    return
            except Exception:
                self._send_json({"error": "Invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not _tgt_sar.is_file():
                self._send_json({"error": f"File not found: {sub_sar}"}, status=HTTPStatus.NOT_FOUND)
                return
            _MIME_SAR = {
                ".htm": "text/html; charset=utf-8", ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",  ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml", ".png": "image/png", ".gif": "image/gif",
                ".json": "application/json; charset=utf-8", ".xml": "application/xml; charset=utf-8",
                ".woff": "font/woff", ".woff2": "font/woff2",
            }
            self._send_bytes(_tgt_sar.read_bytes(), _MIME_SAR.get(_tgt_sar.suffix.lower(), "application/octet-stream"))
            return

        if path == "/api/runs":
            self._send_json({"results_root": str(self._root),
                              "runs": _list_runs(self._root)})
            return

        if path == "/api/status":
            data = _read_json(_resolve_artefact(self._root, run_dir, "status"))
            if data is None:
                self._send_json({"finished": False, "iteration": 0,
                                  "_jelly_note": "no jelly_status.json yet"})
                return
            self._send_json(data)
            return

        if path == "/api/scene_understanding":
            data = _read_json(_resolve_artefact(self._root, run_dir, "scene"))
            self._send_json(data if data is not None else {})
            return

        if path == "/api/agent_trace":
            data = _read_json(_resolve_artefact(self._root, run_dir, "decisions"))
            if isinstance(data, list):
                tail = data[-limit:]
                self._send_json({"count": len(data), "tail": tail})
            else:
                self._send_json({"count": 0, "tail": []})
            return

        if path == "/api/coverage":
            data = _read_json(_resolve_artefact(self._root, run_dir, "summary"))
            self._send_json(data if data is not None else {})
            return

        if path == "/api/gate_graph":
            data = _read_json(_resolve_artefact(self._root, run_dir, "gate_graph"))
            self._send_json(data if data is not None else {"nodes": [], "edges": []})
            return

        if path == "/api/iterations":
            data = _read_json(_resolve_artefact(self._root, run_dir, "iterations"))
            if isinstance(data, list):
                self._send_json({"count": len(data), "tail": data[-limit:]})
            else:
                self._send_json({"count": 0, "tail": []})
            return

        if path == "/api/test_plan":
            data = _read_json(_resolve_artefact(self._root, run_dir, "test_plan"))
            self._send_json(data if data is not None else {})
            return

        # ── Workflow control (read-only side) ──────────────────────────────

        if path == "/api/projects":
            self._send_json(self.server.projects_config.load())  # type: ignore[attr-defined]
            return

        if path == "/api/ui_settings":
            # Never return the key itself — only indicate whether one is saved
            key = self.server.ui_settings.get_api_key()  # type: ignore[attr-defined]
            self._send_json({"has_api_key": bool(key)})
            return

        if path == "/api/scenes":
            project_path = (qs.get("project_path") or [None])[0]
            if not project_path:
                self._send_json({"error": "missing project_path"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"scenes": _find_scenes(str(_resolve_user_path(project_path, self._root)))})
            return

        if path == "/api/run/status":
            self._send_json(self.server.run_manager.get_status())  # type: ignore[attr-defined]
            return

        if path == "/api/run/log":
            from_idx = _safe_int((qs.get("from") or ["0"])[0], default=0, lo=0, hi=999_999)
            rm = self.server.run_manager  # type: ignore[attr-defined]
            lines = rm.get_log_slice(from_idx)
            status = rm.get_status()
            self._send_json({
                "lines": lines,
                "from": from_idx,
                "total": rm.total_lines(),
                "state": status["state"],
                "params": status.get("params", {}),
            })
            return

        if path == "/api/preprocess/status":
            shared_dir = (qs.get("results_dir") or [""])[0].strip()
            dir1 = (qs.get("results_dir1") or [shared_dir])[0].strip()
            dir2 = (qs.get("results_dir2") or [shared_dir or dir1])[0].strip()
            dir3 = (qs.get("results_dir3") or [shared_dir or dir2 or dir1])[0].strip()
            scene_name = (qs.get("scene_name") or [""])[0].strip()
            self._send_json(_build_preprocess_status(
                _normalize_preprocess_dir(dir1, self._root),
                _normalize_preprocess_dir(dir2, self._root),
                _normalize_preprocess_dir(dir3, self._root),
                scene_name,
            ))
            return

        if path == "/api/file":
            rel = (qs.get("path") or [None])[0]
            if not rel:
                self._not_found("missing path parameter")
                return
            result = _read_file_safe(self._root, rel)
            if result is None:
                self._not_found("file not found or path outside results root")
                return
            self._send_json(result)
            return

        if path == "/api/result_files":
            files = _list_result_files(self._root, run_dir)
            self._send_json({"files": files})
            return

        # ── Find Unity project root (walk up from any path inside project) ──
        if path == "/api/find_project_root":
            search_path = (qs.get("path") or [""])[0].strip()
            if not search_path:
                self._send_json({"found": False, "project_root": ""})
                return
            p = _resolve_user_path(search_path, self._root).resolve()
            for _ in range(12):
                if (p / "Assets").is_dir() and (p / "ProjectSettings").is_dir():
                    self._send_json({"found": True, "project_root": str(p)})
                    return
                parent = p.parent
                if parent == p:
                    break
                p = parent
            self._send_json({"found": False, "project_root": ""})
            return

        if path == "/api/browse":
            browse_path = (qs.get("path") or [""])[0].strip()
            browse_type = (qs.get("type") or ["dir"])[0]  # "dir" | "file"
            # Default to drives on Windows, root on Unix
            if not browse_path:
                import os as _os
                if _os.name == "nt":
                    import string as _string
                    drives = [d + ":\\" for d in _string.ascii_uppercase
                              if _os.path.exists(d + ":\\")]
                    self._send_json({"path": "", "parent": None, "dirs": drives, "files": []})
                else:
                    browse_path = "/"
            if browse_path:
                try:
                    bp = _resolve_user_path(browse_path, self._root) if _has_path_token(browse_path) else Path(browse_path)
                    if not bp.exists() or not bp.is_dir():
                        self._send_json({"error": "path not found"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    dirs, files_list = [], []
                    for child in sorted(bp.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                        try:
                            if child.is_dir():
                                dirs.append({"name": child.name, "path": str(child)})
                            elif browse_type == "file" and child.is_file():
                                files_list.append({"name": child.name, "path": str(child)})
                        except PermissionError:
                            pass
                    parent = str(bp.parent) if bp.parent != bp else None
                    self._send_json({"path": str(bp), "parent": parent,
                                     "dirs": dirs, "files": files_list})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/replay_options":
            dirs_param = (qs.get("dirs") or [""])[0].strip()
            work_dir_param = (qs.get("work_dir") or [""])[0].strip()
            work_dir_root = _resolve_user_path(work_dir_param, self._root) if work_dir_param else self._root
            roots: List[Path] = []
            if dirs_param:
                for raw in dirs_param.split(","):
                    raw = raw.strip()
                    if not raw:
                        continue
                    p_dir = _resolve_user_path(raw, self._root) if (Path(raw).is_absolute() or _has_path_token(raw)) else (work_dir_root / raw)
                    try:
                        p_dir = p_dir.resolve()
                    except Exception:
                        pass
                    if p_dir.is_dir() and p_dir not in roots:
                        roots.append(p_dir)
            # Always include server root
            if self._root not in roots:
                roots.append(self._root)
            all_options: List[Dict[str, Any]] = []
            seen_paths: set = set()
            for r in roots:
                for o in _scan_results_for_models(r):
                    if o["path"] not in seen_paths:
                        seen_paths.add(o["path"])
                        all_options.append(o)
            all_options.sort(key=lambda x: x["label"].lower())
            self._send_json({"options": all_options})
            return

        if path == "/api/unity_coverage":
            xml_param = (qs.get("xml_path") or [None])[0]
            if xml_param:
                xml_path = _resolve_user_path(xml_param, self._root)
            else:
                # Walk up from results_root to find a Unity project root
                candidate = self._root.parent
                xml_path = None
                for _ in range(8):
                    if (candidate / "Assets").is_dir() and (candidate / "ProjectSettings").is_dir():
                        xml_path = candidate / "CodeCoverage" / "Report" / "Summary.xml"
                        break
                    parent = candidate.parent
                    if parent == candidate:
                        break
                    candidate = parent
                if xml_path is None:
                    xml_path = self._root.parent / "VRAgent" / "CodeCoverage" / "Report" / "Summary.xml"
            self._send_json(_parse_unity_coverage_xml(xml_path))  # type: ignore[arg-type]
            return

        # ── Smart coverage: walk up from project assets_path to find Unity root ─
        if path == "/api/smart_coverage":
            assets_path = (qs.get("project_path") or qs.get("assets_path") or [""])[0].strip()
            unity_root_param = (qs.get("unity_root") or [""])[0].strip()
            unity_root: Optional[Path] = None
            if unity_root_param:
                unity_root = _resolve_unity_project_root(unity_root_param, self._root)
            if unity_root is None and assets_path:
                unity_root = _resolve_unity_project_root(assets_path, self._root)
            if unity_root is None:
                self._send_json({"found": False,
                                 "error": "Cannot find Unity project root. Provide project_path.",
                                 "unity_root": ""})
                return
            report_dir_sc = unity_root / "CodeCoverage" / "Report"
            data_sc = _parse_coverage_report_dir(report_dir_sc)
            if not data_sc.get("found"):
                # Try fallback paths
                for sub_sc in (unity_root / "CodeCoverage", unity_root / "Coverage" / "Report"):
                    if sub_sc.is_dir():
                        data_sc = _parse_coverage_report_dir(sub_sc)
                        if data_sc.get("found"):
                            break
            if not data_sc.get("found"):
                data_sc["unity_root"] = str(unity_root)
            self._send_json(data_sc)
            return

        # ── Run coverage: check snapshot first, fall back to live report ────
        if path == "/api/run_coverage":
            project_path_rc = (qs.get("project_path") or qs.get("assets_path") or [""])[0].strip()
            data_rc = _build_run_coverage_diagnosis(self._root, run_dir, project_path_rc)
            if data_rc.get("found") and data_rc.get("report_dir"):
                try:
                    self.server.coverage_report_dir = Path(str(data_rc["report_dir"]))
                except Exception:
                    pass
            self._send_json(data_rc)
            return

        if path == "/api/oracle":
            data = _read_json(_resolve_artefact(self._root, run_dir, "oracle_bugs"))
            self._send_json(data if data is not None else {"found": False, "bugs": []})
            return

        # ── Oracle evaluate: load oracle_bugs.json + iteration_logs.json, compute triggered ──
        if path == "/api/oracle_evaluate":
            oracle_path = _resolve_artefact(self._root, run_dir, "oracle_bugs")
            oracle_def = _read_json(oracle_path) if oracle_path else None
            if oracle_def is None:
                self._send_json({"found": False, "error": "oracle_bugs.json not found for this run."})
                return
            # Collect console logs from iteration_logs.json
            iter_log_path = _resolve_artefact(self._root, run_dir, "iterations")
            console_logs: list = []
            if iter_log_path:
                iter_data = _read_json(iter_log_path)
                if isinstance(iter_data, list):
                    for entry in iter_data:
                        if not isinstance(entry, dict):
                            continue
                        for field in ("bugs", "console_logs"):
                            val = entry.get(field)
                            if isinstance(val, list):
                                console_logs.extend(str(s) for s in val)
                            elif isinstance(val, str) and val:
                                console_logs.append(val)
            try:
                import sys as _sys, importlib as _il
                _ora = _il.import_module("vragent2.utils.oracle")
                result = _ora.evaluate_oracle_coverage(console_logs, oracle_def)
                result["found"] = True
                self._send_json(result)
            except Exception as exc:
                # Fallback: just return raw oracle_def without evaluation
                oracle_def["found"] = True
                oracle_def["_eval_error"] = str(exc)
                self._send_json(oracle_def)
            return

        # ── Coverage history: list all saved snapshots ──────────────────────
        if path == "/api/coverage_history":
            _run_prefix = (qs.get("run_prefix") or [""])[0].strip().replace("\\", "/").strip("/")
            _hist: List[Dict[str, Any]] = []
            try:
                for _snap_p in self._root.rglob("coverage_snapshot.json"):
                    _snap_d = _read_json(_snap_p)
                    if not (_snap_d and isinstance(_snap_d, dict) and _snap_d.get("found")):
                        continue
                    try:
                        _rel = _snap_p.parent.relative_to(self._root)
                    except ValueError:
                        continue
                    _rk = str(_rel).replace("\\", "/")
                    if _run_prefix and not _rk.startswith(_run_prefix):
                        continue
                    _parts = _rk.split("/")
                    _hist.append({
                        "run_dir":         _rk,
                        "scene":           _parts[0] if _parts else "",
                        "model":           _parts[-1] if len(_parts) > 1 else _parts[0] if _parts else "",
                        "snapshot_time":   _snap_d.get("snapshot_time", ""),
                        "snapshot_model":  _snap_d.get("snapshot_model", ""),
                        "line_coverage":   _snap_d.get("line_coverage", 0),
                        "method_coverage": _snap_d.get("method_coverage", 0),
                        "covered_lines":   _snap_d.get("covered_lines", 0),
                        "coverable_lines": _snap_d.get("coverable_lines", 0),
                        "covered_methods": _snap_d.get("covered_methods", 0),
                        "total_methods":   _snap_d.get("total_methods", 0),
                    })
            except Exception as _exc:
                self._send_json({"history": [], "error": str(_exc)})
                return
            _hist.sort(key=lambda r: r.get("snapshot_time", ""), reverse=True)
            self._send_json({"history": _hist, "run_prefix": _run_prefix})
            return

        # ── Coverage snapshots list: all timestamped archives for a run ───────────
        if path == "/api/coverage_snapshots_list":
            if not run_dir:
                self._send_json({"snapshots": [], "run_dir": ""})
                return
            _snaps_base = self._root / run_dir.replace("\\", "/") / "coverage_snapshots"
            if not _snaps_base.is_dir():
                self._send_json({"snapshots": [], "run_dir": run_dir})
                return
            _snaps_out: List[Dict[str, Any]] = []
            for _ts_dir in sorted(_snaps_base.iterdir(), reverse=True):
                if not _ts_dir.is_dir():
                    continue
                _meta = _read_json(_ts_dir / "meta.json")
                if _meta is None:
                    continue
                _snaps_out.append({
                    "ts":              _ts_dir.name,
                    "snapshot_time":   _meta.get("snapshot_time", ""),
                    "snapshot_model":  _meta.get("snapshot_model", ""),
                    "line_coverage":   _meta.get("line_coverage", 0),
                    "method_coverage": _meta.get("method_coverage", 0),
                    "covered_lines":   _meta.get("covered_lines", 0),
                    "coverable_lines": _meta.get("coverable_lines", 0),
                    "covered_methods": _meta.get("covered_methods", 0),
                    "total_methods":   _meta.get("total_methods", 0),
                    "classes":         _meta.get("classes", []),
                    "has_html":        (_ts_dir / "index.htm").is_file() or (_ts_dir / "index.html").is_file(),
                })
            self._send_json({"snapshots": _snaps_out, "run_dir": run_dir})
            return

        # ── Smart oracle: locate scene file under project, look for oracle*.json next to it ─
        if path == "/api/smart_oracle":
            assets_path = (qs.get("project_path") or qs.get("assets_path") or [""])[0].strip()
            scene_name = (qs.get("scene_name") or [""])[0].strip()
            if not assets_path:
                self._send_json({"found": False, "error": "missing project_path"})
                return
            base = _resolve_user_path(assets_path, self._root)
            if not base.is_dir():
                self._send_json({"found": False, "error": f"project_path not a directory: {assets_path}"})
                return
            tried: List[str] = []
            found_path: Optional[Path] = None
            try:
                # Find scene file(s) and check sibling oracle*.json
                scene_files = []
                if scene_name:
                    scene_files = [p for p in base.rglob(f"{scene_name}.unity")]
                if not scene_files:
                    scene_files = list(base.rglob("*.unity"))
                for scene_file in scene_files[:50]:
                    sib_dir = scene_file.parent
                    for pattern in ("oracle_bugs.json", "oracle*.json", "*oracle*.json"):
                        for cand in sib_dir.glob(pattern):
                            tried.append(str(cand))
                            if cand.is_file():
                                found_path = cand
                                break
                        if found_path:
                            break
                    if found_path:
                        break
            except Exception as exc:
                self._send_json({"found": False, "error": str(exc)})
                return
            if found_path is None:
                self._send_json({"found": False,
                                 "error": "No oracle*.json next to any .unity scene file",
                                 "tried": tried[:10]})
                return
            data = _read_json(found_path)
            self._send_json({"found": True, "path": str(found_path), "data": data})
            return

        if path == "/api/benchmark":
            entries = _scan_benchmark_data(self._root)
            self._send_json({"entries": entries})
            return

        # ── Smart benchmark: scan one or more results dirs (comma-separated) ─
        if path == "/api/smart_benchmark":
            dirs_param = (qs.get("results_dirs") or [""])[0].strip()
            work_dir_bm = (qs.get("work_dir") or [""])[0].strip()
            work_dir_root_bm = _resolve_user_path(work_dir_bm, self._root) if work_dir_bm else self._root
            bm_roots: List[Path] = []
            if dirs_param:
                for raw in dirs_param.split(","):
                    raw = raw.strip()
                    if not raw:
                        continue
                    p_bm = _resolve_user_path(raw, self._root) if (Path(raw).is_absolute() or _has_path_token(raw)) else (work_dir_root_bm / raw)
                    try:
                        p_bm = p_bm.resolve()
                    except Exception:
                        pass
                    if p_bm.is_dir() and p_bm not in bm_roots:
                        bm_roots.append(p_bm)
            if not bm_roots:
                bm_roots = [self._root]
            bm_entries: List[Dict[str, Any]] = []
            bm_seen: set = set()
            for r in bm_roots:
                for e in _scan_benchmark_data(r):
                    key = (str(r), e.get("scene", ""), e.get("model", ""))
                    if key in bm_seen:
                        continue
                    bm_seen.add(key)
                    e["_source_root"] = str(r)
                    bm_entries.append(e)
            self._send_json({"entries": bm_entries, "roots": [str(r) for r in bm_roots]})
            return

        # Static assets (anything else under /static/)
        if path.startswith("/static/"):
            asset = path[len("/static/"):]
            # Disallow path escape.
            if ".." in asset or asset.startswith("/"):
                self._not_found("invalid asset path")
                return
            blob = _read_static(asset)
            if blob is None:
                self._not_found(f"asset not found: {asset}")
                return
            ctype = _guess_ctype(asset)
            self._send_bytes(blob, ctype)
            return

        self._not_found(f"no route for {path}")

    # ------------------------------------------------------------------
    # Workflow control: POST endpoints
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        path = url.path
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body: Dict[str, Any] = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
            return

        # ── Project config management ──────────────────────────────────────
        if path == "/api/projects":
            cfg = self.server.projects_config  # type: ignore[attr-defined]
            c = cfg.load()
            action = body.get("action", "add")
            if action == "add":
                project = body.get("project", {})
                name = project.get("name", "").strip()
                if not name:
                    self._send_json({"error": "project.name is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                c["projects"] = [p for p in c.get("projects", []) if p.get("name") != name]
                c["projects"].append(project)
            elif action == "remove":
                name = body.get("name", "")
                c["projects"] = [p for p in c.get("projects", []) if p.get("name") != name]
            elif action == "global":
                for k in ("python_exe", "work_dir", "default_model"):
                    if k in body:
                        c[k] = body[k]
            else:
                self._send_json({"error": f"unknown action: {action}"}, status=HTTPStatus.BAD_REQUEST)
                return
            cfg.save(c)
            self._send_json({"ok": True, "config": c})
            return

        # ── Start a vragent2 run ───────────────────────────────────────────
        if path == "/api/run/start":
            cfg = self.server.projects_config.load()  # type: ignore[attr-defined]
            python_exe = _resolve_python(body.get("python_exe") or cfg.get("python_exe"), self._root)
            work_dir   = _resolve_work_dir(body.get("work_dir") or cfg.get("work_dir"), self._root)

            # Build CLI args
            cmd = [python_exe, "-m", "vragent2"]
            str_flags = [
                ("scene_name",      "--scene_name"),
                ("hierarchy_json",  "--hierarchy_json"),
                ("scene_gml",       "--scene_gml"),
                ("output",          "--output"),
                ("app_name",        "--app_name"),
                ("model",           "--model"),
                ("api_base",        "--api_base"),
                ("scripts_dir",     "--scripts_dir"),
                ("unity_host",      "--unity_host"),
                ("scene_doc",       "--scene_doc"),
            ]
            path_like_flags = {"hierarchy_json", "scene_gml", "output", "scripts_dir", "scene_doc"}
            resolved_params = {k: v for k, v in body.items() if k not in ("api_key",)}
            int_flags = [
                ("budget",          "--budget"),
                ("max_repair",      "--max_repair"),
                ("limit",           "--limit"),
                ("unity_port",      "--unity_port"),
            ]
            for key, flag in str_flags:
                val = body.get(key)
                if val:
                    if key in path_like_flags and _has_path_token(val):
                        val = str(_resolve_user_path(val, self._root))
                        resolved_params[key] = val
                    cmd += [flag, str(val)]
            for key, flag in int_flags:
                val = body.get(key)
                if val is not None and str(val).strip():
                    cmd += [flag, str(val)]
            if body.get("unity"):
                cmd.append("--unity")
            if body.get("resume"):
                cmd.append("--resume")
            if body.get("no_info_sharing"):
                cmd.append("--no_info_sharing")
            replay_val = body.get("replay", "").strip() if isinstance(body.get("replay"), str) else ""
            if replay_val:
                if _has_path_token(replay_val):
                    replay_val = str(_resolve_user_path(replay_val, self._root))
                    resolved_params["replay"] = replay_val
                cmd += ["--replay", replay_val]
            clean_val = body.get("clean", "").strip() if isinstance(body.get("clean"), str) else ""
            if clean_val:
                cmd += ["--clean", clean_val]

            # --clean and --replay both skip LLM calls — no API key needed
            is_no_llm_mode = bool(clean_val) or bool(replay_val)

            env: Optional[Dict[str, str]] = None
            if not is_no_llm_mode:
                api_key = body.get("api_key", "").strip()
                # Fallback: use key saved in .ui_settings.json when field is empty
                if not api_key:
                    api_key = self.server.ui_settings.get_api_key()  # type: ignore[attr-defined]
                if api_key:
                    env = {"OPENAI_API_KEY": api_key}
                else:
                    # No key anywhere — fail fast with a clear message before even launching
                    self._send_json({"error": "No API key. Enter it in the API Key field or click '保存到本地' to save it locally first."}, status=HTTPStatus.BAD_REQUEST)
                    return

            try:
                resolved_params["python_exe"] = python_exe
                resolved_params["work_dir"] = work_dir
                self.server.run_manager.start(cmd, work_dir, resolved_params, env)  # type: ignore[attr-defined]
                self._send_json({"ok": True, "cmd": cmd, "pid": self.server.run_manager._proc.pid})  # type: ignore[attr-defined]
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                self._send_json({"error": f"Failed to start process: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # ── Stop the running process ───────────────────────────────────────
        if path == "/api/run/stop":
            self.server.run_manager.stop()  # type: ignore[attr-defined]
            self._send_json({"ok": True})
            return

        # ── Save / clear local UI settings (API key etc.) ──────────────────
        if path == "/api/ui_settings":
            ui = self.server.ui_settings  # type: ignore[attr-defined]
            settings = ui.load()
            new_key = body.get("api_key", "").strip()
            if new_key:
                settings["api_key"] = new_key
            elif "api_key" in body:
                # Explicit empty string means clear the saved key
                settings.pop("api_key", None)
            ui.save(settings)
            self._send_json({"ok": True, "has_api_key": bool(settings.get("api_key"))})
            return

        # ── Save coverage snapshot from current Unity report to run dir ──────
        if path == "/api/coverage_snapshot":
            assets_path_cs = body.get("assets_path") or body.get("project_path", "")
            snap_run_dir   = (body.get("run_dir") or "").strip()
            model_label    = body.get("model") or (snap_run_dir.replace("\\", "/").split("/")[-1] if snap_run_dir else "")
            unity_root_param_cs = body.get("unity_root", "")

            # Resolve Unity project root
            unity_root_cs: Optional[Path] = None
            if unity_root_param_cs:
                unity_root_cs = _resolve_unity_project_root(unity_root_param_cs, self._root)
            if unity_root_cs is None and assets_path_cs:
                unity_root_cs = _resolve_unity_project_root(str(assets_path_cs), self._root)
            if unity_root_cs is None:
                self._send_json({"error": "Cannot find Unity project root. Provide assets_path."},
                                status=HTTPStatus.BAD_REQUEST)
                return

            # Parse the live coverage report
            cov_cs = _parse_coverage_report_dir(unity_root_cs / "CodeCoverage" / "Report")
            if not cov_cs.get("found"):
                self._send_json({"error": "No coverage report found. Run Window > Analysis > Code Coverage in Unity Editor first."},
                                status=HTTPStatus.NOT_FOUND)
                return

            # Strip local filesystem paths before saving, add snapshot metadata
            from datetime import datetime as _dt
            snap_ts_str = _dt.utcnow().strftime("%Y%m%dT%H%M%SZ")
            cov_cs.pop("index_htm_path", None)
            cov_cs.pop("report_dir", None)
            cov_cs["snapshot_model"] = model_label
            cov_cs["snapshot_time"]  = _dt.utcnow().isoformat() + "Z"
            cov_cs["snapshot_ts"]    = snap_ts_str

            # Save to run dir (run-binding quick snapshot)
            save_base = self._root / snap_run_dir.replace("\\", "/") if snap_run_dir else self._root
            save_path_cs = save_base / "coverage_snapshot.json"
            try:
                save_path_cs.parent.mkdir(parents=True, exist_ok=True)
                save_path_cs.write_text(json.dumps(cov_cs, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            # Copy full report directory to timestamped archive
            report_dir_src = unity_root_cs / "CodeCoverage" / "Report"
            # fallback search for report dir if default path not found
            if not report_dir_src.is_dir():
                for _cand_rd in (unity_root_cs / "CodeCoverage", unity_root_cs / "Coverage" / "Report"):
                    if _cand_rd.is_dir() and any(_cand_rd.glob("Summary.json")):
                        report_dir_src = _cand_rd
                        break
            snap_archive_dir = save_base / "coverage_snapshots" / snap_ts_str
            archive_ok = False
            archive_err = ""
            if report_dir_src.is_dir():
                try:
                    snap_archive_dir.mkdir(parents=True, exist_ok=True)
                    for _item in report_dir_src.iterdir():
                        if _item.is_file():
                            shutil.copy2(str(_item), str(snap_archive_dir / _item.name))
                        elif _item.is_dir():
                            shutil.copytree(str(_item), str(snap_archive_dir / _item.name))
                    # Save meta.json alongside
                    (snap_archive_dir / "meta.json").write_text(
                        json.dumps(cov_cs, ensure_ascii=False, indent=2), encoding="utf-8")
                    archive_ok = True
                except Exception as _exc_ar:
                    archive_err = str(_exc_ar)
            self._send_json({"ok": True, "saved_to": str(save_path_cs),
                             "model": model_label,
                             "line_coverage": cov_cs.get("line_coverage", 0),
                             "archive_ok": archive_ok,
                             "archive_dir": str(snap_archive_dir) if archive_ok else "",
                             "archive_error": archive_err})
            return

        # ── Load a local JSON file by absolute path ────────────────────────
        if path == "/api/load_local_json":
            file_path = body.get("file_path", "").strip()
            if not file_path:
                self._send_json({"error": "file_path is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                p = Path(file_path).resolve()
                if not p.exists() or not p.is_file():
                    self._send_json({"error": f"File not found: {file_path}"}, status=HTTPStatus.NOT_FOUND)
                    return
                if p.suffix.lower() not in (".json",):
                    self._send_json({"error": "Only .json files are supported"}, status=HTTPStatus.BAD_REQUEST)
                    return
                data = json.loads(p.read_text(encoding="utf-8"))
                self._send_json({"ok": True, "data": data, "path": str(p)})
            except json.JSONDecodeError as exc:
                self._send_json({"error": f"Invalid JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/mkdir":
            dir_path = body.get("path", "").strip()
            if not dir_path:
                self._send_json({"error": "path is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            # Security: reject any path traversal attempt
            try:
                target = Path(dir_path).resolve()
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                target.mkdir(parents=True, exist_ok=True)
                self._send_json({"ok": True, "path": str(target)})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # ── Start a preprocessing step ─────────────────────────────────────
        if path == "/api/preprocess/start":
            cfg = self.server.projects_config.load()  # type: ignore[attr-defined]
            python_exe = _resolve_python(body.get("python_exe") or cfg.get("python_exe"), self._root)
            # Preprocessing scripts always run from the TP_Generation directory (results_root)
            preprocess_cwd = str(self.server.results_root)  # type: ignore[attr-defined]
            step        = body.get("step", "").strip()
            results_dir = body.get("results_dir", "").strip()
            if _has_path_token(results_dir):
                results_dir = str(_resolve_user_path(results_dir, self._root))
            params = {k: v for k, v in body.items()}
            params["python_exe"] = python_exe
            params["work_dir"] = preprocess_cwd
            params["results_dir"] = results_dir
            if step == "extract_scene":
                project_path = body.get("project_path", "").strip()
                if not project_path:
                    self._send_json({"error": "project_path required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if not results_dir:
                    self._send_json({"error": "results_dir required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                project_path = str(_resolve_user_path(project_path, self._root))
                params["project_path"] = project_path
                cmd = [python_exe, "ExtractSceneDependency.py", "-p", project_path, "-r", results_dir]
                scene_name = body.get("scene_name", "").strip()
                if scene_name:
                    cmd += ["-s", scene_name]
            elif step == "traverse_hierarchy":
                if not results_dir:
                    self._send_json({"error": "results_dir required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                cmd = [python_exe, "TraverseSceneHierarchy.py", "-r", results_dir]
            elif step == "special_logic":
                if not results_dir:
                    self._send_json({"error": "results_dir required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                cmd = [python_exe, "SpecialLogicPreprocessor.py", "-r", results_dir]
                app_name = body.get("app_name", "").strip()
                if app_name:
                    cmd += ["-a", app_name]
            else:
                self._send_json({"error": f"unknown step: {step!r}"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self.server.run_manager.start(cmd, preprocess_cwd, params, None)  # type: ignore[attr-defined]
                self._send_json({"ok": True, "cmd": cmd, "pid": self.server.run_manager._proc.pid})  # type: ignore[attr-defined]
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                self._send_json({"error": f"Failed to start process: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # ── File write (Results/ only, .json/.md/.txt) ────────────────────
        if path == "/api/file":
            rel     = body.get("path", "")
            content = body.get("content", "")
            err = _write_file_safe(self._root, rel, content)
            if err:
                self._send_json({"error": err}, status=HTTPStatus.BAD_REQUEST)
            else:
                self._send_json({"ok": True})
            return

        self._not_found(f"no POST route for {path}")


def _safe_int(s: str, *, default: int, lo: int, hi: int) -> int:
    try:
        v = int(s)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _guess_ctype(name: str) -> str:
    n = name.lower()
    if n.endswith(".html"):
        return "text/html; charset=utf-8"
    if n.endswith(".css"):
        return "text/css; charset=utf-8"
    if n.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if n.endswith(".json"):
        return "application/json; charset=utf-8"
    if n.endswith(".svg"):
        return "image/svg+xml"
    if n.endswith(".png"):
        return "image/png"
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(*, host: str, port: int, results_dir: str,
          auto_open: bool = False) -> None:
    """Run the Jelly server until interrupted."""
    root = Path(results_dir).expanduser().resolve()
    server = _ThreadingHTTPServer((host, port), _JellyHandler)
    server.results_root = root          # type: ignore[attr-defined]
    server.run_manager = _RunManager()  # type: ignore[attr-defined]
    server.projects_config = _ProjectsConfig(root)  # type: ignore[attr-defined]
    server.ui_settings = _UiSettingsConfig(root)    # type: ignore[attr-defined]
    server.coverage_report_dir = None   # type: ignore[attr-defined]  # cached from last successful coverage parse
    server.active_snap_dir = None       # type: ignore[attr-defined]  # cached from last snapshot HTML request

    url = f"http://{host}:{port}/"
    print(f"[jelly] serving XRPlayer dashboard on {url}")
    print(f"[jelly] watching results dir: {root}")

    if auto_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# Fallback HTML (used only if static/index.html is missing)
# ---------------------------------------------------------------------------

_FALLBACK_HTML = """<!doctype html>
<html><head><meta charset='utf-8'><title>Jelly</title></head>
<body style='font-family:sans-serif'>
<h1>Jelly is running.</h1>
<p>The bundled dashboard (<code>static/index.html</code>) was not found.
Use the JSON endpoints directly:</p>
<ul>
  <li><a href='/api/health'>/api/health</a></li>
  <li><a href='/api/runs'>/api/runs</a></li>
  <li><a href='/api/status'>/api/status</a></li>
  <li><a href='/api/agent_trace?limit=50'>/api/agent_trace</a></li>
  <li><a href='/api/coverage'>/api/coverage</a></li>
  <li><a href='/api/gate_graph'>/api/gate_graph</a></li>
  <li><a href='/api/scene_understanding'>/api/scene_understanding</a></li>
</ul>
</body></html>
"""
