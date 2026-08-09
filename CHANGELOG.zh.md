# 更新日志

> 本文件是 [`CHANGELOG.md`](CHANGELOG.md) 的中文翻译镜像，与英文版保持同步，英文版为源。
> 已发布版本的完整说明在 [`CHANGELOG-history.zh.md`](CHANGELOG-history.zh.md)。

## 项目速览

> 定位 / 当前状态 / 下一步——AI 接手快照。仅作导航；属规则/不变量的关键判断见本地 CLAUDE.md（开发约定）。条目里的 issue 路径是本地维护记录（gitignored，不在本仓库）。

- **定位**：本地 MITM 代理桌面应用，透明录制 Claude Code ↔ 上游端点的全部 HTTP 流量，填补 jsonl 日志与 OTLP 遥测看不到的链路级维度。双模式：GUI 给人看，`serve` 子命令暴露 headless HTTP API，让 AI agent 自己驱动排查——面向 agent 的说明书打包在产物里（`--help`，以及运行后的 `GET /api/ai-guide`），换一台机器用它不需要仓库。
- **当前状态**：**v0.4.11 已发布**（2026-08-09）。头号新特性是**就地自更新**：关于页的「检查更新」此前比完 tag 就打印一行地址，现在能下载、校验、替换正在运行的二进制、并重启——整条链路在 `/api/update/*` 后面，agent 也能驱动。它是「点一下就换好」，不是「自动升级」：没有定时检查、没有静默安装，每一步都对应一次点击，录制中拒绝替换且不代劳停代理。作为本项目第一条会下载并执行二进制的路径，带着第 10 条安全不变量（来源硬编码、逐跳 host 白名单、校验和优先）。版本号也从「只有打开程序才看得到」变成 PE 资源 / macOS Info.plist / 资产名四处可见。另有：`tools/build.py` 让本地打包与 CI 同源、更新重启的退出顺序从时序假设改为顺序保证、修了本地 `uv run pyinstaller` 打的 exe 在 serve 模式崩 werkzeug metadata 的问题。**macOS 升级用户注意**（自 v0.4.2 起未变）：应用包由 `CCWireAnalyzer.app` 改名 `cc-wire-analyzer.app`，`/Applications` 里旧的那份不会被替换，需自行删除。
- **下一步**：
  1. **把自迭代闭环走通**：`/api/diagnose/trends` 现在能可靠回答「新发还是老毛病」，但从「一个复发模式」到「一条体检规则」仍然靠人——`effort_max_rejected_upstream` 之所以存在，是因为有人盯出了那次复发并手写了规则。把这半自动化，雷达与趋势才不只是「读一读」。
  2. **判别残余**（暂缓）：交互模式（`cc_entrypoint=cli`）的子代理仍缺一次人工核对过的采集。历史录制已有统计旁证（225 条全部带判别位、零反例），但那与「采一次会话逐条对照 ground truth」不是一回事。
  3. 录制盲区审计（协议面 + 能力面）已于 v0.4.3~v0.4.6 收口，方法见 `docs/reference/开发约定.md` 第二·五节与 `docs/methodology/同类工具构建手册.md` 单元 0。

## 未发布

（暂无）

## v0.4.11 - 2026-08-09

### 新增

- **「检查更新」现在把活干完：下载、校验、替换、重启。** 此前它比完 tag 打印一行地址就结束——通知做完了，最麻烦的六步（记地址、开浏览器、找资产、下载、关掉正在跑的程序、覆盖）全留给用户。整条链路现在在 `/api/update/*` 后面，于是 agent 也能驱动它，前后端也不会各查一次 GitHub 得到两个不同的答案。**这是「点一下就换好」，不是「自动升级」**，区别不是措辞：本工具在录制期间持有用户 `settings.json` 的 patch 态，所以没有定时检查、没有静默安装——每一步都对应一次点击，而且**录制中拒绝替换，不代劳停止代理**，因为停代理会写回你的 settings.json，那不该由「我想升级」这个意图顺带触发。Windows 就地替换：正在运行的 exe 不能被写，但**可以被改名**，所以顺序是同目录中转 → 把旧的改名挪开 → 把新的换进来，任一步失败整体回滚——这是本项目唯一会动用户磁盘上可执行文件的路径，出事时用户手上连一个能用的程序都没有。macOS 有意只做到下载、校验、在访达里指出来：维护者在 Windows，而替换一个正在运行的 bundle 还牵扯隔离属性与 Gatekeeper。作为这里第一条**会下载并执行二进制**的路径，它成了第 10 条安全不变量：来源仓库硬编码（下载地址一旦可配置，这个无需认证的本机 HTTP 接口就成了「让本机下载并运行任意二进制」的入口）、只走 https 且**逐跳**校验重定向主机（release 资产必然重定向到对象存储，只查第一跳等于没查）、release 带 `SHA256SUMS.txt` 就强制比对——没有时面板会**明说没有并给出实测校验值**，而不是悄悄降级成「仅传输层保护」。自测抓到一个真 bug：下载失败原本会把上一份同名安装包留在更新目录里，那是最糟的残留形态——一个看起来完好、来路不明的 exe 躺在那儿等人双击。

- **不打开程序也能看到版本号了。** 版本号此前只活在运行期（`/api/about`、`--help`），下载到磁盘上的 exe 属性页里「文件版本」一栏是空的，想分辨两个版本只能双击打开其中一个——而对一个启动就可能 patch `settings.json` 的工具来说，「打开」不是零成本动作。CI 从 tag 生成的那份 `src/_version.py` 现在供给四个出口：API、Windows 的 PE 版本资源、macOS 的 `Info.plist`，以及 release 资产文件名（`cc-wire-analyzer-v0.4.11-windows.exe`）。**两份 spec 共用 `tools/version_res.py`，不各写一份**——它们分叉过一次（mac spec 没跟上 `brotli`，macOS 上每条非流式响应都丢了 body），共享模块让分叉在结构上不可能发生，比加一条要人记得跑的检查更彻底。`doc_audit` 仍兜一层：哪份 spec 掉了这个 import 就挡发版。release 另出 `SHA256SUMS.txt`，正是软件内自动更新用来校验的那一份。

- **`tools/build.py`：本地打包与 CI 同一份版本号 / 命名 / 校验和。** `uv run python tools/build.py` 产出 `cc-wire-analyzer-v<版本>-<平台>.exe` + `SHA256SUMS.txt`，与 CI 一致——命名规则和校验和 glob 此前只在 `release.yml`（bash）里，两个语言各写一份字符串拼接规则正是惯犯⑦的形状。`--from-git` 从 `git describe --tags` 取版本；`--self-test` 独立拼出期望文件名再与函数对照，哪边改了没跟另一边就会响。

### 修复

- **切换界面语言后，Analyse 标签页里已渲染的快照对比结果现在会跟着刷新。** 对比结果——结论行、工具按钮、隐蔽差异表、正文表头——由 `renderDiff` 生成，它把 `t18()` 文案**直接拼成纯文本**写进 DOM（没有 `data-i18n`），`applyI18n()` 够不到；切语言后它停在「做对比那一刻」的语言上，要 reload 页面才更新。和 260801 设置页撞的是同一个坑（`renderSettingsI18n`），只是这次落在 v0.4.10 才加的 Analyse 视图上——260801 那条教训虽写进了开发约定，但一条文字规则拦不住一个全新视图再次漏掉重渲。`renderDiff` 现在按面板缓存结果（`AN.pDiff` / `AN.rDiff`），`setLang` 在该面板仍选中两个快照时用缓存重渲——选中状态本身就是缓存的有效性闸卫，选择变了就不会把失效的对比复活。无新 API 调用、无 loading 闪烁。
- **快照对比里的可比性护栏 warnings 现在也跟随界面语言。** 这些 warnings（「请求类型不同」「提示词身份指纹不同——这两段本就是不同的提示词」「模型不同」……）原本是 `snapshot_diff.py` 里硬编码的中文、被原样渲染，于是在任何语言下都停在中文——和上一条同形的缺口，只是这段文本住在后端。`renderDiff` 现在把每条 warning 的 `field` 映射到 `an.guard.<field>` i18n 键（三语、五个 field），仅在缺键时回退后端 `why`；后端原文保留给 HTTP API 消费者（agent），API 契约不变。后端未改。

- **更新重启现在先恢复 settings.json 再拉新进程。** 原来顺序是 Popen → 恢复 → 退出，靠"新进程冷启动慢（1~2 秒）、恢复微秒级"这个时序保证正确。但 serve 模式新进程启动时会自动 patch settings.json，万一旧进程的 restore 跑在新进程 patch 之后，就会撤销新进程刚做的 patch。改成 恢复 → Popen → 退出，三步在同一线程内顺序执行，不再依赖时序假设。这个修复在跑第一次完整 e2e apply 时才暴露——一个改名残留（`on_exit` → `restore_fn`，`py_compile` 不报、运行时 NameError，惯犯⑥的 Python 侧）让 apply 500 了。

- **本地 `uv run pyinstaller` 打的 exe 在 serve 模式崩 `PackageNotFoundError: werkzeug`。** Werkzeug 3.x 在 `BaseWSGIServer.__init__` 里调 `importlib.metadata.version("werkzeug")`，PyInstaller 的自动 metadata hook 在 uv 的 venv 布局下（hardlink 而非标准 site-packages）找不到 `.dist-info`。CI 不受影响（标准 pip install）。`version_res.runtime_metadata()` 现在收集六个 dist-info（werkzeug / flask / click / jinja2 / itsdangerous / markupsafe），两份 spec 都追加到 `datas`——与版本资源一样共用一个模块，两份 spec 不会分叉。

## 更早的版本

v0.4.8 及更早：[CHANGELOG-history.zh.md](CHANGELOG-history.zh.md)，或 [GitHub Releases 页](https://github.com/Fuhehe12/cc-wire-analyzer/releases)（同一份说明）。
