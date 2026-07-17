# 更新日志

> 本文件是 [`CHANGELOG.md`](CHANGELOG.md) 的中文翻译镜像，与英文版保持同步。英文版为源。

## [Unreleased]

### 新增
- **settings.json 外部修改监视。** 用 cc-switch 切换端点（或手改文件）会覆写
  `ANTHROPIC_BASE_URL`——CC 静默绕过代理直连上游，而 UI 仍显示「运行中」，监控断档且毫无征兆。
  现在后台线程每 2 秒比对一次值（读几 KB JSON；刻意不用 mtime 基线——patch 后有竞态窗，
  也不引入文件事件库依赖）。发现不符即置「已断开」状态、清 marker、**绝不回写文件**
  （新值是用户的新意图），界面红色横幅显示新上游并提供一键**重新接管**——本质就是一次普通
  start，snapshot 自然收编新上游。`/api/proxy/status` 暴露 `external_change` 字段，
  serve 模式下驱动它的 AI 同样感知得到。
- **能回答「上次会话怎么结束的」的退出日志。** run.log 此前只以副产品形式记录退出
  （一行 `restored BASE_URL`，且仅当代理在跑时）——07-15 的一次会话只留下孤零零一行日志，
  怎么结束的无从知晓。现在有：启动横幅（`=== started mode=gui|serve pid=… version=… port=… ===`）、
  每条可落笔的退出路径的显式记录（关窗、GUI 收尾、API 手动停止、atexit、信号），以及孤儿自愈
  触发时一句人话「上次进程未正常退出（强杀/断电/崩溃）」。启动横幅后没有对应退出行 = 必是强杀。

### 修复
- run.log 此前按系统 locale 编码写入（中文 Windows 是 GBK），中文日志在任何 UTF-8 工具里
  都是乱码。现在显式 UTF-8（历史 GBK 段不迁移）。

### 变更
- **release notes 现在取自 `CHANGELOG.md`。** 发布工作流此前用的是 `generate_release_notes`，
  它按 pull request 分组列出条目——对这种单人直接提交（无 PR）的项目毫无意义，因此 v0.1.0 和
  v0.2.0 的 release 页面只剩一行光秃秃的 "Full Changelog" 链接，详细的 changelog 根本没人读到。
  现在 release job 会从这个文件提取当前 tag 对应的段落（带 tag message 和占位兜底），release 页面
  自动带上完整的 changelog。

### 新增
- 本更新日志的中文版 `CHANGELOG.zh.md`，与英文版保持同步。

## v0.2.0 - 2026-07-14

### 变更
- **合并为单一二进制。** 此前：GUI exe + CLI exe（51 MB，两个文件）。现在：一个 noconsole GUI
  exe，带 `serve` 子命令。双击 → 给人用的 GUI；`cc-wire-analyzer.exe serve` → 后台 HTTP 服务 +
  代理，不开窗，给 agent 用。agent 调用的是 GUI 早已在用的同一套 HTTP API
  （`/api/proxy/*`、`/api/captures`、`/api/dag`）。之所以能这样：Windows 的 noconsole 二进制没有
  stdout——CLI 子命令本来就没法把结果打印回给 agent；HTTP 才是正确的通道。macOS 同样是单一二进制
  （它从来没有 console / 窗口态的区分）。参见 [docs/AI_USAGE.md](docs/AI_USAGE.md)。`cli.py` 作为
  开发者便利保留在源码树中（`uv run python src/cli.py`），但不再打包或随发行版分发。

### 新增
- 界面复制支持：每个内容块上的**复制**按钮（折叠时也能复制全文）、**自定义右键菜单**，以及
  **Ctrl/Cmd+C** 处理。pywebview 在 debug 模式之外会禁用 WebView2 的原生右键菜单，而它的 WebKit
  后端根本不构建 Edit 菜单——所以 macOS 上 Cmd+C 原本毫无反应。现在复制完全由前端处理，两个平台
  行为一致。
- 详情视图中的**响应头面板**。代理一直在录制 `response.headers_safe`，界面却从未展示——把这一层
  最有价值的东西扔了：`anthropic-ratelimit-*`、`request-id`、`x-should-retry`、上游实际服务的模型。
- `tools/lane_probe.py`——把区分主线和子代理的候选信号摊开来（`X-Claude-Code-Session-Id`、
  `cc_entrypoint`、是否带 `Agent` 工具、system 块结构、派生 prompt 对齐），让分类器能对着真实流量
  校准，而不是靠猜。
- `CCWA_HOME` / `CCWA_CLAUDE_SETTINGS` 环境变量覆盖，以及 `src/cli_selftest.py`。本项目最危险的路径
  ——改写用户的 `~/.claude/settings.json`——以前无法端到端测试，除非拿用户真实的 Claude Code 配置
  当试验品。现在跑在临时目录里。

### 修复
- **退出时不恢复 `ANTHROPIC_BASE_URL`。** 恢复逻辑挂在 `webview.start()` 返回上，但 macOS 的
  Cmd+Q / 红点关窗走的是 `NSApplication.terminate:` → C 层 `exit()`，不展开任何 Python 调用栈、
  也不跑任何 `atexit` 钩子。`settings.json` 被留在指向一个死掉的本地端口，**Claude Code 再也连不上
  任何上游**——而且是在工具已经关掉之后。现在挂到窗口的 `closing` 事件上——这是 pywebview 唯一同步
  派发的事件，也是 macOS 两条退出路径都会触发的那个。已在 macOS 上验证（pywebview 6.2.1）：红点和
  Cmd+Q 都会恢复 `BASE_URL` 并清掉 marker——源码层面的假设（`closing` = 同步的 `Event(self, True)`，
  两条 Cocoa 退出路径都经 `should_close()` 走）在 6.2.1 依然成立。
- **陈旧的恢复 marker 可能删掉用户的配置。** `recover_from_orphan()` 只看 marker 文件就动手，从
  不检查 `settings.json` 当前到底是什么。如果 app 在 patch 状态下被杀、用户随后又自己设了
  `ANTHROPIC_BASE_URL`（比如用 cc-switch），下次启动就会覆盖它——或者，对 `had_key: false` 的
  marker，**直接把键删掉**。现在恢复只在当前值仍等于我们 patch 进去的地址时才进行。
  （`_is_local_proxy_url()` 自从 marker 重构后一直是个零调用的死代码；这道守卫回来了。）
- **保留天数是个死配置。** 设置页承诺"超过 N 天的录制会自动清理"，但代码库里没有任何东西读
  `retention_days`。录制永远累积——13 条就已经 5.6 MB。现在在启动时强制执行，结果回传给界面，
  并提供 `clear --older-than N` 命令。
- **非流式响应丢了 usage、内容块和停止原因。** 非 SSE 分支只在 JSON 的*顶层*找 token 计数
  （恰好是 `count_tokens` 返回的形状），而正常的 `/v1/messages` 响应把它们嵌在 `"usage"` 下；
  `content_blocks` / `stop_reason` 又只在 SSE 分支里解析。Claude Code 的**安全分类器调用正是非流式
  的**——它们在每个会话后台跑、用户看不见、却花真金白银（实测 551 input + 28,224 cached）。它们的
  成本被这个"专门用来揭示成本"的工具扔掉了。
- **失败的录制写入被静默吞掉。** 磁盘满、权限问题或文件被锁时，`append()` 丢掉 `OSError` 照常继续
  ——而坐在 `try` 外面的 LIVE deque 和 SSE 推送还在照常跳。界面继续跳着新录制、磁盘上却什么都没落。
  现在写入失败会被计数、记录、暴露到 `/api/proxy/status`，并以红色横幅展示。（转发仍然绝不被写入
  失败阻塞——那部分是对的。）
- DAG 节点的 token 计数永远是空的，CLI 的 token 总数永远是 0：两者都读短的 `usage.input` 键，而
  SSE 聚合产生的是 Anthropic 的全名（`input_tokens`、`cache_read_input_tokens`）。键名归一化现在
  只在一个地方（`classifier.usage_norm`）——这个 bug 之所以出现两次，正是因为那段逻辑被抄来抄去。
- 上游错误的真实原因从不显示。代理在连接/超时失败时记录 `{kind, detail}`，但界面只渲染
  `kind`/`status`/`body_snippet`——所以一次失败的上游连接只显示成一个光秃秃的 `connect`，原因被丢
  了。讽刺，对一个调试工具来说。
- `auto_start_proxy` 是个死配置，和 `retention_days` 一样：设置页提供开关、忠实地存储它，却从没
  有任何东西读它。现在接上了。
- 自测的 mock SSE 用了现实中不存在的 token 键名（`input`、`output`，而非 `input_tokens`、
  `output_tokens`），这正是上面的键名错位一直没被发现的原因。已修，并补了一个非流式上游用例——整
  条非 SSE 路径此前从没被断言过。
- **长文本翻译静默失败。** `_llm_chat` 不发 `max_tokens`（上游的小默认值会截断长输出），并在 120 秒
  超时；失败时界面只闪一下 toast、翻译区留白，用户看到一个空的"重译"、没有任何原因。现在设了
  `max_tokens`、把超时提到 180 秒并带专属 `timeout` 错误码，**把错误持久化到结果区**（带
  `error_code` + 上游 `finish_reason` 提示，如 length / content_filter），而不是凭空消失。已验证：
  一段 106K 字符的安全 prompt（截到 20K）约 38 秒译完。
- **带非 ASCII 字符的 API Key / Base URL** 会产生一段晦涩的 `'latin-1' codec can't encode…`
  traceback（HTTP 头是 latin-1）。从网页复制时零宽空格和全角字符很容易混进来。现在在前端就拦住，
  给出一条人能读懂、点名出问题字符的提示。
- 翻译/解读的输出有时会漏出引擎包裹内容用的 `<text>` / `<content>` 定界符标签。现在会从结果里剥掉。

### 移除
- **独立的 CLI 二进制**（`cc-wire-analyzer-cli.exe`）——并入 GUI 二进制的 `serve` 模式（见"变更"）。
  下面的"头部脱敏"开关也一并去掉了。
- **"头部脱敏"开关**。它从没起过作用（`_redact()` 一直被无条件应用），与其接上它，不如直接移除：
  让它真正生效，意味着提供把 API key 明文写进录制文件的选项——而那些文件现在正被 agent 读取。
  脱敏是无条件的，不再假装是可选的。
- `config.read_port()`——自从 shell 不再是独立进程后就是死代码。

## v0.1.0

首个开源发行版。
