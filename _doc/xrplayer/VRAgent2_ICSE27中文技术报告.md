# VRAgent 2.0：面向 XR 应用的覆盖率驱动多智能体自动化测试技术报告

日期：2026-04-30

## 0. 面向 ICSE 2027 的投稿约束摘要

根据 ICSE 2027 Research Track Call for Papers 页面，本工作更适合选择 `Testing and Analysis` 作为主领域，`AI for Software Engineering` 作为可选副领域。需要特别注意：

- 投稿模板：ICSE 2027 Research Track 使用 IEEE conference proceedings template，而不是 ACM 模板。
- LaTeX 类：应使用 `\documentclass[10pt,conference]{IEEEtran}`，不能使用 `compsoc` 或 `compsocconf` 选项。
- 页数：主文最多 10 页，包含所有图、表、附录；另外最多 2 页只能放 references。
- 审稿：double-anonymous review，论文和 artifact 均需要匿名处理。
- 时间：mandatory abstract 截止 2026-06-23，submission 截止 2026-06-30，均为 AoE。
- 开放科学：建议提供匿名 artifact 或解释为什么不能开放。
- 生成式 AI 披露：如使用生成式 AI 生成文本、表格、代码等，需要在论文中按 ACM/IEEE 规则披露；正式投稿前应确认 double-anonymous 情况下的披露写法。

因此，本文档后续论文草稿按 IEEEtran 模板组织，并在图表、baseline、实验结果、artifact 链接处保留匿名占位符。

## 1. 研究问题与论文定位

### 1.1 背景

VR/XR 应用由 Unity 场景、Prefab、GameObject 层级、XR Interaction Toolkit 组件、C# 脚本事件、UI 状态、运行时对象生成与销毁共同构成。与传统 GUI 或 Web 应用相比，XR 应用测试面临更强的空间性、状态性和物理交互性：

- 交互对象不一定是按钮，可能是可抓取物、插槽、门、钥匙、开关、触发区域或动态生成物。
- 一个动作的效果可能不体现在被操作对象上，而体现在另一个对象、全局 flag、UI 面板、Inventory 或脚本内部状态上。
- Unity 对象引用不稳定，运行时对象、Prefab instance 和 scene object 的 FileID/GUID 解析容易失败。
- 代码覆盖率的提升通常依赖正确的交互前置条件，例如先拿钥匙再开门、先打开电源再触发设备。

现有 VRAgent 1.0 已经能够把 LLM 生成的 JSON test plan 导入 Unity，通过 FileID-based object resolution 动态附加 XRGrabbable/XRTriggerable/XRTransformable 等组件执行测试。但 VRAgent 1.0 的核心范式仍是“一次性生成 test plan，然后批量执行”。这导致它难以处理执行失败、状态门控和低收益重复动作。

### 1.2 核心问题

本工作的核心问题可以表述为：

> 如何让 LLM 参与的 XR 自动化测试从一次性计划生成，升级为能够利用项目知识、执行反馈和覆盖率信号持续调整策略的在线闭环系统？

更具体地说，系统需要解决三类失败：

1. 可执行性失败：对象找不到、组件缺失、方法签名不匹配、运行时引用失效。
2. 语义性失败：动作结构合法但无意义，例如反复抓取装饰物、触发不满足前置条件的门。
3. 探索性失败：覆盖率没有增长，但系统仍然沿线性顺序继续消耗预算。

### 1.3 论文主张

论文可以主张：

> 面向 XR 应用测试，覆盖率提升不是单靠更大的 LLM 或更长 prompt 能解决的问题，而需要一个可验证、可修复、可反馈的多智能体闭环。VRAgent 2.0 将项目检索、结构化 Planner/Verifier/Executor/Observer 协作、门控图推理和运行时覆盖反馈结合起来，使 XR 测试能够从静态计划转向在线探索。

## 2. 系统概述

### 2.1 从 VRAgent 1.0 到 VRAgent 2.0

VRAgent 1.0 的主流程是：

1. Python 端分析 Unity 项目，生成 scene dependency graph、gobj hierarchy 和脚本上下文。
2. LLM 根据静态上下文生成 JSON test plan。
3. Unity 端 VRAgent 导入 test plan，解析 FileID，动态附加 XR 组件，执行 Grab/Trigger/Transform 等动作。

VRAgent 2.0 将上述流程改造成在线闭环：

```text
SceneUnderstanding -> Scheduler -> Planner -> Static Verifier
                  -> Semantic Verifier -> Executor -> Observer
                  -> Blackboard/GateGraph update -> next iteration
```

系统通过 Python TCP client `UnityBridge` 与 Unity 端 `AgentBridge/VRAgentOnline` 交互。Python 每次发送单个 action 或 batch，Unity 执行后返回 state_before、state_after、events、exceptions、duration_ms 和 success。Observer 根据这些结果更新 SharedWorldState 和 GateGraph。

### 2.2 核心模块

| 模块 | 代码位置 | 论文中的角色 |
| --- | --- | --- |
| RetrievalLayer | `TP_Generation/vragent2/retrieval/` | 项目知识检索：场景、层级、脚本、组件、特殊逻辑 |
| PlannerAgent | `TP_Generation/vragent2/agents/planner.py` | 生成候选 Action Units，并根据 Observer 指令修正 |
| VerifierAgent | `TP_Generation/vragent2/agents/verifier.py` | 静态可执行性检查与结构化修复反馈 |
| SemanticVerifier | `TP_Generation/vragent2/agents/verifier.py` | LLM critic，检查语义合理性和前置条件 |
| ExecutorAgent | `TP_Generation/vragent2/agents/executor.py` | 确定性执行，记录 trace，计算 runtime novelty proxy |
| ObserverAgent | `TP_Generation/vragent2/agents/observer.py` | 弱 oracle，解释失败并推荐下一步策略 |
| ObjectScheduler | `TP_Generation/vragent2/scheduling/object_scheduler.py` | 基于优先级、失败历史、Observer bias 选择对象 |
| GateGraph | `TP_Generation/vragent2/graph/gate_graph.py` | 维护成功/失败边与门控前沿 |
| UnityBridge | `TP_Generation/vragent2/bridge/unity_bridge.py` | Python 和 Unity 运行时之间的在线协议 |
| VRAgentOnline | `VRAgent/Assets/Package/VRAgent2.0-PVEO/Online/` | Unity 侧动作执行、状态采集和日志采集 |

## 3. 方法设计

### 3.1 Project Retrieval Layer

RetrievalLayer 为每个 agent 构造不同粒度的上下文包，避免把整个项目无差别塞进 prompt。当前主要包括：

- object summary：对象 FileID、组件、子对象、tag/layer。
- scene meta：从 Unity 场景图中提取的局部元数据。
- relevant scripts：与对象关联的 C# 脚本源码。
- nearby interactables：同层级或同父节点下的潜在交互对象。
- special logic：tag/layer/GameObject.Find/Instantiate 等特殊依赖。
- gate hints 和 recent failures：上一轮 Observer 的反馈。

论文中应强调检索层的意义：它把 Unity 项目从“纯文本 prompt”转化为结构化、可查询的局部上下文，使 Planner 和 Verifier 可以围绕当前对象和当前目标生成动作，而不是盲目全局推理。

### 3.2 Contract-based Multi-Agent Pipeline

VRAgent 2.0 的 agent 输出采用 schema 化契约。例如：

- Planner 输出 `actions, intent, expected_reward`。
- Verifier 输出 `executable_score, errors, pass, patched_actions`。
- Executor 输出 `trace, coverage_delta, exceptions`。
- Observer 输出 `coverage_delta, bug_signals, next_exploration_suggestion, gate_hints, state_delta, failure_hypotheses, strategy`。

这种设计的论文卖点是：多智能体协作不是自由聊天，而是可测试、可记录、可复现的 pipeline。每一轮都有明确责任划分：Planner 只生成，Verifier 只审查，Executor 只执行，Observer 只观察与给策略反馈。

### 3.3 Static + Semantic Verification

Verifier 分为两层：

1. Rule-based static verifier：检查 FileID 是否存在、Grab 是否有 Rigidbody/Collider、Trigger 是否有 condition 和 methodCallUnits、脚本方法是否存在、重复动作是否存在。
2. LLM-based semantic verifier：检查动作是否符合场景语义、是否违反 gate chain、是否缺少前置条件、是否对装饰物或系统对象执行无效动作。

论文中可以将其定位为“LLM 生成不可信动作”的 guardrail。它不是为了完全证明动作正确，而是为了把高概率错误在执行前转化为结构化 repair signal。

### 3.4 Online Execution and Runtime Observation

Unity 端 `VRAgentOnline` 支持以下命令：

- `ImportObjects`：预解析 FileID 到 GameObject/Component。
- `Execute`：执行单个 ActionUnit。
- `ExecuteBatch`：顺序执行多个 ActionUnit。
- `QueryState`：查询对象状态。
- `QueryLogs`：读取 Unity Console 日志。
- `Reset`：清理运行时状态。

每个动作返回：

```json
{
  "success": true,
  "state_before": {},
  "state_after": {},
  "events": [],
  "exceptions": [],
  "duration_ms": 0
}
```

Observer 将这些信号转化为弱 oracle：

- 运行时异常或 Console error 是 bug signal。
- completed/direct_trigger 事件代表技术执行成功。
- state_before/state_after 差异代表对象状态变化。
- 无状态变化但已完成的 Trigger 不直接判定为失败，因为 XR 中事件常常改变其他对象或隐藏状态。

### 3.5 Runtime Coverage Proxy

当前系统最终仍需 Unity Code Coverage 作为真实 LC/MC 结果。但在线闭环不能等到整个实验结束才得到覆盖率，否则 Scheduler 和 Explorer 无法学习。因此 Executor 维护一个 runtime novelty proxy：

```text
r_t = 0.4 * delta_LC_proxy + 0.3 * delta_MC_proxy + 0.3 * delta_CoIGO_proxy
```

其中：

- `delta_LC_proxy` 来自新成功 action pattern 和新事件。
- `delta_MC_proxy` 来自新的 methodCallUnits。
- `delta_CoIGO_proxy` 来自新的对象状态变化。

这不是最终实验指标，而是在线决策的 reward signal。论文中应清楚区分“online reward proxy”和“offline ground-truth coverage measurement”。

### 3.6 Gate Graph and Failure-to-Condition Reasoning

GateGraph 将探索过程建模为：

- 节点：状态签名或 room/UI/object-level 状态。
- 成功边：动作导致可达状态。
- 失败边：动作失败，附带 failure_type 和 evidence。

Observer 从 trace、exceptions、console logs 中推断 failure condition，例如：

- locked
- need_item
- need_state
- ui_hidden
- reference_invalid

当系统发现门控失败时，下一轮 Scheduler/Planner 应优先尝试满足条件，而不是继续线性探索未测对象。

### 3.7 Object Scheduling and Limited Revisiting

VRAgent 2.0 不再简单遍历 GameObject 列表，而是用 ObjectScheduler 选择下一对象。fallback 打分考虑：

- SceneUnderstanding 的 object priority ranking。
- Observer 的 scheduler_bias。
- key_objects。
- 脚本数量、子对象数量、特殊逻辑字段。
- 每个对象失败次数。

更重要的是：当 Observer 点名一个已处理对象时，Scheduler 允许它有限重访。这对 XR 应用尤其重要，因为门、锁、按钮常常需要在新前置条件被满足后再次交互。

## 4. 论文贡献点梳理

建议论文贡献写成 4 点：

1. 问题建模：首次系统化刻画 LLM-based XR testing 中“一次性计划生成”在对象解析、语义门控和覆盖反馈方面的失败模式。
2. 方法：提出一个基于项目检索增强、契约式多智能体协作和 GateGraph 的在线 XR 测试生成框架。
3. 实现：实现 VRAgent 2.0，集成 Python 多智能体控制器、Unity 在线执行桥、FileID 解析、Verifier/Observer/Runtime coverage proxy。
4. 评估：在多个 Unity XR 应用上评估代码覆盖率、交互逻辑触发率、失败修复率、冗余动作比例和 token/time 成本，并与 VRAgent 1.0、NoTODG、Random/Greedy、LLM-only 等 baseline 对比。

## 5. 评估设计

### 5.1 Research Questions

| RQ | 问题 | 指标 |
| --- | --- | --- |
| RQ1 | VRAgent 2.0 是否提升 XR 应用代码覆盖率？ | Line coverage, method coverage, CoIGO |
| RQ2 | 多智能体闭环是否比一次性 LLM 生成更有效？ | coverage delta per budget, action success rate |
| RQ3 | 各组件贡献如何？ | ablation: no RAG, no Verifier, no Observer, no GateGraph, no revisit |
| RQ4 | 系统是否减少无效/冗余动作？ | duplicate rate, no-effect rate, invalid target rate |
| RQ5 | 成本是否可接受？ | token cost, wall-clock time, Unity execution time |

### 5.2 Subjects

候选 subject 可从当前 artifact 中选择：

- BowlingVR
- EE-Room
- EscapeTheRoom
- escapeVr
- maze
- Parkinson-VR
- UnityCityView
- UnityVR
- VGuns
- VR-Basics
- vr-firefighter-simulator
- VR-Room
- wheelchair-sim

正式论文中建议筛选 6 到 10 个项目，覆盖不同类型：room escape、training simulation、navigation、object manipulation、UI-heavy app。

### 5.3 Baselines

| Baseline | 说明 | 当前状态 |
| --- | --- | --- |
| VRAgent 1.0 one-shot | 单 LLM 一次性生成 test plan | 需要跑完整实验 |
| VRAgent 2.0 no RAG | Planner 不使用 RetrievalLayer context | 需要加开关或实验脚本 |
| NoTODG | 现有 `GenerateTestPlanNoTODG.py` | 已有脚本，可复用 |
| Random object/action | 随机选择对象和动作类型 | 需要实现简单 baseline |
| Greedy static | 按脚本数/组件数排序，一次性处理 | 可由 Scheduler fallback 固定化 |
| LLM-only online | 无 Verifier/Observer/GateGraph，仅在线调用 LLM | 需要 ablation |
| Coverage-guided fuzzing/RL | SOTA 或近似 baseline | 需要调研与可运行替代 |

### 5.4 Metrics

主要指标：

- LC：Unity Code Coverage 的 line coverage。
- MC：Unity Code Coverage 的 method coverage。
- CoIGO：Interesting Game Objects 被有效交互的覆盖比例。
- Action success rate：成功执行动作数 / 总动作数。
- Semantic success rate：产生状态变化或有效事件的动作数 / 总动作数。
- Gate solved count：被 GateGraph 标记为 solved 的 gate 数。
- Redundancy：重复动作比例、重复失败比例。
- Cost：LLM tokens、API 调用次数、运行时间。

### 5.5 Ablation Study

建议 ablation 矩阵：

| Variant | RAG | Verifier | Observer | GateGraph | Revisit | Coverage proxy |
| --- | --- | --- | --- | --- | --- | --- |
| Full VRAgent 2.0 | yes | yes | yes | yes | yes | yes |
| w/o RAG | no | yes | yes | yes | yes | yes |
| w/o Verifier | yes | no | yes | yes | yes | yes |
| w/o Observer | yes | yes | no | no | no | yes |
| w/o GateGraph | yes | yes | yes | no | yes | yes |
| w/o Revisit | yes | yes | yes | yes | no | yes |
| w/o Coverage Proxy | yes | yes | yes | yes | yes | no |

## 6. 图表规划

### Figure 1：System Overview

建议画成横向闭环图：

```text
Unity Project -> Retrieval Layer -> Blackboard
                                  -> Scheduler
                                  -> Planner -> Verifier -> Executor -> Observer
                                  <- GateGraph / Coverage / Failures
Unity Runtime <-------------------- UnityBridge -------------------- Executor
```

### Figure 2：Agent Contract Protocol

展示每个 agent 输入/输出 schema，例如 PlannerOutput、VerifierOutput、ExecutorOutput、ObserverOutput。

### Figure 3：GateGraph 示例

以 escape room 为例：

```text
S0 --Trigger Door--> blocked: locked
S0 --Grab Key--> S1
S1 --Trigger Door--> S2(open)
```

### Figure 4：Coverage Over Budget

横轴为 interaction budget，纵轴为 LC/MC/CoIGO，比较 Full、VRAgent 1.0、NoTODG、Random、w/o Observer。

### Table 1：Subject Apps

包含 project、scene count、GameObject count、MonoBehaviour count、event count、LOC。

### Table 2：Overall Effectiveness

包含 LC、MC、CoIGO、action success rate、gate solved count。

### Table 3：Ablation Results

各组件移除后的覆盖率下降和成本变化。

### Table 4：Failure Categories

统计 MissingObject、MissingComponent、InvalidMethod、NoStateChange、NeedItem、NeedState 等失败类型。

## 7. 当前工作还缺什么

为了达到 ICSE main track 的完整度，仍需要补齐：

1. 真实 Unity Code Coverage 增量接入或至少完整离线统计。
2. 多项目、多随机种子的实验结果。
3. baseline 和 ablation 的完整实现与运行脚本。
4. artifact 匿名化，包括仓库名、用户名、路径、API key、LLM 日志。
5. Related Work 的系统调研和引用。
6. overview 图、GateGraph 示例图、实验结果图表。
7. Threats to validity 与 Open Science 说明。

## 8. 推荐论文标题

候选英文标题：

1. Coverage-Guided Multi-Agent Exploration for Testing Unity XR Applications
2. From One-Shot Plans to Closed-Loop Exploration: Multi-Agent Testing of XR Applications
3. VRAgent 2.0: Retrieval-Augmented Multi-Agent Test Generation for Unity XR Applications
4. Gate-Aware LLM Agents for Coverage-Guided XR Application Testing

当前建议使用第 1 个，最直接面向 ICSE Testing and Analysis。

## 9. 投稿风险判断

### 优势

- 题目结合 XR testing、LLM agents、coverage-guided testing，属于 ICSE 2027 关注的 Testing and Analysis + AI4SE 交叉方向。
- 工程系统完整，有 Unity 端运行时执行，不只是 prompt 论文。
- 可以用真实开源 XR 项目评估，有 artifact 潜力。
- GateGraph 和 failure-to-condition 对 XR 场景有清晰动机。

### 风险

- 如果没有扎实实验，容易被认为只是系统集成或 prompt engineering。
- runtime coverage proxy 必须和真实 Code Coverage 明确区分，否则容易被质疑指标有效性。
- Multi-agent 架构需要证明每个 agent 的必要性，ablation 很重要。
- 与 GUI testing、game testing、LLM test generation、coverage-guided fuzzing 的关系需要写清楚。

### 最需要优先补的证据

1. Full VRAgent 2.0 相比 VRAgent 1.0 在 LC/MC/CoIGO 上显著提升。
2. w/o Observer / w/o Revisit / w/o Coverage Proxy 明显下降，证明闭环反馈是关键。
3. 失败分类显示 Verifier 和 Observer 能减少无效动作。
4. 至少 2 到 3 个 case study 展示 GateGraph 如何帮助打开门控交互链。
