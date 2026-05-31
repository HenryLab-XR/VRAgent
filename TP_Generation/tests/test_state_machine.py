"""v2.2 verifier symbolic state-machine tests.

Tests run against the ``_simulate_state_machine`` method directly (no
RetrievalLayer needed). Three cases:
  1. gold-manual-kitchen-v2 -> no violations, full state trace
  2. drop depends_on_task_index but keep required_state_changes -> MISSING_DECLARED_DEP
  3. drop the prerequisite-producing task -> MISSING_PRECONDITION
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

# Make TP_Generation importable when run as `python tests/test_state_machine.py`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vragent2.agents.verifier import VerifierAgent
from vragent2.contracts import VerifierErrorType


def _verifier_no_retrieval() -> VerifierAgent:
    """Build a VerifierAgent shell that only uses the state machine method."""
    # We don't call retrieval-backed methods; bypass __init__ to avoid graph load.
    agent = VerifierAgent.__new__(VerifierAgent)
    return agent


GOLD_PATH = ROOT / "Results" / "Kitchen_TestRoom" / "gold-manual-kitchen-v2" / "test_plan.json"


def test_gold_passes():
    plan = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    agent = _verifier_no_retrieval()
    errors, violations, trace = agent._simulate_state_machine(plan["taskUnits"])
    assert not errors, f"gold should have no state-machine errors, got: {errors}"
    assert not violations, f"gold should have no dependency violations, got: {violations}"
    assert len(trace) == 3
    final_state = trace[-1]["world_state"]
    assert final_state.get("DoorNode_A_Lobby.isOpen") == "true"
    assert final_state.get("Key_Pantry.inHand") == "true"
    assert final_state.get("DoorNode_B_Pantry.isOpen") == "true"
    print("[PASS] gold_passes — final state:", final_state)


def test_missing_declared_dep():
    plan = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    # Strip depends_on_task_index from task 1 (still references state from task 0)
    plan["taskUnits"][1]["actionUnits"][0]["depends_on_task_index"] = []
    agent = _verifier_no_retrieval()
    errors, violations, _ = agent._simulate_state_machine(plan["taskUnits"])
    types = {e.type for e in errors}
    assert VerifierErrorType.MISSING_DECLARED_DEP.value in types, f"expected MISSING_DECLARED_DEP, got: {types}"
    assert any(v.get("reason") == "undeclared_dependency" for v in violations)
    print("[PASS] missing_declared_dep — errors:", types)


def test_missing_precondition():
    plan = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    # Remove task 0 entirely; task 1 should now lack its required state
    plan["taskUnits"] = plan["taskUnits"][1:]
    # Rewrite task 1's (now task 0) depends_on so dep-index sanity passes
    plan["taskUnits"][0]["actionUnits"][0]["depends_on_task_index"] = []
    # Task that was 2 (now 1) still references task 1 (now 0) — keep deps[0]
    plan["taskUnits"][1]["actionUnits"][0]["depends_on_task_index"] = [0]
    agent = _verifier_no_retrieval()
    errors, violations, _ = agent._simulate_state_machine(plan["taskUnits"])
    types = {e.type for e in errors}
    assert VerifierErrorType.MISSING_PRECONDITION.value in types, f"expected MISSING_PRECONDITION, got: {types}"
    assert any(v.get("reason") == "key_never_produced" for v in violations)
    print("[PASS] missing_precondition — errors:", types)


if __name__ == "__main__":
    test_gold_passes()
    test_missing_declared_dep()
    test_missing_precondition()
    print("\nAll 3 state-machine tests passed.")
