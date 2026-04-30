# VRAgent2 XR 探索覆盖率瓶颈诊断与改进

日期：2026-04-30

## 结论摘要

当前多智能体在 XR 应用上探索效果差，核心不是“LLM 不够聪明”，而是闭环反馈链路没有真正把“是否触发了交互逻辑、是否产生了新覆盖、下一步该优先哪里”传回 Planner 和 Scheduler。

这次检查确认了几个主因：

1. Executor 的覆盖增量长期为 0，Explorer/Observer/Scheduler 缺少可用 reward signal。
2. Unity Bridge 返回的 `success` 没进入 Python trace，Controller 后续只能靠源对象状态变化判断成功，导致大量 Trigger 被误判为失败。
3. Observer 即使推断出下一步建议，Planner 之前没有真正消费 `observer_instruction` 和共享 world state。
4. Scheduler 把对象“一次处理后永久排除”，门控对象、钥匙、按钮这类需要重访的 XR 交互无法形成闭环。
5. fallback 调度过于接近线性顺序，在 LLM 不可用或输出不稳定时容易先消耗预算在低价值装饰物上。

## 关键代码改进

### 1. 运行时覆盖代理

修改位置：`TP_Generation/vragent2/agents/executor.py`

原先 `_compute_coverage()` 直接返回：

```python
CoverageDelta(LC=0.0, MC=0.0, CoIGO=0.0)
```

这会让 Explorer 永远认为没有新增覆盖，触发 Recover 或继续盲目 Expand。现在改为在线 runtime novelty proxy：

- 新成功 action pattern 计入 LC 代理；
- 新触发事件和直接触发事件计入 LC 代理；
- action 中新的 `methodCallUnits` 计入 MC 代理；
- 真实对象位置/旋转/active/scale 改变计入 CoIGO 代理。

注意：这不是最终 Unity Code Coverage 的替代品。最终 benchmark 仍然应解析 Unity CodeCoverage 的 `Summary.xml`。这个代理的意义是给在线探索提供即时 reward，避免闭环在运行中失明。

### 2. 保留 Unity 执行成功信号

修改位置：`TP_Generation/vragent2/contracts.py`、`TP_Generation/vragent2/agents/executor.py`、`TP_Generation/vragent2/controller.py`

`TraceEntry` 新增：

```python
success: bool = False
duration_ms: float = 0.0
```

Executor 会把 Unity Bridge 的 `success` 和 `duration_ms` 写进 trace。Controller 的 `_is_trace_success()` 现在会识别：

- `completed:*`
- `fallback_completed:*`
- `direct_trigger:*`
- `dispatched:*`
- `success=True`

这样 Trigger 类动作即使没有改变“源对象”状态，只要事件/方法确实完成，也不会被当成失败边写入 Gate Graph。

### 3. 减少 Trigger 的误报失败

修改位置：`TP_Generation/vragent2/agents/observer.py`

XR 中很多按钮、门锁、脚本事件并不会改变被触发的 source object，而是改变另一个对象、全局 flag、UI panel 或脚本内部状态。过去 Observer 看到 `state_before == state_after` 就加入 `[NO_STATE_CHANGE]`，这会把有效 Trigger 错误反馈给 Scheduler/Planner。

现在规则改为：

- 已完成的 Trigger/DirectTrigger：记录为“执行完成，但源对象没有状态变化”，不作为 bug；
- 未完成且无状态变化：才作为 no-effect/semantic failure；
- 有异常、bridge error、import error：仍然作为失败。

### 4. Observer 建议进入 Planner

修改位置：`TP_Generation/vragent2/agents/planner.py`

Planner 现在会接收并注入：

- 当前 exploration goal；
- Observer 的 `planner_instruction`；
- SharedWorldState 摘要；
- gate hints；
- recent trace failures。

这让 Planner 不再只是“按对象静态生成一批动作”，而是能根据上一轮失败和门控推断做局部修复或换策略。

### 5. 调度器支持有限重访

修改位置：`TP_Generation/vragent2/scheduling/object_scheduler.py`

原逻辑只选择 `not in processed` 的对象，导致已经测试过的门、按钮、钥匙无法在获取新信息后重试。

现在如果对象出现在 Observer 的 `scheduler_bias` 中，并且失败次数低于 `max_revisits`，即使已经 processed，也允许再次进入候选集。fallback 调度也从线性顺序升级为覆盖导向打分：

- Observer bias 权重大；
- SceneUnderstanding priority ranking 权重大；
- key_objects 加分；
- 有脚本、有子对象、有特殊逻辑加分；
- 多次失败对象扣分。

## 为什么这些改动会改善覆盖率

覆盖率提升依赖三个条件：

1. 能识别“刚才做了有效事”；
2. 能把有效/无效反馈转化为下一步动作选择；
3. 能在发现门控关系后回到关键对象，而不是一次性扫过。

之前第 1 点和第 3 点基本断裂：执行结果没有变成 reward，关键对象也不能重访。修改后，闭环至少具备了基础的正反馈和重试能力。

## 仍建议继续做的算法优化

### A. 真正接入 Unity CodeCoverage 增量

当前 runtime novelty proxy 可以驱动在线探索，但最终目标仍是代码覆盖率。建议在 Unity Bridge 增加 `QueryCoverage` 命令：

```json
{ "type": "QueryCoverage", "scope": "delta" }
```

Unity 侧返回最近一轮新增覆盖的 method/class/line 信息，Python 侧把它合并进 `CoverageDelta`。这样 Observer 的 reward 就能从代理信号升级为真实覆盖信号。

### B. 记录方法级事件名

现在 Executor 只能从 action JSON 的 `methodCallUnits` 推断“计划调用了哪些方法”，但 Unity 侧最好在 `ParameterResolver` 或 direct invocation 处记录实际执行的方法名，例如：

```text
method_invoked:DoorController.OpenDoor
method_invoked:Inventory.AddItem
```

这样 MC reward 可以基于真实执行，而不是基于计划内容。

### C. 引入 bandit 式 action pattern 选择

为每类对象维护 action pattern 的收益统计：

- `Trigger(method)`
- `Grab(to object)`
- `Grab(to position)`
- `Transform(delta)`
- `Socket(insert/remove)`

用 UCB/Thompson Sampling 在同类对象上优先选择历史收益高、但仍有探索价值的 pattern，避免重复生成低收益动作。

### D. Gate Graph 使用状态签名而不是对象名

当前 Gate Graph 的 node 主要按对象名建状态，表达不了“门已开 / UI panel 已显示 / inventory 有 key”这类状态变化。建议状态签名加入：

- active UI；
- 已触发事件；
- 最近 changed_objects；
- inferred facts；
- open/blocked gates。

这会让 Expand/Exploit/Recover 更接近真实状态机。

## 本次验证

已运行：

```powershell
Set-Location TP_Generation
E:/--SoftWare/python.exe -m compileall vragent2 tests/test_vragent2_smoke.py
E:/--SoftWare/python.exe -m tests.test_vragent2_smoke
```

结果：45 条 smoke tests 全部通过。