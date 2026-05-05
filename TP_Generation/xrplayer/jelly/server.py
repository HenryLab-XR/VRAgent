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
import subprocess
import sys
import time
import threading
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit


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
            self._state = "running"
            self._start_time = time.time()
            self._returncode = None
            self._params = params
            self._env = env
        proc_env = os.environ.copy()
        # Force unbuffered output so log lines appear even if process exits immediately
        proc_env["PYTHONUNBUFFERED"] = "1"
        if env:
            proc_env.update(env)
        # On Windows, prevent subprocess from opening a console window
        _extra: Dict[str, Any] = {}
        if sys.platform == "win32":
            _extra["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            cmd, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            env=proc_env, **_extra,
        )
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
        self._lock = threading.Lock()

    def load(self) -> Dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            # Merge with defaults so new keys are always present
            merged = dict(self._DEFAULT)
            merged.update(data)
            return merged
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


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------

def _find_scenes(project_path: str, max_results: int = 200) -> List[Dict[str, Any]]:
    """Discover .unity scene files inside a Unity project directory."""
    base = Path(project_path)
    if not base.is_dir():
        return []
    scenes: List[Dict[str, Any]] = []
    try:
        for p in base.rglob("*.unity"):
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


def _scan_benchmark_data(root: Path) -> List[Dict[str, Any]]:
    """Scan results root for all <scene>/<model>/summary.json entries."""
    entries: List[Dict[str, Any]] = []
    if not root.is_dir():
        return entries
    try:
        for scene_dir in sorted(root.iterdir()):
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
                entries.append({
                    "scene": scene_dir.name,
                    "model": model_dir.name,
                    "run_dir": f"{scene_dir.name}/{model_dir.name}",
                    "summary": summary,
                    "oracle": oracle,
                    "status": status,
                })
    except Exception:
        pass
    return entries


def _normalize_preprocess_dir(path_value: str) -> Optional[Path]:
    if not path_value:
        return None
    try:
        return Path(path_value).resolve()
    except OSError:
        return None


def _infer_scene_name_from_dir(results_dir: Optional[Path]) -> str:
    if results_dir is None or not results_dir.is_dir():
        return ""

    scene_meta_dir = results_dir / "scene_detailed_info" / "mainResults"
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
    for path in sorted(results_dir.glob(f"*{hierarchy_suffix}")):
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
        scene_meta_dir = step1_dir / "scene_detailed_info" / "mainResults"
        graph_path = scene_meta_dir / f"{scene_name}.unity.json_graph.gml"
        database_path = scene_meta_dir / f"{scene_name}.unity.json_database.json"
        scene_json_path = scene_meta_dir / f"{scene_name}.unity.json"

    hierarchy_path2 = (step2_dir / f"{scene_name}_gobj_hierarchy.json") if step2_dir is not None and scene_name else None
    hierarchy_path3 = (step3_dir / f"{scene_name}_gobj_hierarchy.json") if step3_dir is not None and scene_name else None

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

        if path == "/api/health":
            self._send_json({"ok": True, "results_root": str(self._root)})
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
            self._send_json({"scenes": _find_scenes(project_path)})
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
            })
            return

        if path == "/api/preprocess/status":
            shared_dir = (qs.get("results_dir") or [""])[0].strip()
            dir1 = (qs.get("results_dir1") or [shared_dir])[0].strip()
            dir2 = (qs.get("results_dir2") or [shared_dir or dir1])[0].strip()
            dir3 = (qs.get("results_dir3") or [shared_dir or dir2 or dir1])[0].strip()
            scene_name = (qs.get("scene_name") or [""])[0].strip()
            self._send_json(_build_preprocess_status(
                _normalize_preprocess_dir(dir1),
                _normalize_preprocess_dir(dir2),
                _normalize_preprocess_dir(dir3),
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
            p = Path(search_path).resolve()
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
                    bp = Path(browse_path)
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
            roots: List[Path] = []
            if dirs_param:
                for raw in dirs_param.split(","):
                    raw = raw.strip()
                    if not raw:
                        continue
                    p_dir = Path(raw)
                    if not p_dir.is_absolute() and work_dir_param:
                        p_dir = Path(work_dir_param) / raw
                    elif not p_dir.is_absolute():
                        p_dir = self._root / raw
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
                xml_path = Path(xml_param)
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
            # Accept either assets_path (will walk up to find Unity root) or direct unity_root
            assets_path = (qs.get("project_path") or qs.get("assets_path") or [""])[0].strip()
            unity_root_param = (qs.get("unity_root") or [""])[0].strip()
            xml_path2: Optional[Path] = None
            tried: List[str] = []
            # Determine Unity project root
            unity_root: Optional[Path] = None
            if unity_root_param:
                pr = Path(unity_root_param)
                if (pr / "Assets").is_dir() and (pr / "ProjectSettings").is_dir():
                    unity_root = pr
            if unity_root is None and assets_path:
                p = Path(assets_path).resolve()
                for _ in range(12):
                    if (p / "Assets").is_dir() and (p / "ProjectSettings").is_dir():
                        unity_root = p
                        break
                    nxt = p.parent
                    if nxt == p:
                        break
                    p = nxt
            if unity_root is not None:
                # Unity CodeCoverage folder is directly under project root
                for sub in (
                    unity_root / "CodeCoverage" / "Report" / "Summary.xml",
                    unity_root / "CodeCoverage" / "Summary.xml",
                    unity_root / "Coverage" / "Report" / "Summary.xml",
                ):
                    tried.append(str(sub))
                    if sub.exists():
                        xml_path2 = sub
                        break
            if xml_path2 is None:
                self._send_json({"found": False,
                                 "error": "Coverage Summary.xml not found. Run Window > Analysis > Code Coverage in Unity Editor first.",
                                 "tried": tried[:6],
                                 "unity_root": str(unity_root) if unity_root else ""})
                return
            data = _parse_unity_coverage_xml(xml_path2)
            data["xml_path"] = str(xml_path2)
            self._send_json(data)
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

        # ── Smart oracle: locate scene file under project, look for oracle*.json next to it ─
        if path == "/api/smart_oracle":
            assets_path = (qs.get("project_path") or qs.get("assets_path") or [""])[0].strip()
            scene_name = (qs.get("scene_name") or [""])[0].strip()
            if not assets_path:
                self._send_json({"found": False, "error": "missing project_path"})
                return
            base = Path(assets_path)
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
            bm_roots: List[Path] = []
            if dirs_param:
                for raw in dirs_param.split(","):
                    raw = raw.strip()
                    if not raw:
                        continue
                    p_bm = Path(raw)
                    if not p_bm.is_absolute():
                        if work_dir_bm:
                            p_bm = Path(work_dir_bm) / raw
                        else:
                            p_bm = self._root / raw
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
            python_exe = body.get("python_exe") or cfg.get("python_exe") or sys.executable
            work_dir   = body.get("work_dir")   or cfg.get("work_dir")   or str(self.server.results_root)  # type: ignore[attr-defined]

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
            int_flags = [
                ("budget",          "--budget"),
                ("max_repair",      "--max_repair"),
                ("limit",           "--limit"),
                ("unity_port",      "--unity_port"),
            ]
            for key, flag in str_flags:
                val = body.get(key)
                if val:
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

            params = {k: v for k, v in body.items() if k not in ("api_key",)}
            try:
                self.server.run_manager.start(cmd, work_dir, params, env)  # type: ignore[attr-defined]
                self._send_json({"ok": True, "cmd": cmd, "pid": self.server.run_manager._proc.pid})  # type: ignore[attr-defined]
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
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
            python_exe = body.get("python_exe") or cfg.get("python_exe") or sys.executable
            # Preprocessing scripts always run from the TP_Generation directory (results_root)
            preprocess_cwd = str(self.server.results_root)  # type: ignore[attr-defined]
            work_dir = preprocess_cwd  # alias for clarity
            step        = body.get("step", "").strip()
            results_dir = body.get("results_dir", "").strip()
            if step == "extract_scene":
                project_path = body.get("project_path", "").strip()
                if not project_path:
                    self._send_json({"error": "project_path required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if not results_dir:
                    self._send_json({"error": "results_dir required"}, status=HTTPStatus.BAD_REQUEST)
                    return
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
            params = {k: v for k, v in body.items()}
            try:
                self.server.run_manager.start(cmd, preprocess_cwd, params, None)  # type: ignore[attr-defined]
                self._send_json({"ok": True, "cmd": cmd, "pid": self.server.run_manager._proc.pid})  # type: ignore[attr-defined]
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
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
