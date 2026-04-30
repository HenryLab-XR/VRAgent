"""
Executor Agent — Deterministic execution + trace recording.

This agent does NOT participate in generation — it only executes a verified
action sequence and records the resulting trace.

Supports two modes:
    1. **Online** (UnityBridge connected) — sends actions via TCP to Unity,
       receives real state_before/state_after/events/exceptions.
    2. **Offline / dry-run** — logs actions to disk for manual import.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .base_agent import BaseAgent
from ..contracts import ExecutorOutput, TraceEntry, CoverageDelta
from ..utils.file_utils import save_json, load_json


class ExecutorAgent(BaseAgent):
    """Agent 3 — Executes verified actions and records traces."""

    name = "ExecutorAgent"

    def __init__(self, output_dir: str = "", unity_bridge=None):
        """
        Parameters
        ----------
        output_dir : str
            Directory for trace persistence.
        unity_bridge : UnityBridge or None
            If provided, actions are executed in Unity via TCP.
            If None, falls back to dry-run / file-based mode.
        """
        self.output_dir = output_dir
        self.bridge = unity_bridge  # vragent2.bridge.UnityBridge
        self._trace: List[TraceEntry] = []
        self._exceptions: List[str] = []
        self._log_cursor: int = 0  # for incremental log queries
        self._seen_action_keys: set[str] = set()
        self._seen_event_keys: set[str] = set()
        self._seen_method_keys: set[Tuple[str, str]] = set()
        self._seen_changed_objects: set[str] = set()

    # ------------------------------------------------------------------
    # Contract entry point
    # ------------------------------------------------------------------

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parameters
        ----------
        input_data : dict
            Required keys:
                actions – list of verified action-unit dicts

        Returns
        -------
        dict matching ExecutorOutput schema.
        """
        actions: List[Dict] = input_data.get("actions", [])
        self._trace.clear()
        self._exceptions.clear()

        for action in actions:
            entry = self._execute_single(action)
            self._trace.append(entry)

        output = ExecutorOutput(
            trace=self._trace,
            coverage_delta=self._compute_coverage(actions),
            exceptions=self._exceptions,
        )

        # Persist trace to disk
        if self.output_dir:
            self._save_trace()

        return output.to_dict()

    # ------------------------------------------------------------------
    # Execution — routes to online (TCP) or offline (file) mode
    # ------------------------------------------------------------------

    def _execute_single(self, action: Dict[str, Any]) -> TraceEntry:
        """Execute one action unit."""
        action_type = action.get("type", "Unknown")
        source_name = action.get("source_object_name") or str(action.get("source_object_fileID", ""))

        # ── Online mode: real Unity execution ────────────────────────
        if self.bridge is not None and self.bridge.connected:
            return self._execute_via_bridge(action, action_type, source_name)

        # ── Offline / dry-run mode ───────────────────────────────────
        return self._execute_offline(action, action_type, source_name)

    def _execute_via_bridge(self, action: Dict, action_type: str, source_name: str) -> TraceEntry:
        """Send action to Unity via TCP and parse the response."""
        entry = TraceEntry(
            action=f"{action_type}:{source_name}",
            state_before={},
            state_after={},
            events=[],
            success=False,
        )
        try:
            prewarm_plan = {
                "taskUnits": [
                    {
                        "actionUnits": [action]
                    }
                ]
            }
            import_result = self.bridge.import_objects(prewarm_plan, use_file_id=True)
            if not import_result.get("success", False):
                error_msg = import_result.get("error_message", "ImportObjects failed")
                self._exceptions.append(f"{action_type}:{source_name} → import_failed:{error_msg}")
                entry.events.append(f"import_error:{error_msg}")
                print(f"[EXECUTOR] IMPORT FAILED: {action_type} on {source_name} — {error_msg}")
                return entry

            result = self.bridge.execute(action)

            if result.get("success", False):
                entry.state_before = result.get("state_before", {}) or {}
                entry.state_after = result.get("state_after", {}) or {}
                entry.events = result.get("events", [])
                entry.success = True
                entry.duration_ms = float(result.get("duration_ms", 0) or 0)
                duration = result.get("duration_ms", 0)
                print(f"[EXECUTOR] {action_type} on {source_name} — {duration:.0f}ms")
            else:
                error_msg = result.get("error_message", "Unknown error")
                self._exceptions.append(f"{action_type}:{source_name} → {error_msg}")
                entry.events.append(f"error:{error_msg}")
                print(f"[EXECUTOR] FAILED: {action_type} on {source_name} — {error_msg}")

            # Collect any exceptions reported by Unity
            for exc in result.get("exceptions", []):
                self._exceptions.append(f"{action_type}:{source_name} → {exc}")
                entry.events.append(f"exception:{exc}")
                entry.success = False

        except Exception as exc:
            self._exceptions.append(f"{action_type}:{source_name} → {exc}")
            entry.events.append(f"bridge_error:{exc}")
            print(f"[EXECUTOR] Bridge exception: {exc}")

        return entry

    def _execute_offline(self, action: Dict, action_type: str, source_name: str) -> TraceEntry:
        """Dry-run / file-based fallback."""
        entry = TraceEntry(
            action=f"{action_type}:{source_name}",
            state_before={},
            state_after={},
            events=[],
            success=False,
        )
        try:
            if self.output_dir:
                cmd_path = os.path.join(self.output_dir, "pending_command.json")
                save_json(cmd_path, action)
                print(f"[EXECUTOR] Dispatched: {action_type} on {source_name}")
                entry.events.append(f"dispatched:{action_type}")
                entry.success = True

                result_path = os.path.join(self.output_dir, "command_result.json")
                if os.path.exists(result_path):
                    result = load_json(result_path)
                    entry.state_after = result.get("state_after", {})
                    entry.events.extend(result.get("events", []))
                    entry.success = bool(result.get("success", entry.success))
                    os.remove(result_path)
            else:
                print(f"[EXECUTOR] (dry-run) {action_type} on {source_name}")
        except Exception as exc:
            self._exceptions.append(f"{action_type}:{source_name} → {exc}")
            print(f"[EXECUTOR] Exception: {exc}")

        return entry

    # ------------------------------------------------------------------
    # Unity Console Logs (online only)
    # ------------------------------------------------------------------

    def get_console_logs(self) -> List[str]:
        """Fetch new console logs from Unity since last call."""
        if self.bridge is None or not self.bridge.connected:
            return []
        try:
            result = self.bridge.query_logs(since_index=self._log_cursor)
            self._log_cursor = result.get("next_index", self._log_cursor)
            return [
                f"[{log.get('level', 'Log')}] {log.get('message', '')}"
                for log in result.get("logs", [])
            ]
        except Exception as exc:
            print(f"[EXECUTOR] Failed to query logs: {exc}")
            return []

    # ------------------------------------------------------------------
    # Coverage / novelty computation
    # ------------------------------------------------------------------

    def _compute_coverage(self, actions: List[Dict[str, Any]]) -> CoverageDelta:
        """Compute a runtime novelty proxy for closed-loop planning.

        Unity CodeCoverage still gets parsed at benchmark/final-report time.
        During online exploration, the controller needs immediate feedback, so
        we use deterministic runtime signals: new successful action patterns,
        newly fired events/methods, and newly changed game objects.
        """
        new_action_count = 0
        new_event_count = 0
        new_method_count = 0
        new_changed_object_count = 0

        for action, trace_entry in zip(actions, self._trace):
            if not self._trace_action_succeeded(trace_entry):
                continue

            action_key = self._action_key(action)
            if action_key not in self._seen_action_keys:
                self._seen_action_keys.add(action_key)
                new_action_count += 1

            for event_key in self._event_keys(trace_entry):
                if event_key not in self._seen_event_keys:
                    self._seen_event_keys.add(event_key)
                    new_event_count += 1

            for method_key in self._method_keys(action):
                if method_key not in self._seen_method_keys:
                    self._seen_method_keys.add(method_key)
                    new_method_count += 1

            if self._state_changed_meaningfully(trace_entry):
                object_key = self._object_key(trace_entry, action)
                if object_key and object_key not in self._seen_changed_objects:
                    self._seen_changed_objects.add(object_key)
                    new_changed_object_count += 1

        lc_delta = min(1.0, 0.01 * new_action_count + 0.004 * new_event_count)
        mc_delta = min(1.0, 0.02 * new_method_count)
        coigo_delta = min(1.0, 0.03 * new_changed_object_count)
        return CoverageDelta(
            LC=round(lc_delta, 4),
            MC=round(mc_delta, 4),
            CoIGO=round(coigo_delta, 4),
        )

    @staticmethod
    def _trace_action_succeeded(trace_entry: TraceEntry) -> bool:
        events = trace_entry.events or []
        joined = " ".join(str(event) for event in events).lower()
        if any(token in joined for token in ("error:", "exception:", "bridge_error:", "import_error:")):
            return False
        return bool(trace_entry.success) or any(
            str(event).startswith(("completed:", "fallback_completed:", "direct_trigger:", "dispatched:"))
            for event in events
        )

    @staticmethod
    def _state_changed_meaningfully(trace_entry: TraceEntry) -> bool:
        before = trace_entry.state_before or {}
        after = trace_entry.state_after or {}
        if not before or not after or before == after:
            return False
        return any(before.get(field) != after.get(field) for field in ("position", "rotation", "active", "scale"))

    @staticmethod
    def _action_key(action: Dict[str, Any]) -> str:
        return json.dumps(
            {
                "type": action.get("type", ""),
                "source": action.get("source_object_fileID", ""),
                "target": action.get("target_object_fileID", ""),
                "condition": action.get("condition", ""),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    @staticmethod
    def _event_keys(trace_entry: TraceEntry) -> Iterable[str]:
        action_prefix = trace_entry.action or "unknown"
        for event in trace_entry.events or []:
            event_text = str(event)
            if event_text.startswith(("execute:", "component_added:", "xrbase_initialized:")):
                continue
            yield f"{action_prefix}|{event_text}"

    @staticmethod
    def _method_keys(action: Dict[str, Any]) -> Iterable[Tuple[str, str]]:
        for event_key in ("triggerring_events", "triggerred_events"):
            for event_unit in action.get(event_key, []) or []:
                for method_call in event_unit.get("methodCallUnits", []) or []:
                    script_id = str(method_call.get("script_fileID", ""))
                    method_name = str(method_call.get("method_name", ""))
                    if script_id or method_name:
                        yield (script_id, method_name)

    @staticmethod
    def _object_key(trace_entry: TraceEntry, action: Dict[str, Any]) -> str:
        after = trace_entry.state_after or {}
        return str(
            after.get("fileid")
            or after.get("fileId")
            or action.get("source_object_fileID", "")
            or after.get("name", "")
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_trace(self) -> None:
        path = os.path.join(self.output_dir, f"trace_{datetime.now():%Y%m%d_%H%M%S}.json")
        from dataclasses import asdict
        save_json(path, [asdict(t) for t in self._trace])
        print(f"[EXECUTOR] Trace saved: {path}")
