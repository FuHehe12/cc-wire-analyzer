# CC Wire Analyzer — 看懂 Claude Code 的思考过程、提示词与子代理行为

你是否遇到过：安全分类器报错，却不知道是哪次隐藏调用；自动模式忽然变慢，却看不出在等待什么；子代理越来越积极，想知道它拿到了什么提示词；thinking 里混着英文和其他语言，想先翻译再判断？CC Wire Analyzer 把一次本地会话中的这些幕后步骤按轮次、提示词和子代理关系整理出来，支持对选中内容翻译或让你配置的 AI 解读，原文始终保留在旁边对照。

它适合“Claude Code 说发生了某件事，但你想知道为什么”的时候。

[English](README.md) · [日本語](README.ja.md)

[官网](https://fuhehe12.github.io/cc-wire-analyzer/zh/) · [下载最新版](https://github.com/FuHehe12/cc-wire-analyzer/releases/latest) · [使用文档](docs/README.md) · [更新日志](CHANGELOG.zh.md)

**支持 Windows 与 macOS · 中文/英文/日文 · 可选翻译与 AI 解读 · 内容默认只留在本机**

## 为什么要用它

当 Claude Code 的表面会话没有回答关键问题时，打开一条记录，先看译文，再按需展开原文、工具和调用关系：

- **安全分类器报错。** 找到失败的隐藏调用，读取上游错误，并看清它关联的提示词、模型设置或工具调用。
- **自动模式变慢。** 沿时间线判断它是在思考、重试、统计 Token，还是卡在某个辅助调用上。
- **子代理突然变多。** 看清是谁派了谁、Task/Agent 使用了什么 prompt，以及每个子代理拿到了什么上下文。
- **thinking 混着英文和其他语言。** 翻译选中的 thinking 或提示词，同时保留原文进行对照。
- **交给 agent 去分析。** 一切以纯 JSONL 写在本机，GUI 用的那套端点也对外开放 HTTP——你（或另一个 agent）可以事后逐条翻查、搜索、交叉分析，而不必尝试复现那一刻。

## 截图

录制视图分两层：先在列表里看到整天的请求，再点开任意一条进入详情；详情里可以展开 `System`、`thinking`、工具和消息，并对选中的原文翻译。下面两张图是同一条示例录制。

| 录制列表（中文界面） | 录制详情：展开 System / thinking 并翻译 |
|---|---|
| ![CCWA 中文录制列表](docs/screenshots/zh/view-a-captures-zh.png) | ![CCWA 录制详情：System、thinking 与翻译](docs/screenshots/zh/view-b-capture-detail-zh.png) |

| 时序 DAG | 设置 |
|---|---|
| ![CCWA 时序 DAG](docs/screenshots/zh/view-d-dag.png) | ![CCWA 设置](docs/screenshots/zh/view-c-settings.png) |

| 分析 —— 快照与对比 |
|---|
| ![Analyse](docs/screenshots/zh/view-e-analyse.png) |

截图用的是 v0.4.7 起的默认外观「深色专业」。设置页还有「经典暖灰」（v0.4.7 之前的界面）与
「实验室日光」；外观只属于界面本地，不会碰你的代理配置。

录制列表和详情页使用同一条中文录制：详情中展开 `System` 后，每个提示词块都可以复制、格式化、翻译或交给 AI 解读；原文始终保留，译文显示在原文旁边，方便核对模型到底收到了什么。

## 使用方法：从录制到定位问题

最短路径是：**启动软件 → 开始录制 → 重现一次问题 → 先看捕获列表 → 再打开详情和时序图**。不需要先理解 HTTP；你只要从一条真实请求开始。

### 1. 开始一条录制

1. 从 [Releases](../../releases) 下载并启动 Windows 或 macOS 版本。
2. 在「捕获」页点击「启动代理」，再照常运行 Claude Code，重现你想查的现象。
3. 回到 CCWA，停止代理或退出软件；这次会话就会出现在当天的捕获列表中。

### 2. 先从捕获列表判断发生了什么

列表里的每一行是一条上游请求。先看这几列：

- **类型**：主线、标题生成、安全审查、子代理或压缩等辅助调用；隐藏调用也会单独出现。
- **耗时与首字时间**：判断是在思考、重试，还是卡在某个辅助请求上。
- **Token 与缓存**：看哪一轮上下文突然变大，或是否反复读取缓存。
- **状态与摘要**：红色失败、上游错误、审查结果和响应摘要，通常就是定位问题的第一条线索。

例如自动模式变慢时，先按耗时找异常行；安全分类器有问题时，先找「安全」或失败行，不必从整段会话里盲猜。

### 3. 打开详情，看模型真正收到的内容

点击任意一行进入详情页，再按问题展开：

- 展开 **System**，查看完整 system prompt、身份声明和上下文 reminder；选中英文内容可以直接翻译，原文始终保留在旁边。
- 展开 **thinking**、**Messages** 和 **Tools**，对照模型的思考片段、用户消息、工具定义与工具调用。
- 遇到不认识的字段，先用「格式化」读结构，再复制单个块或交给你配置的 AI 解读。

这样可以回答“它为什么这样做”“这次子代理到底拿到了什么 prompt”“安全分类器为什么判定失败”等问题，而不是只看到 Claude Code 最后的总结。

### 4. 用时序图和 Analyse 找跨请求的问题

- **时序**页按泳道连接主线、子代理和辅助调用；沿着派生边看谁派了谁，沿时间轴找等待、重试和红色错误节点。
- **Analyse** 页把一条请求或一段提示词保存成快照，再逐项比较不同轮次，适合查提示词漂移、上下文变化和看不见的字符差异。
- 需要批量检索时，使用本地 API 或 [AI 使用文档](docs/reference/AI_USAGE.md)，让 agent 读取录制并返回失败归因。

网络转发、数据位置、完整 API 和安全边界等细节，放在 [docs](docs/README.md) 中按需查阅。

## 特性

- **零侵入** —— 只改 `~/.claude/settings.json` 的 `ANTHROPIC_BASE_URL`，token、模型映射、OTLP 配置全保留。关闭软件时字节级复原该文件。
- **官方直连与第三方端点都支持** —— 没有 `ANTHROPIC_BASE_URL`（直连 Anthropic）也能用，自动回退抓官方端点；有则跟随（例如用 [cc-switch](https://github.com/farion1231/cc-switch) 配的网关）。
- **透明流式** —— SSE 边转发边录制，CC 用起来和直连完全一样。
- **崩溃保护** —— 原子写 + 每次启动备份 + atexit/signal/excepthook 三重恢复 + 孤儿备份恢复。
- **时序 DAG** —— 泳道视图；每条主线会话在泳道头、轴线、节点边框、连线上都用各自颜色；子代理/辅助节点带关联主线颜色的点，一眼看出谁派生了谁。
- **详情工具** —— 翻译、"问 AI 这是什么意思"（带提示词注入防护）、格式化/美化；界面支持**中文/英文/日文**切换（即时、持久化）。
- **快照与对比（Analyse 标签页）** —— 把一条提示词或一整段录制备份成快照，再逐项比较。揭示肉眼看不见的差异（CC 针对中国用户的字符水印——日期里 `-`/`/` 互换、撇号同形异码字——显示成可见占位标记）。思考链分三层抽取、预算硬约束；与内置模型多轮分析对话。快照单位是一条请求、不是一个会话。
- **清理录制** —— 清掉某天的捕获（直接删除 / 压缩存档后删除），内联二次确认。
- **盲区雷达** —— `GET /api/unknowns` 主动标出工具还不认识的协议值（新块类型/字段、未解析请求字段、非标枚举、beta 特性长尾），每项带内容片段 + 它伴随的 beta 特性。CC 发新 beta 时它是预警；把分析器迁到别的 agent 框架时，它是协议发现工具——把"猜新协议"变成"扫一遍、逐个确认未知、建该框架的已知集合"。
- **跨平台** —— Windows `.exe` 和 macOS `.app`，由 GitHub Actions 构建。**字体全打包**（Inter + JetBrains Mono + Noto Sans SC），每台机器上界面都长得一样。

## 快速开始

### 方式 A —— 下载 release 构建

从 [Releases](../../releases) 下载最新的 `cc-wire-analyzer-v<版本>-windows.exe` 或 `cc-wire-analyzer-v<版本>-macos.zip`。不需要 Python。版本号既在文件名里，也刻在文件属性里（Windows 右键属性 →「详细信息」，macOS「显示简介」），**不打开程序也能分辨手上是哪一版**。旁边的 `SHA256SUMS.txt` 就是软件内自动更新用来校验下载的那份清单。

- **Windows**：双击 `.exe`。如果提示 WebView2 缺失，装一下 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
- **macOS**：解压，把 `cc-wire-analyzer.app` 拖到 `/Applications`。应用**未签名、未公证**（免费开源项目常态——签名要 $99/年），所以**首次启动会被 Gatekeeper 拦**。放行一次即可：
  - 右键 `cc-wire-analyzer.app` →「打开」→ 弹窗点「打开」；**或**
  - 较新 macOS 没有上面那个选项时：**系统设置 → 隐私与安全性 → 拉到底 → 点「仍要打开」**。
  - 首次放行后正常打开，不再提示。（这是 Apple 的安全机制，不是 app 本身有问题。）

### 方式 B —— 源码运行

```bash
git clone https://github.com/FuHehe12/cc-wire-analyzer.git && cd cc-wire-analyzer
uv sync                 # Windows
uv sync --extra mac     # macOS（装 pyobjc）
uv run python src/desktop.py
```

然后在软件里点**启动代理**，新开一个 Claude Code 会话，正常使用——流量就出现在捕获列表里。

## 工作原理（30 秒版）

1. 你点**启动代理**。
2. 软件备份 `~/.claude/settings.json`，然后把 `ANTHROPIC_BASE_URL` 设成 `http://127.0.0.1:<端口>`（只这一字段，其他不动）。
3. Claude Code 此后所有请求都发给本地代理，代理录制（JSONL，headers 脱敏）并转发给真正的上游。
4. 你点**停止代理**（或关闭软件）→ `ANTHROPIC_BASE_URL` 字节级复原。

代理运行期间，**不要用 cc-switch 切换端点** —— 它会重写 `BASE_URL`，CC 就绕过代理了。

## Claude Code 报 API 错误怎么办

录制靠临时把 `ANTHROPIC_BASE_URL` 指向本地代理，软件退出时会自动恢复（多重兜底 + 孤儿标记自愈）。如果录制后 CC 仍报 API 错误——连不上、401、超时——基本是 `~/.claude/settings.json` 里的 `BASE_URL` 残留或不对。按端点类型处理：

- **第三方 API / 网关**：打开 `~/.claude/settings.json`，把 `ANTHROPIC_BASE_URL` 改回你网关的地址（或用 cc-switch 切回）。
- **官方 Anthropic 订阅**：**删掉** `ANTHROPIC_BASE_URL` 这个字段——官方端点不需要 base URL——然后**完全退出 Claude Code 再重启**。CC 只在启动时读 `BASE_URL`，运行时改文件不生效。

## 数据位置

| 路径 | 内容 |
|------|---------|
| `~/.cc-wire-analyzer/captures/<YYYY-MM-DD>.jsonl` | 请求/响应录制（只追加） |
| `~/.cc-wire-analyzer/archives/<date>.<HHMMSS>.jsonl.zip` | 归档录制（选“压缩存档后删除”时） |
| `~/.cc-wire-analyzer/snapshots/snap_*.json`（+ `.chat.jsonl`、`index.jsonl`） | 你在 Analyse 标签页保存的快照——永不自动删除（`retention_days` 不碰），标签页显示总占用 |
| `~/.cc-wire-analyzer/backups/settings.json.<ts>` | settings.json 备份（留最近 5 份） |
| `~/.cc-wire-analyzer/config.json` | 应用配置（ui_lang / translate / explain…） |
| `~/.cc-wire-analyzer/run.log` | 运行日志 |

## 给 AI agent：用 HTTP 驱动它

这软件不只是给人看的 —— **AI 也能自己开、自己查**。一个 exe，三种调用：

- `cc-wire-analyzer.exe`（双击）→ 开 GUI
- `cc-wire-analyzer.exe serve` → 起**后台 HTTP 服务 + 代理**，不开窗，给 AI 用
- `cc-wire-analyzer.exe --help` → 打印完整用法说明后退出（不开窗）

**说明书打在二进制里。** 让 AI 用这个工具不需要这个仓库：`--help` 直接打印说明；服务起来后
`GET /api/ai-guide` 返回同一份正文，外加这台机器的运行期事实（实际端口、数据目录绝对路径、
是否正在录制）。所以把它交给你自己的 AI 只要一句话：

> 这台机器上开着 CC Wire Analyzer。读 `http://127.0.0.1:<端口>/api/ai-guide`，然后按说明驱动它。
> （端口写在 `~/.cc-wire-analyzer/port.txt`。）

通过 `127.0.0.1` 上的 HTTP 跟它对话（和 GUI 用的是同一套端点）：

```bash
cc-wire-analyzer.exe serve &                     # 起服务 + 代理（patch settings.json）
port=$(cat ~/.cc-wire-analyzer/port.txt)
curl 127.0.0.1:$port/api/proxy/status            # 在录吗？
# …跑你要录的会话…
curl -X POST 127.0.0.1:$port/api/proxy/stop
curl "127.0.0.1:$port/api/captures?date=2026-07-13"
```

单条录制可超过 5 MB，先查摘要、按 id 取单条。完整 API、记录 schema 与安全注意事项见
**[docs/reference/AI_USAGE.md](docs/reference/AI_USAGE.md)**。

macOS 同样是一个二进制 —— `cc-wire-analyzer.app/Contents/MacOS/cc-wire-analyzer serve`。

## 可选：翻译 / 问 AI

详情页可以通过任何 OpenAI 兼容的 `/chat/completions` 端点翻译文本或解读"这段内容在干什么"。在**设置 → LLM 模型**里配 API key / base URL / model。解读功能内置注入防护（不可信的捕获内容被定界符包裹；字面闭合标签被转义；隔离框架是硬编码的，不受你的自定义提示词影响）。

## 源码构建

构建步骤见 [CONTRIBUTING.md](CONTRIBUTING.md#building)（单一真源，避免 Windows/macOS 两套命令分叉）。Release 由 [`.github/workflows/release.yml`](.github/workflows/release.yml) 在每个 `v*` tag 上自动构建。

## 和其他可观测性工具的关系

本工具覆盖**链路层**（原始 HTTP）。它和基于 jsonl 的对话分析器（CC 自己的视图）、OTLP 遥测（指标视图）配合得很好——三者互补。

## 许可证

- 代码：**MIT**。
- 文档与文字（README / docs / 界内文字）：**CC BY 4.0** —— 复用时请注明出处。
- 打包字体（Inter / JetBrains Mono / Noto Sans SC）：**SIL OFL 1.1**。
- 打包 JS（marked.js：MIT；DOMPurify：Apache-2.0/MPL-2.0）。

代码协议见 [LICENSE](LICENSE)，文档与文字协议见 [LICENSE-DOCS](LICENSE-DOCS)，打包依赖见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES)。API 契约等技术文档见 [docs/reference/API契约.md](docs/reference/API契约.md)，开发设置见 [CONTRIBUTING.md](CONTRIBUTING.md)。
