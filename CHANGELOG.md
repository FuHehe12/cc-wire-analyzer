# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.35 已发布。实时分析的 A→G 图把 G 与 T 的层级画了出来（G 段有自己的底衬，编号做成徽标），并改成二遍布局——位置按实测高度排，不再出现卡片互相压住；顶部「理解与现状」重排。观察者提示词补上了 `goal` 的判据、正例与「整体目标尚未成型」这一合法状态。捕获页在看历史日期时，今天新到的录制会在日期条上出现待看徽标（不抢焦点、不新增轮询）。工具面雷达、betas 归属、`/api/*` 的 404 指路如 v0.4.34。`public/` 仍冻结，发版不更新它。
- **下一步**：收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## v0.4.35 - 2026-09-12

### 中文

#### 新增

- **看历史日期时，今天来的录制会在日期条上报到**（issue 260912_今日新录制在历史日期下无提示）。此前用户若先切到某个历史日期再开始录制，今天的录制会被 `flushSSE` 整批静默丢掉：`checkDayRollover()` 只在「用户本来就在看今天」时才切（260801 定的原则：不打断主动选了历史日期的人），而日期条上今天那一格压根不会出现——`dates_available` 只在 `fetchCaptures` 时刷新。用户只能自己想起来手动切。现在丢弃前先记一笔：把今天补进日期条、按 id 去重记一个待看计数，那一格显示徽标并高亮，点一下切过去即清零。**不抢焦点的原则保留**，列表与 total 也不被污染（260712 的幽灵「加载更多」是这么来的）。**没有新增任何轮询或请求**：capture 本来就由 SSE 推来，数据已经在手上，成本为零。

#### 修复

- **时序页的 `×N` 计数色块在三套外观下对比度都不达标**（issue 260912_视觉整体走查结果）。主线 1 的泳道色 `#A66B13` 亮度 0.186 卡在正中间——白字 4.44、黑字 4.18，**两种字色都过不了 4.5**，而 `fgOnHex()` 只会按亮度在黑白里二选一，选完仍然不达标。新增 `inkBg()`：保持色相逐档压暗直到白字达标，色块底改用它。泳道身份靠色相认，压暗不影响辨认，也不动泳道色板本身（连线与图例共用那份）；`fgOnHex` 随之无人调用，删除。同一处理用在轮卡的子代理徽章上。这一处是 `contrast_probe.js` 逐视图跑出来的，目视没看出来。

#### 文档

- **观察者提示词补上 `goal` 的判据与正例**（issue 260912_观察者提示词目标漂移判据）。`AI_USAGE.md` 的顶部主指令此前只定义了「修正」（`refine`）与「转折」（`turn`），`goal` 只在下方长契约里留了「整体目标本身变了」一句、没有任何例子；同一段还单边警示「别把又开了一件事记成目标变了」。**起因**：一台跨机现场用 0.4.34 的观察者跑 A→G 时，用户起初没说真实目的、中途要求连续跳变（精炼 CHANGELOG → 改工作区规范 → 删测试材料 → 合并栏目 → 删打包文档 → 重组 issue → 为原型阶段做准备），观察者把这一串压成了一个贯穿全程的总目标，只在末尾记一次 `goal`，被用户退回后连做两次 `rebuild_goal_flow` 才改对（最终三处 `goal`）。改动：三类变化在主指令里并列给定义、触发信号与正例；判据补成双向的一张小表（什么不算 `goal` / 什么确实是 `goal`）；「G」一词只留给整体目标，任务级一律说 T 或「该任务的首个迭代」；要求记 `goal` 时在 trigger 里写一句「为什么是 goal 不是 turn」——两者结构条件完全相同，写不出理由的通常就是 `turn`；新增第 9 条允许「整体目标尚未成型」成为可记录状态（`current.understanding` 首句写明当前整体目标，未明确就直写「用户尚未说明真实目的，目标逐步显现」），不要事后补造连贯；`mode` 补一句判据（随录制增长分批提交＝`incremental`，整场一次性重建＝`retrospective`）。`API契约.md` 的 `change` 表与两平面段同步同一口径。
- **同伴会话的消息收成一条可执行规则**。`origin=user` 但正文以 `Another Claude session sent a message:` 开头、随后是 `<teammate-message teammate_id="…">` 的，是别的 CC 会话发进这条泳道的消息（多 agent 协作时的空闲通知与审查汇报），不是真人，也不是子代理泳道里的 `[派生指令]`，而它照样占一个轮号。实测样本：`9287e1ca` 会话 46 条 `[用户]` 行里 28 条属于这类。此前这条判据散在多处，观察者按 `[用户]` 读会把子代理汇报当成用户的新要求，凭空造出目标变化。

#### 变更

- **A→G 图把 G 和 T 的层级画出来**（issue 260912_AG图G与T视觉层级）。用户反馈「界面挺好看，但 G 和 T 一眼看上去不能区分」。此前 G 段头是一条顶线加 11px 小标签，T 段头是一条左线加 11px 小标签，两者只差边框方向和 10px 缩进，而下属的 T 卡片是全场最重的元素——层级是反的。现在每个 G 段有自己的底衬（主色淡雾 + 描边 + 顶线），把属于它的 T 全圈进去，「谁属于谁」直接可见；G 的编号做成实心徽标，标题提到 15px；T 的编号改成描边 chip、标题回到常规字重。颜色全部由 `--ag-key` / `--brand-ink` 经 `color-mix` 派生，不新增主题 token。底衬**不能**用负 z-index：`.ag-canvas` 自己有背景且不构成层叠上下文，负层级会退到更外层被画布背景整个盖住（实测完全不可见），改为插在连线 `svg` 之前靠 DOM 顺序压底；段高取决于本段 T 排完后的位置，先渲染再回填。
- **A→G 图改成二遍布局，卡片不再互相压住**（同一 issue）。此前每个块的位置按固定节拍常量算，而真实高度由内容决定：G 段头实测 67px 而节拍只留 64，于是**每一段都压住下面的 T 段头 2px**；T 段头只有 25px 却按 46px 留位，间距排下来是 12 / -2 / 21 / 30 / 48 的乱序。调大常量治不了根——段头一换行就又会压上去（260909 反馈「被挡住一部分」是同一病根的上一次发作）。现在生成时的 top 只作首屏近似位，渲染后 `layoutGoalFlow()` 按实测高度重排一次，再画连线；间距统一成 A→G 段 30、段与段 36、G 段头→T 段头 12、T 段头→卡片 10、卡片之间 20。卡片高度由钉死的 112px 改成 `min-height`、正文 clamp 2 行放到 3 行——钉死高度会把长一点的目标截半句，而位置又按同一个常量算，两件事本就连在一起。实测（1600px / 1180px 两档，含展开折叠任务与打开就地详情）：重叠 0 处，卡片全部落在各自 G 段内。
- **顶部「当前的理解与现状」重排**（同一 issue）。用户反馈展开后「字体怪、集中在一侧、小标题比正文还小、正文叠成一坨、①② 混在一起」。一句话汇报此前卡着 `max-width:46em`，宽屏上只占左半边；小标题 13px 比它领起的 14px 正文还小；观察者又常把要点写成一整段、序号埋在句中。现在汇报放开宽度上限、提到 18px 并加左色条，小标题提到 15px 加色点，两栏各自坐进一张卡片，正文行距放宽到 2.0；渲染时在 ①–⑳ 前补换行并按行拆段、序号行加悬挂缩进——只动显示，存储的 `current.understanding` 正文不变。
- **「录制分析agent行为」补上中英文之间的空格**（中文与日文各一处），与项目其它文案一致。
- **两处浏览器探针断言修正**。`observe_goal_browser.cjs` 里「页面正文逐字包含 `current.understanding`」改为去掉空白后比对：分条渲染加的只是空白，不改一个字，这样反而更贴合它要守的「页面不篡改观察者写的内容」。另一处 `[data-om-action="goal-anchor"]` 在 strict 模式下命中两个元素——首个 G 段没有显式目标变化可指时，段头自 260909 起就与 A 卡片共用这个 action，与本次改动无关，只是这个手动探针本机从没跑起来过（缺 playwright）所以一直没暴露；改为 `.ag-anchor [data-om-action="goal-anchor"]`。

### English

#### Added

- **Recordings that arrive today now announce themselves while you are looking at an older date** (issue 260912). If the user switched to a past date before starting a recording, today's captures were dropped wholesale by `flushSSE`: `checkDayRollover()` only switches when the user was already on today (the 260801 rule: never take away a date the user chose deliberately), and today's chip would not even appear, because `dates_available` is refreshed only by `fetchCaptures`. The only way out was to remember to switch by hand. Now the batch is counted before it is dropped: today joins the date bar, a pending count is kept (deduplicated by id), that chip shows a badge and highlights, and one click switches over and clears it. **The no-stealing-focus rule stays**, and neither the list nor `total` is polluted — that is where the 260712 phantom "load more" came from. **No polling and no request was added**: captures already arrive over SSE, so the data was in hand and the cost is zero.

#### Fixed

- **The `×N` count swatch on the timeline failed contrast in all three appearances** (issue 260912). Lane colour `#A66B13` has luminance 0.186, right in the middle: white text scores 4.44 and black 4.18, so **neither text colour clears 4.5**, while `fgOnHex()` only ever picks one of the two and the result stays below the bar. The new `inkBg()` keeps the hue and darkens step by step until white text passes, and the swatch uses it. Lanes are recognised by hue, so darkening costs nothing, and the lane palette itself — shared with the wires and the legend — is untouched; `fgOnHex` lost its last caller and was removed. The same treatment applies to the sub-agent badge on turn cards. This one surfaced only by running `contrast_probe.js` per view; looking at the page was not enough.

#### Documentation

- **The observer prompt gains criteria and a worked example for `goal`** (issue 260912). The top-level instruction in `AI_USAGE.md` defined only refinement (`refine`) and turn (`turn`); `goal` had a single sentence — "the overall goal itself changed" — buried in the contract below with no example at all, and the same passage warned in one direction only ("do not record starting another piece of work as a changed goal"). **Why**: on another machine, an observer running A→G on 0.4.34 met a user who had not stated the real purpose and whose requests jumped repeatedly — trim the CHANGELOG → change the workspace rules → delete test material → merge sections → delete packaging docs → reorganise issues → prepare for the prototype phase. The observer compressed all of it into one overall goal and recorded `goal` only at the end; after the user pushed back it took two `rebuild_goal_flow` passes to get it right, ending at three `goal` entries. Changes: all three kinds of change now sit side by side in the top instruction with definitions, trigger signals and a worked example; the criteria became a two-way table (what is not a `goal` / what really is one); the letter "G" is reserved for the overall goal, with the task level always called T; recording a `goal` now requires one line in the trigger saying why it is a goal and not a turn — the two have identical structural conditions, and being unable to write that line usually means it is a turn; a new ninth rule makes "the overall goal has not formed yet" a recordable state instead of forcing a guess between two failing criteria; and `mode` gains a one-line test. `API契约.md` follows the same wording.
- **Messages from a teammate session became one executable rule.** A line with `origin=user` whose body starts with `Another Claude session sent a message:` followed by `<teammate-message teammate_id="…">` comes from another CC session on the same lane — idle notices and review reports during multi-agent work. It is not the human, nor the `[派生指令]` of a sub-agent lane, and it still occupies a turn number. Measured sample: 28 of the 46 `[用户]` lines in session `9287e1ca`. The criterion used to be scattered, so an observer reading `[用户]` at face value would take a sub-agent's report for a new user request and invent a goal change.

#### Changed

- **The A→G diagram now draws the difference between G and T** (issue 260912). User feedback: "the interface looks good, but G and T cannot be told apart at a glance." A G heading was a top rule plus an 11px label; a T heading was a left rule plus an 11px label — they differed by which side the border sat on and 10px of indent, while the T cards below them were the heaviest elements on screen. The hierarchy was upside down. Each G section now sits in its own band (tinted wash, hairline, top rule) enclosing its T sections, so membership is visible instead of read; the G number became a solid badge and its title moved up to 15px, while the T number became an outlined chip with a regular-weight title. Every colour derives from `--ag-key` / `--brand-ink` through `color-mix`, so no theme token was added. The band **cannot** use a negative z-index: `.ag-canvas` has its own background and is not a stacking context, so a negative layer falls outside it and the canvas background covers it completely (verified: invisible). It is inserted before the wire `svg` instead and sits underneath by DOM order; its height depends on where the section ends, so it is filled in after rendering.
- **The A→G diagram switched to a two-pass layout; cards no longer overlap.** Positions came from fixed cadence constants while real heights depend on content: a G heading measures 67px against the 64px the cadence reserved, so **every section overlapped the T heading below it by 2px**, and a T heading of 25px was given 46px — leaving gaps of 12 / -2 / 21 / 30 / 48. Raising the constants does not fix it; one wrapped heading and the overlap is back (the 260909 report "partly covered" was the same root cause). The generated `top` is now only a first-paint approximation: after rendering, `layoutGoalFlow()` re-places everything by measured height and the wires are drawn against the new positions. Card height moved from a hard 112px to `min-height` and the clamp from 2 lines to 3 — a fixed height cut long goals in half, and position derived from that same constant, so the two belong together. Measured at 1600px and 1180px, including expanded tasks and an open inline detail: zero overlaps.
- **The "current understanding and situation" block was re-set.** User feedback on the expanded block: the type looks odd and bunches to one side, the small headings are smaller than the body text they introduce, the body is one solid mass, and ① ② run together. The spoken headline was capped at `max-width:46em` and took up half of a wide screen; the headings were 13px against 14px body text; and observers tend to write the points as one paragraph with the numbers buried mid-sentence. The headline now has no width cap, is 18px with a colour rule at its left, the headings are 15px with a dot, each column sits in its own card, and body leading opened to 2.0. At render time a newline goes in before ①–⑳, the text is split into paragraphs and numbered lines get a hanging indent — display only; the stored `current.understanding` is unchanged.
- **Two browser-probe assertions were corrected.** In `observe_goal_browser.cjs`, "the page contains `current.understanding` verbatim" now compares with whitespace removed: the itemised rendering adds only whitespace and changes no character, which expresses what the assertion guards — the page does not alter what the observer wrote — more precisely. The other, `[data-om-action="goal-anchor"]`, matched two elements under strict mode: when the first G section has no explicit goal change to point at, its heading has shared that action with the A card since 260909. Unrelated to this release; it simply never surfaced because this manual probe had never run here (no playwright installed). It now targets `.ag-anchor [data-om-action="goal-anchor"]`.

### 日本語

#### 追加

- **過去の日付を見ている間に届いた本日の記録が、日付バーに現れます**（issue 260912）。記録開始前に過去の日付へ切り替えていると、本日のキャプチャは `flushSSE` でまとめて捨てられていました：`checkDayRollover()` は「もともと本日を見ていた場合」しか切り替えず（260801 の原則＝利用者が自分で選んだ日付を奪わない）、`dates_available` は `fetchCaptures` のときしか更新されないため、本日のチップ自体が現れません。結果、手で切り替えるしかありませんでした。今は捨てる前に記録します：本日を日付バーに加え、id で重複を除いた未読件数を保ち、そのチップにバッジと強調を出します。クリックすれば切り替わり、件数は 0 に戻ります。**焦点を奪わない原則はそのまま**で、一覧も `total` も汚しません（260712 の幽霊「もっと読み込む」の原因がこれでした）。**ポーリングもリクエストも増やしていません**：キャプチャはもともと SSE で届いており、データは手元にあるので費用はゼロです。

#### 修正

- **時系列ページの `×N` バッジが三つの外観すべてでコントラスト不足でした**（issue 260912）。レーン色 `#A66B13` の輝度は 0.186 とちょうど中間で、白文字 4.44・黒文字 4.18 と**どちらの文字色も 4.5 を超えられません**。`fgOnHex()` は二者択一しかせず、選んでも不足のままでした。新設の `inkBg()` は色相を保ったまま段階的に暗くし、白文字が基準を満たしたところで止めます。レーンは色相で識別するため暗くしても支障はなく、レーン配色そのもの（線と凡例が共有）は触りません。`fgOnHex` は呼び出し元を失ったので削除しました。同じ処理をターンカードのサブエージェント章にも適用しています。この一件は `contrast_probe.js` をビューごとに走らせて初めて見つかりました。

#### ドキュメント

- **観察者プロンプトに `goal` の判断基準と実例を追加**（issue 260912）。`AI_USAGE.md` の冒頭指示は「修正」（`refine`）と「転換」（`turn`）しか定義しておらず、`goal` は下の契約に「全体目標そのものが変わった」の一文があるだけで例が皆無、しかも同じ箇所の注意書きは片側だけ（「別の作業を始めたことを目標変更と記録するな」）でした。**きっかけ**：別のマシンで 0.4.34 の観察者が A→G を記録した際、利用者は当初本当の目的を述べず、要求が何度も不連続に飛びました。観察者はそれを一つの全体目標に圧縮し、最後に一度だけ `goal` を記録。指摘を受けて `rebuild_goal_flow` を二度行い、ようやく三箇所の `goal` になりました。変更点：三種類の変化を冒頭指示に並べて定義・兆候・実例を示す／基準を双方向の表にする／「G」は全体目標だけに使いタスク階層は T と呼ぶ／`goal` を記録する際は trigger に「なぜ turn ではなく goal なのか」を一行書く（両者は構造条件が同一で、書けないなら大抵 turn です）／第 9 条を新設し「全体目標がまだ形になっていない」を記録可能な状態にする／`mode` の判断基準を一行追加。`API契約.md` も同じ言い回しに揃えました。
- **同僚セッションからのメッセージを一つの実行可能な規則に集約。** `origin=user` でありながら本文が `Another Claude session sent a message:` で始まり `<teammate-message teammate_id="…">` が続く行は、同じレーンに届いた別の CC セッションのメッセージ（マルチエージェント作業中の待機通知やレビュー報告）です。人間でもサブエージェントレーンの `[派生指令]` でもなく、それでもターン番号を一つ占めます。実測：セッション `9287e1ca` の `[用户]` 46 行のうち 28 行。判断材料が各所に散っていたため、`[用户]` をそのまま読むとサブエージェントの報告を利用者の新しい要求と取り違え、ありもしない目標変化を作ってしまいます。

#### 変更

- **A→G 図で G と T の階層が見えるようになりました**（issue 260912）。利用者の指摘：「画面はきれいだが、G と T が一目で区別できない」。従来 G の見出しは上罫線＋11px の小ラベル、T の見出しは左罫線＋11px の小ラベルで、違いは罫線の向きと 10px の字下げだけ。一方その下の T カードは画面で最も重い要素でした。階層が逆だったのです。今は各 G 区画が自分の帯（淡い色地＋細枠＋上罫）を持ち、属する T をすべて囲みます。G の番号は塗りのバッジ、見出しは 15px に。T の番号は輪郭チップ、見出しは通常の字面に戻しました。色はすべて `--ag-key` / `--brand-ink` から `color-mix` で導出し、テーマトークンは増やしていません。帯に負の z-index は**使えません**：`.ag-canvas` は自前の背景を持ちながら重ね合わせコンテキストを作らないため、負の層は外側に落ちてキャンバス背景に完全に隠れます（実測で不可視）。線の `svg` の前に挿入し、DOM 順で下に敷いています。高さは区画を並べ終えて初めて決まるので、描画後に埋めます。
- **A→G 図を二段階レイアウトに変更、カードが重ならなくなりました。** 位置は固定の拍で計算していたのに、実際の高さは内容で決まります：G 見出しの実測は 67px、拍が確保していたのは 64px——**どの区画も下の T 見出しを 2px 押していました**。T 見出しは 25px しかないのに 46px 分の場所を取り、間隔は 12 / -2 / 21 / 30 / 48 とばらばらでした。定数を大きくしても根治しません（見出しが一行増えればまた重なります。260909 の「一部が隠れる」も同じ病根です）。生成時の `top` は初回描画の近似値に格下げし、描画後に `layoutGoalFlow()` が実測高さで並べ直してから線を引きます。カードの高さは固定 112px から `min-height` へ、本文のクランプは 2 行から 3 行へ——固定高さは長い目標を途中で切り、位置もその同じ定数から来ていたので、二つは元々ひと続きの問題でした。1600px と 1180px、折りたたみ展開と詳細表示を含めて実測：重なり 0 件。
- **上部「現在の理解と状況」を組み直しました。** 展開後について「字が妙で片側に寄る、小見出しが本文より小さい、本文が一塊、①② が混ざる」との指摘。要約一行は `max-width:46em` で止まり広い画面では左半分しか使わず、小見出しは 13px で本文 14px より小さく、観察者は要点を一段落に書いて番号を文中に埋めがちでした。今は要約の幅上限を外して 18px にし左に色罫を添え、小見出しは 15px にドットを付け、二欄はそれぞれカードに収め、本文の行送りを 2.0 に広げました。描画時に ①–⑳ の前で改行して段落に分け、番号行はぶら下げ字下げにします——表示だけの処理で、保存された `current.understanding` は変わりません。
- **ブラウザ探針のアサーションを二箇所修正。** `observe_goal_browser.cjs` の「ページが `current.understanding` を一字一句含む」は空白を除いた比較に変更：箇条書き化で加わるのは空白だけで一文字も変えないため、本来守りたい「ページは観察者の書いたものを改変しない」をより正確に表せます。もう一つの `[data-om-action="goal-anchor"]` は strict モードで 2 要素に一致していました——最初の G 区画に指すべき明示的な目標変化がない場合、その見出しは 260909 以降 A カードと同じ action を共有しています。今回の変更とは無関係で、この手動探針がこの環境で一度も動いていなかった（playwright 未導入）ために露見しなかっただけです。`.ag-anchor [data-om-action="goal-anchor"]` に変更しました。

