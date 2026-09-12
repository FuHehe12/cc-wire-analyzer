# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.36 已发布。观察者提示词把「G 是什么」与「最高目标的两种变法」写成可操作的判据——G 记的是执行 AI 当时认定的最高目标（不是用户原话的抄录，也不是事后归纳的主题），最高目标被抬高、收窄或换向都记 `goal`，并从「先复核 G 变没变」起固定成三步判断；三处提示词面（`AI_USAGE.md`、`API契约.md`、界面「复制接入说明」三语）与界面图例同步。A→G 图的 G/T 层级与二遍布局、日期条待看徽标、`×N` 色块对比度如 v0.4.35。`public/` 仍冻结，发版不更新它。
- **下一步**：收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

### 修复

- **`tools/build/manual/build_product.py` 在 Python 3.11 下编译不过**（issue 260912_build_product在311下不可编译）。第 34 行在 f-string 的替换字段里用了与外层同类型的引号（`f'… {gap['id']}'`），这是 PEP 701（3.12）才合法的写法，3.10/3.11 直接报 `SyntaxError: f-string: unmatched '['`。CONTRIBUTING 写的是「本地说明书生成使用 Python 3.12+」，所以生成说明书本身没暴露它；露出来的是第八节清单最后那条 `compileall … tools/build …`——它覆盖了 `tools/build` 却没写这个前提，于是任何人按清单跑到最后一条，都会撞上一个与本次改动毫无关系的报错，还得先判断「这是不是我改坏的」。在 3.11.13 下逐文件 `compile()` 扫描 `src/`、`tests/`、`tools/` 全部 74 个 .py，**失败只有这一处**，是孤例不是一类问题。改成内层双引号后 3.10+ 均可编译，语义不变。

### 文档

- **第八节自测清单补回 `node tests/observe_guide_selftest.js`**（issue 260912_自测清单漏登observe_guide_selftest）。与 `release.yml` 的 verify job 逐条对账，**CI 有而清单没有的只有这一条**（清单多出的 compileall 是有意差异：CI 把语法检查拆成单独的 Syntax 步，路径只到 `src tests tools`，清单那条多覆盖 `tools/build`、`tools/checks`、`tools/probes`）。少这一条的后果是它只会在 CI 上跑，本地怎么跑都是绿的——而 CI 一旦红在它上面，本地复现不出来；它覆盖的正是界面「复制接入说明」三语×已建/未建观测的文案断言，属本版改动的邻接面。清单自己在 260825 就写过「这张清单自己也会腐化，改 CI 时顺手对一遍」，这次是发版逐条跑时对账对出来的，说明「顺手」这件事没有触发点，靠不住。

## v0.4.36 - 2026-09-12

### 中文

#### 文档

- **观察者提示词把「G 是什么」和「最高目标的两种变法」写成可操作的判据**（issue 260912_G的定义与最高目标的两种变法）。用户反馈「G 是本次对话中的最高目标，是 AI 理解的最高目标，任务是不改变这个目标的情况下的任务；对于最高目标，有的时候是改进，有的时候是转折——提示词没有清晰写出来，其他 AI 总是弄不清」。逐处核对属实，且三处提示词面（`AI_USAGE.md`、`API契约.md`、界面「复制接入说明」的 `ob.guide` 三语）缺的是同样两件事：①**定义不可操作**——都写「最高目标／用户总体上要达到的结果」，是同义反复，没给观察者拿什么去量；②**最高目标的变化只写了转折这一种**，举例全是「旧目标被放下、换成另一件」，而真实会话里更常见的是目标仍指向同一件事但被抬高、收窄或加了新的结果条件（「原来是精炼这份 CHANGELOG，现在是把整个项目转到原型阶段，前面那件成了它的第一步」），这一型方向连续、没有「换了一件事」的外部信号，于是被回落记成 `refine`——260912 反馈包里两次被误记的跳变正是它。还有一个可指认的成因：`turn` 的中文标签就叫「转折」，那是**任务层**的转折，与用户说的「最高目标转折」撞车。改动：给 G 和 T 各一句判据（G＝「它现在做的每件事最终是为了什么」，T＝「这件事做完或放弃，最高目标还是那个吗」），并写明 G 记的是**执行 AI 当时认定的**目标，不是用户原话的抄录、也不是观察者事后归纳的主题；把最高目标的两种变法（改进 / 转折）并列成表，各给形态、例子和**各自会被误记成什么**（改进→`refine`，转折→`turn`）；判断固定成三步（先复核 G 变没变 → 变了记 `goal` 并在 trigger 写清是改进还是转折 → 没变才在 `refine`/`turn` 里二选一）；点破术语撞车，要求写的时候把层说出来；旧 G 的收口一并写全（`superseded` / `unresolved` / `mistaken`）。**不新增 `change` 取值**——改进与转折的结构条件完全相同，差别用 trigger 一句话承载即可，新增取值要动校验、编号、自测与三语标签。界面图例 `G｜目标` 的单边说法（「只有出现新的结果诉求才会有 G2、G3」）同步补成「被抬高、收窄或换了方向都算」。

### English

#### Documentation

- **The observer prompt turns "what G is" and "the two ways the top-level goal changes" into criteria you can act on** (issue 260912_G的定义与最高目标的两种变法). User feedback: "G is the highest goal in this conversation, the highest goal as the AI understands it, and a task is work that does not change that goal. As for the highest goal, sometimes it is an improvement and sometimes a turn — the prompt does not say this clearly, and other AIs keep getting it wrong." Each place checked out, and all three prompt surfaces (`AI_USAGE.md`, `API契约.md`, and the three languages of `ob.guide` behind the interface's "copy setup instructions") were missing the same two things: ① **the definition was not actionable** — every one of them said "highest goal / the result the user is after overall", which is circular and leaves the observer nothing to measure against; ② **only one kind of change to the highest goal was described** — a turn, with every example being "the old goal was dropped and replaced by another", whereas the more common real case is a goal that still points at the same thing but is raised, narrowed, or given a new result condition ("it used to be trimming this CHANGELOG; now it is moving the whole project to the prototype phase, and the earlier piece has become its first step"). That shape is directionally continuous and carries no external signal of "something else was started", so it fell back to `refine` — and exactly that was the jump mis-recorded twice in the 260912 feedback pack. One more identifiable cause: the Chinese label of `turn` is literally "转折", a **task-level** turn, which collides with what the user means by a turn of the highest goal. Changes: G and T each get one criterion (G = "what is everything it is doing now ultimately for", T = "if this were finished or dropped, would the highest goal still be that one?"), together with the statement that G records **the goal the acting AI held at the time**, not a transcript of the user's words nor a theme the observer abstracts afterwards; the two ways the highest goal changes (improvement / turn) are laid out side by side in a table, each with its shape, an example, and **what it tends to be mis-recorded as** (improvement → `refine`, turn → `turn`); the decision is fixed to three steps (first re-check whether G changed → if it did, record `goal` and say in the trigger whether it is an improvement or a turn → only if it did not, choose between `refine` and `turn`); the collision of terms is called out with an instruction to name the level when writing; and closing out the old G is spelled out (`superseded` / `unresolved` / `mistaken`). **No new `change` value** — improvement and turn have identical structural conditions, so one line in the trigger carries the difference, while a new value would mean touching validation, numbering, self-tests and three-language labels. The interface legend's one-sided wording for `G｜目标` ("a G2 or G3 appears only when a new result is asked for") is brought in line with "raised, narrowed, or pointed elsewhere all count".

### 日本語

#### ドキュメント

- **観察者プロンプトで「G とは何か」と「最高目標の二通りの変わり方」を実行可能な判断基準にしました**（issue 260912_G的定义与最高目标的两种变法）。利用者からのフィードバック：「G はこの会話における最高目標であり、AI が理解している最高目標です。タスクとは、その目標を変えない範囲の作業です。最高目標には、改善のときもあれば転換のときもあります——プロンプトにそれが明確に書かれておらず、他の AI はいつも混乱します」。箇所ごとに確認したところ事実で、しかも三つのプロンプト面（`AI_USAGE.md`、`API契約.md`、画面の「接続手順をコピー」にある `ob.guide` の三言語）に同じ二点が欠けていました：①**定義が実行不可能**——いずれも「最高目標／利用者が全体として達成しようとしている結果」と書くだけで同義反復であり、観察者が何をものさしにすればよいかを与えていません。②**最高目標の変化が転換の一種類しか書かれていない**——例はすべて「古い目標が置き去られ、別のものに置き換わる」ものでしたが、実際の会話でより多いのは、目標が同じ事柄を指したまま引き上げられ、絞り込まれ、あるいは新たな結果条件が加わる型です（「もともとはこの CHANGELOG を精錬することだったが、今はプロジェクト全体を試作段階へ移すことで、前のものはその第一歩になった」）。この型は方向が連続していて「別のことを始めた」という外部信号がないため、`refine` に落ちて記録されます——260912 のフィードバックで二度誤記された跳躍がまさにこれでした。もう一つ特定できる原因があります：`turn` の中国語ラベルがそのまま「転換」であり、それは**タスク層**の転換で、利用者の言う「最高目標の転換」と衝突します。変更点：G と T にそれぞれ一句の判断基準を与え（G＝「今行っている一つ一つのことの最終的な目的は何か」、T＝「これをやり終えても、あるいは放棄しても、最高目標は依然としてそれか」）、G が記録するのは**実行 AI がその時点で認定していた**目標であり、利用者の発言の筆記でも観察者が事後にまとめた主題でもないことを明記しました。最高目標の二通りの変わり方（改善／転換）を表に並べ、それぞれ形態・例・**誤記されやすい先**（改善→`refine`、転換→`turn`）を付けました。判断は三歩に固定（まず G が変わったかを再確認 → 変わったら `goal` を記録し trigger に改善か転換かを明記 → 変わっていなければ `refine`/`turn` の二択）。用語の衝突を指摘し、書くときは層を明示するよう求めました。古い G の収束も書き揃えています（`superseded` / `unresolved` / `mistaken`）。**`change` の値は増やしていません**——改善と転換は構造条件が完全に同じで、違いは trigger の一行が担えます。値を増やせば検証・採番・セルフテスト・三言語ラベルに手が入ります。画面の凡例 `G｜目標` の片側の書き方（「新しい結果要求が現れて初めて G2、G3 ができる」）も「引き上げ、絞り込み、方向転換のいずれも該当する」に揃えました。
