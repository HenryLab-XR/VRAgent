# VR Room artifact analysis

Reference version: `vr-room-2026-09-28`  
Primary scene: `Assets/Scenes/My VR Room.unity`  
Evidence boundary: serialized scene data and project-owned scripts present on 2026-09-28

## Reference scenarios

| Scenario | Required action | Directed static evidence | Semantic postcondition |
|---|---|---|---|
| `start-room` | Activate `OK` | `Button.onClick -> LoadSceneUsingName` | Configured target scene becomes active |
| `fire-projectile` | Activate held launcher | XR activation -> `Fire`; the same serialized chain invokes audio `Play` | New projectile exists and moves away |
| `control-media` | Press play/pause/stop controls | Serialized calls to `Play`, `Pause`, `Stop`, `PlayPause`, and `TogglePlayPause` | Playing state equals the last requested state |
| `toggle-room-effects` | Activate connected XR control | Serialized calls to `SetActive`, `Toggle`, and `ToggleParticleSystem` | Intended target active/particle state changes and persists |
| `rotate-cover` | Activate cover control | Serialized call to `RotateCover.StartRotation`; code rotates toward `targetRotation` | Cover reaches configured target angle |

## Static dependency calculation

SDC uses the same endpoint + connection + directed-relation rule as the reference task. The denominator contains the nine dependency entries in `reference-scenarios.json`; each was admitted only after all three evidence requirements were found.

| Scenario | Covered | Required |
|---|---:|---:|
| `start-room` | 1 | 1 |
| `fire-projectile` | 3 | 3 |
| `control-media` | 2 | 2 |
| `toggle-room-effects` | 1 | 1 |
| `rotate-cover` | 2 | 2 |
| **SDC** | **9 (100.0%)** | **9** |

This 100% result means the selected reference dependencies have static support. It does not mean every scene behavior was modeled, nor does it establish runtime success.

PIC is not reported because no generated interaction plan was supplied in this workspace. REC and SCR are not reported until a semantic runtime trace is collected. Reporting either as zero would confuse “not evaluated” with “evaluated and uncovered.”

## Candidate-only behaviors

The following are useful trace candidates but are not separate reference scenarios yet because the artifacts do not establish a complete user action, causal path, and semantic postcondition: `BallCollisionSound`, `LightCandle`, `PhoneRingScreen`, `PlayAtIntervals`, and generic controller ray activation/deactivation. The fallback trace inventories these at runtime so later evidence can promote them without changing the current denominator retroactively.

## Known artifact defect

`Assets/Data Files/BallBounce.cs` declares `BallCollisionSound`. Unity requires a `MonoBehaviour` filename to match its class name for normal script-component attachment. The fallback inventory can therefore show whether an existing serialized component resolves, but this candidate should not be credited as a mapped executable behavior until the asset/class identity is corrected and revalidated.
