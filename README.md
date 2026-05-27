# XRPlayer / VRAgent 启动与环境安装指南

当前分支：`XRPlayer/beta`

这个仓库把三部分放在了一起：

- `VRAgent/`：真正要用 Unity Hub 打开的 Unity 工程
- `TP_Generation/`：Python 侧分析、测试计划生成、`vragent2` 和 Jelly 面板
- `_doc/`：架构说明、Jelly 设计说明、迁移文档

如果你只记一件事，请记这个：

> Unity 要打开的是 `VRAgent/` 子目录，不是仓库根目录。

## 1. 仓库结构

| 路径 | 作用 |
| --- | --- |
| `VRAgent/` | Unity 工程根目录 |
| `VRAgent/Assets/SampleScene/` | 示例场景，推荐先从 `Kitchen_TestRoom` 跑通 |
| `TP_Generation/` | Python 工具链、Jelly、`vragent2` |
| `TP_Generation/Results/` | 分析结果、生成结果、回放结果 |
| `TP_Generation/start_jelly.ps1` | 启动 Jelly 本地面板 |
| `TP_Generation/check_env.py` | 检查 Python 依赖和内置分析器是否齐全 |
| `_doc/xrplayer/` | 分支内 XRPlayer/Jelly 相关设计文档 |

## 2. 环境要求

### 必需

- Windows
- Git
- Unity `2021.3.45f1c2`
- Python `3.8.x`（当前分支推荐）

### 按需

- OpenAI 兼容 API Key
  - 只有在你要跑 `SpecialLogicPreprocessor.py`、`GenerateTestPlanModified.py` 或 `python -m vragent2` 的 LLM 流程时才需要
  - 如果你只是导入现成 `test_plan.json` 或做 Unity 侧回放，不需要 API Key

### 第一次打开 Unity 时的网络要求

`VRAgent/Packages/manifest.json` 里声明了 Git 依赖：

- `com.henrylab.vrexplorer`: `https://github.com/TsingPig/VRExplorer_Release.git`

所以第一次在新机器上打开 Unity 工程时，需要联网让 Package Manager 拉包。

## 3. 克隆仓库并安装 Python 环境

```powershell
git clone https://github.com/HenryLab-XR/VRAgent.git
cd VRAgent
git checkout XRPlayer/beta
```

创建并激活虚拟环境：

```powershell
py -3.8 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python TP_Generation\check_env.py
```

如果你还要跑测试工具：

```powershell
python -m pip install -r TP_Generation\requirements-dev.txt
python TP_Generation\check_env.py --dev
```

`check_env.py` 会检查三件事：

- Python 版本是否满足要求
- `networkx`、`openai`、`jsonschema` 是否已安装
- `TP_Generation/` 下的三个内置分析器 `.exe` 是否存在

现在它还会额外检查这些包是不是“看起来装了，但其实已经损坏”。
例如这次 Jelly GUI 里出现的：

```text
AttributeError: module 'networkx' has no attribute 'Graph'
```

就不是代码逻辑错误，而是当前 `.venv` 里的 `networkx` 安装不完整。

之后每次打开新终端，只需要：

```powershell
cd <repo-root>
.\.venv\Scripts\activate
```

## 4. 配置 API Key（只在 LLM 流程需要时做）

推荐直接用环境变量：

```powershell
$env:OPENAI_API_KEY = "<your-api-key>"
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
```

当前分支里常见的读取顺序如下：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_API_BASE`
- 命令行参数 `--api_key` / `--api_base`

如果你使用兼容 OpenAI 的中转服务，把 `OPENAI_BASE_URL` 改成你的 `/v1` 入口即可。

## 5. 打开 Unity 工程

### 正确的 Unity 工程路径

在 Unity Hub 中添加并打开：

```text
<repo-root>\VRAgent
```

不要打开仓库根目录。

### Unity 版本

项目当前记录的版本是：

```text
2021.3.45f1c2
```

它来自：

- `VRAgent/ProjectSettings/ProjectVersion.txt`

### 推荐先打开的示例场景

第一次上手，建议先开这个场景：

```text
<repo-root>\VRAgent\Assets\SampleScene\Kitchen_TestRoom\Kitchen_TestRoom.unity
```

仓库里还带了这些示例场景：

- `Apartment`
- `Bedroom`
- `Home_TwoRooms`
- `Kitchen_TestRoom`
- `MusicRoom`

### 如果你要把功能接到新场景

当前仓库里在线桥接相关脚本在：

- `VRAgent/Assets/Package/VRAgent2.0-PVEO/Online/`

常见入口包括：

- `VRAgentOnline.cs`
- `AgentBridge.cs`
- `StateCollector.cs`
- `EditorPlayerController.cs`

如果你只是打开仓库自带的示例场景，通常不需要手动重新搭这些组件；如果你在自建场景里做在线执行，请确认场景里已经挂好对应对象或 Prefab。

## 6. 先跑通最短路径

如果你只是想验证“这个分支能不能在新机器上跑起来”，最短路径建议按这个顺序：

1. 安装 Python 环境并通过 `check_env.py`
2. 用 Unity Hub 打开 `VRAgent/`
3. 打开 `Kitchen_TestRoom.unity`
4. 导入仓库里现成的测试计划

### 6.1 直接在 Unity 里导入现成测试计划

现成样例在：

```text
<repo-root>\TP_Generation\Results\Kitchen_TestRoom\gold-manual-kitchen-v1\test_plan.json
```

在 Unity 里通过菜单导入：

```text
Tools -> VR Explorer -> Import Test Plan
```

这条路径的优点是：

- 不依赖 API Key
- 不依赖 Jelly
- 不依赖先跑场景分析
- 最适合先验证 Unity 侧功能是否正常

## 7. 启动 Jelly 本地面板

Jelly 是当前分支自带的本地 Web 面板，默认监听：

- Web 面板：`127.0.0.1:2000`
- Unity Bridge：`127.0.0.1:6400`

一句话区分：

- `2000` 是浏览器访问的端口
- `6400` 是 Python 和 Unity Play Mode 通信的端口

### 推荐启动方式

```powershell
cd TP_Generation
.\start_jelly.ps1
```

这个脚本会优先使用：

```text
<repo-root>\.venv\Scripts\python.exe
```

启动后访问：

```text
http://127.0.0.1:2000/
```

### 手动启动方式

```powershell
cd TP_Generation
python -m xrplayer.jelly --port 2000 --results-dir Results --auto-open
```

兼容旧入口：

```powershell
python -m vragent2.jelly --port 2000 --results-dir Results
```

### 停止 Jelly

```powershell
cd TP_Generation
.\stop_jelly.ps1
```

### 检查 Jelly 是否还活着

```powershell
cd TP_Generation
.\xrplayer\jelly\check_jelly.ps1
```

### Jelly 里常用路径怎么填

新增项目时，下面这组值最稳妥：

| 字段 | 推荐值 |
| --- | --- |
| `Assets 路径` | `<repo-root>\VRAgent` 或 `<repo-root>\VRAgent\Assets` |
| `Python 路径` | 留空，或 `<repo-root>\.venv\Scripts\python.exe` |
| `工作目录` | `<repo-root>\TP_Generation` |
| `结果目录` | `Results` |
| `默认模型` | `gpt-4o` |

补充说明：

- Jelly 前端提示写的是 “Unity project root or Assets path”，所以这两个路径都能被当前版本兼容处理
- 如果你要跑完整 workflow，`项目根目录` 应该指向 `<repo-root>\VRAgent`
- 如果 Jelly 用的是仓库里的 `.venv\Scripts\python.exe`，但这个虚拟环境里某个包装坏了，GUI 也会跟着报错；这种情况优先重新安装依赖，而不是怀疑 GUI 配置本身

## 8. 完整工作流：从场景分析到 `vragent2`

当前分支推荐主线是：

1. `ExtractSceneDependency.py`
2. `TraverseSceneHierarchy.py`
3. `SpecialLogicPreprocessor.py`
4. `python -m vragent2`

下面以 `Kitchen_TestRoom` 为例。

### 8.1 Step 1：提取场景依赖

```powershell
cd <repo-root>\TP_Generation
..\.venv\Scripts\python.exe .\ExtractSceneDependency.py `
  -p "..\VRAgent" `
  -r ".\Results\Kitchen_TestRoom" `
  --scene-path "Assets/SampleScene/Kitchen_TestRoom/Kitchen_TestRoom.unity"
```

这一步会把场景、脚本、Prefab 等分析结果写到：

```text
TP_Generation\Results\Kitchen_TestRoom\workflow\step1_extract_scene\
```

关键产物通常包括：

- `scene_detailed_info/mainResults/*.unity.json_graph.gml`
- `script_detailed_info/mainResults/*`

注意：

- `TP_Generation\Results\Kitchen_TestRoom\gold-manual-kitchen-v1\` 里只有手工测试计划
- 它不是 `TraverseSceneHierarchy.py` 需要的 Step 1 输入
- 如果你在 Jelly 里直接对一个还没有 `.gml` 的结果目录点 Step 2，会看到“未找到任何GML文件”

### 8.2 Step 2：遍历层级并生成可测对象列表

```powershell
cd <repo-root>\TP_Generation
..\.venv\Scripts\python.exe .\TraverseSceneHierarchy.py `
  -r ".\Results\Kitchen_TestRoom"
```

关键产物：

```text
TP_Generation\Results\Kitchen_TestRoom\Kitchen_TestRoom_gobj_hierarchy.json
```

### 8.3 Step 3：预处理特殊逻辑

这一步会调用 LLM，因此需要先配好 API Key。

```powershell
cd <repo-root>\TP_Generation
..\.venv\Scripts\python.exe .\SpecialLogicPreprocessor.py `
  -r ".\Results\Kitchen_TestRoom" `
  -a "Kitchen_TestRoom"
```

### 8.4 Step 4：运行 `vragent2`

#### 离线模式

离线模式不会连接 Unity，适合先验证计划、日志和产物结构。

```powershell
cd <repo-root>\TP_Generation
..\.venv\Scripts\python.exe -m vragent2 `
  --scene_name Kitchen_TestRoom `
  --hierarchy_json ".\Results\Kitchen_TestRoom\Kitchen_TestRoom_gobj_hierarchy.json" `
  --scene_gml ".\Results\Kitchen_TestRoom\workflow\step1_extract_scene\scene_detailed_info\mainResults\Kitchen_TestRoom.unity.json_graph.gml" `
  --output ".\Results" `
  --app_name Kitchen_TestRoom `
  --model gpt-4o `
  --budget 20
```

#### 在线模式

在线模式要求：

- Unity 已打开目标场景
- Unity 进入 Play Mode
- 场景内有在线桥接组件
- `6400` 端口可连接

```powershell
cd <repo-root>\TP_Generation
..\.venv\Scripts\python.exe -m vragent2 `
  --unity `
  --unity_host 127.0.0.1 `
  --unity_port 6400 `
  --scene_name Kitchen_TestRoom `
  --hierarchy_json ".\Results\Kitchen_TestRoom\Kitchen_TestRoom_gobj_hierarchy.json" `
  --scene_gml ".\Results\Kitchen_TestRoom\workflow\step1_extract_scene\scene_detailed_info\mainResults\Kitchen_TestRoom.unity.json_graph.gml" `
  --output ".\Results" `
  --unity_project "..\VRAgent\Assets" `
  --app_name Kitchen_TestRoom `
  --model gpt-4o `
  --budget 20
```

### 8.5 输出目录怎么组织

`vragent2` 会自动把 `--output` 当作“基目录”，然后按：

```text
<output>\<scene_name>\<model>\
```

组织结果。

比如上面的命令传了：

```text
--output .\Results
```

那么最终运行结果会落到：

```text
TP_Generation\Results\Kitchen_TestRoom\gpt-4o\
```

常见文件包括：

- `test_plan.json`
- `summary.json`
- `iteration_logs.json`
- `gate_graph.json`
- `session_state.json`
- `execution/`
- `replay/`

## 9. 回放已有 `test_plan.json`

如果你已经完成 Step 1 和 Step 2，之后可以用 `vragent2` 做在线回放。

示例：

```powershell
cd <repo-root>\TP_Generation
..\.venv\Scripts\python.exe -m vragent2 `
  --unity `
  --scene_name Kitchen_TestRoom `
  --hierarchy_json ".\Results\Kitchen_TestRoom\Kitchen_TestRoom_gobj_hierarchy.json" `
  --scene_gml ".\Results\Kitchen_TestRoom\workflow\step1_extract_scene\scene_detailed_info\mainResults\Kitchen_TestRoom.unity.json_graph.gml" `
  --output ".\Results" `
  --replay ".\Results\Kitchen_TestRoom\gold-manual-kitchen-v1\test_plan.json"
```

注意：

- `--replay` 不会替你补 Step 1/2 的输入，所以 `scene_name`、`hierarchy_json`、`scene_gml` 仍然要传
- 如果你只是想最快验证 Unity 导入能力，优先用第 6 节的 Unity 菜单导入方式

## 10. 常见问题排查

### `python TP_Generation\check_env.py` 失败

优先检查：

- 虚拟环境是否已激活
- 是否执行过 `python -m pip install -r requirements.txt`
- `TP_Generation/UnityDataAnalyzer/`
- `TP_Generation/CSharpScriptAnalyzer/`
- `TP_Generation/CodeStructureAnalyzer/`

### `AttributeError: module 'networkx' has no attribute 'Graph'`

这类报错在 Jelly GUI 里尤其常见，因为 GUI 会直接调用你配置的 Python 解释器。  
这次的实际原因是：

- Jelly 启动了 `E:\HenryLab\XRPlayer\VRAgent\.venv\Scripts\python.exe`
- 这个解释器里导入到的 `networkx` 不是完整安装
- 它的包目录存在，但缺少正常的 `__init__.py` 导出，所以 `nx.Graph` 不存在

先执行：

```powershell
cd <repo-root>
.\.venv\Scripts\activate
python TP_Generation\check_env.py
```

如果仍然报 `networkx` 损坏，直接强制重装：

```powershell
python -m pip install --force-reinstall --no-cache-dir networkx
python -m pip install -r requirements.txt
python TP_Generation\check_env.py
```

如果你想最稳妥一点，直接删掉并重建虚拟环境也可以：

```powershell
Remove-Item -Recurse -Force .venv
py -3.8 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python TP_Generation\check_env.py
```

然后再回到 Jelly 里重跑 `TraverseSceneHierarchy.py`。

### Unity 第一次打开一直报包错误

优先检查：

- Unity 版本是否是 `2021.3.45f1c2`
- 新机器是否能访问 GitHub
- `VRAgent/Packages/manifest.json` 里的 Git 包是否成功拉取

### 浏览器打不开 `http://127.0.0.1:2000/`

优先检查：

- 是否执行过 `TP_Generation/start_jelly.ps1`
- `2000` 端口是否已被其他进程占用
- `TP_Generation/.jelly.log` 和 `.jelly.log.err` 是否有报错

### `Cannot connect to Unity` 或 `connection refused`

优先检查：

- Unity 是否进入 Play Mode
- 场景里是否有 `AgentBridge` / `VRAgentOnline`
- `--unity_port` 是否仍是 `6400`
- 本机防火墙是否拦截了 `127.0.0.1:6400`

### 找不到 `Kitchen_TestRoom_gobj_hierarchy.json` 或 `.gml`

说明你还没有完成：

- Step 1：`ExtractSceneDependency.py`
- Step 2：`TraverseSceneHierarchy.py`

当前分支的结果目录优先走新结构：

```text
Results\<Scene>\workflow\step1_extract_scene\...
```

但代码也兼容一部分旧的平铺目录结构，所以看到旧路径文档时不要混淆。

### `未找到任何GML文件`

这说明你点了 Step 2，但对应的结果目录里还没有 Step 1 产物。

对 `TraverseSceneHierarchy.py` 来说，至少要先有：

```text
<results_dir>\workflow\step1_extract_scene\scene_detailed_info\mainResults\*.unity.json_graph.gml
```

也就是说，要先运行：

```powershell
python .\ExtractSceneDependency.py -p "<UnityProjectPath>" -r "<ResultsDir>" --scene-path "<ScenePath>"
```

再运行：

```powershell
python .\TraverseSceneHierarchy.py -r "<ResultsDir>"
```

## 11. 补充文档

- Python 工具说明：[TP_Generation/README.md](TP_Generation/README.md)
- `vragent2` 命令行指南：[TP_Generation/Guide.md](TP_Generation/Guide.md)
- Kitchen 场景上手说明：[TP_Generation/Results/Kitchen_TestRoom/README.md](TP_Generation/Results/Kitchen_TestRoom/README.md)
- XRPlayer 架构说明：[_doc/xrplayer/XRPlayer_Architecture.md](_doc/xrplayer/XRPlayer_Architecture.md)
- Jelly UI 说明：[_doc/xrplayer/XRPlayer_Jelly_UI.md](_doc/xrplayer/XRPlayer_Jelly_UI.md)
- Unity 包说明：[VRAgent/Assets/Package/Documentation.md](VRAgent/Assets/Package/Documentation.md)

## 12. 推荐的第一次上手顺序

如果是新同学接手，建议按下面顺序来：

1. 跑通第 3 节，确保 `check_env.py` 通过
2. 用 Unity Hub 打开 `VRAgent/`
3. 打开 `Kitchen_TestRoom.unity`
4. 用第 6 节的方法导入 `gold-manual-kitchen-v1/test_plan.json`
5. 再启动 Jelly
6. 最后再跑第 8 节的完整分析与生成链路

这样最容易把问题定位清楚：先确认环境，再确认 Unity，再确认 Python workflow。
