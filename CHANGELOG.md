# 变更记录

开头是项目状态卡（只写现在），下面是未发布改动与当前版本；更早版本见[变更历史](CHANGELOG-history.md)。变更按新增、修复、变更或文档分类，说明问题、改动与必要影响；大体经历查 `git tag -n`，每步改了什么查 `git log`，为什么这么定查本地 `issues/closed/`。

## 定位

- 本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。
- 人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。

## 背景

- 从 wire 流量记录发展而来，与 Claude Code 本地日志和 OTLP 互补。
- 要解决的是让调用、上下文、失败与分析结论都能回到证据核对。

## 现状

- v0.4.36 已发布。观察者提示词把「G 是什么」与「最高目标的两种变法」写成可操作的判据——G 记的是执行 AI 当时认定的最高目标（不是用户原话的抄录，也不是事后归纳的主题），最高目标被抬高、收窄或换向都记 `goal`，并从「先复核 G 变没变」起固定成三步判断。
- 三处提示词面（`AI_USAGE.md`、`API契约.md`、界面「复制接入说明」三语）与界面图例已同步；A→G 图的 G/T 层级与二遍布局、日期条待看徽标、`×N` 色块对比度如 v0.4.35。
- 产出是桌面应用、供 agent 使用的 HTTP/CLI 分析面，以及由本地源生成的产品说明书。
- `public/` 仍冻结，发版不更新它。
- macOS 升级提示：自 v0.4.2 起应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 关键判断

- 外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- 保留的产品问题一：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发。
- 保留的产品问题二：是否利用 Claude Code 本地日志修正轮次来源，尚未采用。
- 保留的产品问题三：存储方面仍有骨架指针增量编码和「先压实再清理」的后续方案；指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。

## 下一步

- 收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。

## 未发布

### 修复

- **`tools/build/manual/build_product.py` 在 Python 3.11 下编译不过**（issue 260912_build_product在311下不可编译）。第 34 行 f-string 的替换字段里用了与外层同类型的单引号（`f'… {gap['id']}'`），这是 PEP 701（3.12）才合法的写法，3.10/3.11 直接报 `SyntaxError`。在 3.11 下逐文件扫描 `src/`、`tests/`、`tools/` 共 54 个 .py，**失败只有这一处**。CI 没拦住是因为 verify job 跑 3.12、CONTRIBUTING 也写明「本地说明书生成使用 Python 3.12+」，只有第八节清单的 `compileall` 条目覆盖 `tools/build` 却没带这个前提，在 3.11 本机按清单跑就会撞上。外层引号改成双引号后 3.10+ 均可编译，语义不变。

### 文档

- **第八节自测清单补回 `node tests/observe_guide_selftest.js`**（issue 260912_自测清单漏登observe_guide_selftest）。与 `release.yml` verify 的 Self-tests 步（17 条 Python + 2 条 Node）逐条对账，**CI 有而清单没有的只有这一条**；它断言界面「复制接入说明」三语×已建/未建观测的文案，少登则它只在 CI 上跑，CI 红在它上面时本地复现不出来。核对中发现此前对 compileall 的理解有误：清单那条与 CI 的 Syntax 步只是路径写法不同，`compileall` 递归子目录，两者覆盖完全相同，并非「清单多覆盖」；上一条 bug 没被 CI 拦住的原因是 CI 跑 3.12，与路径无关。「改 CI 时顺手对一遍清单」260825 就写了，这次是发版逐条跑时才对出来的——「顺手」没有触发点。
- **架构总览 §3.1 端点分组表补齐整组缺失，并给 `doc_audit` 加分组覆盖软检查**（issue 260911_架构总览端点表补齐）。问题：该表只列了约 20 条路由骨架，快照、就地更新、外环观测、来源、上游配置历史、实例、存储占用、失败趋势等整组缺席（合计 40+ 端点、外加页面路由），而 `doc_audit` 的端点对账只认 API契约.md，契约侧全绿，导航层没有任何机器在看——「架构总览」是新人和 agent 的第一张地图。改动：①表按方案 B 重写成通配分组（组名 / 通配端点 / 受众 / 契约章节指路，行序跟契约章节走），受众列逐组对照契约原文、前端 fetch 调用面与 CLI 子命令重新核对（`/api/actions` 契约明写「外环观测者用」、界面只读显示清单；`trends` / `uncompact` 无界面入口走 CLI 或 API；`ai-guide` / `unknowns` 前端零调用，维持仅 AI）；补页面路由行（`/`、`/view`、`/favicon.ico`）与 catch-all 并列。②`doc_audit` 新增第 10 条检查 `_overview_group_gaps`：每个 `/api/*` 路由的组前缀（第一段）须在 §3.1 出现，只查组不查端点，与通配写法天然兼容；归软差异不挡发版（导航层漏一行不该卡发版，契约那条硬门已保证事实源不缺）；自测补五条用例（缺口能检出 / 通配覆盖同组 / §3.1 锚点解析到正文 / 真实表全覆盖 / 软分类不挡）。③开发约定第十一节文档维护表新增「端点分组导航」行：新增端点不必回改表，新增组必须登记。实施中踩到一次自误报：示例写法 `` `/api/<组>` `` 被幽灵端点正则当成引用提取，改成散文写法后干净——闸门对自己人也生效。验证：`doc_audit.py` 对账干净（通配写法未触发 ghost 误报）、`--self-test` 全过、`check_refs.py` 未解析 0，issue 的缺失清单逐组人工对拍全部覆盖。

## v0.4.36 - 2026-09-12

### 中文

#### 文档

- **观察者提示词把「G 是什么」和「最高目标的两种变法」写成可操作的判据**（issue 260912_G的定义与最高目标的两种变法）。用户反馈：G 的定义是同义反复（「最高目标／用户总体上要达到的结果」），观察者没有可量的判据；最高目标的变化只写了「转折」一种，更常见的「改进」（目标仍指向同一件事，但被抬高、收窄或加了新的结果条件，方向连续、没有「换了一件事」的信号）被回落记成 `refine`——260912 反馈包里两次误记正是它；且 `turn` 的中文标签「转折」是任务层转折，与最高目标转折撞车。三处提示词面（`AI_USAGE.md`、`API契约.md`、界面「复制接入说明」的 `ob.guide` 三语）缺的是同样两件事。改动：G/T 各一句判据（G＝「它现在做的每件事最终是为了什么」，T＝「这件事做完或放弃，最高目标还是那个吗」），并写明 G 记的是**执行 AI 当时认定的**目标，不是用户原话的抄录、也不是事后归纳；改进/转折并列成表，各给形态、例子和易误记去向（改进→`refine`，转折→`turn`）；判断固定成三步（先复核 G 变没变 → 变了记 `goal` 并在 trigger 写清改进还是转折 → 没变才在 `refine`/`turn` 里二选一）；旧 G 的收口写全（`superseded` / `unresolved` / `mistaken`）。**不新增 `change` 取值**——两种变法结构条件相同，差别由 trigger 一句承载；界面图例 `G｜目标` 同步改成「被抬高、收窄或换了方向都算」。

### English

#### Documentation

- **The observer prompt turns "what G is" and "the two ways the top-level goal changes" into criteria you can act on** (issue 260912_G的定义与最高目标的两种变法). User feedback: the definition of G was circular ("the highest goal / the result the user is after overall"), leaving the observer nothing to measure against; and only one kind of change — a turn — was described, whereas the more common "improvement" (the goal still points at the same thing but is raised, narrowed, or given a new result condition; directionally continuous, no signal of "something else was started") fell back to `refine` — exactly the jump mis-recorded twice in the 260912 feedback pack; the Chinese label of `turn`, "转折", is a task-level turn and collides with a turn of the highest goal. All three prompt surfaces (`AI_USAGE.md`, `API契约.md`, the three languages of `ob.guide` behind the interface's "copy setup instructions") lacked the same two things. Changes: one criterion each for G and T (G = "what is everything it is doing now ultimately for", T = "if this were finished or dropped, would the highest goal still be that one?"), with the statement that G records **the goal the acting AI held at the time**, not a transcript of the user's words nor a theme abstracted afterwards; improvement and turn laid out in a table, each with its shape, an example, and what it tends to be mis-recorded as (improvement → `refine`, turn → `turn`); the decision fixed to three steps (re-check whether G changed → if it did, record `goal` and say in the trigger whether it is an improvement or a turn → only if it did not, choose between `refine` and `turn`); closing out the old G spelled out (`superseded` / `unresolved` / `mistaken`). **No new `change` value** — the two have identical structural conditions and one line in the trigger carries the difference; the interface legend follows with "raised, narrowed, or pointed elsewhere all count".

### 日本語

#### ドキュメント

- **観察者プロンプトで「G とは何か」と「最高目標の二通りの変わり方」を実行可能な判断基準にしました**（issue 260912_G的定义与最高目标的两种变法）。利用者からのフィードバック：G の定義は同義反復（「最高目標／利用者が全体として達成しようとしている結果」）で、観察者がものさしを持たず、最高目標の変わり方については「転換」の一種類しか書かれておらず、より多い「改善」（目標が同じ事柄を指したまま引き上げられ、絞り込まれ、新たな結果条件が加わる型。方向は連続し「別のことを始めた」信号がない）が `refine` に誤記される——260912 のフィードバックで二度誤記された跳躍がまさにこれ。さらに `turn` の中国語ラベル「転換」はタスク層の転換で、最高目標の転換と衝突しています。三つのプロンプト面（`AI_USAGE.md`、`API契約.md`、画面の「接続手順をコピー」の `ob.guide` 三言語）に同じ二点が欠けていました。変更点：G と T にそれぞれ一句の判断基準を与え（G＝「今行っている一つ一つのことの最終的な目的は何か」、T＝「これをやり終えても、あるいは放棄しても、最高目標は依然としてそれか」）、G が記録するのは**実行 AI がその時点で認定していた**目標であり、利用者の発言の筆記でも事後の要約でもないことを明記。改善／転換を表に並べ、それぞれ形態・例・誤記されやすい先（改善→`refine`、転換→`turn`）を付けました。判断は三歩に固定（まず G が変わったかを再確認 → 変わったら `goal` を記録し trigger に改善か転換かを明記 → 変わっていなければ `refine`/`turn` の二択）。古い G の収束も書き揃えています（`superseded` / `unresolved` / `mistaken`）。**`change` の値は増やしていません**——両者は構造条件が同じで、違いは trigger の一行が担います。画面の凡例も「引き上げ、絞り込み、方向転換のいずれも該当する」に揃えました。
