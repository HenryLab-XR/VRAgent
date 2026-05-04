"""
Scene Understanding Agent — Reads scene ground-truth docs *and* Unity scene
hierarchy data, then produces a structured ``SceneUnderstandingOutput``.

XRPlayer enhancements (vs. the original v2.0 implementation):

* Accepts an optional ``hierarchy_json_path`` (or already-loaded ``gobj_list``)
  so it can ground its output in the actual Unity scene rather than only the
  ``.md`` documentation.
* Runs a heuristic pre-pass that classifies every GameObject as
  ``interactable``, ``system``, or ``decoration`` based on attached components,
  XR interaction hints, name patterns, and child structure.
* Merges heuristic findings with the LLM output (LLM wins on naming/roles,
  heuristics fill ``key_objects`` / ``forbidden_test_objects`` /
  ``object_priority_ranking`` whenever the LLM under-specifies them).
* Falls back to a fully heuristic ``SceneUnderstandingOutput`` when LLM is
  disabled or unavailable, so the rest of the XRPlayer pipeline still gets
  useful scene knowledge.
* Emits an ``AgentDecision`` summarising what it learned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, TYPE_CHECKING

from .base_agent import BaseAgent, measure_ms
from ..contracts import SceneUnderstandingOutput, InteractionDependency

if TYPE_CHECKING:
    from ..utils.llm_client import LLMClient
    from ..utils.config_loader import AgentLLMConfig


_SYSTEM_PROMPT = """\
You are an expert VR scene analyst. Given documentation about a Unity VR scene,
extract structured knowledge that will guide automated VR testing.

Return a JSON object with the following fields:
{
  "scene_overview": "<1-3 sentence overview of what the scene is about>",
  "key_objects": ["<objectName>", ...],
  "interaction_dependencies": [
    {"source": "<obj>", "target": "<obj>", "relation": "<unlocks|enables|requires|triggers>"},
    ...
  ],
  "gate_chains": [
    "<Step N: description of gating requirement>",
    ...
  ],
  "main_path": [
    "<Step 1: first thing to do>",
    ...
  ],
  "failure_paths": [
    "<Common failure pattern description>",
    ...
  ],
  "object_priority_ranking": ["<mostImportantObj>", "<nextObj>", ...],
  "object_roles": {
    "<objectName>": "<role: unlocker|gated_target|feedback|tool|container|trigger|optional_decoration>",
    ...
  },
  "oracle_hints": [
    "<observable condition that should be true if the interaction succeeded>",
    ...
  ],
  "completion_criteria": [
    "<what counts as completing the scene / test objective>",
    ...
  ],
  "forbidden_test_objects": ["<objectName that should NEVER be tested — controllers, agents, system objects>", ...]
}

Rules:
- "key_objects" should list all interactable GameObjects mentioned in the docs.
- "interaction_dependencies" captures causal relationships (A unlocks B, etc.).
- "gate_chains" describes locked/gated sequences the player must solve in order.
- "main_path" is the intended walkthrough sequence.
- "failure_paths" lists things that commonly go wrong.
- "object_priority_ranking" orders objects by testing importance (gates first, then critical interactions, then optional).
- "object_roles" assigns a semantic role to each key object.
- "oracle_hints" are observable post-conditions (state changes, log events, visual changes) that verify success.
- "completion_criteria" describes the final success condition(s) for the scene.
- "forbidden_test_objects" are objects the agent should never interact with (controllers, managers, system infrastructure).
- Be concise. Do NOT invent objects/interactions not mentioned in the docs.
- Return ONLY valid JSON, no extra text.
"""


class SceneUnderstandingAgent(BaseAgent):
    """Agent 0 — Produces structured scene knowledge from documentation."""

    name = "SceneUnderstandingAgent"

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

    # ------------------------------------------------------------------
    # Contract entry
    # ------------------------------------------------------------------

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Produce structured scene understanding.

        Parameters
        ----------
        input_data : dict
            Recognised keys:
                scene_doc_path     : str  — path to a ``.md`` doc or directory
                extra_context      : str  — extra prompt context
                hierarchy_json_path: str  — path to ``gobj_hierarchy.json``
                gobj_list          : list — pre-loaded hierarchy entries
                scene_name         : str  — Unity scene name (informational)

        Returns
        -------
        dict — serialised :class:`SceneUnderstandingOutput`.
        """
        t0 = measure_ms()
        doc_path = input_data.get("scene_doc_path", "")
        extra_ctx = input_data.get("extra_context", "")
        scene_name = input_data.get("scene_name", "")

        # ── 1. Heuristic pre-pass over Unity hierarchy ───────────────
        gobj_list = input_data.get("gobj_list")
        if gobj_list is None and input_data.get("hierarchy_json_path"):
            gobj_list = self._load_hierarchy(input_data["hierarchy_json_path"])
        heuristic = (
            self._heuristic_understanding(gobj_list, scene_name)
            if gobj_list else None
        )

        # ── 2. Load .md docs ─────────────────────────────────────────
        doc_text = self._load_docs(doc_path)
        evidence: List[str] = []
        if heuristic:
            evidence.append(
                f"hierarchy:{len(gobj_list)} key={len(heuristic.key_objects)}"
                f" forbidden={len(heuristic.forbidden_test_objects)}"
            )
        if doc_text:
            evidence.append(f"docs:{len(doc_text)}chars")

        # ── 3. LLM pass (docs preferred, but hierarchy-only scenes should
        #        still get an LLM scene summary) ───────────────────────
        llm_output: Optional[SceneUnderstandingOutput] = None
        if self.llm is not None and self.llm_enabled and (doc_text or heuristic):
            llm_output = self._call_llm(doc_text, extra_ctx, heuristic)

        # ── 4. Merge LLM + heuristic ─────────────────────────────────
        merged = self._merge(llm_output, heuristic, fallback_overview=scene_name)

        # ── 5. Emit decision summary ─────────────────────────────────
        sources: List[str] = []
        if llm_output is not None:
            sources.append("llm")
        if heuristic is not None:
            sources.append("heuristic")
        if not sources:
            sources.append("empty")

        self.record_decision(
            summary=(
                f"Scene understood ({', '.join(sources)}): "
                f"{len(merged.key_objects)} key obj, "
                f"{len(merged.forbidden_test_objects)} forbidden, "
                f"{len(merged.interaction_dependencies)} deps"
            ),
            confidence=0.7 if llm_output is not None else (0.4 if heuristic else 0.0),
            inputs={
                "scene_doc_path": doc_path,
                "scene_name": scene_name,
                "hierarchy_objects": len(gobj_list) if gobj_list else 0,
            },
            outputs={
                "key_objects": len(merged.key_objects),
                "forbidden": len(merged.forbidden_test_objects),
                "ranking": len(merged.object_priority_ranking),
            },
            evidence=evidence or ["no-input"],
            next_hint="Scheduler should pull from object_priority_ranking",
            duration_ms=measure_ms() - t0,
        )

        return merged.to_dict()

    # ------------------------------------------------------------------
    # LLM call (extracted from previous run() body)
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        doc_text: str,
        extra_ctx: str,
        heuristic: Optional[SceneUnderstandingOutput],
    ) -> Optional[SceneUnderstandingOutput]:
        if doc_text:
            user_prompt = f"## Scene Documentation\n\n{doc_text}"
        else:
            user_prompt = "## Scene Hierarchy Summary\n\nNo markdown scene document was provided. Infer the scene from the extracted Unity hierarchy and candidate objects below."

        if heuristic:
            user_prompt += "\n\n## Unity Scene Hierarchy (heuristic candidates)\n\n"
            user_prompt += heuristic.to_prompt_text()
        if extra_ctx:
            user_prompt += f"\n\n## Additional Context\n\n{extra_ctx}"

        model = (
            self.llm_config.effective_model(self._default_model)
            if self.llm_config else self._default_model
        )
        temp = self.llm_config.temperature if self.llm_config else 0.2

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        raw = self.llm.chat(
            messages, model=model, temperature=temp, caller="scene_understanding",
        )
        if not raw:
            print("[SCENE_UNDERSTANDING] LLM returned empty response")
            return None
        parsed = self.llm.extract_json(raw)
        if parsed is None:
            print("[SCENE_UNDERSTANDING] Failed to parse LLM JSON")
            return SceneUnderstandingOutput(scene_overview=raw[:500])
        return SceneUnderstandingOutput.from_dict(parsed)

    # ------------------------------------------------------------------
    # Document loader
    # ------------------------------------------------------------------

    @staticmethod
    def _load_docs(path_str: str) -> str:
        """Load ``.md`` files from a file or directory path."""
        if not path_str:
            return ""

        p = Path(path_str)
        parts: List[str] = []

        if p.is_file() and p.suffix.lower() == ".md":
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
        elif p.is_dir():
            for md in sorted(p.glob("*.md")):
                parts.append(f"# {md.name}\n\n{md.read_text(encoding='utf-8', errors='replace')}")
        else:
            print(f"[SCENE_UNDERSTANDING] Invalid path: {p}")

        return "\n\n---\n\n".join(parts)

    # ------------------------------------------------------------------
    # Hierarchy loader (Unity gobj_hierarchy.json)
    # ------------------------------------------------------------------

    @staticmethod
    def _load_hierarchy(path_str: str) -> List[Dict[str, Any]]:
        """Load and flatten ``gobj_hierarchy.json`` produced by
        ``TraverseSceneHierarchy.py``."""
        try:
            data = json.loads(Path(path_str).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[SCENE_UNDERSTANDING] Failed to read hierarchy {path_str}: {exc}")
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Common layouts: {"objects": [...]} or already a single object.
            if isinstance(data.get("objects"), list):
                return data["objects"]
            return [data]
        return []

    # ------------------------------------------------------------------
    # Heuristic Unity-side understanding
    # ------------------------------------------------------------------

    # Component / script-name keywords that strongly suggest interactability.
    _INTERACTABLE_HINTS: Tuple[str, ...] = (
        "xrgrab", "xrtrigger", "xrsocket", "xrsimpleinteractable",
        "interactable", "xrbasecontroller", "rigidbody", "collider",
        "button", "toggle", "slider", "dropdown", "inputfield",
        "door", "key", "lever", "switch", "lock", "trigger",
        "valve", "handle", "pickup", "grabbable",
    )
    # Names / components that should never be tested.
    _SYSTEM_HINTS: Tuple[str, ...] = (
        "manager", "controller", "rig", "camera", "audiolistener",
        "eventsystem", "navmesh", "lighting", "directionallight",
        "skybox", "pool", "spawner", "agentbridge", "vragent",
        "xrplayer", "fileidmanager",
    )
    # Names that are usually decoration only.
    _DECORATION_HINTS: Tuple[str, ...] = (
        "wall", "floor", "ceiling", "ground", "plane", "terrain",
        "particle", "fx", "vfx", "decal", "skybox", "post",
        "decoration", "environment", "tree", "rock", "grass",
    )

    def _heuristic_understanding(
        self,
        gobj_list: List[Dict[str, Any]],
        scene_name: str,
    ) -> SceneUnderstandingOutput:
        """Build a baseline ``SceneUnderstandingOutput`` from raw Unity data.

        This pass is intentionally conservative: it does not invent
        relationships, only labels objects.  The LLM (or downstream agents)
        can refine the result.
        """
        key_objects: List[Tuple[str, float]] = []
        forbidden: List[str] = []
        roles: Dict[str, str] = {}

        for entry in gobj_list:
            name = self._object_name(entry)
            if not name:
                continue

            score, role = self._classify_object(name, entry)
            if role in {"system", "agent_internal"}:
                forbidden.append(name)
                roles[name] = role
                continue
            if score <= 0:
                # decoration / unknown — keep out of the priority ranking
                if role:
                    roles[name] = role
                continue
            key_objects.append((name, score))
            if role:
                roles[name] = role

        # Stable sort: highest score first, name as tiebreaker.
        key_objects.sort(key=lambda kv: (-kv[1], kv[0]))
        ranking = [n for n, _ in key_objects]

        overview = (
            f"Heuristic scene snapshot for '{scene_name}': "
            f"{len(gobj_list)} candidate GameObjects, "
            f"{len(ranking)} likely interactable, "
            f"{len(forbidden)} system/forbidden."
        ) if scene_name else (
            f"Heuristic scene snapshot: {len(gobj_list)} candidate GameObjects, "
            f"{len(ranking)} likely interactable."
        )

        return SceneUnderstandingOutput(
            scene_overview=overview,
            key_objects=ranking[:50],
            object_priority_ranking=ranking[:50],
            forbidden_test_objects=forbidden[:50],
            object_roles=roles,
        )

    @staticmethod
    def _object_name(entry: Dict[str, Any]) -> str:
        for key in ("gameobject_name", "name", "object_name"):
            v = entry.get(key)
            if isinstance(v, str) and v.strip() and v.strip().lower() != "unknown":
                return v.strip()
        return ""

    def _classify_object(
        self, name: str, entry: Dict[str, Any]
    ) -> Tuple[float, str]:
        """Return ``(score, role)`` where ``score>0`` means the object is
        worth testing.  ``role`` is one of ``""``, ``"system"``,
        ``"interactable"``, ``"decoration"``."""
        lname = name.lower()
        comp_blob = self._collect_component_text(entry)

        # System / agent infrastructure → never test.
        if any(h in lname for h in self._SYSTEM_HINTS):
            return 0.0, "system"
        if any(h in comp_blob for h in ("agentbridge", "fileidmanager", "vragent")):
            return 0.0, "agent_internal"

        # Decoration → de-prioritise unless they also have interaction comps.
        if any(h in lname for h in self._DECORATION_HINTS) and not any(
            h in comp_blob for h in ("interactable", "xrgrab", "xrtrigger")
        ):
            return 0.0, "decoration"

        # Interactable signals
        score = 0.0
        if any(h in comp_blob for h in self._INTERACTABLE_HINTS):
            score += 3.0
        if any(h in lname for h in self._INTERACTABLE_HINTS):
            score += 1.5
        # Children with scripts → likely a composite interactable.
        scripts = entry.get("scripts") or entry.get("monoBehaviours") or []
        if isinstance(scripts, list) and scripts:
            score += min(2.0, 0.5 * len(scripts))
        children = entry.get("children") or []
        if isinstance(children, list) and len(children) > 0:
            score += min(1.0, 0.1 * len(children))

        role = "interactable" if score > 0 else ""
        return score, role

    @staticmethod
    def _collect_component_text(entry: Dict[str, Any]) -> str:
        """Lower-cased blob of every component / script / type name found in
        the hierarchy entry. Used for keyword matching."""
        blob_parts: List[str] = []
        for key in ("components", "monoBehaviours", "scripts", "tags",
                    "interactable_components"):
            v = entry.get(key)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        blob_parts.append(item)
                    elif isinstance(item, dict):
                        for sub in ("name", "type", "class", "script_name"):
                            sv = item.get(sub)
                            if isinstance(sv, str):
                                blob_parts.append(sv)
            elif isinstance(v, str):
                blob_parts.append(v)
        return " ".join(blob_parts).lower()

    # ------------------------------------------------------------------
    # Merge LLM + heuristic
    # ------------------------------------------------------------------

    @staticmethod
    def _merge(
        llm: Optional[SceneUnderstandingOutput],
        heuristic: Optional[SceneUnderstandingOutput],
        *,
        fallback_overview: str = "",
    ) -> SceneUnderstandingOutput:
        """Combine LLM and heuristic outputs.  LLM has priority on free-form
        fields; heuristics fill object lists when the LLM under-specifies."""
        if llm is None and heuristic is None:
            return SceneUnderstandingOutput(scene_overview=fallback_overview)
        if llm is None:
            return heuristic  # type: ignore[return-value]
        if heuristic is None:
            return llm

        merged = SceneUnderstandingOutput.from_dict(llm.to_dict())

        # Augment key_objects / forbidden / ranking with heuristic findings.
        merged.key_objects = _ordered_unique(
            list(merged.key_objects) + list(heuristic.key_objects)
        )[:60]
        merged.forbidden_test_objects = _ordered_unique(
            list(merged.forbidden_test_objects) + list(heuristic.forbidden_test_objects)
        )[:60]
        merged.object_priority_ranking = _ordered_unique(
            list(merged.object_priority_ranking) + list(heuristic.object_priority_ranking)
        )[:60]
        # Merge roles (LLM wins on conflicts).
        for k, v in heuristic.object_roles.items():
            merged.object_roles.setdefault(k, v)
        if not merged.scene_overview:
            merged.scene_overview = heuristic.scene_overview
        return merged


def _ordered_unique(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for it in items:
        if it and it not in seen:
            out.append(it)
            seen.add(it)
    return out
