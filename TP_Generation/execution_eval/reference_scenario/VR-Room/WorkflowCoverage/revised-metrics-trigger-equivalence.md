# Metrics under the trigger-equivalence standard

The revised standard treats a targeted plan `Trigger` as a valid representation of the corresponding interaction when it invokes the correct callback or method. Static dependencies and runtime-event matching are unchanged. SCR was rechecked because interaction validity is one of its completion conditions.

| Project | Scenarios | Dependencies | SDC | PIC | REC | SCR |
|---|---:|---:|---:|---:|---:|---:|
| `escapeVr` | 3 | 18 | 15/18 (83.3%) | 7/7 (100.0%) | 30/30 (100.0%) | 2/3 (66.7%) |
| `VR-Room` | 5 | 9 | 5/9 (55.6%) | 4/6 (66.7%) | 10/15 (66.7%) | 3/5 (60.0%) |
| **Combined** | **8** | **27** | **20/27 (74.1%)** | **11/13 (84.6%)** | **40/45 (88.9%)** | **5/8 (62.5%)** |

## Metric impact

| Metric | Affected by revised rule? | Result |
|---|---|---|
| SDC | No | Static graph evidence is unchanged. |
| PIC | Yes | Direct targeted triggers now satisfy matching interactions. |
| REC | No | The observed semantic event sets are unchanged. |
| SCR | Potentially | Recalculated, but unchanged for these traces because the remaining failures are missing workflows or terminal-state violations. |

The `escapeVr` values use the final action--object--event SDC assessment and the 239-record strict-terminal runtime evaluation from the referenced task. The `VR-Room` values use reference version `vr-room-2026-09-28` and trace `trace-20260929T033905412Z.jsonl`.
