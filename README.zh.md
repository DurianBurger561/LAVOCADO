<p align="center">
  <img src="assets/神秘牛油果.png" height="300" width="300" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center"><a href="README.md"><b>🇬🇧🇺🇸🇨🇦🇦🇺🇳🇿English<b></a> | <a href="README.zh.md"><b>🇨🇳中文<b></a></p>

LAVOCADO 是一款本地优先的桌面守护工具。它独立监控每一块相连的显示器,通过连续多帧确认视觉风险,并且只遮挡触发保护的那一块屏幕。

截图全部在本地处理,不会被存储,也不会发送给 LLM。主检测器对整屏使用 NudeNet 640m 模型,以 640 像素进行推理。原始分辨率的截图仅保留在内存中,供后续本地复检使用。

当风险被确认后,受影响的屏幕会经过一次短暂停顿、一次引导呼吸,再进入准备阶段,之后才会启用"继续"按钮。`Esc` 键始终可用作紧急退出。

## 本地数据与隐私

保护被触发时,LAVOCADO 只记录 UTC 时间、检测标签、置信度、显示器编号,以及是否展示了干预。它不会存储截图、URL 或窗口标题。

SQLite 事件数据库存放在当前用户的应用数据目录下:

- Windows:`%LOCALAPPDATA%\\LAVOCADO\\events.db`
- macOS:`~/Library/Application Support/LAVOCADO/events.db`
- Linux 或 WSL:`${XDG_DATA_HOME:-~/.local/share}/lavocado/events.db`

启动前设置 `LAVOCADO_DATA_DIR` 环境变量,可指定其他目录。

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

## 前台窗口黑名单

在 `app/config.py` 中添加不区分大小写的应用名或标题关键词:

```python
BLOCKED_APPS = ["Steam", "reddit.com"]
```

当某个关键词匹配时,LAVOCADO 会以前台窗口的中心为准,只遮挡包含该窗口的那块屏幕。窗口元数据在内存中检查,不会被存储,也不会发送给 AI 服务。列表为空则禁用窗口检查。

在 macOS 上,读取前台窗口信息需要为终端或打包后的应用授予"辅助功能"权限。在 X11 的 Linux 上,需安装 `xprop` 和 `xwininfo`(Ubuntu 上由 `x11-utils` 提供)。WSL 只能读取 WSLg 暴露出来的窗口元数据;若要匹配所有 Windows 应用,请使用原生 Windows 构建版本。

## 支持的平台

- Windows 10/11
- macOS
- 支持 X11 屏幕捕获的 Linux(含 WSLg)

Wayland 的支持取决于其合成器的屏幕捕获权限。

运行时的平台集成被隔离在 `app/platforms/` 目录下:

- `windows.py` 包含 User32/Kernel32 前台窗口访问、DPI 设置、Windows 数据路径,以及原生运行时指引。
- `macos.py` 包含通过 System Events 访问前台窗口、macOS 数据路径,以及权限指引。
- `linux.py` 包含 X11 前台窗口访问、XDG 数据路径,以及 Linux 和 WSLg 所用的 Qt WebView 配置。

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

### Ubuntu、Linux 或 WSL

```bash
sudo apt install \
  python3-tk x11-utils libpulse0 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-util1 libxcb-xkb1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py
```

Linux 会显式选择 pywebview 的 Qt 后端,因此即便缺少可选的 GTK `gi` 模块,也不会被当作启动失败。在 WSLg 环境下,当没有暴露 DRM 渲染节点时,LAVOCADO 会默认让 Qt WebEngine 使用软件渲染,以避免 Mesa/Zink 报错。用户自行提供的 Qt 或 Mesa 环境变量不会被覆盖。

固定版本的 640m 模型约 99 MiB,从 NudeNet 官方 GitHub release 下载,并做字节大小和 SHA-256 校验。该模型不纳入 Git。源码运行时若缺少它,LAVOCADO 会记录一条警告并降级到 NudeNet 320n;而打包构建版本则要求必须有经校验的 640m 文件。设置 `LAVOCADO_NUDENET_MODEL` 可指定使用位于其他路径的本地 640m 文件。

若想在本地对比 320n 和 640m,且不保存任何分析结果:

```bash
python scripts/benchmark_detectors.py /path/to/test-image-1.jpg /path/to/test-image-2.jpg
```

### 可选的上下文模型基准测试

Viddexa 五分类上下文模型目前是一个可选的开发依赖,尚未包含在发布包中。安装后,它仅用于在放大的本地裁剪图上,对 NudeNet 的边界检测结果做二次确认。Viddexa 的结果本身绝不会单独触发保护,且 `sexy` 或 `hentai` 分类不会提升一个边界结果的判定。安装并测试它:

```bash
python -m pip install -r requirements-context.txt
python scripts/benchmark_context.py /path/to/test-image-1.jpg /path/to/test-image-2.jpg
```

固定版本的模型文件从 Hugging Face 下载,推理则在本地运行。基准测试用的图片不会被上传或保存,该命令只打印编号结果,而非输入路径。若依赖或模型不可用,LAVOCADO 仍能以纯 NudeNet 模式运行。在融合候选决策之后,原有的"三帧中两帧"时序确认依然生效。

对于小面积内容的救援机制,每块显示器被分为四块区域,每次扫描只对其中一块做上下文分类。当某块区域的本地 `porn` 分数非常高时,只是让同一个 NudeNet 640m 实例重新检查该区域;Viddexa 绝不会单独生成候选。被救援的区域会在接下来的两次检查中被锁定,以便原有的"三帧中两帧"时序验证器对同一区域做确认或排除。当只有 NudeNet 320n 降级方案可用时,救援机制会自动禁用。

保护诊断信息保存在一个线程安全的内存快照中。它包含模型可用性、最近一次扫描延迟、显示器编号、置信度最高的检测器元数据、上下文结果、决策来源、时序历史,以及救援计划。该快照采用明确的安全数据结构,绝不包含图像像素、截图、裁剪图、URL、窗口标题或图片路径。它不会被写入 SQLite,也不会发送给 OpenAI。

当保护由仪表盘托管时,一套固定的 stdin/stdout 消息协议会把这份安全快照从保护子进程复制到仪表盘内存中。该协议只支持启动、停止、读取诊断和测试干预这几种操作;这座桥梁无法执行命令或访问任意文件。手动测试干预由保护进程在其 GUI 主线程上展示,不会创建 SQLite 保护事件。

## 使用 LAVOCADO

直接启动保护(默认方式):

```bash
python main.py
```

或打开 WebView 仪表盘,用于启动/停止保护、查看实时诊断、测试干预,以及查看近期的隐私安全事件:

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