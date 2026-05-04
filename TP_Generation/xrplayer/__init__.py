"""XRPlayer — public façade over the ``vragent2`` engine.

XRPlayer is the production name for the multi-agent XR test driver.  The
runtime engine still lives under :mod:`vragent2` for backwards compatibility;
this package re-exports the stable surface so user code can write::

    from xrplayer import VRAgentController, SharedWorldState

…and not depend on the internal ``vragent2`` module path.

The Jelly dashboard ships as :mod:`xrplayer.jelly` and is launched via::

    python -m xrplayer.jelly --port 2000 --results-dir <output_root>
"""
from __future__ import annotations

# Re-export the controller and key contracts.  Failures are tolerated so
# `import xrplayer` never breaks the host application during partial installs.
try:
    from vragent2.controller import VRAgentController  # noqa: F401
    from vragent2.contracts import (  # noqa: F401
        SharedWorldState,
        AgentDecision,
        PlannerOutput,
        VerifierOutput,
        ExecutorOutput,
        SemanticVerifierOutput,
        SceneUnderstandingOutput,
        ExplorationMode,
    )
except Exception as exc:  # pragma: no cover - only triggers on broken installs
    import warnings
    warnings.warn(f"xrplayer: failed to import vragent2 surface: {exc}")

__version__ = "0.1.0-xrplayer"
__all__ = [
    "VRAgentController",
    "SharedWorldState",
    "AgentDecision",
    "PlannerOutput",
    "VerifierOutput",
    "ExecutorOutput",
    "SemanticVerifierOutput",
    "SceneUnderstandingOutput",
    "ExplorationMode",
    "__version__",
]
