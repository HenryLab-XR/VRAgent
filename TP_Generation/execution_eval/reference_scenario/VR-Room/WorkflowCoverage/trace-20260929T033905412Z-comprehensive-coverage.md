# VR-Room workflow coverage — test-plan rerun

Inputs:

- Reference scenarios: `WorkflowCoverage/reference-scenarios.json`
- Extracted TODG/hierarchy: `artifacts/My VR Room_gobj_hierarchy.json`
- Generated test plan: `artifacts/My VR Room_consolidated_test_plans.json`
- Runtime trace: `WorkflowCoverage/traces/trace-20260929T033905412Z.jsonl`
- Evaluation boundary: sequences 1--772, including `session.started` and `session.ended`

## Metric standard

- **SDC** credits a reference dependency only when both endpoints, the object/component connection, and directed static evidence can be reconstructed from the extracted graph. Structural containment or attachment alone does not count.
- **PIC** credits `Grab`, `Transform`, or `Trigger` when the action identifies the correct target and expresses the required effect. Under the revised project rule, a targeted `Trigger` may satisfy an activation/press interaction by invoking its corresponding callback directly.
- **REC** counts each unique required semantic runtime obligation at most once. Repetitions do not increase coverage.
- **SCR** requires one correctly correlated and ordered event chain, a successful postcondition after the required events, no failure oracle, and a valid terminal state.

## Aggregate result

| Project | Scenarios | Dependencies | SDC | PIC | REC | SCR |
|---|---:|---:|---:|---:|---:|---:|
| `VR-Room` | 5 | 9 | 5/9 (55.6%) | 4/6 (66.7%) | 10/15 (66.7%) | 3/5 (60.0%) |
| **Overall** | **5** | **9** | **5/9 (55.6%)** | **4/6 (66.7%)** | **10/15 (66.7%)** | **3/5 (60.0%)** |

## Per-workflow result

| Reference workflow | Static evidence | Generated-plan action | Runtime evidence | SDC | PIC | REC | SCR |
|---|---|---|---|---:|---:|---:|---:|
| `start-room` | No start/OK-to-load operational mapping in the extracted graph | No start/OK action | No workflow records | 0/1 | 0/1 | 0/2 | 0 |
| `fire-projectile` | Serialized activation-to-`Fire` mapping and `Instantiate_Logic_Relation`; audio is a sibling persistent call rather than `Fire -> Play` | `Trigger(Launcher_DartGun)` invokes `Fire` and `Play` | Sequences 465--469: correlated activation, callback, projectile, audio, and true postcondition | 2/3 | 1/1 | 4/4 | 1 |
| `control-media` | Serialized control-to-`PlayPause` mapping plus linked playback state logic | Targeted triggers invoke play and pause/stop methods | Sequences 502--507: correlated play, playing, pause, not-playing, and true postconditions | 2/2 | 2/2 | 4/4 | 1 |
| `toggle-room-effects` | Serialized Light Switch-to-`ToggleOnOff.Toggle` mapping | `Trigger(Light_Switch)` and targeted `Toggle` calls | Sequences 485--487: correlated particle activation, state change, and true postcondition | 1/1 | 1/1 | 2/2 | 1 |
| `rotate-cover` | `StartRotation` appears with an unresolved serialized target, so the object/component connection is incomplete | No cover interaction | No workflow records | 0/2 | 0/1 | 0/3 | 0 |

## Interpretation

The revised PIC rule matches the available plan vocabulary: targeted `Trigger` actions receive credit for the corresponding activation or press even when implemented by direct callback invocation. Missing start-room and rotate-cover actions remain uncovered.

The graph contains 63 `Has_Child`, 59 `Has_Mono_Comp`, and one `Instantiate_Logic_Relation` edge. The structural edges identify candidates but receive no causal credit by themselves. Serialized UnityEvent evidence supplies the other credited static mappings.

This trigger-equivalence rule is applied consistently to both projects; it changes PIC only and does not alter SDC, REC, or SCR.
