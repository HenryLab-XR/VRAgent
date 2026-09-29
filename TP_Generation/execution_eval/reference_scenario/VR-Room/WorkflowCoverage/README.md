# Workflow tracing and metric standard

`reference-scenarios.json` is the fixed denominator for this project. It was derived from `My VR Room.unity`, serialized UnityEvent calls, and the project-owned scripts under `Assets/Data Files`.

`reference-scenarios-table.tex` presents the same fixed model in the publication-oriented $P,I,T,Q$ format used for `escapeVr`. Its trailing comments define every VR-Room symbol used in the table.

The runtime fallback is installed automatically after a scene loads. It writes JSONL under the repository's `WorkflowCoverage/traces` directory and records the concrete `MonoBehaviour` types found in loaded scenes plus observable state changes. These records identify which scripts execute and where semantic probes should be added; they do **not** receive REC credit on their own. Fallback and semantic records use the same file and global sequence.

Semantic probes are wired into scene loading, projectile launch/audio, audio and video controls, light/particle toggles, and cover rotation. Each interaction chain carries a `correlationId`. Preserve the physical interaction path when extending this instrumentation: a direct method call is not a substitute for the required XR action.

After scripts recompile, start a new Play session and exercise each workflow through its normal UI/XR control. A new `WorkflowCoverage/traces/trace-*.jsonl` file is created for every run. Do not append a new run to an older trace. Standalone builds can set `WORKFLOW_COVERAGE_DIR` to the absolute repository `WorkflowCoverage` path; otherwise the folder is created beside the build data directory.

Evaluate a trace with:

```powershell
pwsh -File Tools/WorkflowTrace/Measure-WorkflowCoverage.ps1 `
  -Reference WorkflowCoverage/reference-scenarios.json `
  -Trace <path-to-semantic-jsonl>
```

Metric rules match the reference project:

- **SDC**: statically mapped causal dependencies / fixed reference dependencies. Both endpoints, object/component connection, and directed evidence are required.
- **PIC**: plan-expressible required interactions / fixed reference interactions. The supported plan vocabulary is `Grab`, `Transform`, and `Trigger`; a targeted `Trigger` may cover an activation or press by invoking its corresponding callback directly. Target identity and required effect must still match.
- **REC**: uniquely observed semantic runtime obligations / fixed event obligations. Repeats do not add credit.
- **SCR**: completely satisfied scenarios / fixed scenarios. Ordering, postconditions, failure oracles, and terminal state are mandatory.

Always report raw counts with percentages and record the reference version, artifact revision, plan revision, trace identifier, evaluation boundary, and any manual judgment.
