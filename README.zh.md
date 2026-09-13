<p align="center">
  <img src="assets/神秘牛油果.png" height="300" width="300" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center"><a href="README.md"><b>🇬🇧🇺🇸🇨🇦🇦🇺🇳🇿English<b></a> | <a href="README.zh.md"><b>🇨🇳中文<b></a></p>

LAVOCADO 是一款本地优先的桌面守护工具。它在需要保护的上下文中检测视觉违规内容,通过连续多帧确认后,只遮挡触发保护的那一块屏幕。

LAVOCADO 不会判断观看目的。受信任的应用或网站可以加入白名单,以便在医学、教育、艺术、新闻或其他用户认可的用途下跳过视觉保护。

截图全部在本地处理,不会被存储,也不会发送给 LLM。主检测器对整屏使用 NudeNet 640m 模型,以 640 像素进行推理。原始分辨率的截图仅保留在内存中,供后续本地复检使用。

当风险被确认后,受影响的屏幕会经过一次短暂停顿、一次引导呼吸,再进入准备阶段,之后才会启用"继续"按钮。`Esc` 键始终可用作紧急退出。

## 本地数据与隐私

保护被触发时,LAVOCADO 只记录 UTC 时间、触发类型、置信度、显示器编号,以及是否展示了干预。视觉检测事件还可以保存检测类别。应用规则、网站规则和旧版窗口黑名单事件的标签始终为空,因此应用标识和域名不会写入历史。它不会存储截图、完整 URL 或窗口标题。

SQLite 事件数据库存放在当前用户的应用数据目录下:

- Windows:`%LOCALAPPDATA%\\LAVOCADO\\events.db`
- macOS:`~/Library/Application Support/LAVOCADO/events.db`
- Linux 或 WSL:`${XDG_DATA_HOME:-~/.local/share}/lavocado/events.db`

启动前设置 `LAVOCADO_DATA_DIR` 环境变量,可指定其他目录。
同一个文件还保存 `application_rules` 和 `website_rules`。网站输入在保存前会转成域名,路径与查询参数不会存入规则。请在保护停止时通过仪表盘编辑这些规则;Protection 进程启动时加载它们。

发现、诊断和历史记录的边界见 [上下文隐私审计](docs/context_privacy_audit.md)。

## 保护规则

仪表盘在保护停止时可编辑四组本地规则。更改会在下次启动保护时生效:

- 应用黑名单
- 应用白名单
- 网站黑名单
- 网站白名单

使用 **Pick current app** 可从前台窗口填入稳定的可执行文件名、桌面应用 ID 或 bundle ID。网站输入接受域名或 HTTPS URL,只保存域名。匹配方式可以是精确主机名,也可以包含子域名。

加入白名单时会弹出确认:白名单中的应用和网站将完全跳过 LAVOCADO 的视觉保护。如果你需要查看医学、教育、艺术、新闻或其他非色情目的但可能包含裸露或明确人体内容的来源,可以将可靠来源加入白名单。你将自行负责白名单环境中显示的内容。白名单不是 LAVOCADO 对来源安全性的认证。

LAVOCADO 会先识别前台应用。如果它是受支持的浏览器,再通过平台辅助功能 API 读取活动标签页的域名(Windows UI Automation、macOS Accessibility、Linux AT-SPI)。它不会根据窗口标题猜测网站。若无法读取地址栏,网站上下文保持 UNKNOWN,只应用应用规则。

应用规则与网站规则先独立计算,再统一合并:

```text
FORCE_BLOCK > FULL_BYPASS > NORMAL
```

黑名单始终优先于白名单。没有任何匹配规则时,保护行为与现有视觉检测路径完全一致。

- `FORCE_BLOCK` 立即遮挡前台窗口所在的显示器,跳过 NudeNet、YOLO、区域排序和时序确认。
- `FULL_BYPASS` 在该上下文活动期间跳过整个视觉流水线,离开后再从干净状态恢复。
- `NORMAL` 运行截图和视觉违规检测。Vision 只判断画面是否违反 LAVOCADO 的视觉内容规则,不负责医学、艺术、教育或新闻等观看目的。确认后的违规仍需在 3 个新帧中命中 2 次才会保护。

实时诊断只显示粗粒度状态:是否识别到应用、是否为浏览器、网站是否已知,以及规则动作。不会包含应用标识、域名、窗口标题或 URL。

## 可选的 AI 支持消息

LAVOCADO 无需 API key 即可运行,默认使用内置的本地消息。若想在干预的最后阶段启用一段 AI 生成的简短消息,请在启动应用前设置 OpenAI API key:

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY="你的-api-key"
```

```bash
# macOS、Linux 或 WSL
export OPENAI_API_KEY="你的-api-key"
```

发送出去的仅仅是一个固定的"请给一句鼓励的话"的请求。截图、检测标签、置信度、显示器编号、URL、窗口标题都绝不会被包含在内。此请求已禁用 API 响应存储。设置 `LAVOCADO_OPENAI_MODEL` 可覆盖默认模型。

## 旧版前台窗口黑名单

请优先使用上面的仪表盘规则。`app/config.py` 中的 `BLOCKED_APPS` 只留给无法存成稳定应用标识的名称或标题关键词:

```python
BLOCKED_APPS = ["Steam", "reddit.com"]
```

当某个关键词匹配时,LAVOCADO 会以前台窗口的中心为准,只遮挡包含该窗口的那块屏幕。窗口元数据在内存中检查,不会被存储,也不会发送给 AI 服务。列表为空则禁用这段旧逻辑。
`chrome.exe` 等可确定的旧应用标识会迁移一次,成为结构化应用黑名单规则;`Steam` 等可能是应用名或窗口标题的词仍由旧逻辑处理,避免改变原有行为。

在 macOS 上,读取前台窗口信息需要为终端或打包后的应用授予"辅助功能"权限。在 X11 的 Linux 上,需安装 `xprop` 和 `xwininfo`(Ubuntu 上由 `x11-utils` 提供)。WSL 只能读取 WSLg 暴露出来的窗口元数据;若要匹配所有 Windows 应用,请使用原生 Windows 构建版本。

## 支持的平台

- Windows 10/11
- macOS
- 支持原生 X11 或 Wayland 屏幕捕获的 Linux(含 WSLg)

Wayland 使用桌面的 ScreenCast Portal 和 PipeWire。保护启动时请在系统选择器中批准显示器。明确取消或拒绝该请求会停止捕获,而不会改走 MSS 绕过这一决定。

运行时的平台集成被隔离在 `app/platforms/` 目录下:

- `windows.py` 包含 User32/Kernel32 前台窗口访问、DPI 设置、Windows 数据路径,以及原生运行时指引。
- `macos.py` 包含通过 System Events 访问前台窗口、macOS 数据路径,以及权限指引。
- `linux.py` 包含 X11 前台窗口访问、XDG 数据路径,以及 Linux 和 WSLg 所用的 Qt WebView 配置。

网站发现同样按平台实现,位于 `app/platforms/website/`:Windows UI Automation、macOS `AXUIElement`、Linux AT-SPI。读取失败或不可用时绝不会停止视觉保护,网站一侧保持 UNKNOWN。

每个进程只创建一个 `PlatformAdapter`,并将其传递给截图、黑名单、遮挡、存储和仪表盘等模块。因此各业务模块无需自行判断操作系统,也无需导入具体的平台实现。

## 安装配置

请使用 Python 3.12 并创建虚拟环境。

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py
```

首次启动时,请在 **系统设置 → 隐私与安全性 → 屏幕与系统音频录制** 中允许"终端"或 LAVOCADO,然后重启应用。
浏览器地址栏发现还需要 **隐私与安全性 → 辅助功能**;没有该权限时,网站上下文保持 UNKNOWN。

### Ubuntu、Linux 或 WSL

```bash
sudo apt install \
  python3-tk x11-utils libpulse0 libxkbcommon-x11-0 libxcb-shm0 \
  gstreamer1.0-tools gstreamer1.0-pipewire \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-util1 libxcb-xkb1 \
  gcc libcairo2-dev pkg-config python3-dev \
  libgirepository-2.0-dev gir1.2-atspi-2.0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py
```

Linux 会显式选择 pywebview 的 Qt 后端。PyGObject/AT-SPI 只用于前台浏览器地址栏发现;若桌面辅助功能不可用,网站保持 UNKNOWN,视觉保护继续运行。
在 WSLg 环境下,当没有暴露 DRM 渲染节点时,LAVOCADO 会默认让 Qt WebEngine 使用软件渲染,以避免 Mesa/Zink 报错。用户自行提供的 Qt 或 Mesa 环境变量不会被覆盖。

可在不打开捕获会话的情况下校验当前 Linux 捕获路径:

```bash
python scripts/validate_linux_capture.py --self-check
```

在真实的 X11、Wayland 或 WSLg 桌面上运行现场校验:

```bash
python scripts/validate_linux_capture.py
```

现场检查会向每个已选显示器请求两帧新画面,校验尺寸、BGR 格式和递增序号,然后丢弃它们。它不会保存或上传像素。在 Wayland 上,请在系统选择器中批准每一块显示器。取消选择器会报告 `permission_denied`,不会改试 MSS。JSON 结果在 X11 上应为 `linux_xshm`,在 Wayland 上应为 `linux_pipewire_portal`;原生后端技术上不可用时则为带降级原因的 `mss`。完整的 GNOME、KDE、WSLg、权限和多显示器矩阵见 [Linux 捕获校验清单](docs/linux-capture-validation.md)。

固定版本的 640m 模型约 99 MiB,从 NudeNet 官方 GitHub release 下载,并做字节大小和 SHA-256 校验。该模型不纳入 Git。源码运行时若缺少它,LAVOCADO 会记录一条警告并降级到 NudeNet 320n;而打包构建版本则要求必须有经校验的 640m 文件。设置 `LAVOCADO_NUDENET_MODEL` 可指定使用位于其他路径的本地 640m 文件。

也可以把本地已有的 YOLO11 NSFW 模型作为第二个主检测器。它把性行为和解剖标签映射到同一套视觉违规策略。LAVOCADO 不会训练或下载该模型；未设置权重时保持关闭。缺少 ultralytics 或权重时，仍以纯 NudeNet 模式运行:

```bash
python -m pip install -r requirements-yolo.txt
export LAVOCADO_YOLO_MODEL=/path/to/existing-yolo11.pt
```

若想在本地对比 320n 和 640m 的延迟,且不保存任何分析结果:

```bash
python scripts/benchmark_detectors.py /path/to/test-image-1.jpg /path/to/test-image-2.jpg
```

开发者 Benchmark Lab 把两套计分板分开。Vision Benchmark 只问像素是否违反
LAVOCADO 的视觉内容规则(Violation / Clear,标注为 Visual Policy Ground Truth)。
medical、education、art、news 只是场景元数据,不会把 Vision 结果改成 Allow。
Full Pipeline Benchmark 再加上应用/网站规则夹具,输出 FORCE_BLOCK、FULL_BYPASS
或 NORMAL,以及 Failure Explorer(上下文策略、规则、是否调用 Vision、检测证据、
时序状态、最终动作)。Full Product Benchmark 会跑 Context + Vision + Temporal:
一次视觉违规不够,保护需要 3 个新帧中的 2 次确认。UNCERTAIN 不计为时序命中:

```bash
python scripts/benchmark_vision.py --tag medical /path/to/test-image.jpg
python scripts/benchmark_pipeline.py --website-action full_bypass --tag medical
python scripts/benchmark_pipeline.py --website-unknown --vision-classification violation --temporal-confirmed
python scripts/benchmark_pipeline.py --vision-frames violation,violation,clear --tag medical
```

若要在隔离的开发进程中对比原生捕获路径和 MSS:

```bash
python -m pip install -r requirements-benchmark.txt
python scripts/benchmark_capture.py
```

捕获基准会汇总延迟、帧龄、CPU、常驻内存、显示器分辨率,以及从捕获到 NudeNet 决策的耗时。它不会保留或上传帧。各后端命令、权限行为和分辨率/显示器测试矩阵见 [捕获基准指南](docs/capture-benchmark.md)。

发布稳定性校验时,请按平台和后端模式至少运行一小时捕获浸泡测试:

```bash
python scripts/soak_capture.py --backend auto --duration-seconds 3600
```

它会检测停滞序号、不健康后端、内存/资源增长、降级切换和未完成清理,且不保留帧。八小时命令、失败阈值和平台矩阵见 [捕获浸泡测试指南](docs/capture-soak-testing.md)。

### 可选的区域排序基准测试

Viddexa 五分类模型目前是一个可选的开发依赖,尚未包含在发布包中。安装后,它只给 tile 排序,让主检测器优先复检 porn/hentai 风险最高的区域。Viddexa 不判断观看目的,不能单独触发保护,也不会把 NudeNet 的边界结果提升为违规。安装并测试排序延迟:

```bash
python -m pip install -r requirements-context.txt
python scripts/benchmark_context.py /path/to/test-image-1.jpg /path/to/test-image-2.jpg
python scripts/benchmark_ranking.py --tiles '[{"index":0,"scores":{"porn":0.99},"primary_hit":false},{"index":1,"scores":{"porn":0.2},"primary_hit":true}]' --baseline-hits 6 --with-tile-hits 8 --positives 10
```

Viddexa Benchmark 只报告 tile 排序质量、候选优先级、召回增益和延迟。它不会把 Viddexa 的 porn 准确率当成产品 Block 准确率。NudeNet/YOLO 的 Detector Benchmark 仍然是召回、精确率、小目标召回、ROI 救援增益、tile 召回和延迟。

固定版本的模型文件从 Hugging Face 下载,推理则在本地运行。基准测试用的图片不会被上传或保存,该命令只打印编号结果,而非输入路径。若依赖或模型不可用,LAVOCADO 仍能以纯 NudeNet 模式运行。确认后的视觉违规仍需在 3 个新帧中命中 2 次才会保护。

对于小面积内容的救援机制,每块显示器被分为四块区域。Viddexa 按 porn/hentai 风险排序这些区域;高分只是让同一个 NudeNet 640m 实例复检该区域。被救援的区域会在接下来的两次检查中被锁定,以便时序验证器对同一区域做确认或排除。当只有 NudeNet 320n 降级方案可用时,救援机制会自动禁用。

保护诊断信息保存在一个线程安全的内存快照中。它包含模型可用性、最近一次扫描延迟、显示器编号、置信度最高的检测器元数据、上下文结果、决策来源、时序历史、救援计划,以及粗粒度的前台策略状态。捕获健康信息报告首选与当前后端、是否降级及原因、帧龄和检测到的显示器数量。该快照采用明确的安全数据结构,绝不包含图像像素、截图、裁剪图、URL、窗口标题、应用标识、域名或图片路径。它不会被写入 SQLite,也不会发送给 OpenAI。

每一帧新画面在进入 NudeNet 推理前,还会经过按显示器划分的变化调度器。若当前后端提供原生脏区域元数据则优先使用;否则 LAVOCADO 会在内存中比较一份有界的 64x64 灰度图。第一帧、周期性安全帧,以及候选出现后的时序跟进帧始终会被扫描。变化图不会写入磁盘、进入诊断或被上传。

源码开发者可以显式测试 `Auto`、仅原生和仅 MSS 的捕获路径。该覆盖由环境变量控制,在打包给用户的构建中禁用,也不会出现在仪表盘上。跨平台命令和权限策略说明见 [开发者捕获覆盖指南](docs/developer-capture-override.md)。

实现与需求的对应关系,以及仍待在真实设备上核对的项目,记录在 [原生捕获验收清单](docs/native-capture-acceptance.md)。

当保护由仪表盘托管时,一套固定的 stdin/stdout 消息协议会把这份安全快照从保护子进程复制到仪表盘内存中。该协议只支持启动、停止、读取诊断、测试干预和本地规则编辑这几种操作;这座桥梁无法执行命令或访问任意文件。手动测试干预由保护进程在其 GUI 主线程上展示,不会创建 SQLite 保护事件。

## 使用 LAVOCADO

直接启动保护(默认方式):

```bash
python main.py
```

或打开 WebView 仪表盘,用于启动/停止保护、编辑应用和网站规则、查看实时诊断、测试干预,以及查看近期的隐私安全事件:

```bash
python main.py dashboard
```

仪表盘使用 pywebview,搭配本地的 HTML、CSS 和 JavaScript。它只暴露固定的 `DashboardAPI`,在读取状态前会等待 `pywebviewready`,并使用隐私浏览模式。Linux 安装使用 Qt 后端;Windows 在可用时使用 WebView2,macOS 使用系统 WebKit 视图。关闭窗口会停止并回收由仪表盘托管的保护子进程。

仪表盘会把保护作为独立进程启动,以便遮挡窗口在 Windows、macOS 和 Linux 上都保持在 GUI 主线程。关闭仪表盘会请求保护进程干净地退出。

在无显示器的机器上,可在终端查看近期的本地事件:

```bash
python main.py events --limit 20
```

## 构建桌面应用

安装独立的构建依赖,并在目标操作系统上构建:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/download_models.py
python -m PyInstaller --noconfirm --clean lavocado.spec
```

产物写入 `dist/` 目录。PyInstaller 应用必须在各自的目标操作系统上构建;无法直接从 WSL/Linux 生成 Windows 可执行文件或 macOS 应用。

**Package** 工作流可以构建可下载的 Windows、macOS 和 Linux 产物,无需三台本地机器。打开仓库的 **Actions** 标签页,选择 **Package**,点击 **Run workflow**,待所有矩阵任务完成后即可下载三个产物。以 `v` 开头的标签也会自动触发该工作流。

打包后的应用在不带参数启动时会打开仪表盘。目前 Windows 和 macOS 产物尚未签名,因此开发机器可能会显示常见的"未知发布者"警告。在配置代码签名之前,请勿将它们作为可信版本分发。

## 运行测试

```bash
python -m unittest discover -s tests -v
```
