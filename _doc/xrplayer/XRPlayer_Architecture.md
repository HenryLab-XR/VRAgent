# XRPlayer Architecture

> **状态**：本文件描述 XRPlayer 的当前模块布局与运行时数据流。所有路径均为仓库内真实路径。

XRPlayer 是 VRAgent 2.0 在生产环境下使用的产品名。运行时引擎仍位于
`TP_Generation/vragent2/`，对外门面在 `TP_Generation/xrplayer/`。两者共享同一份 `SharedWorldState` blackboard 与 `AgentDecision` 协作记录。

---

## 1. 模块分层

| 层 | 路径 | 职责 |
|---|---|---|
| **Engine** | `TP_Generation/vragent2/` | 多 Agent 协作核心：Controller、Agents、Contracts、Bridge、Retrieval、Graph |
| **Façade** | `TP_Generation/xrplayer/` | 重新导出 Engine 的稳定 API；提供 `python -m xrplayer` CLI |
| **Dashboard** | `TP_Generation/xrplayer/jelly/` | Jelly：本地 HTTP 仪表盘（stdlib `http.server`） |
| **Tests** | `TP_Generation/tests/test_vragent2_smoke.py` | 55 个 stdlib unittest 用例覆盖 contracts / agents / 集成 |

`vragent2` 的旧入口（`python -m vragent2.main`、`python -m vragent2.jelly`）仍然有效，只是
内部委托到 `xrplayer.jelly.__main__:main` 等新实现。这保证了既有脚本与文档不被破坏。

---

## 2. Agent 拓扑

```
                ┌──────────────────────────────────────┐
                │          VRAgentController           │
                │    (TP_Generation/vragent2/...)      │
                └──────────────────────────────────────┘
                          │
   Phase 0 ── SceneUnderstandingAgent ── (md docs + Unity hierarchy)
                          │
   Per-iteration loop ────┼──────────────────────────────────────
                          ▼
        ┌──── Planner ──── Verifier ── SemanticVerifier ──┐
        │                                                  │
        │                  ▼                               │
        │              Executor (online TCP / offline file)│
        │                  ▼                               │
        │              Observer  ────► Strategy/GateGraph │
        └──────── ObjectScheduler  ── ExplorationController┘
                          │
                          ▼
                   SharedWorldState (blackboard)
                          │
                          ▼
                  agent_decisions.json
                  jelly_status.json
                  → Jelly UI (port 2000)
```

每个 Agent 都继承自 `vragent2.agents.base_agent.BaseAgent`，必须实现
`run(input_data: dict) -> dict`，并通过 `record_decision(...)` 记录该次决策。

---

## 3. 数据流要点

1. **场景理解** — 由 `SceneUnderstandingAgent` 输出 `SceneUnderstandingOutput`
   （存储于 `world_state.scene_understanding`），现在同时接受
   `.md` 文档和 Unity 实时 hierarchy（`gobj_list`）。
2. **协作 trace** — 每个 Agent 在 `run()` 末尾调用 `self.record_decision(...)`，
   Controller 在 `_run_single_object` 内通过 `_drain_agent_decisions(agent)` 把这些
   `AgentDecision` 移入 `world_state.agent_decisions`，并增量持久化到
   `output_dir/agent_decisions.json`。
3. **Jelly 状态** — `Controller._write_jelly_status()` 在每次迭代结束后写入
   `output_dir/jelly_status.json`，Jelly 服务器以 3s 周期轮询渲染。
4. **Coverage 与门控** — `Observer` 输出 `coverage_delta` / `gate_hints`，
   `GateGraph` 持久化到 `output_dir/gate_graph.json`。

---

## 4. 关键源文件速查

- `TP_Generation/vragent2/controller.py` — 主调度器，含 `_drain_agent_decisions` 与 `_build_jelly_status`
- `TP_Generation/vragent2/contracts.py` — `AgentDecision`、`SharedWorldState`、`SceneUnderstandingOutput`
- `TP_Generation/vragent2/agents/base_agent.py` — 抽象基类与 decision-recording API
- `TP_Generation/vragent2/agents/scene_understanding.py` — 启发式 + LLM 合并
- `TP_Generation/xrplayer/jelly/server.py` — stdlib HTTP 仪表盘
- `TP_Generation/xrplayer/jelly/static/index.html` — 单页前端
