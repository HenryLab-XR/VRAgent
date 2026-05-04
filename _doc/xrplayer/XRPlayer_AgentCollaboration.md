# XRPlayer Agent Collaboration

> 描述 XRPlayer 中各 Agent 的职责、契约与协作时序，以及 `AgentDecision` trace 机制。

---

## 1. Agent 职责矩阵

| Agent | 输入主键 | 输出主键 | 决策意图 |
|---|---|---|---|
| `SceneUnderstandingAgent` | `scene_doc_path` / `gobj_list` / `scene_name` | `SceneUnderstandingOutput` | 把项目级知识压缩成可被 Planner 消费的 prompt |
| `PlannerAgent` | `gobj_info`、`goal`、`gate_hints`、`recent_trace`、`scene_context` | `PlannerOutput { actions, intent, expected_reward }` | 在不知道执行细节的前提下生成动作候选 |
| `VerifierAgent` | `actions`, `shared_context` | `VerifierOutput { passed, errors, patched_actions, executable_score }` | 形式化检查（FileID、方法签名、目标存在性） |
| `SemanticVerifierAgent` | `actions`, `world_state`, `planner_intent`, `recent_failures` | `SemanticVerifierOutput { verdict, reason, ... }` | 语义层面拒绝重复或与目标冲突的方案 |
| `ExecutorAgent` | `actions` | `ExecutorOutput { trace, coverage_delta, exceptions }` | 通过 Unity Bridge 真实执行或离线录制 |
| `ObserverAgent` | `executor_output`, `console_logs`, `goal`, `actions`, `world_state` | `ObserverOutput { coverage_delta, bug_signals, gate_hints, strategy, recommended_mode, ... }` | 状态分析 → 影响下一轮 mode / scheduler bias |

`ObjectScheduler` 不是 BaseAgent 子类（它消费 `world_state.scheduler_bias`），但仍参与
协作记录：每次选择的对象会出现在 `iteration_logs.json`。

---

## 2. AgentDecision 协作记录

每个 Agent 在 `run()` 完成前都会调用：

```python
self.record_decision(
    summary="Planned 5 actions",
    confidence=0.7,
    inputs={"goal": ..., "gobj": ...},
    outputs={"n_actions": 5, ...},
    evidence=["..."],
    next_hint="Verifier should check FileIDs",
)
```

`AgentDecision` 字段（来自 `vragent2/contracts.py`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `iteration` | int | Controller 写入的轮次编号；场景理解阶段为 -1 |
| `agent` | str | 默认是子类类名，可被 `name = "..."` 覆盖 |
| `summary` | str | 一行摘要（Jelly 表格首列），最长 200 chars |
| `confidence` | float | `[0,1]`；用于 Jelly 进度条 |
| `inputs` / `outputs` | dict | 关键键值对；自动 truncate（list/dict 仅显示长度） |
| `evidence` | list[str] | 支持决策的证据片段（最多 5 条） |
| `next_hint` | str | 给下游 Agent 的指示 |
| `duration_ms` | float | 以 `time.monotonic()` 测量 |
| `timestamp` | str | ISO-8601（UTC） |

Controller 通过 `_drain_agent_decisions(agent)` 在每个 Agent.run() 之后立刻
把记录搬到 `world_state.agent_decisions`，并增量写盘到 `agent_decisions.json`。
列表上限 500 条，避免长跑膨胀。

---

## 3. 一次迭代的完整时序

```
controller.iteration = N
└─ agent.set_iteration(N)        # 标记所有 5 个 Agent
   ├─ Planner.run()              → record_decision(...)
   ├─ Verifier.run()             → record_decision(...)
   ├─ SemanticVerifier.run()     → record_decision(...)
   ├─ Executor.run()             → record_decision(...)
   └─ Observer.run()             → record_decision(...)
└─ _write_jelly_status()         # 刷新 dashboard pulse
└─ save_session()                # 增量持久化
```

Jelly UI 通过 `/api/agent_trace?limit=200` 拉取最近 200 条决策，按
`(iteration, agent)` 顺序倒序展示，实时观察 "谁决策了什么 → 谁受到影响"。

---

## 4. 失败回路

* `Verifier.passed == False` ⇒ Controller 不会推进到 Executor，但仍会写入决策记录，
  Planner 在下一轮收到 `recent_failures`。
* `Observer.bug_signals` 与 `failure_hypotheses` ⇒ 注入 GateGraph，作为后续
  `gate_hints` 反馈给 Planner（白盒 guided exploration）。
* `SemanticVerifier.verdict == "reject"` ⇒ Controller 记录拒绝原因到
  `world_state.recent_failures`，让 Planner 收到的 prompt 中能看到"上次为何被否"。

这种失败 → 反馈 → 修复的循环不依赖任何 LLM 自由文本，所有跨 Agent 信息均通过
schema-validated 字段传递，从而把"聊天"变成"可测 pipeline"。
