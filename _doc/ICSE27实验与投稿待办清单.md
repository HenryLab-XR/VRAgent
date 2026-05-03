# ICSE 2027 实验与投稿待办清单

## 1. 模板与格式

- [ ] 使用 IEEE conference proceedings template。
- [ ] LaTeX 使用 `\documentclass[10pt,conference]{IEEEtran}`。
- [ ] 主文不超过 10 页，references 最多 2 页。
- [ ] 不能使用 `compsoc` 或 `compsocconf`。
- [ ] PDF 中不能出现作者、单位、实名仓库、个人路径、API key、非匿名 artifact 链接。
- [ ] Abstract 在 2026-06-23 23:59:59 AoE 前提交。
- [ ] Full paper 在 2026-06-30 23:59:59 AoE 前提交。

## 2. 论文结构待办

- [ ] 最终确定标题。
- [ ] 将 introduction 改成强结果导向，补充真实数值。
- [ ] 添加 Figure 1 system overview。
- [ ] 添加 Figure 2 GateGraph case study。
- [ ] 添加 Figure 3 coverage-over-budget 曲线。
- [ ] 添加 Table 1 subject apps。
- [ ] 添加 Table 2 overall effectiveness。
- [ ] 添加 Table 3 ablation。
- [ ] 添加 Table 4 failure categories。
- [ ] 补全 Related Work 真实引用。
- [ ] 补全 Threats to Validity 的统计方法。
- [ ] 补全 Artifact Availability。
- [ ] 补全生成式 AI 使用披露。

## 3. 实验实现待办

- [ ] 统一实验 runner，支持固定 budget、model、scene、seed。
- [ ] 支持 Full VRAgent 2.0。
- [ ] 支持 VRAgent 1.0 one-shot baseline。
- [ ] 支持 NoTODG baseline。
- [ ] 支持 Random baseline。
- [ ] 支持 Greedy static baseline。
- [ ] 支持 LLM-only online baseline。
- [ ] 支持 ablation flags：no RAG、no Verifier、no Observer、no GateGraph、no Revisit、no Runtime Proxy。
- [ ] 每个 subject 至少重复运行 3 到 5 次。
- [ ] 保存每次运行的 prompt、response、actions、traces、coverage、token usage、wall-clock time。

## 4. Coverage 接入待办

- [ ] 确认 Unity Code Coverage package 在所有 subject 项目中可用。
- [ ] 统一 coverage report 路径。
- [ ] 解析 `Summary.xml` 的 line coverage 和 method coverage。
- [ ] 收集 per-class coverage，定位哪些脚本被触发。
- [ ] 实现或模拟在线 `QueryCoverage` 命令，用于每轮 coverage delta。
- [ ] 将 runtime coverage proxy 与真实 coverage 做相关性分析。

## 5. Subject Apps 数据待办

候选 subject：

- [ ] BowlingVR
- [ ] EE-Room
- [ ] EscapeTheRoom
- [ ] escapeVr
- [ ] maze
- [ ] Parkinson-VR
- [ ] UnityCityView
- [ ] UnityVR
- [ ] VGuns
- [ ] VR-Basics
- [ ] vr-firefighter-simulator
- [ ] VR-Room
- [ ] wheelchair-sim

每个 subject 需要统计：

- [ ] Scene 数量。
- [ ] GameObject 数量。
- [ ] MonoBehaviour 数量。
- [ ] UnityEvent / method binding 数量。
- [ ] C# LOC。
- [ ] XR interaction component 数量。
- [ ] 是否包含门控交互链。

## 6. Baseline 对比待办

- [ ] VRAgent 1.0：同 budget 下生成并执行 test plan。
- [ ] NoTODG：使用 `GenerateTestPlanNoTODG.py`。
- [ ] Random：随机对象 + 随机合法 action pattern。
- [ ] Greedy static：按脚本数、事件数、组件数排序。
- [ ] LLM-only online：保留在线 LLM，关闭 Verifier/Observer/GateGraph。
- [ ] 近似 SOTA：调研 Unity/VR/game/GUI testing 可运行工具，若不可运行，需要在论文中解释。

## 7. Artifact 匿名化待办

- [ ] 新建匿名仓库或匿名压缩包。
- [ ] 移除用户名、机器路径、API key、私有链接。
- [ ] 提供 `README.md`：环境、依赖、运行命令、复现实验表格。
- [ ] 提供 Docker/conda/requirements 或明确 Python/Unity 版本。
- [ ] 提供 raw results 和 analysis scripts。
- [ ] 提供最小 subject 或可公开 subject。
- [ ] 检查所有文件是否泄露作者身份。

## 8. 当前已完成的工程验证

- [x] Python 编译检查：`E:/--SoftWare/python.exe -m compileall vragent2 tests/test_vragent2_smoke.py`。
- [x] Smoke tests：`E:/--SoftWare/python.exe -m tests.test_vragent2_smoke`，45 tests passed。
- [x] `git diff --check` 无格式错误。
- [x] 已生成中文诊断文档。
- [x] 已生成中文技术报告。
- [x] 已生成 ICSE 2027 IEEEtran 论文初稿。
