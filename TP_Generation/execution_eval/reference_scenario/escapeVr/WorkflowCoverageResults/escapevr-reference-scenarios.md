# escapeVr candidate-derived reference interaction scenarios

Scope: `Assets/Scenes/BatScene.unity`. These are draft reference scenarios built from the rule-based candidate report, serialized scene/prefab bindings, and the instrumented C# causal chains. They become ground truth only after the two-evaluator validation protocol in the JSON definition is completed.

| ID | Workflow | Initial state / preconditions | Required player interactions | Expected causal chain | Semantic postconditions | Key failure oracle |
|---|---|---|---|---|---|---|
| `escape-room-door` | Place the `Objet1` key object to open a door | Trigger active; `openTrigger=true`; object tagged `Objet1`; door closed and passage blocked | Grab object; move and release it inside `collider_porte` | `OnTriggerEnter` → `place-key-object` → `Snap` → consume trigger → `openTrigger=false` → request `DoorOpen` | Object snapped/non-manipulable; trigger inactive; door passage unblocked | Wrong tag, absent trigger callback, or blocked passage after trigger consumption |
| `room2-shape-placement` | Match the three shapes to Room 2 receptacles | Three check flags and `doorOpen=false`; shapes movable; door closed and blocked | Put sphere, cube, and pyramid into matching triggers, in any order | Three matching `OnTriggerEnter` callbacks → three `Set*Check` callbacks and snaps → all flags true → `doorOpen=true` → animation/unblock | All distinct checks true; all shapes snapped; door passage unblocked | Duplicate/wrong placement, early door open, or missing shape transition |
| `room3-laser` | Interrupt both laser paths | Both senders connected; `laser1=false`; `laser2=false`; `doorOpen=false`; door blocked | Move an obstruction into each sender-to-receiver path | Each non-receiver hit → `isConnected=false` → `SetLaser` → `laser1/laser2=true` → `doorOpen=true` → animation/audio/unblock | Both laser flags and door state true; both paths disconnected; audio requested; passage unblocked | Same sender counted twice, laser reconnect clears state, or effects occur without state/postcondition |

## Completion and trace matching

A scenario completes only when all required actions and trace events occur in the specified partial order, no failure rule is triggered, and every semantic postcondition is true. `Grabbed` must be paired with a corresponding movement/release observation for placement workflows. A movement is invalid when the exact runtime error `Destination ... is not reachable on NavMesh.` is associated with that action. Visual animation alone is not a semantic completion oracle.

The machine-readable version includes candidate provenance, dependency edges, trace predicates, cardinalities, postconditions, and failure rules: `WorkflowCoverageResults/escapevr-reference-scenarios.json`.
