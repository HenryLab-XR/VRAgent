"""Analyze ___gpt-5.2 execution logs using segment-level verdicts.

Usage: python analyze_execution_rates.py
Outputs execution_rates.json and execution_rates.csv beside this script.
"""
from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "___gpt-5.2"
RESULTS_DIR = ROOT / "Results"
HEADER = re.compile(r"\[Task\s+(\d+)\]\[Action\s+(\d+)\]\s+Type:\s*(Grab|Trigger|Transform|Move)\b")
NAVMESH_FAILURE = re.compile(
    r"Destination\s*\([^)]*\)\s*(?:is\s+)?not\s+on\s+(?:the\s+)?NavMesh"
    r"|failure_type\s*=\s*spatial_reachability", re.I)


def plain(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def verdict(segment: str, kind: str) -> str:
    low = segment.lower()
    if re.search(rf"Skip\s+{kind}\s+action\s+due\s+to\s+semantic\s+mismatch", segment, re.I):
        return "skipped_semantic"
    if kind == "Move":
        if NAVMESH_FAILURE.search(segment):
            return "failed_reachability"
        return "success" if "Action: MoveAction" in segment else "partial"
    action = f"Action: {kind}Action"
    if kind == "Grab":
        if action not in segment:
            return "skipped_syntax" if "Skip" in segment else "partial"
        if re.search(r"Exception", segment, re.I):
            if NAVMESH_FAILURE.search(segment):
                return "failed_reachability"
            return "partial" if "State Grabbed" in segment else "failed_execution"
        return "success" if "State Grabbed" in segment else "failed_execution"
    if action not in segment:
        return "skipped_syntax" if "Skip" in segment else "partial"
    started = "Triggerring" in segment
    finished = re.search(r"State\s+Triggerred\b", segment) is not None
    if started and finished:
        # Only exceptions before completion invalidate the segment.
        before_finish = re.split(r"State\s+Triggerred\b", segment, maxsplit=1)[0]
        if re.search(r"Exception", before_finish, re.I):
            return "failed_reachability" if NAVMESH_FAILURE.search(before_finish) else "partial"
        return "success"
    if NAVMESH_FAILURE.search(segment):
        return "failed_reachability"
    if re.search(r"Exception", segment, re.I):
        return "failed_execution"
    return "failed_execution" if started or action in segment else "skipped_syntax"


def analyze(path: Path) -> list[dict]:
    text = plain(path.read_text(encoding="utf-8", errors="replace"))
    matches = list(HEADER.finditer(text))
    rows = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[match.start():end]
        kind = match.group(3)
        rows.append({"task": int(match.group(1)), "action": int(match.group(2)),
                     "type": kind, "verdict": verdict(segment, kind)})
    return rows


def plan_action_count(project: str) -> int | None:
    """Count planned actionUnits for this project from GPT-5.2 plans."""
    key = re.sub(r"[^a-z0-9]", "", project.lower())
    counts = []
    for path in RESULTS_DIR.rglob("*_consolidated_test_plans.json"):
        parts = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in path.parts]
        if "gpt52" not in parts:
            continue
        project_parts = [p for p in parts if p.startswith("results")]
        if not project_parts:
            continue
        project_key = project_parts[-1].replace("results", "")
        if key not in project_key and project_key not in key:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            counts.append(sum(len(unit.get("actionUnits", []))
                              for unit in data.get("taskUnits", [])))
        except (OSError, json.JSONDecodeError):
            continue
    return sum(counts) if counts else None


def main() -> None:
    projects = []
    for path in sorted(LOG_DIR.glob("*.html")):
        rows = analyze(path)
        counts = {label: sum(r["verdict"] == label for r in rows)
                  for label in ["success", "partial", "skipped_semantic", "skipped_syntax",
                                "failed_execution", "failed_reachability"]}
        executable = len(rows) - counts["skipped_semantic"] - counts["skipped_syntax"]
        observed_segments = len(rows)
        projects.append({"project": path.stem, "observed_segments": observed_segments,
                         "executable_segments": executable, **counts,
                         "dispatched_rate_percent": round(100 * executable / observed_segments, 2)
                         if observed_segments else None,
                         "execution_rate_percent": round(100 * (counts["success"] + counts["partial"]) / executable, 2)
                         if executable else None})
    measurable = [p for p in projects if p["executable_segments"]]
    total_exec = sum(p["executable_segments"] for p in measurable)
    total_success = sum(p["success"] + p["partial"] for p in measurable)
    summary = {"projects": projects,
               "macro_average_percent": round(sum(p["execution_rate_percent"] for p in measurable) / len(measurable), 2),
               "micro_average_percent": round(100 * total_success / total_exec, 2),
               "total_executable_segments": total_exec, "total_success": total_success}
    (ROOT / "execution_rates.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    fields = list(projects[0])
    with (ROOT / "execution_rates.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(projects)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
