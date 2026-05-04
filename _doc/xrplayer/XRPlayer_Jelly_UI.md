# Jelly — XRPlayer Local Dashboard

> Jelly 是 XRPlayer 的本地 Web 仪表盘，**默认监听 127.0.0.1:2000**，仅依赖
> Python 标准库（`http.server` + `socketserver`），不需要 pip install 任何东西。

---

## 1. 启动

推荐：

```powershell
cd <repo>\TP_Generation
python -m xrplayer.jelly --port 2000 --results-dir Results
```

兼容入口（旧脚本仍可用）：

```powershell
python -m vragent2.jelly --port 2000 --results-dir Results
```

可选参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--host` | `127.0.0.1` | 仅本机访问；改成 `0.0.0.0` 暴露到局域网 |
| `--port` | `2000` | TCP 端口 |
| `--results-dir` | `.` | 包含运行 artefacts 的根目录，可指向 `Results/` 或某具体场景目录 |
| `--auto-open` | off | 启动后自动打开默认浏览器 |

成功启动后会打印：

```
[jelly] serving XRPlayer dashboard on http://127.0.0.1:2000/
[jelly] watching results dir: D:\...\TP_Generation\Results
```

---

## 2. 端点（read-only JSON）

所有 `/api/*` 端点都接受可选 `?run=<scene>/<model>` 参数；不传时直接读 `--results-dir` 根。

| Endpoint | 内容 |
|---|---|
| `GET /` | 单页前端（`xrplayer/jelly/static/index.html`） |
| `GET /api/health` | `{"ok": true, "results_root": "..."}` |
| `GET /api/runs` | 自动发现的 `<scene>/<model>` 目录列表 |
| `GET /api/status` | `jelly_status.json`：当前轮次、模式、tested objects、coverage proxy、Unity bridge 状态 |
| `GET /api/scene_understanding` | `scene_understanding.json` 的合并结果 |
| `GET /api/agent_trace?limit=N` | `agent_decisions.json` 的最近 N 条决策 |
| `GET /api/coverage` | `summary.json` 的 explorer / token 统计 |
| `GET /api/gate_graph` | `gate_graph.json` 的 nodes / edges |
| `GET /api/iterations?limit=N` | `iteration_logs.json` 的最近 N 条 |
| `GET /api/test_plan` | `test_plan.json`（VRAgent 兼容格式） |

> Jelly **不写盘**。所有 artefacts 由 `VRAgentController` 在 `_drain_agent_decisions` /
> `_write_jelly_status` / `_finalize` 中产出。

---

## 3. 前端面板

| Tab | 数据源 | 用途 |
|---|---|---|
| Overview | `/api/status` + `/api/agent_trace?limit=10` | 总览卡片 + 最近 10 条决策；3s 自动刷新 |
| Scene Understanding | `/api/scene_understanding` | overview / key_objects / forbidden / roles |
| Agent Collaboration | `/api/agent_trace?limit=200` | 完整 trace 表格（iter · agent · summary · confidence · next_hint） |
| Coverage | `/api/coverage` | summary JSON |
| Gate Graph | `/api/gate_graph` | nodes / edges JSON |
| Iterations | `/api/iterations?limit=200` | per-object 表 |

刷新策略：
* 顶部 pulse 每 **3 s** 触发一次 `refreshOverview()`；
* 每 **15 s** 调用一次 `refreshAll()`；
* 每 **30 s** 重新发现可用 runs。

---

## 4. 安全

* 默认仅绑 `127.0.0.1`，外网不可见；
* 路径解析使用 `_resolve_artefact()`，对 `..` / 绝对路径 silently 降级为 root，
  无法读取 `--results-dir` 之外的文件；
* 静态资产路径同样禁止 `..`；
* **不在 UI 显示 API key**：所有 LLM 配置仅出现在 `summary.token_usage`
  / `world_state` 摘要中，敏感字段从未写入 `agent_decisions`。

---

## 5. 验证

```powershell
$proc = Start-Process E:/--SoftWare/python.exe `
  -ArgumentList "-m","xrplayer.jelly","--port","2000","--results-dir","Results" `
  -WorkingDirectory "<repo>\TP_Generation" -WindowStyle Hidden -PassThru
Start-Sleep 2
(Invoke-WebRequest http://127.0.0.1:2000/api/health -UseBasicParsing).Content
Stop-Process -Id $proc.Id -Force
```

期望输出：

```
{"ok": true, "results_root": "...\\TP_Generation\\Results"}
```
