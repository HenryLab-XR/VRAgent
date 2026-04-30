"""
Object Scheduler — Dynamic "think-then-select" object ordering.

Replaces the fixed ``for gobj in gobj_list`` loop with an LLM-driven
scheduler that considers scene understanding, runtime coverage, failure
history, and gate constraints to decide **which object to test next**.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..contracts import SchedulerDecision, SceneUnderstandingOutput

if TYPE_CHECKING:
    from ..utils.llm_client import LLMClient
    from ..utils.config_loader import AgentLLMConfig


_SYSTEM = """\
You are the object scheduler for an automated VR testing system.
Given the current testing state, choose the SINGLE best object to test next.

Consider:
1. Scene priority ranking (from scene understanding)
2. Objects NOT yet processed
3. Gate dependencies — if object A requires B to be solved first, prefer B
4. Recent failures — avoid objects that repeatedly fail without new context
5. Coverage — prefer objects likely to increase coverage

Return a JSON object:
{
  "object_name": "<name of the chosen object>",
  "reason": "<brief explanation>",
  "priority_score": <0.0-1.0>,
  "skip_list": ["<objects deliberately skipped this round>"]
}

Return ONLY valid JSON.
"""


class ObjectScheduler:
    """LLM-driven dynamic object selector."""

    def __init__(
        self,
        *,
        llm: "LLMClient",
        llm_config: Optional["AgentLLMConfig"] = None,
        default_model: str = "gpt-4o",
    ):
        self.llm = llm
        self.llm_config = llm_config
        self._default_model = default_model
        self._history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_next(
        self,
        candidates: List[Dict[str, Any]],
        *,
        processed: set[str],
        scene_understanding: Optional[SceneUnderstandingOutput] = None,
        gate_hints: Optional[List[Dict]] = None,
        recent_failures: Optional[List[str]] = None,
        coverage_state: Optional[Dict[str, float]] = None,
        scheduler_bias: Optional[List[str]] = None,
        failure_counts: Optional[Dict[str, int]] = None,
        max_revisits: int = 2,
    ) -> Optional[SchedulerDecision]:
        """Pick the next object to process.

        Parameters
        ----------
        candidates : list[dict]
            Full ``gobj_list`` from hierarchy JSON.
        processed : set[str]
            Names of objects already tested.
        scene_understanding : SceneUnderstandingOutput, optional
            Structured scene knowledge.
        gate_hints, recent_failures, coverage_state : optional runtime state.
        scheduler_bias : list[str], optional
            Observer-recommended object priorities from blackboard.
        failure_counts : dict[str, int], optional
            Per-object failure counts from blackboard.

        Returns
        -------
        SchedulerDecision or None (if nothing left or LLM fails).
        """
        bias_names = self._normalise_bias_names(scheduler_bias or [])
        failure_counts = failure_counts or {}
        remaining = []
        for candidate in candidates:
            candidate_name = candidate.get("gameobject_name", "")
            was_processed = candidate_name in processed
            is_biased = self._name_matches_bias(candidate_name, bias_names)
            failure_count = failure_counts.get(candidate_name, 0)
            if not was_processed or (is_biased and failure_count < max_revisits):
                remaining.append(candidate)
        if not remaining:
            return None

        # If LLM is unavailable or disabled, fall back to priority / linear order
        if not self._is_llm_enabled():
            return self._fallback_select(
                remaining, scene_understanding,
                scheduler_bias=scheduler_bias,
                failure_counts=failure_counts,
            )

        # Build prompt
        user_prompt = self._build_prompt(
            remaining, processed, scene_understanding,
            gate_hints, recent_failures, coverage_state,
            scheduler_bias, failure_counts,
        )

        model = (
            self.llm_config.effective_model(self._default_model)
            if self.llm_config
            else self._default_model
        )
        temp = self.llm_config.temperature if self.llm_config else 0.3

        raw = self.llm.chat(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=temp,
            caller="scheduler",
        )

        if not raw:
            return self._fallback_select(
                remaining, scene_understanding,
                scheduler_bias=scheduler_bias,
                failure_counts=failure_counts,
            )

        parsed = self.llm.extract_json(raw)
        if not parsed:
            return self._fallback_select(
                remaining, scene_understanding,
                scheduler_bias=scheduler_bias,
                failure_counts=failure_counts,
            )

        chosen_name = parsed.get("object_name", "")
        # Validate that the chosen object actually exists in remaining
        obj_info = next(
            (g for g in remaining if g.get("gameobject_name", "") == chosen_name),
            None,
        )
        if obj_info is None:
            # LLM hallucinated an object name — fall back
            return self._fallback_select(
                remaining, scene_understanding,
                scheduler_bias=scheduler_bias,
                failure_counts=failure_counts,
            )

        decision = SchedulerDecision(
            object_name=chosen_name,
            object_info=obj_info,
            reason=parsed.get("reason", ""),
            priority_score=float(parsed.get("priority_score", 0.5)),
            skip_list=parsed.get("skip_list", []),
        )
        self._history.append(decision.__dict__)
        return decision

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        remaining: List[Dict],
        processed: set[str],
        scene_understanding: Optional[SceneUnderstandingOutput],
        gate_hints: Optional[List[Dict]],
        recent_failures: Optional[List[str]],
        coverage_state: Optional[Dict[str, float]],
        scheduler_bias: Optional[List[str]] = None,
        failure_counts: Optional[Dict[str, int]] = None,
    ) -> str:
        parts: List[str] = []

        # Scene understanding
        if scene_understanding:
            parts.append(scene_understanding.to_prompt_text())

        # Remaining candidates (compact)
        obj_names = [g.get("gameobject_name", "?") for g in remaining]
        parts.append(f"**Remaining objects** ({len(obj_names)}):\n{json.dumps(obj_names)}")

        # Already processed
        if processed:
            parts.append(f"**Already processed** ({len(processed)}): {json.dumps(sorted(processed))}")

        # Gate hints
        if gate_hints:
            parts.append(f"**Gate hints**:\n```json\n{json.dumps(gate_hints[:5], indent=2)}\n```")

        # Recent failures
        if recent_failures:
            parts.append(f"**Recent failures**: {json.dumps(recent_failures[:10])}")

        # Coverage
        if coverage_state:
            parts.append(f"**Coverage state**: {json.dumps(coverage_state)}")

        # Scheduler bias from Observer/blackboard
        if scheduler_bias:
            parts.append(f"**Observer priority recommendations**: {json.dumps(scheduler_bias[:10])}")

        # Per-object failure counts from blackboard
        if failure_counts:
            relevant = {k: v for k, v in failure_counts.items() if v > 0}
            if relevant:
                parts.append(f"**Failure counts**: {json.dumps(relevant)}")

        # Selection history (last 5)
        if self._history:
            recent = [
                {"object_name": h["object_name"], "reason": h["reason"]}
                for h in self._history[-5:]
            ]
            parts.append(f"**Recent selections**: {json.dumps(recent)}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Fallback (no LLM)
    # ------------------------------------------------------------------

    def _fallback_select(
        self,
        remaining: List[Dict],
        scene_understanding: Optional[SceneUnderstandingOutput],
        *,
        scheduler_bias: Optional[List[str]] = None,
        failure_counts: Optional[Dict[str, int]] = None,
    ) -> SchedulerDecision:
        """Deterministic fallback with coverage-oriented scoring."""
        bias_names = self._normalise_bias_names(scheduler_bias or [])
        failure_counts = failure_counts or {}
        ranking = scene_understanding.object_priority_ranking if scene_understanding else []
        key_objects = set(scene_understanding.key_objects if scene_understanding else [])

        scored: List[tuple[float, Dict]] = []
        for index, candidate in enumerate(remaining):
            name = candidate.get("gameobject_name", "")
            score = 1.0 / (index + 1)
            if self._name_matches_bias(name, bias_names):
                score += 8.0
            if name in key_objects:
                score += 4.0
            if name in ranking:
                score += max(0.0, 12.0 - 1.0 * ranking.index(name))
            score += 0.6 * len(candidate.get("mono_comp_relations", []) or [])
            score += 0.15 * len(candidate.get("child_relations", []) or [])
            if any(candidate.get(field) for field in (
                "sorted_target_logic_info",
                "sorted_layer_logic_info",
                "gameobject_find_info",
                "gameobject_instantiate_info",
            )):
                score += 2.5
            score -= min(3.0, 0.8 * failure_counts.get(name, 0))
            scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, first = scored[0]
        return SchedulerDecision(
            object_name=first.get("gameobject_name", ""),
            object_info=first,
            reason="coverage-oriented fallback",
            priority_score=round(min(1.0, max(0.0, best_score / 10.0)), 3),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_llm_enabled(self) -> bool:
        if self.llm_config:
            return self.llm_config.enabled
        return self.llm is not None

    @staticmethod
    def _normalise_bias_names(raw_bias: List[str]) -> List[str]:
        names: List[str] = []
        for item in raw_bias:
            text = str(item).strip()
            if not text:
                continue
            names.append(text.lower())
        return names

    @staticmethod
    def _name_matches_bias(name: str, bias_names: List[str]) -> bool:
        lowered = name.lower()
        return any(lowered == bias or lowered in bias or bias in lowered for bias in bias_names)
