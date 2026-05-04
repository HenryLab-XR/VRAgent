# XRPlayer Changelog

## v0.1.0-xrplayer (current)

### Added
* **`xrplayer/`** —  公开 façade 包，重新导出 `VRAgentController`、
  `SharedWorldState`、`AgentDecision`、`PlannerOutput`、`VerifierOutput`、
  `ExecutorOutput`、`SemanticVerifierOutput`、`SceneUnderstandingOutput`、
  `ExplorationMode`。
* **`xrplayer/__main__.py`** — `python -m xrplayer` CLI（委托到 `vragent2.main`）。
* **`xrplayer/jelly/`** — Jelly 本地仪表盘，**默认监听 127.0.0.1:2000**，
  仅依赖 Python 标准库。
* **`vragent2/jelly.py`** — `python -m vragent2.jelly` 兼容入口，
  转发到 `xrplayer.jelly`。
* **`AgentDecision` dataclass** (`vragent2/contracts.py`) —
  schema 化的 Agent 决策记录；包含 `iteration / agent / summary / confidence /
  inputs / outputs / evidence / next_hint / duration_ms / timestamp`。
* **`SharedWorldState.agent_decisions`** — blackboard 上的协作 trace 列表
  （上限 500 条），写入 `to_dict()`（最近 100 条）。
* **`SceneUnderstandingAgent` 启发式增强** —
  - 接受 `gobj_list` / `hierarchy_json_path`；
  - `_INTERACTABLE_HINTS` / `_SYSTEM_HINTS` / `_DECORATION_HINTS` 三套关键字；
  - `_classify_object` 给出 `(score, role)`；
  - `_merge(llm, heuristic)` 自动合并双源结果；
  - `record_decision(...)` 输出 confidence 0.7 / 0.4 / 0.0。
* **Controller 钩子** —
  - `_drain_agent_decisions(agent)` 把每个 Agent 的决策搬入 blackboard
    并增量写盘到 `agent_decisions.json`；
  - `_build_jelly_status(...)` / `_write_jelly_status()` 写
    `jelly_status.json`；
  - 每个 Agent 在 `run()` 之前都会被 `agent.set_iteration(N)` 标记。
* **Planner / Verifier / Executor / Observer** — 在各自 `run()` 末尾调用
  `record_decision(...)`，summary 描述本轮行为，next_hint 指向下游 Agent。
* **`tests/test_vragent2_smoke.py`** — 新增 10 个测试，总数从 45 → **55**：
  - `TestAgentDecision` (×3)
  - `TestBaseAgentRecording` (×2)
  - `TestSceneUnderstandingHeuristic` (×2)
  - `TestJellyArtefactResolution` (×3)

### Changed
* `BaseAgent` 重写：增加 `record_decision`、`drain_decisions`、`set_iteration`、
  `llm_enabled` 属性；使用 `getattr` lazy access 兼容不调用
  `super().__init__()` 的子类。
* `_run_scene_understanding()` 现在传 `gobj_list` / `scene_name` 给 Agent。

### Unchanged / Compatibility
* `vragent2.*` 命名空间完全保留；旧导入与 CLI 100% 可用。
* Unity .meta / Prefab / GUID / Package：**未触碰**。
* `UnityBridge` TCP 协议（端口 6400）：**未变**。
* `test_plan.json` 与 `benchmark.json` 输出格式：**未变**。
* `session_state.json` schema：仅追加字段，向后兼容。

### Verified
* `python -m compileall` 通过；
* `python -m tests.test_vragent2_smoke` 55/55 OK；
* `python -m xrplayer.jelly --port 2000` 启动成功；
  `GET /api/health` 返回 `{"ok": true, ...}`。
