# PIC recalculation with trigger equivalence

Revised rule: because the generated plans expose only `Grab`, `Transform`, and `Trigger`, a `Trigger` action receives PIC credit when it identifies the correct source/target and invokes the callback corresponding to the required interaction. Direct triggering is therefore not treated as a shortcut for PIC in this evaluation.

## Results

| Project | Required interactions | Covered | PIC |
|---|---:|---:|---:|
| `escapeVr` | 7 | 7 | 7/7 (100.0%) |
| `VR-Room` | 6 | 4 | 4/6 (66.7%) |
| **Combined** | **13** | **11** | **11/13 (84.6%)** |

## escapeVr

| Workflow | Covered | Basis |
|---|---:|---|
| Room 1 key | 2/2 | Targeted `Grab`/placement operations cover acquisition and placement. |
| Room 2 shapes | 3/3 | Three targeted `Grab` operations cover placement into the three receptacles. |
| Room 3 lasers | 2/2 | The two targeted `Trigger` operations invoking `SetLaser` cover the two beam actions under trigger equivalence. |

## VR-Room

| Workflow | Covered | Basis |
|---|---:|---|
| Start room | 0/1 | No start/OK action appears in the plan. |
| Fire projectile | 1/1 | `Trigger(Launcher_DartGun)` invokes `Fire` and `Play`. |
| Media controls | 2/2 | Targeted triggers invoke play and pause/stop callbacks. |
| Room effects | 1/1 | `Trigger(Light_Switch)` and targeted `Toggle` calls express activation. |
| Rotate cover | 0/1 | No cover/`StartRotation` action appears in the plan. |

Only PIC is recalculated. The static graph, runtime trace, postconditions, failure rules, and therefore SDC, REC, and SCR are unchanged.

## Effect on the other metrics

The rule has no effect on SDC because SDC evaluates the extracted static dependency representation, not plan-action validity. It has no effect on REC because REC counts observed semantic event obligations independently of how the plan expressed the initiating action.

The rule can affect SCR in principle because strict completion includes a valid interaction path. Re-evaluation produces no numerical change for these runs:

| Project | Previous SCR | Revised SCR | Reason |
|---|---:|---:|---|
| `escapeVr` | 2/3 (66.7%) | 2/3 (66.7%) | Room 3 remains invalidated by its later reconnection/laser-clear terminal-state failure, not by Trigger eligibility. |
| `VR-Room` | 3/5 (60.0%) | 3/5 (60.0%) | The three completed workflows remain complete; start-room and rotate-cover still have no required runtime chains. |

Thus, for the evaluated runs, only PIC changes numerically.
