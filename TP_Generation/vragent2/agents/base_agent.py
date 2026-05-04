"""
Base Agent — Abstract interface that all XRPlayer agents must implement.

Every agent has typed input/output conforming to ``contracts.py`` AND emits
a compact ``AgentDecision`` summary on each call so that Jelly UI and
post-hoc analysis can show *what each agent did*, not just the final
test plan.

Design intent (XRPlayer multi-agent collaboration):

* Each agent has its **own** ``AgentLLMConfig`` (model, temperature,
  enabled/disabled) — see ``utils.config_loader.AgentLLMConfig``.
* Each agent records short ``AgentDecision`` entries via
  ``record_decision()``. The Controller drains ``last_decisions`` after
  each ``run()`` and appends them to ``SharedWorldState.agent_decisions``.
* Heuristic fallback paths set ``decision.evidence`` to ``["heuristic"]`` so
  the UI can distinguish LLM-driven from rule-driven decisions.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..contracts import AgentDecision

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.config_loader import AgentLLMConfig


class BaseAgent(ABC):
    """Abstract base for all XRPlayer agents."""

    name: str = "BaseAgent"

    def __init__(self) -> None:
        # Decisions recorded during the most recent ``run()``.
        # Controller drains this list (and clears it) per iteration.
        self._last_decisions: List[AgentDecision] = []
        # Optional iteration index injected by Controller before ``run()``.
        self._current_iteration: int = -1

    # ------------------------------------------------------------------
    # Contract entry
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent's task and return a contract-conforming output.

        Subclasses MUST also call ``self.record_decision(...)`` at least once
        with a short summary so the Jelly trace stays informative.
        """

    # ------------------------------------------------------------------
    # Decision recording (called by subclasses)
    # ------------------------------------------------------------------

    def record_decision(
        self,
        summary: str,
        *,
        confidence: float = 0.0,
        inputs: Optional[Dict[str, Any]] = None,
        outputs: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[str]] = None,
        next_hint: str = "",
        duration_ms: float = 0.0,
    ) -> AgentDecision:
        """Record a compact ``AgentDecision`` entry for this agent."""
        decision = AgentDecision(
            iteration=self._iteration_safe(),
            agent=(self.name if getattr(self, "name", "BaseAgent") != "BaseAgent"
                   else self.__class__.__name__),
            summary=str(summary)[:400],
            confidence=max(0.0, min(1.0, float(confidence))),
            inputs=_compact_dict(inputs or {}),
            outputs=_compact_dict(outputs or {}),
            evidence=[str(e)[:200] for e in (evidence or [])][:8],
            next_hint=str(next_hint)[:200],
            duration_ms=float(duration_ms),
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )
        self._decisions_safe().append(decision)
        return decision

    def drain_decisions(self) -> List[AgentDecision]:
        """Return and clear the current ``run()``'s decisions."""
        decisions = self._decisions_safe()
        out = list(decisions)
        decisions.clear()
        return out

    def set_iteration(self, iteration: int) -> None:
        """Tag subsequent decisions with the given iteration index."""
        self._current_iteration = int(iteration)

    # -- internal lazy accessors (work even if subclass skipped super().__init__) --

    def _decisions_safe(self) -> List[AgentDecision]:
        d = getattr(self, "_last_decisions", None)
        if d is None:
            d = []
            self._last_decisions = d
        return d

    def _iteration_safe(self) -> int:
        return int(getattr(self, "_current_iteration", -1))

    # ------------------------------------------------------------------
    # Config helpers (subclasses may override)
    # ------------------------------------------------------------------

    @property
    def llm_enabled(self) -> bool:
        """Whether the agent should attempt LLM calls.

        Default: True. Subclasses with an ``llm_config`` attribute return its
        ``enabled`` flag; agents without an LLM (e.g. Executor) override this.
        """
        cfg = getattr(self, "llm_config", None)
        if cfg is None:
            return True
        return bool(getattr(cfg, "enabled", True))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{self.name} iter={self._current_iteration}>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compact_dict(d: Dict[str, Any], max_str: int = 200) -> Dict[str, Any]:
    """Produce a JSON-serialisable, length-bounded version of ``d`` for the
    ``AgentDecision.inputs`` / ``outputs`` fields. Avoids dumping prompts."""
    out: Dict[str, Any] = {}
    for k, v in (d or {}).items():
        if isinstance(v, str):
            out[k] = v if len(v) <= max_str else v[:max_str] + "…"
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = f"<list len={len(v)}>"
        elif isinstance(v, dict):
            out[k] = f"<dict keys={len(v)}>"
        else:
            out[k] = f"<{type(v).__name__}>"
    return out


def measure_ms() -> float:
    """Return current monotonic time in milliseconds (helper for ``run()``)."""
    return time.monotonic() * 1000.0
