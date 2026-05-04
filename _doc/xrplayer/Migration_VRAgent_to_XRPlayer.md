# Migration: VRAgent → XRPlayer

> 旧 `vragent2` 包**完全保留**，所有公开 API 仍然可用。XRPlayer 只是把这套 API
> 重新打包到一个更稳定的命名空间下。本文件给出"新→旧"对照与迁移步骤。

---

## 1. 命名空间映射

| 旧位置 (`vragent2`) | 新位置 (`xrplayer`) | 状态 |
|---|---|---|
| `vragent2.controller.VRAgentController` | `xrplayer.VRAgentController` | re-export |
| `vragent2.contracts.SharedWorldState` | `xrplayer.SharedWorldState` | re-export |
| `vragent2.contracts.AgentDecision` | `xrplayer.AgentDecision` | new in v0.1 |
| `vragent2.contracts.PlannerOutput` 等 | `xrplayer.PlannerOutput` 等 | re-export |
| `python -m vragent2.main` | `python -m xrplayer` | thin delegator |
| `python -m vragent2.jelly` | `python -m xrplayer.jelly` | 兼容入口仍可用 |

---

## 2. 迁移步骤

1. **导入路径**（可选）：把 `from vragent2.contracts import ...` 改成
   `from xrplayer import ...`。旧导入仍然 work。
2. **CLI**：把脚本里的 `python -m vragent2.main` 改成 `python -m xrplayer`，
   参数完全一致。
3. **Jelly**：新场景下推荐 `python -m xrplayer.jelly --port 2000 --results-dir <path>`。
   `python -m vragent2.jelly` 等价。
4. **Unity 端**：`UnityBridge` 的 TCP 协议（端口 6400）未变；
   `Online` 模块代码不需要改动。
5. **测试**：原先依赖 `vragent2.*` 的测试无需改动；新增能力建议直接 import
   `xrplayer`。

---

## 3. 不变量

* Unity .meta / Prefab / Package / GUID **从未被触碰**。
* 旧 test plan JSON 格式（VRAgent 1.0 兼容格式）继续由 `_build_test_plan()` 输出。
* 旧 benchmark 写入入口 `append_benchmark(...)` 保持不变。
* 旧 session 恢复机制 (`session_state.json`) 与字段保持兼容。

---

## 4. 何时仍然要用 `vragent2.*`？

* 直接深入 Engine 内部 hook（例如自定义 `agents/` 子类、复用 `retrieval/`
  或 `graph/` 工具）时。
* 修改、调试 Engine 自身实现时。

外部使用者（实验脚本、CI、文档示例）应优先使用 `xrplayer.*`。
