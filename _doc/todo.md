请先在 VSCode / Codex 的用户级或账号级 skills 配置中安装并启用：
https://github.com/forrestchang/andrej-karpathy-skills

注意：

- 这是 VSCode 账号级或用户级 skill，不要安装到当前 XRPlayer 仓库里；
- 本次代码修改只允许发生在 XRPlayer/beta 分支中与需求直接相关的文件里。

当前分支是 XRPlayer/beta。请做一次小范围修复，不要大重构。

目标一：修正 Kitchen gold test plan

我调整了 Kitchen 场景的 NavMesh 可达性。现在进入房间前需要先开门。

请检查 Kitchen 相关 gold test plan，把跨房间移动前的步骤改成：

接近/定位门对象 → 使用符合 VRExplorer / VRAgent action schema 的 trigger action 执行 Open Door → 再进入房间 → 继续原任务。

约束：

- action 必须符合 VRExplorer / VRAgent 当前动作约束；
- 不要写自由文本动作；
- 不要绕过 Executor / EAT / HAU 绑定机制；
- 不要在 Unity 侧硬编码自动开门；
- 不要破坏 Kitchen 做菜任务原有顺序；
- 如果 object name、trigger name、action 参数不一致，优先修正 plan 绑定。

目标二：修复 Unity Code Coverage 与 test plan 的映射

注意：Unity Code Coverage 插件导出的 summary report 本身不区分 test plan。它只会覆盖 summary，或在 summary 中新增 history node。因此不能假设一个 coverage report 就对应一个 test plan。

需要实现的是：

- 每次执行 test plan 时，XRPlayer 自己记录 run metadata；
- metadata 至少包含 scene、model、test_plan_id/test_plan_name、run_id、start_time、end_time、result_dir；
- 解析 Unity Code Coverage summary report 中的 history nodes；
- 用 run metadata 把 coverage history node 关联回 test plan run；
- 对同一个 test plan 关联到的所有 coverage nodes，取最高 Code Coverage；
- 如果无法可靠关联，显示 missing / unmapped，不要硬猜。

优先用时间窗口匹配：coverage node timestamp 落在某个 test plan run 的 start_time/end_time 附近，就归属该 run。若已有 run_id、result_dir、report_path、generated_time 等字段，也可以一起用于更稳的匹配。

如果当前 metadata 不够，请只补一个最小 run_metadata.json，例如写到：
Results/<scene>/<model>/<run_id>/run_metadata.json

目标三：统一 Results 目录结构

目前 workflow 前两步生成的分析前置数据被放在 Results/Results_<scene>/，但后续结果又在 Results/<scene>/，导致结果目录割裂。

请修正 workflow 生成路径：

- 所有与某个 scene 相关的前置分析数据、运行结果、metadata、coverage 映射数据，都应统一放到 Results/<scene>/ 下；
- 不再默认生成 Results/Results_<scene>/ 这种平行目录；
- 如需兼容旧数据，可以只做只读 fallback，不要继续写入旧目录；
- 修改后确保后续 Benchmark / Diagnose 都读取统一后的 Results/<scene>/ 结构。

目标四：Coverage tab 改为 Diagnose tab

把前端顶部 Coverage tab 改名为 Diagnose。

Diagnose 页面仍显示 coverage，但作为诊断信息的一部分。至少显示：

- 当前 scene / model / test plan；
- 当前 run_id 或 result_dir；
- coverage 是否来自真实 Unity summary report；
- 匹配到的 coverage history node 数量；
- 当前 test plan 对应节点中的最高 Code Coverage；
- coverage report 路径；
- missing / unmapped / no report 状态。

不要沿用旧 snapshot、mock coverage、缓存 JSON。没有真实 report 或无法映射时，显示 missing / unmapped。

目标五：Benchmark 页面加入 Code Coverage

Benchmark 页面新增 Code Coverage 列。

要求：

- Benchmark 的 Code Coverage 必须复用 Diagnose 的同一套 backend coverage 解析与映射逻辑；
- 不要写 benchmark 专用 coverage 逻辑；
- 每一行根据 scene / model / test_plan_id / run_id 查对应 coverage；
- 对该 test plan 关联到的 coverage history nodes 取最高值；
- 无法关联时显示 missing / unmapped；
- 原有“覆盖代理”不要和 Unity Code Coverage 混淆，建议显示为 Agent Coverage / Plan Coverage；
- 新增的 Unity 真实覆盖率列命名为 Code Coverage。

目标六：文档和最小验证

修改 docs/devlog，记录本次改动。

最后输出：

1. 修改了哪些文件；
2. Kitchen gold test plan 是否已加入符合 VRExplorer / VRAgent 约束的 Open Door trigger action；
3. 是否新增或修正 run_metadata.json；
4. Results/Results_<scene>/ 是否停止作为默认写入目录；
5. workflow 前置分析数据是否统一到 Results/<scene>/；
6. 是否能解析 Unity Code Coverage summary history nodes；
7. 是否能把 coverage node 映射回 test plan run；
8. Diagnose 是否显示真实 report、匹配节点数量、最高 coverage；
9. Benchmark 是否新增 Code Coverage 列，并复用 Diagnose 的同一套数据来源；
10. 无法映射时是否显示 missing / unmapped；
11. 剩余风险。

执行原则：

- 先读现有代码再改；
- 只改本次需求直接相关文件；
- 不做无关重构；
- 不新增复杂框架；
- 每个改动都要有对应验证；
- 如果发现无法确定的旧数据格式，只标记 fallback / unmapped，不要凭空推断。