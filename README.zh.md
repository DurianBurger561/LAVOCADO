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

### AI 打字冥想

**推荐先使用 OpenAI 的 `gpt-4o-mini`。** 注意名称中有字母 **o**，不是 `gpt-4-mini`，也不是 `gpt-5-mini`。它是程序当前默认模型，适合本功能的短文本交流与轻量生成。能力、价格和限额以 [OpenAI 官方模型说明](https://developers.openai.com/api/docs/models/gpt-4o-mini)为准。推荐不代表所有账号都能访问，也不保证每次回复质量或服务可用性。

#### 产品定位与使用机制

系统提示词由 LAVOCADO 控制，明确说明这是一个帮助用户戒除色情浏览的戒色应用。AI 的职责是温和但明确地劝用户停止继续浏览、关闭触发页面，并选择替代行动；情绪陪伴和打字冥想都服务于这个目标。它不能羞辱用户、编造健康危害、保证恢复，也不能冒充心理医生。知道产品用途不等于知道本次具体触发原因：遮挡可能来自误判、应用规则或手动测试，触发次数也不等于复发次数。

1. 本地保护触发遮挡，经过 Pause、Breathe 后进入 Ready 阶段。Catppuccin 风格的 AI 面板显示在原有干预内容上方，Continue 和 Exit 不依赖 AI 的判断。
2. AI 收到产品提示词、当天触发次数、大致时间段和本次对话，直接回答用户的问题，再顺着实际表达交流。每次回复最多提出一个有帮助的追问，在线交流没有固定问答轮数。
3. 模型返回回应、可选追问和「是否了解足够」的信号。程序据此在了解用户的具体处境、感受或需求及可行方向后推进练习；没有追问不等于自动开始。用户也可以点击「开始打字冥想」提前进入。
4. AI 介绍练习并给出第一句。用户输入并提交后，后续句子结合本次交流和近期练习文字逐句请求生成，共 **5 轮**，最后生成结束语。不是启动时取出五段预设练习。当前提交要求是内容非空，并不逐字强制校验是否完全照抄。
5. 用户可以随时离开，不需要聊完或完成五轮，更不需要 AI 批准才能关闭遮挡。

这是基于**本次会话**的定制，不是长期记忆。AI 不会读取以前的聊天，也不会通过浏览历史建立心理画像；当前使用的历史信息仅为当天触发总次数。提示词和请求实现位于 [app/intervention/llm.py](app/intervention/llm.py)，设置页没有自定义系统提示词入口。

对话支持中文和英文，默认跟随仪表板语言。面板文字、生成内容和本地引导均跟随所选语言。

#### 推荐配置：在设置页接入 OpenAI

1. 在 [OpenAI API 密钥页面](https://platform.openai.com/api-keys)创建密钥，并在 [API 账单页面](https://platform.openai.com/settings/organization/billing/overview)确认余额和计费设置。API 与 ChatGPT 订阅分别计费，购买 ChatGPT Plus 不等于充值 API。
2. 运行 `python main.py dashboard`，打开设置页，找到「智能冥想」。
3. 按下表填写，选择对话语言，并勾选「启用智能冥想」：

| 字段 | 推荐填写内容 |
| --- | --- |
| 接口密钥 | 你自己的 OpenAI API Key，不要截图分享或提交到代码仓库 |
| 模型 | `gpt-4o-mini` |
| 兼容接口 | `https://api.openai.com/v1/chat/completions` |

4. 点击「保存智能设置」，再点击「测试已保存的连接」。保存本身不会发送请求，也不能证明密钥有效。连接测试会发起一次小型 API 请求，可能产生费用。
5. 测试通过后，新开一次「测试干预」，实际体验交流和冥想。保存的设置在下一次干预生效，不会替换已经打开的 AI 面板配置。如果更新了程序中的提示词代码，还需要重启程序。

「兼容接口」是服务商的 API 地址，不是 ChatGPT 网页地址。以 `/chat/completions` 结尾的完整地址直接使用；以 `/v1` 结尾时追加 `/chat/completions`；其他基础地址会追加 `/v1/chat/completions`。建议直接填写上面的完整地址，避免拼接错误。不要把 OpenAI 密钥发送给不可信的中转服务。

#### 当前支持哪些 AI 和模型？

当前客户端只实现了**非流式、OpenAI 风格的 Chat Completions 协议**：使用 `Authorization: Bearer ...` 鉴权，请求体包含 `model`、`messages`、`temperature` 和 **`max_tokens`**，从 `choices[0].message.content` 读取文字。它不会根据模型名称自动切换协议或调整请求参数。

| 服务商 / 模型 | 当前适配情况 |
| --- | --- |
| OpenAI `gpt-4o-mini` | 当前默认和推荐配置，符合现有请求格式。仍需验证账号权限、余额和网络。 |
| OpenAI `gpt-4o`、`gpt-4.1-mini` | 使用相同文本 Chat Completions 格式的候选模型，但本项目没有逐个完成端到端认证；需测试连接及完整冥想流程。参见 [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o) 和 [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) 官方说明。 |
| OpenAI GPT-5 及推理模型，例如 `gpt-5`、`gpt-5-mini`、o 系列 | **当前客户端没有专门适配。** 旧式 `max_tokens`、自定义温度、较小输出预算和超时设置可能不兼容或不适合，不能认为只改模型名就完成了迁移。 |
| DeepSeek 或其他 OpenAI-compatible 服务 | **协议层面有条件兼容，不代表所有模型直接可用。** 所选接口和模型必须接受当前全部参数，并在超时内返回预期文字字段。程序没有 DeepSeek 专用适配器，也没有处理思考模式或推理参数。服务商宣称兼容不等于本项目已完成实测。 |
| Claude / Anthropic 原生 Messages API | **不支持。** 请求体、鉴权头和返回格式不同，需要单独适配。第三方提供的 OpenAI 兼容中转是另一项服务，不等于原生 Claude API 已适配。 |
| OpenAI Responses API、Gemini 原生 API 等非 Chat Completions 接口 | **当前不支持。** 修改接口地址不会自动改变程序发送的数据格式。 |

这个地址**不是 mini 模型专用接口**。能否使用，先看协议与参数是否兼容，再看账号是否有该模型的访问权限。模型输入框是自由文本，不是经过验证的模型列表。应核对服务商文档，并测试已保存的连接。[OpenAI Chat Completions 参数文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)也说明了不同模型的参数限制。

当前实现还有以下限制：请求不流式输出，网络超时设置为 8 秒；对话、练习开场、后续单句、结束语的输出上限分别为 320、520、180、160 tokens，连接测试仅为 8 tokens。这些不是设置页可调整的选项。短测试成功不代表更长的请求或需要较多推理的模型一定能成功，程序也没有自动重试退避循环。

#### 连接状态与本地回退

| 状态 | 实际含义 |
| --- | --- |
| 已配置 · 尚未验证 | 配置中有密钥，但尚未确认该配置的请求成功。 |
| 上次连接测试通过 | 仪表板上次小型测试返回了非空文字，不是持续健康检查，也不保证下次冥想请求成功。 |
| API 连接测试失败 | 测试已保存配置失败，需要根据错误提示检查。 |
| API 尚未验证 / 正在请求 API | 遮挡窗口还没有验证响应，或正在等待本次请求。 |
| 本轮 API 已响应 | 当前遮挡操作收到了可用的模型回复。 |
| 本地引导 / API 失败 / 本地引导 | 当前使用程序内置脚本，不是成功的 LLM 回复。 |

仪表板的连接测试与遮挡里的实时请求状态是两回事。保存设置会清除之前的测试结果，重启也会丢失内存中的测试结果；以前测试成功不能掩盖后来发生的超时、限流或无效响应。

没有密钥、关闭 AI，或者请求失败、回复无法使用时，会回退到固定的本地引导流程。它可能按简单状态或时间选择文字，但**不是一个免费的本地大模型**。系统开场白同样是程序文案，不是模型生成的回复。后续请求可能恢复成功，应看当前状态和消息署名区分来源。等待回复时会暂停继续提交，但仍可退出。

#### 隐私、上下文和密钥保存

- 远程请求包括产品提示词、当天触发次数、大致时间段、本次用户与 AI 的对话，以及近期打字练习内容。上下文有长度限制，单条消息会截断，练习记录只取近期内容。
- 程序不会自动给 LLM 附带截图、检测标签、置信度、应用名称、URL、窗口标题或浏览历史。**用户主动输入或粘贴的文字可以被发送**，其中也包括手动写入的网址或隐私信息。
- 对话保存在程序内存中，不写入保护事件数据库或聊天记录文件。但这不代表 API 服务商或中转服务不保留数据，其数据政策仍然适用。远程 LLM 功能与完全本地的视觉检测是两条不同的数据路径。
- 密钥保存在本机的 **明文 JSON 文件** `llm_settings.json` 中，不是系统钥匙串或加密保险库；程序会尝试限制文件访问权限。默认路径为 macOS 的 `~/Library/Application Support/LAVOCADO/llm_settings.json`，以及 Windows 的 `%LOCALAPPDATA%\LAVOCADO\llm_settings.json`。
- 后端不会把已保存的原始密钥返回给仪表板，也不写入保护事件。密钥输入框留空代表保留旧密钥；要移除请点击「清除已保存的接口密钥」。不要提交或分享这个配置文件。

#### 使用环境变量配置

推荐使用设置页。需要通过终端配置时，可以在启动前显式设置同一套 OpenAI 参数：

```bash
export LAVOCADO_LLM_API_KEY="your API key"
export LAVOCADO_LLM_ENDPOINT="https://api.openai.com/v1/chat/completions"
export LAVOCADO_LLM_MODEL="gpt-4o-mini"
export LAVOCADO_LLM_LANGUAGE="zh"
python main.py
```

Windows PowerShell：

```powershell
$env:LAVOCADO_LLM_API_KEY = "your API key"
$env:LAVOCADO_LLM_ENDPOINT = "https://api.openai.com/v1/chat/completions"
$env:LAVOCADO_LLM_MODEL = "gpt-4o-mini"
$env:LAVOCADO_LLM_LANGUAGE = "zh"
python main.py
```

对于密钥、接口和模型，设置页保存的非空值优先于环境变量。环境变量逐项按以下顺序查找：`LAVOCADO_LLM_*`，然后是 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`，最后是 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`。接口和模型最终默认使用上面的 OpenAI 配置。这些变量别名**不会自动识别服务商**：只设置 DeepSeek 密钥不会自动切换到 DeepSeek 接口和模型。

显式保存的中文或英文选项优先于 `LAVOCADO_LLM_LANGUAGE`（`zh` 或 `en`），再回退到仪表板语言。清除已保存的密钥后，程序仍可能使用环境变量中的密钥。如果要无论环境变量如何都停止远程请求，请在设置页关闭智能冥想。

#### 常见问题排查

| 错误 / 现象 | 检查方向 |
| --- | --- |
| 400 / 422，拒绝请求参数 | 检查模型与参数是否兼容。充值不能解决不支持的 `max_tokens` 或 `temperature`，可先使用推荐配置。 |
| 401，鉴权失败 | 检查密钥有效性，以及密钥和接口是否属于同一个服务商。 |
| 403，拒绝访问 | 检查模型、项目权限和服务商地区限制。 |
| 404，找不到接口或模型 | 检查完整接口地址、准确模型名及账号权限。 |
| 429，请求受限或额度不足 | 同时检查请求频率限制与 API 余额、配额；有余额不代表没有限流。 |
| 超时、网络错误或 5xx | 检查网络、TLS、服务商状态及客户端较短的超时设置，稍后重试。 |
| 连接测试通过，但练习回退本地 | 较长请求或需要的结构化回复仍可能失败。看遮挡的本轮状态，连接测试不等于完整流程验证。 |
| 回答像预设好的 | 先确认署名是 AI 还是本地引导。在线定制只使用本次对话，不会记住以前的聊天；更新提示词代码后需重启。 |

服务商侧错误可参考 [OpenAI API 错误说明](https://developers.openai.com/api/docs/guides/error-codes)。本节列出的模型和服务均不代表免费、无限额或始终稳定可用。

### 保护历史

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
