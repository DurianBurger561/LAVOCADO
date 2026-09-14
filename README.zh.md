<p align="center">
  <img src="assets/logo.png" height="300" width="300" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center">
  <a href="README.md"><b>🇬🇧 English</b></a> |
  <a href="README.zh.md"><b>🇨🇳 中文</b></a>
</p>

LAVOCADO 是一个面向 Windows 和 macOS 的本地优先桌面保护工具。

它会在本机检测屏幕中的明确成人视觉内容，通过多帧确认降低误报，并在确认后于对应显示器上显示干预界面。

所有截图均只在本地内存中处理，**不会保存或上传**。

## 功能

- 本地视觉内容检测
- 多帧确认，降低误报
- 多显示器支持
- 应用程序黑名单和白名单
- 网站黑名单和白名单
- 本地 Dashboard，用于设置、规则、诊断和历史记录
- 支持 Windows 10/11 和 macOS

## 隐私

LAVOCADO 的设计目标是尽可能让屏幕内容只留在本机。

不会保存：

- 屏幕截图或图像裁剪
- 完整 URL
- 窗口标题

保护历史只保存有限的元数据，例如：

- 事件时间
- 触发类型
- 置信度
- 显示器编号
- 是否显示了干预界面

网站规则只保存 hostname，不保存 URL 路径或查询参数。

## 保护规则

可以在 Dashboard 中配置：

- 被阻止的应用程序
- 白名单应用程序
- 被阻止的网站
- 白名单网站

规则优先级：

```text
FORCE_BLOCK > FULL_BYPASS > NORMAL
```

- **命中黑名单：** 立即触发保护。
- **命中白名单：** 暂时跳过视觉检测。
- **没有命中规则：** 正常运行视觉检测。

黑名单始终优先于白名单。

白名单适合用于可信场景，例如医疗、教育、艺术或新闻内容，这些内容可能合法地包含人体解剖或裸露画面。

## 环境要求

- Python 3.12
- Windows 10/11 或 macOS

## 安装

克隆仓库并创建虚拟环境。

### Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/download_models.py --model all
python main.py
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py --model all
python main.py
```

在 macOS 上，需要在以下位置为 LAVOCADO 或当前终端授予权限：

- **系统设置 → 隐私与安全性 → 屏幕与系统音频录制**
- **系统设置 → 隐私与安全性 → 辅助功能**

屏幕录制权限用于保护功能。

辅助功能权限用于识别当前应用程序和浏览器上下文。

## 使用

直接启动保护：

```bash
python main.py
```

打开 Dashboard：

```bash
python main.py dashboard
```

Dashboard 可以用于：

- 启动和停止保护
- 配置应用程序和网站规则
- 修改视觉检测设置
- 管理本地模型
- 查看运行诊断
- 测试干预界面
- 查看最近的保护事件

在终端中查看最近事件：

```bash
python main.py events --limit 20
```

## 自检

检查本地安装和所需资源：

```bash
python main.py --self-check
```

自检会检查：

- 应用运行环境
- 配置文件
- 本地数据库
- 平台集成
- 必需模型

## 构建

安装运行和构建依赖：

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/download_models.py --model all
```

使用 PyInstaller 构建：

```bash
python -m PyInstaller --noconfirm --clean lavocado.spec
```

生成的应用位于：

```text
dist/
```

Windows 和 macOS 版本需要分别在对应操作系统上构建。

## 测试

运行测试：

```bash
python -m unittest discover -s tests -v
```
