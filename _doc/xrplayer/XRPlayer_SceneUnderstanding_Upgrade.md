# SceneUnderstandingAgent — XRPlayer Upgrade

> 描述对 `vragent2/agents/scene_understanding.py` 做的强化：从"只能消费 .md 文档"
> 升级为"启发式 + LLM 双源合并"。**未新建重复模块**，所有改动落在原文件上。

---

## 1. 背景

旧实现仅在 `scene_doc_path` 指向一个 markdown 文件时才能产出
`SceneUnderstandingOutput`；当用户没写场景文档时，`world_state.scene_understanding`
是空壳，Planner 完全没有项目级上下文。

XRPlayer 升级目标：
1. 即使没有 `.md` 文档，也能基于 Unity hierarchy 输出有用的场景理解；
2. 同时存在文档和 hierarchy 时，自动合并两者；
3. 把推理过程写入 `AgentDecision`，供 Jelly 展示。

---

## 2. 新输入

`run(input_data)` 现在接受：

| key | 类型 | 说明 |
|---|---|---|
| `scene_doc_path` | str (可选) | `.md` 文件或包含 `.md` 的目录 |
| `extra_context` | str (可选) | 额外 prompt 片段，例如 README |
| `hierarchy_json_path` | str (可选) | 直接指向 `gobj_hierarchy.json` |
| `gobj_list` | `List[dict]` (可选) | 已加载的 hierarchy；优先于路径 |
| `scene_name` | str (可选) | 进入 fallback overview |

---

## 3. 启发式分类

`_classify_object(name, entry) -> (score, role)` 把每个 GameObject 归为：

| role | 触发条件 | 写入位置 |
|---|---|---|
| `system` | 名称命中 `_SYSTEM_HINTS`（manager/rig/camera/eventsystem/...) | `forbidden_test_objects` |
| `agent_internal` | 组件或脚本含 agentbridge / fileidmanager / vragent | `forbidden_test_objects` |
| `decoration` | 名称命中 `_DECORATION_HINTS`（wall/floor/terrain/...) 且无可交互组件 | 不进入排序 |
| `interactable` | 组件或名称命中 `_INTERACTABLE_HINTS`（xrgrab / button / lever / door / key / ...） | `key_objects`、`object_priority_ranking` |

得分公式：
* 组件命中关键字：`+3.0`
* 名称命中关键字：`+1.5`
* 持有 MonoBehaviour：`min(2.0, 0.5 × N)`
* 子物体数量：`min(1.0, 0.1 × N)`

按 `(-score, name)` 稳定排序，截断到 50。

---

## 4. LLM + 启发式合并

`_merge(llm, heuristic, fallback_overview)`：

* `scene_overview`、`interaction_dependencies` 等自由文本字段：**LLM 优先**；
  若 LLM 缺失则回退到 heuristic。
* `key_objects` / `forbidden_test_objects` / `object_priority_ranking`：取并集，
  通过 `_ordered_unique` 保留首次出现顺序，截断到 60。
* `object_roles`：LLM 已存在的 key 不被覆盖；heuristic 仅做补全。

合并后的对象：

```python
SceneUnderstandingOutput(
    scene_overview=...,
    key_objects=[...],
    forbidden_test_objects=[...],
    object_priority_ranking=[...],
    object_roles={...},
    interaction_dependencies=[...],
    oracle_hints=[...],
)
```

---

## 5. AgentDecision 输出

`run()` 末尾会调用：

```python
self.record_decision(
    summary=f"Scene understood ({sources}): "
            f"{N_key} key obj, {N_forbid} forbidden, {N_dep} deps",
    confidence=0.7 if had_llm else 0.4 if had_heuristic else 0.0,
    inputs={...},
    outputs={...},
    next_hint="Planner should consult key_objects and avoid forbidden",
)
```

`sources` 取值范围：`"docs+heuristic+llm"` / `"docs+llm"` / `"heuristic"` / `"docs-only"`。

---

## 6. 测试

`tests/test_vragent2_smoke.py::TestSceneUnderstandingHeuristic` 覆盖：
* `DoorPantry` / `RedKey` 出现在 `key_objects`；
* `GameManager` 落入 `forbidden_test_objects` 且 `role == "system"`；
* `FloorTile_01` 不进入测试列表；
* 无 LLM 模式下 `run()` 仍然返回非空输出并发出 1 条 `AgentDecision`。
