# 变更历史

这里记录 v0.4.35 及更早版本的变化，当前版本见 [CHANGELOG.md](CHANGELOG.md)。条目保留当时的问题、改动与必要边界；详细调查过程与验证记录可用 `git show 68881ba:CHANGELOG-history.md` 查看，或阅读[整理前原文](issues/evidence/260906_变更记录简写/CHANGELOG-history-before.md)。历史路径与行为不代表当前状态。

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

## v0.4.34 - 2026-09-11

### 中文

#### 新增

- **工具面进索引与盲区雷达**（issue 260911_工具面雷达与beta归属）。索引新增 `tools_builtin`（内置工具名列表）/ `tools_fp`（内置+MCP 的联合指纹）/ `tools_mcp_n`（MCP 工具数），`/api/unknowns` 随之多出两档：`tools` 报不在 `classifier.KNOWN_TOOLS` 基线里的内置工具（snippet 直接给该工具的 description 片段，一眼看出它是干什么的），`tool_changes` 报同一条泳道内工具集前后不一致（value 是差集，如 `+TaskCreate,TaskGet,TaskList… -EndConversation,RemoteTrigger,SendUserFile`）。**起因**：09-11 查「CC 是不是有新功能」时，`Artifact` / `DesignSync` / `Monitor` / `PowerShell` / `PushNotification` / `SendFeedback` / `Workflow` 七个内置工具只出现在第三方链路的会话上，而索引里关于工具只有 `tools_n` 一个数字——这件事只能靠人打开 40 MB 主文件逐条扫才看得见，雷达一个字都报不出来。工具面是 CC 的能力清单，地位等同于 `anthropic-beta`。`mcp__` 前缀的工具不进基线、不参与未知判定，只记数量：那是使用者自己装的 MCP，报它会把真信号淹掉（与 degraded 从 block_keys 分流出去同一个道理）。**分组键是会话 + kind + agent_id 而不是会话**：首版按会话分组，当天 26 条「工具集变化」没有一条是真的——子代理复用父会话 id、并行子代理之间工具面各不相同、CC 自己发起的检索派发恒 `tools_n=1`，三者合起来就是 main↔subagent 来回翻牌。收口后 09-06 只剩 1 条真变化。详情页的 Tools 折叠同步高亮基线外的内置工具，并在标题显示 MCP 数量。
- **betas 段带归属**。`/api/unknowns` 的 `betas.new` / `betas.known` 现在带 `hosts` / `cc_versions`，`new` 段另带 `samples`。端点的判读第一步写的就是「先看 hosts」，而 betas 恰恰是唯一没有归属的那一段——09-11 的新 beta 正好单一 host 独占，判读要用的信息不在响应里，只能人工拉 `/api/captures?limit=300` 自己按 `beta` 聚合才确认得了。`known` 段不给 samples（上千条给 id 无意义），`new` 段必须给——那才是要接着查上下文的一段。
- **`/api/*` 的 404 会指路**。未命中的 `/api/*` 响应从 `{error, path}` 扩成带 `did_you_mean`（最接近的已注册端点，≤3 个，从 Flask url_map 现算，不维护第二份清单）与 `hint`（指向 `GET /api/ai-guide`）。起因：AI 消费者按别处的惯例第一反应调 `/api/status`（本工具叫 `/api/proxy/status`），旧 404 不给任何线索，只能继续猜。相似度比的是去掉 `api/` 之后的部分——所有候选都以它开头，带着比会让 `/api/logs` 这种根本不存在的东西也配出三个「最接近」；宁可返回空列表也不给错的指引。
- **`/api/grep` 的 coverage 说明未检索区**。新增 `not_searched`：HTTP 头（含 `anthropic-beta`）不在检索区，查 beta / 工具面走 `/api/unknowns`。起因：拿 beta 特性名去 grep，命中的全是别的对话正文里提到它的地方，一条真正带该 beta 的请求都搜不出来，而 `coverage` 只列了「搜过哪些正文区域」，看不出这件事。

#### 变更

- **`KNOWN_BETAS` 并入 `mid-conversation-tool-changes-2026-07-01`**。09-11 首次出现（CC 2.1.268，当天 47 条全在同一条第三方链路上），逐日回查 08-31～09-10 全无，`claude.exe` 二进制里能取到该字符串——是 CC 客户端声明的新能力，不是网关的形状差异。它的语义正是「工具集可在对话中途变化」，与本版新增的 `tool_changes` 档是同一件事的两面。
- **`IDX_SCHEMA` 18 → 19**。新增的三个工具面字段在旧索引里恒缺失，会让 `tools` 档恒空、`tool_changes` 恒无变化而不报任何错（静默降级）。升级后首次读取会重建当天索引。
- **`tests/dev_seed.py`**：工具名从 `Task` / `TodoWrite`（真流量里早已不存在）换成基线内的真实名字，否则 seed 出来的每一条都被新雷达报成「没见过的内置工具」，样例数据自己制造的噪声会盖住真信号；新增 E5 样例演示工具集中途变化（未知内置工具 + MCP 各一个）；docstring 补上「跑完立刻删」的警告——09-10 有 54 条合成记录因为跑完没删留在真实录制里，回头查协议演进时差点被当成真信号。

## v0.4.33 - 2026-09-10

### 中文

#### 变更

- **取消八视图**（issue 260910_取消八视图）。用户真机用过之后的结论是「静态的分析没有用」：八视图是事后静态切分（阶段/快照/血统/反事实），而看一段录制的真实需求由轮次骨架总结与目标流满足。删除范围：`src/trajectory.py` 整个模块（3305 行）；`GET|POST /api/snapshots/<id>/trajectory` 与 `GET /api/snapshots/<id>/semantic` 两个端点及其语义层管线；分析页的「八视图」档与切换器（轮次骨架只剩列表一档）、八视图归纳按钮、「复制指令·流程图」按钮（其数据源与文案整体建立在八视图字段上）；agent-brief 里的 trajectory 入口与字段清单；便携包不再搬运 `.semantic.json`（磁盘上已有的语义层文件不删——那是花过钱的归纳，只是不再有读取方，老包导入时忽略该成员不报错）。**轮次骨架总结（`/api/snapshots/<id>/analysis` 的步级简报+轮次归纳+线级总结）一字不动**。随取消消解两件 open issue（260829 只认 captures、260829 三语——押后理由里「翻完再裁是白翻」按最极端的方式兑现）。HTML 说明书在原八视图位置备注「已于 260910 取消」，不无声消失；产品数据（capabilities 的 I 组 11 项、product-v3 的挂载与张力标记、implementation 的代码证据）同步移除。验证：全自测 + doc_audit（端点对账）+ workspace_audit + i18n 三语 696 键同步 + 浏览器实测（分析页只剩列表档、`/trajectory` 与 `/semantic` 回 404、brief 端点不再列 trajectory、console 无报错）。

### English

#### Changed

- **The 8-views trajectory analysis is removed** (issue 260910). The verdict after real use: static after-the-fact slicing was not what reading a recording needed — the turn-skeleton summary and the goal flow already answer that. Removed: the whole `src/trajectory.py` module (3,305 lines); the `GET|POST /api/snapshots/<id>/trajectory` and `GET /api/snapshots/<id>/semantic` endpoints with their semantic pipeline; the 8-views slot in the analysis page (the turn skeleton stays as the single list view), its summarise button, and the "copy flowchart brief" button (its prompt was built entirely on the 8-views fields); the trajectory entry and field list in the agent brief; `.semantic.json` is no longer carried in portable packs (files already on disk are kept — that summarisation cost money — they just have no reader any more, and old packs import cleanly by ignoring the member). **The turn-skeleton summary (`/api/snapshots/<id>/analysis`: per-step briefs + per-turn rollup + per-lane summary) is untouched.** Two open issues dissolved with the removal (260829 captures-only, 260829 i18n — "translate then cut" landed in its most extreme form). The HTML manual notes the removal in place rather than vanishing silently; product data (capabilities group I, product-tree mounts and tension marks, implementation code evidence) is updated in step. Verified: all selftests + doc_audit (endpoint reconciliation) + workspace_audit + i18n (696 keys, three languages) + browser check (analysis page shows the single list view, both endpoints 404, brief no longer lists trajectory, no console errors).

### 日本語

#### 変更

- **8ビューの軌跡分析を廃止しました**（issue 260910）。実使用後の結論：静的な事後分割は録画を読む要件ではなかった——その役割はターン骨格サマリーとゴールフローが既に担っています。削除対象：`src/trajectory.py` モジュ全体（3,305 行）、`GET|POST /api/snapshots/<id>/trajectory` と `GET /api/snapshots/<id>/semantic` の両エンドポイントとその意味層パイプライン、分析ページの8ビュー枠（ターン骨格はリスト一覧のみに）、その要約ボタン、「フロー図指示をコピー」ボタン（文言全体が8ビューの項目の上に立っていました）、agent ブリーフ内の trajectory 入口と項目一覧。ポータブルパックは `.semantic.json` を運ばなくなりました（ディスク上の既存ファイルは削除しません——お金をかけて作った要約です。読み手がいなくなっただけで、旧パックの取り込みは当該メンバーを無視して正常に完了します）。**ターン骨格サマリー（`/api/snapshots/<id>/analysis`：ステップ別ブリーフ＋ターン別まとめ＋レーン別まとめ）は一切変更していません。** 廃止に伴い open issue 2件を解消（260829 の2件——「翻訳してから切り捨てると無駄になる」が最も極端な形で現実になりました）。HTML マニュアルには元の場所に廃止注記を残し、無言で消えないようにしています。製品データ（capabilities の I グループ、product ツリーのマウントとテンション、implementation のコード証拠）も同期更新。検証：全セルフテスト＋doc_audit（エンドポイント突合）＋workspace_audit＋i18n（三言語 696 キー）＋ブラウザ実測（分析ページはリスト一覧のみ、両エンドポイントは 404、ブリーフに trajectory なし、コンソールエラーなし）。

## v0.4.32 - 2026-09-09

### 中文

实时分析分成两层看：整体目标在外、任务在内；误做过的目标不再被复盘吸收；顶部两段能收起来，并且先给一句口头汇报。

#### 新增

- 观察 AI 可以**按对话轮**读录制：`/api/actions?turns=N` 一次取 N 轮，一轮是一次用户消息加它引发的全部步，取满就停，不在轮中间截断。响应新增 `turns` 清单（不给 `turns` 参数时也有），每轮说明取全没有、是不是残轮、起源是真人还是合成；**该轮还没被下一轮终结时标 `complete:false`**——录制可能仍在进行，读的人据此知道手里是半轮，拉齐后再补建，不拿半轮下结论。实测本机 54 步泳道：逐轮跟随 5 次读完，首次拉取从步分页的 144 万字符降到 34.7 万。
- 用户对选项提问的答复不再消失。`AskUserQuestion` 与 `ExitPlanMode` 的返回是用户的原话拍板，对话视图此前把它和普通工具输出一起剥掉了；现在标 `[答复]` 留在原位，提问那一行也从「用了 AskUserQuestion」改成给出问题与选项。续读时同样认得出来——问在这一步、答在下一步是链路上的真实次序。
- 账本行区分消息来源：`[用户]` 是真人，`[用户·命令]` 是斜杠命令注入，`[系统合成]` 是 CC 内部合成的伪轮，`[派生指令]` 是子代理泳道里上级 AI 的话。此前一律显示为 `[用户]`，观察者要逐条甄别哪句是真人说的——实测某天的对话里有 9 条内部检索伪轮被当成真人要求。

- 导出页改成**两层结构：G 是整体目标，T 是它的内环**。此前每条目标迭代都被编号成 G0、G1、G2……，一场只有一个整体目标的会话看上去像是换了十几次目标；现在整体目标一段一段列在外层（G1、G2……），任务区在段内，卡片按「T3·2」这样的任务内序号编号——换一件交付（`turn`）不再产生新的 G。任务区按任务分区并可折叠：真实观测（7 任务 11 次迭代）首屏从 11 张卡压到 7 张，不在跟进中的任务折成一行，点区头展开。页面顶部常驻 A/G/T 的一句话释义，读者不必事先知道模型。
- 契约新增 `change:"goal"`：整体目标本身变了（用户提出新的结果诉求）。结构条件与 `turn` 完全相同——它同样开一个新任务——区别只在语义：`turn` 是同一个整体目标下换一件交付，`goal` 是整体目标换了。旧数据一条不动，没有这个标记的观测仍显示为一个整体目标。
- 目标流可以给**误目标留痕**：status 事件新增 `mistaken`，表示某个 G 曾被相信、后来判定方向本身就错了——和 `superseded`（被后来的目标接替）不是一回事。事后判定仍只走事件，迭代自身的 status 不接受它，不往当时的记录里塞后见之明。页面把这样的 G 标红划掉留在序列里，任务折叠时区头也标出「· 误目标」，不会被折没。这条来自 260909 实测：一次性复盘把「误做 compare 档案检查页 → 用户打断纠正」压成了一句 trigger，那个错目标在 G 序列里从未存在过。
- 顶部「它对你要求的理解」「它对现状的判断」可以折起来了。真实观测上这两段占 549px，图要滚半屏才看得到；现在默认展开、点标题收起，收起后留一行摘要而不是只剩个标题，收起过就记住。实测收起后这块从 549px 降到 87px，图的起点从 y=843 提到 382。
- `current` 新增可选 `headline`：一句口头汇报，**硬上限 120 字符**。260909 实测的问题是这两段写得像工作简报——「当天依次推进七件事：①……②……」，读的人要读完七条才知道现在什么状况。程序管不住措辞，但管得住长度：一句话装不下清单，写的人只能挑最重要的说。页面把它放在最上面，也是折起后留在页面上的那一行；旧观测没有就没有，页面不会替它从长文里截一句。
- 目标流可以声明**建模模式** `mode`：`incremental`（现场逐轮跟随）或 `retrospective`（事后一次性复盘）。它描述这份记录怎么建的，不描述被观察的会话，因此可以随时改，也能在 delta 里替换。页面按模式给一句提示，复盘模式明说「中途被推翻的目标可能没有留痕」。

#### 修复

- 目标图不再出现卡片互相压住和连线交叉。分层后新增一趟按父节点位置的重心排序，消掉了「上一行 A、B，下一行却是 B 的孩子在左、A 的孩子在右」这种 X 形走线；卡片高度与行距改为固定节拍，算出来的位置和画出来的框对得上。真实观测在 1440／1280／390 三个宽度实测：25 个定位元素，卡片重叠 0、溢出画布 0、页面无横向滚动条；打开就地详情时详情列与卡片列不相交。

- 各视图顶栏此前是三种长相：捕获是 16/22 的大卡片，实时分析与分析是 10/14 的窄条，时序干脆没有容器；同一层信息在三处的字号也不同（11／11.5／12／13／14.5px）。统一成同一种 13/18 卡片与两档字号，日期行补上与顶栏同族的浅底容器，A→G 的 A/G/T 释义改成图例面板而不是正文里的小字。

#### 变更

- `/api/*` 的 JSON 响应显式声明 `charset=utf-8`。需要说明的是**这不是 Windows 读到乱码的解药**：响应体本来就是纯 ASCII 的转义 JSON，按哪种码页解都一样，乱码出在客户端把解析后的中文打到本地码页的控制台。真正的解法写进了接入说明与 API 契约（PowerShell 设 `[Console]::OutputEncoding`，Python 用 `-X utf8`）。

#### 文档

- 契约与接入说明写清 G 与 T 是两个平面（换一件交付用 `turn`、整体目标变了才用 `goal`）、误目标与 `superseded` 的区别、`mode` 的用法，以及**给旧观测后挂目标流的路径**——直接对原来的 goal 条目 `update_item` 挂 `goal_flow`，历史不迁移不补标，不要另建条目形成双轨。`current` 两段的写作口径也写进契约：概览不是工作日志，一件事一句话、最多一个数字，判断性信息必须保留，过程与逐项数字沉进 G 与事件。
- API 契约补 `turns` 入参与出参字段、问答例外与来源前缀的判据；`AI_USAGE` 的外环观察流程改为按轮读、逐轮建模（先更新当前理解，目标实质变化才动 G）；三语接入说明同步。

## v0.4.31 - 2026-09-09

### 中文

捕获与实时分析互相跳得通，证据能回到原文；观察 AI 可以整体重建一份 A→G。

#### 新增

- 捕获详情新增「实时分析」：直接打开覆盖这条请求的观测；还没有观测时带着这段对话的范围过去，「复制接入说明」产出的正是这段范围的新建指令，不必另外查观测 ID。
- 证据里的请求编号新增「在捕获中打开」，回到该请求在捕获里的完整正文；观测范围不是当前日期时先切换日期，返回仍回到实时分析。
- 观察 AI 可用 `rebuild_goal_flow` 整体重建已有的 A→G。重建必须写明理由，上一版保留在条目历史里，页面显示「已重建」并可查看每次理由。

#### 修复

- 滚轮停在目标流画布上时页面无法滚动。
- 详情里的列表与引用比正文大一号；强调改用色条与字重，不再靠字号跳变。
- 观测下拉按「日期 · 泳道 · 名称」排列；外环没写标题时用当前理解或最初原话回落成一句摘要，不再是一整列「未命名观测」。

#### 变更

- 阅读区、说明块与目标流三列按可用宽度展开，中文行宽不再按字母宽度截断；就地详情高度随视口计算，展开 A 不再在下方留出整屏空白。
- 窄屏顶栏改为两行，标题与副标题不再被页签挤成竖排。

#### 文档

- 三语接入说明与界面指引补充重建与跳转用法；API 契约补 `rid` 范围解析、列表 `preview` 与 `rebuild_goal_flow` 的字段与错误。

---


## v0.4.30 - 2026-09-09

### 中文

实时分析聚焦 AI 怎样理解要求、怎样判断现状，以及目标如何修正或转向另一件事。

#### 新增

- 顶部新增“它对你要求的理解”和“它对现状的判断”，先看清双方是否理解一致，再按需查看原话与证据。
- A→G 目标流保留最初理解，区分同任务的“修正”和另一独立任务的“转折”。此前任务可折叠，未完事项与持续要求不会因切换任务而消失。
- 目标状态、核验和观察者的解释订正分别留痕。状态变化不再制造新目标，AI 自称完成不等于通过验收。

#### 变更

- 主画面收起“工作与发现”“原始步骤”“预测核对”，集中呈现 A→G。旧记录与接口保留；尚无目标流的观测可通过“复制接入说明”交给观察 AI 补充。
- 目标详情在同行展开，原话证据就地查看；三套外观保持一致，窄屏可定位目标和详情，刷新保留选择、展开与阅读位置。
- 观察 AI 可增量更新当前理解与目标变化，无需反复提交全部历史；支持跨批次引用条目、删除关系和简短写入回执。

#### 修复

- 观测写入遇到错字段、错层级或内容超限会明确报错，不再出现成功回执却未生效或内容被截断的情况。
- 账本续读到末尾后不再重复读取历史；可过滤辅助调用。修复复制接入说明后提示显示未翻译键名的问题。

#### 文档

- 更新三语接入说明与界面阅读指引，说明如何区分目标和现状、修正和转折，以及继续维护已有观测。刷新页面不会自动启动观察 AI。

---

### English

Live analysis now focuses on how the AI understands the request, sees the situation, and revises its goal or switches tasks.

#### Added and changed

- Two summaries show the AI's current understanding and view of the situation. A→G preserves the starting point and distinguishes revisions within a task from switches to another task, retaining unfinished work.
- Status, verification and observer corrections keep separate histories. The main view focuses on A→G; legacy records and APIs remain available, and Copy setup notes explains how to add a goal flow.
- Evidence opens beside the selected goal. Three themes, narrow-screen navigation and refresh preserve a consistent reading experience. Observers can submit incremental updates, reuse references across batches and request compact replies.

#### Fixed and documented

- Invalid or oversized observation writes now fail explicitly. Empty incremental reads no longer reread history; auxiliary calls can be filtered. Fixed untranslated copy-success feedback.
- Updated setup notes and the interface guide. Refreshing the page does not start the observing AI, and an AI completion claim is not acceptance.

---

### 日本語

リアルタイム分析を、AI が要求をどう理解し、現状をどう判断し、目標を修正・別タスクへ転換したかに集中させました。

#### 追加・変更

- 現在の要求理解と現状判断を上部に表示。A→G は最初の理解を保持し、同タスクの修正と別タスクへの転換を区別して、旧タスクの残件も残します。
- 状態・検証・観測者による解釈訂正を別々に記録。主画面は A→G に絞り、旧記録と API は保持します。目標流の追加方法は接続説明をコピーして確認できます。
- 選択した目標の横で原文・根拠を確認できます。三つの外観、狭い画面の移動、更新時の選択保持を改善し、観測 AI の増分更新と簡潔な応答にも対応しました。

#### 修正・文書

- 不正なフィールドや上限超過を明示的に拒否し、空の増分読み取りで履歴を再読しないよう修正。補助呼び出しの除外と、コピー後の翻訳済み通知に対応しました。
- 接続説明と画面ガイドを更新。画面の更新だけでは観測 AI は起動せず、AI の完了宣言だけで検収済みとは判定しません。

## v0.4.29 - 2026-09-08

### 中文

实时分析升级为目标—阶段—产物/核验的语义观测图，外环配套读取面新增纯对话视图。

#### 新增

- `/api/actions` 增加 `view=dialog` 对话视图：同一套增量与去重管线，只输出用户话语、AI 可见输出与思考，工具输入输出压成每步一行摘要（Bash 取命令首行、编辑类取文件路径、Task 派生取任务一句话）。给只需要"读懂这段会话讲了什么"的外环分析用——实测 311 步真实泳道从全文 6.0 MB / 4 页降到 222 KB / 1 页；子代理对话在其自己泳道的步里，用户消息中的 `<system-reminder>` 与斜杠命令回显剥除、`<command-name>`（如 /compact）保留。
- 实时分析改为目标—阶段—产物/核验关系图，保留关键未决问题、紧凑轮次与未覆盖请求入口；阶段按明确成员下钻，同页查看动作及工具返回证据，旧观测可折叠回退轮次阅读。
- 观测条目兼容新增 goal/artifact/check、短标题、独立执行进度与覆盖成员。连续阶段可用 cover_span 的首末请求 ID，由服务端校验同范围同泳道后展开，无需观察 Agent 枚举全部成员或编写布局。
- 结构化预测记录依据截止请求、后续主线窗口与可观察判断条件，封存原文；支持与反证单独核对，保留改判历史，不把观察者猜错等同执行者出错，不自动计算命中率。
- 只读 `/api/observations/trace` 增量投影：工具返回按同泳道先前调用 ID 配对，区分缺失、空结果与重复 ID 歧义，缓存只读新记录；原始动作账本保持现有格式。

#### 修复

- `/api/actions` 去重补上块级一层：同一段 AI 输出此前会出现两次——产生时标 `[说]`，下一次请求重发的历史里又以 `[助手]` 整段重出（消息级去重挡不住，因为响应块从未进过去重集合）。现在助手正文只在产生处输出一次；`[助手]` 前缀只剩"录制开始之前的历史"一种用途（其产生响应从未被录到，不丢录前上下文）。`since` 续读的预热阶段同步喂块级指纹，续读不会重放。
- 观测刷新增加请求取消与代次校验，防止快速切换后旧响应覆盖新观测；保留展开和选中状态，读取失败明确显示。水位不再误标成当前泳道执行步数。
- 接入说明补齐无观测时的 API 创建流程、来源/session 范围和语义维护方法；三语与三主题同步，修正窄屏选择器溢出和浅色主题的文字对比度。

#### 验证与文档

- 补充状态协议、范围展开、增量读取与前端语义回归，并接入现有 CI 验证；浏览器手动回归脚本覆盖目标阶段图、证据下钻、预测、修订刷新、三语三主题及 390/768/1280 宽度。适用原有自测通过，CLI 进程查询需允许 tasklist/taskkill 的本机环境。
- 用本地复制的54请求会话验证5个语义阶段、产物/核验及前缀预测回放，用247请求/18轮验证旧观测压缩。演示明确为开发期间外环复盘，真实录制与截图只留本地忽略目录，不随代码发布。使用说明、API合同、开发验证说明与本地说明书同步。

## v0.4.28 - 2026-09-08

### 中文

给「外环观测者」开通读写：外环是另开的一个 AI，跟踪被观测 agent 做了什么、在做什么、接下来要做什么。

#### 新增

- `GET /api/actions`：把一条录制流还原成去重后的会话全文，一条 54 步主线由 19.8 MB 降到 241 KB，正文不截断；增量只有一个 `since`。
- `GET|POST /api/observations`：外环观测状态读写，幂等重放、整批生效、改判留痕。
- 「实时分析」标签页：观测清单按类分组，证据可点回具体请求。
- 详情页加泳道内前后导航与时序图定位。
- 本地说明书加入「三类文档与协作」章节。

#### 变更

- 恢复发版流程；`public/` 仍冻结，发版不更新它。
- 产品源可独立生成 HTML 说明书；测试与工具按职责分目录。

#### 修复

- 文档审计增加具名参考文档的正文检查。

#### 文档

- API 契约补两个新端点；开发约定恢复发版章节，自测清单增至十三条。
- 界面导览补详情页泳道导航；报文解读新增「拿网上流传的提示词对照录制」一节。
- README 改为人读入口；变更记录统一以中文为准，本版段另附英文、日文译文供发版说明用。

## v0.4.27 - 2026-09-06

### 变更

- 默认启用滚动压实，预填 DeepSeek 并提高分析上限；API 密钥保持为空。

### 文档

- 官网补充提示词、运行时序、快照、翻译和 AI 解读说明，提供在线文档与可放大的截图。
- 文档维护规则并入产品说明书，研究结论与未决设计问题替代重复历史稿。
- API 契约与开发约定曾迁入产品说明书，并保留兼容链接与文档检查；同日后续已改回 Markdown 正文作为维护源。

## v0.4.26 - 2026-09-05

### 新增

- 详情页新增调用参数折叠区：请求体除三大块外的字段原样摆出，没见过的键标橙。

## v0.4.25 - 2026-09-04

### 修复

- `doc_audit` 限定 docs/ 的 `>` 只留警示、自检钩子与首块受众声明；69 块修辞性引用降为正文。
- `doc_audit` 新增 CHANGELOG 闸门：条目 ≤25 词 / ≤40 字、不许硬折行；上面几条已照此改短。
- 文档：同类工具构建手册搬到 `handbook/`，《报文解读》搬进 `docs/reference/`，`doc_audit` 加查相对链接可达。
- `doc_audit` 开始对账端点标题：同一 (方法, 路径) 只准占一节，声明的方法、查询参数与 `error_code` 必须真实存在。
- 上游拒绝后 CC 原样重发的 prompt 并入它所重试的那一轮，标 ⟲重试 ×N，不再各开一轮。
- 思考档位改按明文判，不按块存在判：只回签名的录制降为 C 档（`signature_only`），新增 `steps_with_plaintext` 字段。
- API 契约：analysis 端点的过时复制品删掉，抽屉章拆成三处；六份文档去掉文章式引子与标题日期戳。

## v0.4.24 - 2026-09-02

### 修复

- 审子代理那次工具调用的安全审查，在时序图里归到那个子代理，不再算在主线上。轮卡计数、级联隐藏、token 成本跟着归对；其余辅助类型不受影响。
- Windows 上 schema 变更后的索引重建此前不删旧文件、只往后追加，索引会越堆越大；现在真的替换，已膨胀的文件首次读取时自动清理。
- 时序图：一张折叠卡代表多个节点时不再画出几十条重合的连线；辅助泳道不再把分属不同会话的调用串成一条「会话顺序」线；切换折叠模式时辅助聚合卡的展开态一并重置，不再留下一组散开的单条。
- 五份参考文档全量体检：自相矛盾与互相矛盾处逐条改对，删文章式引子收束，补丁章节号顺编（随产物打包的 agent 说明书在内）。

## v0.4.23 - 2026-09-02

### 新增

- 新增 `notify_eval` 类别，识别 Claude Code 在用户离开后判断是否需要通知的调用；此前归为 `other`。

### 修复

- 建议补全、离开回顾和内部检索派发改归辅助，不再计入主线轮数。后台任务通知仍保留为真轮。
- 辅助泳道的 `quota_probe`、`hook_eval` 标签补齐中文和日文。

### 文档

- 《报文解读》的分类顺序补上标题 `json_schema` 官方位与无工具不判主线的结构门，与代码一致。

## v0.4.22 - 2026-09-01

### 修复

- 会话标题与 kebab-case slug 请求重新归为辅助，不再计入主线。
- 对话形状但不带工具清单的请求不再判为主线。
- 工具结果附带的图片说明、网页正文和打断标记不再另开一轮。
- 合并三份轮边界实现，时序视图与分析视图共用同一判据。
- 兼容 Claude Code 2.1.238 起的安全审查格式，恢复待判定动作显示，避免历史动作重复计数。
- 时序图安全节点补充判定结果，除待审动作外也能看到是否放行。
- `tools/origin_probe.py` 补齐 `.pack` 读取，避免压实后的录制静默脱离对账。

### 新增

- 盲区雷达增加 `mainline_suspect`，列出被判为主线但缺少主线结构特征的请求。
- `tools/origin_probe.py` 增加 `--mode belong | turns | origin` 三档对账。

### 变更

- `IDX_SCHEMA` 从 15 升至 17，旧索引自动重建。

## v0.4.21 - 2026-08-31

### 新增

- 增加当天录制滚动压实：封存已写完的前缀分片，跨天合并为单个 pack。默认关闭，阈值可设 20～2000 MB，默认 200 MB；解包可逐字节还原。
- 外部 agent 指令的分析端点从 3 条扩至 8 条，补充 `trajectory` 字段，并增加 `?task=flow` 流程图任务。

### 修复

- 修复分片录制归档时只保留最后一段的问题，归档覆盖完整录制。
- 修复 `lang=en` 的 agent 指令仍混有中文标注。

## v0.4.20 - 2026-08-29

### 变更

- 列表与八视图各设独立的 AI 归纳按钮，分别显示状态；两条管线不可同时运行。“全部重算”和自定义归纳提示词只作用于列表。
- 八视图 HTML 按快照与语义层指纹缓存，容量为 2，语义层更新即失效；重复打开不再重算。

### 修复

- 八视图加载时立即显示骨架卡及等待说明，避免计算完成前界面没有反馈。

## v0.4.19 - 2026-08-29

### 变更

- 八视图接入主界面的三套外观与打包字体，提高小字字号；父子页协商高度与可视区，避免双滚动条和抽屉错位。切换外观原地重渲，不重新计算录制。

### 修复

- 修正模型在途时长单位、阶段耗时缺失、取整不一致与硬编码工具数；修复零拦截时的负重试数及空态错误指引。状态快照支持阅读完整文本，补齐图例、空泳道说明与长物料名布局。
- 无法生成轨迹时返回同款外观的错误页，不再把 API 浏览面的整页文字当错误提示；补充相关冒烟检查。
- 可得性横幅区分思考块存在与明文缺失，避免显示“有思考但共 0 字”的矛盾说明。

### 新增

- 分析页树档替换为轨迹八视图，列表保留。以全部主线请求的块并集补回压缩前历史；事实由程序计算，语义由模型生成。八种读法涵盖状态快照、物料血统、验证矩阵、阀门回路、能耗方差、最优轨迹表、物料生命线与最优时序图。语义流水线可续跑、按快照缓存并随便携包导出；原始录制不可用时明确说明，不展示残缺运行。

## v0.4.18 - 2026-08-28

### 修复

- 步级归纳补入用户指令、规范化动作、作用对象和工具结果摘要。结果摘要最多 90 字，图片只计数；纯执行步并入前一个判断步，不增加调用。用户指令预算从 200 提至 2000 字，取头尾。
- 补齐命令作用对象解析，支持先切目录再执行、`uv run`、`python -c` 与带引号的绝对路径。真实录制验证轮级覆盖 199/199 步，未出现失败批。

### 变更

- 步级简报改为 `title`、`why`、`got` 三段：标题最多 20 字，只在存在真实权衡时写原因，结果短引必须能在对应工具结果中找到。旧单段、两段格式与自定义提示词继续兼容。
- 轮头区分用户要求、本轮任务、完成条件、结果与风险，会话层增加总目标与偏移。完成条件仅引用用户已说明的标准；涉及对象及产物是否被读回或运行由程序统计。

## v0.4.17 - 2026-08-27

### 修复

- 自动更新重启时清除子进程环境中的 `_PYI_*` 和 `_MEIPASS2`，避免复用旧解压目录导致新版本加载旧界面或资源缺失。保留其他环境变量；重启后的端口变化仍通过 `port.txt` 发现。
- 思考抽屉按实际位置计算可用高度，仅保留一个滚动容器；打开时定位到吸顶区，避免翻译结果和滚动条落在屏幕外，也兼容界面缩放。
- 快照索引按 sid 格式识别文件，避免把 `.analysis.json` 侧车误收为快照。
- 修正经典暖灰外观下贴纸标签对比度不足；补查带标签、展开子代理及抽屉状态。
- API 浏览面补齐三套外观，修正实验室日光误用暖灰色板；新增外观切换并共用现有偏好，修复文字、链接与空值颜色对比度。

### 变更

- 归纳顺序改为先生成步级简报，再汇总轮级与子代理结论，避免骨架截断丢步。批次默认并发 4，可设 1～8；轮级批次不拆轮，子代理增加任务、问题、处理与结果摘要。
- 思考抽屉宽度改为 `clamp(320px, 30vw, 760px)` 并支持拖动，偏好仅存 localStorage；窄屏仍移到正文下方。

### 新增

- 归纳按阶段落盘并记录失败步号，重跑默认补缺，另设“全部重算”。重试采用退避，配置错误立即终止；进度按阶段显示完成数，失败或结束后清除运行态。
- 快照、AI 归纳与对话历史可导出为 `.ccwa` 便携包，以 manifest 的 `kind` 区分归档类型。导入 ID 冲突时另建 ID，不覆盖本地内容，并保留机器来源。
- API 浏览面为需路径或查询参数的端点提供可编辑完整 URL，优先用本机真实录制及已分析快照生成样例；无数据时明确标为参考格式，样例执行检查要求返回 200。

## v0.4.16 - 2026-08-27

### 新增

- 录制分析接回子代理请求，按派生步骤展示折叠简报与单步思考，支持三层嵌套。同次归纳覆盖主线和子代理并分阶段显示进度；未匹配或录制不可用时单列原因，不解释成“没有子代理”。
- 设置页“给 AI 用”卡增加 API 浏览面入口，地址使用实际 `location.origin`，可点击或复制。
- 列表增加步级 AI 简报、工具聚簇与机械信号，结果随分析缓存。轮级和步级提示词开放设置，防注入骨架保留；长思考取头尾，落盘 2000 字仅作防失控上限；补记分析模型名，失败批明确显示。

### 变更

- 步级简报分为最多 24 字的标题与细节，兼容旧 `brief`；思考原文移入右侧吸顶抽屉，可用 Esc 关闭，打开时不重渲列表，树视图也使用该抽屉。
- 子代理边线、徽章与名称统一为蓝色，并分别校正三套外观的文字对比度。
- 录制分析界面改为单选，提示词仍可双选对比。两条录制的 system、工具集或历史对比保留在 diff API，GUI 不再生成 `face` 参数。
- 多源指令清单默认折叠，标题显示条目数；收录逻辑、API 与分析上下文不变。

### 修复

- 补齐分析提示词的 i18n 键；检查工具同时验证 `data-i18n` 引用存在，避免三张语言表同时漏键仍通过。
- 修正三套外观的文字对比度，拆分装饰色、正文色、危险按钮实底与贴纸角色文字色；新增 `tools/contrast_probe.js`，展开态复测通过 AA。
- 子代理卡头与工具行明确字号，避免继承卡片大字号；探针补查同一行的异常字号差异。
- 删除 `renderDiff` 对已移除参数 `into` 的引用，恢复提示词对比。自由变量静态检查因误报过多未纳入门禁。
- 工具聚簇行与步骤行共用列宽和字号，长步骤区间不再挤压工具标签。
- 工具名标签补上浅色背景，修复浅色外观下白字不可见；重复工具调用合并显示。
- 压实包与归档写入机器 `host` 和真实版本，导入后保留来源，重新归档外来录制不改签。来源列表增加本机 `host` 与 `foreign`；旧归档缺少机器信息时显示未知。
- 从导入来源备份录制时，界面和快照 API 完整传递 `source`，避免到本机命名空间查找而返回 404。
- 白板、贴纸、信号、树分叉、开关与行内差异改用外观 token，补齐两套浅色显示并复核各层文字对比度。
- `doc_audit` 拦截未定义且无 fallback 的 CSS token；清除旧 token 名与会落回系统字体的冗余兜底。

## v0.4.15 - 2026-08-25

### 新增

- 翻译、解读与分析对话的输入上限开放为字符数设置，默认 20000，读写均限制在 1000～2000000；截断提示指向对应设置，内部分配预算保持不变。
- `/view` 列出 GET 端点，`?format=html` 将 JSON 或说明书渲染为人类可读页面；未加参数时响应逐字节不变。需参数、长连接或联网端点列明限制，不隐去。
- 录制支持内容寻址压实、随机读取与单文件归档；压实后查询行为保持一致，空间统计随存储变化。完整重建逐字节校验通过才移除原件，`uncompact` 可还原。
- 外来录制导入独立的 `sources/<label>/`，全部读取面支持 `source`，CLI 使用 `--source`；来源列表与界面切换明确区分本机和外来数据。

### 修复

- 工具调用输入支持折叠与全文展开，移除搜索结果和引用的条数截断；保留的行截断显式标记，并修复双重转义。
- 空 `?date=` 按未指定处理；i18n 检查按正确编码读取 Node 错误输出；保留天数自测改用相对日期，避免随时间失效。

### 变更

- 区分压实、归档与清除：压实可逆，归档默认保留原录制，清除才删除；保留天数仍是自动删除入口。该版本仅压实过去日期，不压实正在写入的当天。

## v0.4.14 - 2026-08-10

### 文档

- 开发约定增加七层识别地图及官方标识、启发式回退关系。轮起源未知时回退 `user`；AI_USAGE 补充 origin 语义，移除已由实测关闭的交互模式子代理缺口说明。

### 新增

- 轮起源用本地日志真值核对，并记录 wire 的 `request-id` 与日志 `assistant.requestId` 的关联。此关联只适用于提供该字段的 Anthropic 上游，网关的 `x-log-id` 不可替代。
- 上线中英双语落地页，补齐搜索、分享元数据和站点验证；三语 README 增加产品全称、clone 与下载入口。社区发帖未在本版执行，本地 `promo/` 保留复现教程。

## v0.4.13 - 2026-08-09

### 修复

- 更新下载在锁内占用运行状态，点击立即反馈并使用唯一临时文件；重复请求接回当前进度。下载中检查更新不清空状态，校验和获取移入下载线程。v0.4.11 的旧更新界面仍带此缺陷，升级时可手动下载替换，或只点一次下载并等待，不要重复点击。

## v0.4.12 - 2026-08-09

### 新增

- 时序图增加 `user`、`synthetic`、`command`、`partial` 轮起源，自动轮单独显示，不隐藏实际工作和成本。未知形态及图片发起的轮仍归 `user`。辅助按轮聚合并可独立折叠，归不到轮的保持单条；`request-id` 可与日志关联，但只适用于提供该字段的 Anthropic 上游，且需区分本地时间与 UTC。
- 设置页实时列出运行实例的端口、模式和录制状态，兼容旧实例。探测固定在 5051～5100，不接受扫描范围参数，并绕过系统代理，不依赖可能过期的 PID 或端口文件。
- 轮次骨架增加可重跑、可缓存的 AI 语义归纳，事实仍由程序抽取。模型步号须通过骨架白名单校验，无效引用剔除并记入 `dropped_steps`；结果作为侧车随快照清理。
- 设置页按录制、索引、存档、快照和日志展示磁盘占用，补充天数与最大单日；只做 `stat`，不读取内容或统计条数，不缓存，也不增加删除入口。容量格式支持 GB。

### 修复

- 残轮的折叠入口挂到首个可见成员，展开后可单独收回，不必重置其他轮。
- 贴纸角色徽章移开删除按钮，拖拽处理排除删除和确认控件，避免点击前重渲导致按钮失效。
- 新快照落位检查已有贴纸矩形，跳过占用位置，保留空位复用。
- 文档审计为外部工具端点增加具名白名单，不豁免整篇手册；白名单中未引用或已变成本项目路由的条目也会被检出。

## v0.4.11 - 2026-08-09

### 新增

- 更新接口支持下载、校验、替换和重启，每步由用户触发，不定时检查或静默安装。录制中拒绝替换，不代停代理；Windows 替换失败整体回滚，macOS 仅下载、校验并定位文件。来源仓库固定，只走 HTTPS 并逐跳检查重定向主机；有校验和时必须比对，缺失时明确提示并展示实测值，下载失败清理旧同名包。
- 构建版本同时写入 API、Windows PE、macOS Info.plist 与资产文件名，两份 spec 共用 `tools/version_res.py`；发布产物附带 `SHA256SUMS.txt`。
- `tools/build.py` 统一本地与 CI 的版本、命名和校验和。`--from-git` 从 tag 读取版本，`--self-test` 核对产物命名。

### 修复

- 切换语言时从缓存重渲快照对比；仅在该面板仍选中两份快照时生效，不重新请求 API。
- 快照对比的可比性提示按字段映射三语文案，缺键才回退后端原文；HTTP API 返回不变。
- 更新重启顺序改为恢复配置、启动新进程、退出，避免旧进程撤销新进程的接管；清除 `Timer` 中变量改名后的残留引用。
- 两份 spec 补齐 Werkzeug 等六个依赖的运行元数据，修复 uv 环境本地打包后 `serve` 报 `PackageNotFoundError`；收集逻辑共用版本资源模块。

## v0.4.10 - 2026-08-08

### 新增

- 分析页提供提示词与录制快照看板，支持拖拽、从详情或选取文本保存、单录制分析和双快照对比。快照以单条请求保存当时上下文，位置随快照存储；历史内容不随后续录制改变。
- 快照支持内置模型多轮分析，逐字稿落盘并可经 API 读取。问题按可得性切换，B 档禁止臆测心理；每轮重建上下文和防注入边界，历史超预算时丢弃最旧轮并明确告知。
- 快照可按类型、标签和日期手动批量清理，先预览再确认，逐项回报失败；保留天数不自动删除用户保存的快照。
- 不可见字符差异增加行号定位和高亮，统计与正文由同次扫描生成。
- 内置模型支持解释及翻译快照差异，只发送差异和元数据，不同时发送两份全文；报告超预算时明确标注截断。
- 差异比较先显化零宽字符、空白与换行差异，再进行文本比较；同形异码字按字符标记，精确区分真实编辑，避免把普通字符变化误报为隐藏水印。
- 步骤骨架增加树视图，展示命中句、实际工具与分支等机械信号。页面明确这些是候选线索，不是模型真实决策树。
- 思考抽取分 L0 骨架、L1 摘录、L2 全文，按信号密度分配预算；序列化后实测并压缩，如实返回 `size`、`budget` 与 `over_budget`。
- 思考可得性按步骤分三档；B 档提供行为链和缺失原因，不推断心理，C 档说明加密块不可读。A 档混有加密块时也提示覆盖限制。
- 列出 system、消息注入和工具描述等指令来源，对重复注入合并计数；提示词快照同时支持 system 块、消息块和自由选取。
- 快照能力同步到 HTTP API 与 AI_USAGE；复制给外部 agent 的是本机端口、端点、元数据和按可得性调整的任务，不直接复制整份录制，支持三语。
- 新增快照自测，覆盖预算、B 档行为链及隐蔽差异正反例；修复环境抽取在 JSON 转义文本上匹配过长的问题，改为遍历真实文本值。
- `tools/check_refs.py` 检查 JS 调用与 CSS 类引用，识别注释、字符串、正则及复合选择器，避免有效引用误报。
- 记录最近 5 套真实上游配置并提供一键还原，本机代理地址不入历史。还原对齐整个 `ANTHROPIC_*` 命名空间，凭据和模型映射一并恢复；官方订阅原本缺失的键恢复为删除。默认选中凭据相同的历史，接口中的 token 始终脱敏。
- 文档审计核对 spec 资源路径及双平台共享配置，防止说明书迁移漏打包或依赖分叉。
- 审计对账 `kind`、`err_kind` 与 doctor 规则 code，按各自语境查幽灵枚举，不混用请求和泳道分类。

### 变更

- 文档审计按差异性质返回结果：错误事实阻止构建，未登记内部能力仅提示；JSON 输出增加 `ok` 并保持同样退出码。CI 构建依赖验证任务。
- BASE_URL 警告提供直达上游配置历史的修复入口，区分污染残留与合法本地网关。
- 捕获列表宽度上限改为 1760px，时序图按视口放宽至最多 2560px 并保留边距；详情、设置与窄窗口不变。

### 文档

- `docs/` 拆为参考手册、方法材料和索引，审计按目录覆盖，避免维护独立文件清单。
- 文档维护策略由日期堆叠的腐化清单改为按问题归纳的教训表。
- 界面导览移除已解决的反思项，保留仍有效的限制与改进问题。
- 开发指南改名为开发约定，问题域手册改名为同类工具构建手册，使名称与用途一致。
- 架构总览聚焦模块分层与数据流；历史、开发约束和设计取舍分别指向对应记录。

### 修复

- 修复提示词看板交换两侧时抛异常，恢复选择与对比状态交换。
- 上游还原成功后同步刷新 BASE_URL 警告；自指和死端口体检建议直接导向历史还原，不再建议无法成功的重启。
- 文档审计递归扫描子目录，具名依赖缺失直接报错，不再把读不到文件当成没有问题。
- `serve` 接管配置失败时仍保留服务与修复接口，并在日志给出恢复命令；此时不录制。
- `serve` 与代理启动 API 共用 `app.begin_recording()`，补齐上游历史采集。
- 未录制时设置页从配置文件读取当前 BASE_URL，不再显示用于恢复的内存快照。
- 上游错误体按声明字符集解码，无声明时依次尝试 UTF-8、GBK、latin-1，并记录回退；不再用替换字符损坏原文。SSE 与 JSON 协议内解码仍保持 UTF-8。
- 失败指纹归一化增加至少 16 位的长十六进制请求 ID，避免同次限流碎成多组；短错误码不归一。
- 四个静态审计脚本统一 UTF-8 输出，避免 Windows 控制台乱码或检查通过后打印失败。

## v0.4.9 - 2026-08-03（紧急修复）

### 修复

- 增加辅助聚合卡高度，恢复被裁掉的分类计数徽章。
- CLI `errors` 返回 `ok: true`，避免将成功返回的失败统计误判为命令失败。

### 新增

- `tools/check_render.py` 静态核对卡片行数、内边距和高度常量，并用反例自测检验溢出判据。

## v0.4.8 - 2026-08-02（紧急修复）

### 修复

- 折叠时序图恢复辅助泳道，每条主线显示一张辅助聚合卡；保留计数、明细展开与主线关联。

## v0.4.7 - 2026-08-02

### 变更

- 时序图按对话轮折叠，以用户话语、子代理和辅助计数为入口；仅整轮失败才整卡标红。索引增加 `turn_user`，避免提醒注入超过截取长度后丢失用户文本。
- `stats` 改读索引，不再逐条读取正文并重复分类。
- DAG 按日期和录制大小缓存；多会话列表显示 session 短码，捕获摘要增加 `session_id`。

### 新增

- 增加深色专业、经典暖灰和实验室日光三套外观，默认深色；偏好只存浏览器，不进配置。补齐键盘、ARIA、减弱动画、窄屏与缩放支持。
- `/api/unknowns` 聚合未知块、字段与枚举，返回样例及来源信息，便于从实际录制发现协议盲区。
- `/api/diagnose/trends` 跨天归并失败，提供每日曲线及供应商、模型、CC 版本切片；仅提供 HTTP 与 CLI，不进 GUI。
- 新增 `/api/grep` 与 `/api/stats`，与 CLI 共用存储层实现，避免查询和统计口径分叉。
- CLI 增加 `unknowns`、`trends`，只读分析面统一支持会话过滤，无需启动会修改配置的录制服务。
- `tools/doc_audit.py` 对账端点、CLI、路径、索引版本和自测清单；该版本只报告差异，退出码保持 0。
- 增加 `quota_probe`、`hook_eval` 分类，识别配额嗅探与 hook 评估。
- 索引增加 `host` 和 `cc_version`，`IDX_SCHEMA` 12→13；供应商按实际路由 host 判断，不靠模型名。
- 专门渲染 `server_tool_use`，索引记录 `output_config.format`；启动时提醒本机 BASE_URL，非自身端口的合法网关不拒绝。

### 修复

- 适应宽度的缩放下限设为 50%，避免多泳道图缩到文字不可读。
- 盲区结果补充主机与 CC 版本归属，beta 改按提升度筛选（≥1.5）；录制降级单列 `degraded`，不再混为协议演进。
- 趋势增加 `burst` 与过期状态，区分形态和新鲜度；空泛错误按 host 拆分，避免跨供应商误归一组。
- 补齐 `compaction` 的已知集合与渲染，避免把自身组装的块当成未知。

### 文档

- 补齐检索、统计、雷达字段、CLI 会话过滤与三外观开发约定，并将盲区观测方法归入同类工具手册。
- 三语 README 的 12 张截图按新外观重制，使用合成数据，不包含真实录制。

## v0.4.6 - 2026-08-01

### 新增

- 检查面支持 `session`、`exclude_session`，CLI 使用对应参数；按会话前缀匹配，在分页前过滤，保证 total 真实。
- 日期数据加载期间显示徽标，避免等待时无法区分加载与空结果。

### 变更

- `grep --in` 增加 `sysmsg`、`tool_result`、`tool_use`、`tools`，`all` 覆盖除工具定义外的全部区域。返回实测 `coverage`，零命中附说明，达到数量上限提前停止时比例为 null。

### 修复

- `stats` 补计 `cache_creation`，修复 token 汇总缺项。
- `get <id>` 自动查日期时排除索引文件，避免命中残缺索引行。
- `decode_error` 进入索引并单列 `decode_failed`，避免解压失败仍计成功；它与上游拒绝区分，同时存在时以上游错误为准。schema 升至 8，旧索引自动重建。
- 协议扩展基线兼容改名前的旧值，不再将老录制误报为未知。

## v0.4.5 - 2026-08-01

### 变更

- 辅助请求优先按 session id 挂到所属主线，仅缺少对应会话时回退时间邻近；节点颜色与级联隐藏跟随正确归属。
- 子代理泳道优先用 `X-Claude-Code-Agent-Id`，旧录制回退 prompt 派生键；父子 trigger 仍靠 prompt 对齐，主线与子代理类别判据不变。
- 隐藏主线或子代理泳道时级联隐藏其关联节点，恢复时保持相同关系。
- 子代理使用派生主线同色的淡化色，强化父子关系辨识。

### 修复

- 无 `settings.json` 时按空配置读取并跳过文件备份，接管时可创建最小配置，修复新机器上 `serve` 启动即退。
- 复制给 agent 的指令随界面语言生成，不再固定中文。
- 翻译和解读区分输入截断、输出上限与内容审查，流式返回截断事件；读取 HTTP 错误正文，显示真实上游原因。
- 为可见文本补齐选取与复制支持，避免内容只能看不能带走。
- 快速切换日期时丢弃过期请求结果，避免图表被先前日期的响应覆盖。

## v0.4.4 - 2026-08-01

### 修复

- 跨午夜后刷新日期与数据订阅，避免软件继续显示旧日空列表。
- 提高次级文字对比度，修复低于 WCAG AA 的小字颜色。

### 新增

- 设置页增加 90%～200% 界面缩放，适配不同屏幕与阅读偏好。

### 变更

- 失败聚合改为捕获页可展开的摘要入口，不再长期占据首屏横幅。

## v0.4.3 - 2026-08-01

### 新增

- 捕获页增加失败聚合入口，可展开错误组、查看请求字段与样例，不再只能经 API 查询。
- AI_USAGE 随软件打包，`/api/ai-guide` 附加实际端口和路径，`--help` 打印说明后退出；设置页提供给 agent 的复制指令，缺少文档时回退最小速查。
- 详情页展示原始 usage 中的 `server_tool_use` 和 `service_tier`，补上服务端工具调用与档位信息。
- 聚合 `compaction_delta` 并记录 `stop_sequence`；补充自测与样例，移除代码不再产出的 `ek.parse` 文案。
- 详情显示 beta 扩展及未知提示，索引补记上下文管理、诊断、停止序列与思考预算，`IDX_SCHEMA` 5→6。
- 记录 `x-claude-code-agent-id` 作为子代理交叉校验位，不据此更改既有分类结论；历史统计旁证不替代人工核对采集。

### 修复

- 纠正 noconsole 无 stdout 的错误假设，恢复管道与重定向下的帮助输出；双击无控制台时使用落盘说明，PowerShell 调用需采用可等待的方式。
- 捕获列表按失败标记显示状态，避免 HTTP 200 的流内错误仍显示成功。
- 详情页按请求 `stream` 判断流式类型，不再把普通响应的分块数误当 SSE。
- 切换语言时重新渲染体检与失败聚合条目，避免保留旧语言。
- macOS spec 补齐 Windows 已有的解压依赖，防止非流式响应解析回归。
- 能力面录制审计确认核心解析；Workflow 子代理用 agent-id 分开泳道，动态脚本派生关系仍明确为限制。隔离采集改用 `--settings` 注入，纠正进程 BASE_URL 环境变量必然生效的说明。
- 工具调用轮的捕获摘要显示实际工具动作，不再留空。
- 识别 SSE 的 `event: error` 及数据内错误类型，记录 `stream_error` 并纳入失败统计；HTTP 状态可仍为 200，消费方须检查 `error` 或 `has_error`。
- 解压与解码失败保留诊断标记及可恢复信息，不再静默丢失响应正文。
- 聚合 `signature_delta` 与 `citations_delta`，保留思考签名和引用信息。
- 增加 brotli、zstd 解压与打包依赖，覆盖 CC 声明的压缩格式；补充非流式自测，真实上游复验仍待其恢复。
- 应用版本从发布 tag 派生，避免界面自报版本与产物不一致。

### 变更

- 协议扩展区默认折叠，摘要保留数量与未知扩展提示。
- 响应 Headers 恢复默认折叠，保留 wire 专有字段的突出显示。

### 文档

- 修正恢复路径、错误枚举、索引版本、字段长度、i18n 键数与固定端口等文档漂移，收紧真源引用。

## v0.4.2 - 2026-07-30

### 修复

- 详情页请求侧元数据改为卡片，与响应侧对齐；`stream` 始终显示 true/false，统一标签边框高度。
- 捕获列表改用固定列宽 grid，避免模型名和类别标签推动其他列；列宽兼顾三语，长值截断后可查看全文。
- 时序图图例换行后左对齐，不再保留宽屏推右的偏移。
- 设置页按钮禁止折行，标签列保留最小宽度，长路径在值区域换行。
- 时序图安全节点显示待审动作，列表与 DAG 共用摘要格式，不再显示难以理解的响应标签片段。

### 变更

- 两平台产物统一使用 cc-wire-analyzer 名称，macOS 应用改为 `cc-wire-analyzer.app`；旧 `CCWireAnalyzer.app` 不会被覆盖，升级时需自行移除。

## v0.4.1 - 2026-07-29

### 新增

- 安全审查展示待执行工具与参数、severity 或放行判定、规则理由及发送内容；分数范围 0～100，50 为放行与拦截分界。解析兼容停止序列截去闭标签的响应。未得到判定时明确提示，不显示为空；索引升级并补充真实形态样例。
- 关于页增加检查更新，比较最新发布版本，12 秒超时后提供手动入口。
- 详情页按内容为 system 块标注计费头、身份、审查等角色，帮助辨认大文本用途。

### 文档

- 新增报文解读，说明七类请求、报文形态、判别方法和易混点，并与其他参考文档互链。
- 开发约定集中到 `docs/开发指南.md`，架构与贡献指南改为引用；补正模板缓存说明，明确模板修改后需重启服务。
- 三语 README 改从使用场景、真实故障案例与数据边界介绍产品；仅需普通历史记录时建议直接读 Claude Code 日志，对外社区发布保留为维护者决定。
- README 移除手填版本号，改用发布列表和日志指针，避免每次发版人工同步多份副本。
- AI_USAGE 改为中文，英文与日文 README 标明深度文档语言；完整多语言文档策略未在本版实施。

### 变更

- 捕获列表为非主线请求显示类别标签，摘要接口增加 `kind`。
- 备份份数从捕获状态卡移至设置页备份目录。
- 列表与详情页的首字时间标签支持中英日三语。
- 请求侧思考块接入统一文本工具条，支持翻译和 AI 解读。
- 移除按官方定价推算的金额，避免误导第三方网关用户；保留上游原始 token 用量。

### 修复

- 详情页将请求体的 `model`、`stream` 放回请求侧，响应区只保留响应字段。
- 隐藏主线时同时隐藏关联辅助调用，空辅助列不再占位，泳道菜单注明联动。
- 删除无法命中的 system 压缩角色标注和 9 个死 i18n 键；分类降级增加有界计数与日志，三语字典统一为 245 项。
- 删除代理 start 响应中恒为 null 的 `orphan_recovered`，保留实际使用的状态字段；对齐 start 错误码并移除不存在的 `parse` 枚举。

## v0.4.0 - 2026-07-28

### 变更

- 停止原因与错误类型改为三语标签，响应头默认展开并突出 wire 独有字段；主线泳道使用序号标识。
- 体检返回 `scope: settings_file`，说明运行会话可能仍持启动时环境；不跨进程读取环境来弥补盲区。
- 主线泳道显示真实 session id 短码，可查看完整值；子代理仍显示派生实例码，避免与父线混同。
- `tools/lane_probe.py` 展示官方位并与分类器双向核对，不一致时警告，用作后续 CC 版本的回归探针。

### 修复

- 并行同模板子代理的探测前缀 120→300、匹配长度 200→1000、任务截取 600→1500，避免多个派生实例挤到一条泳道；索引 3→4 自动重建，前 300 字仍相同的边界情况留待后续处理。
- 子代理优先使用 `cc_is_subagent`，补齐 SDK 主线指纹，未知形状回退主线；派生匹配先去掉提醒再做子串对齐，不因先前类别判错而跳过关联。
- 主线按官方 session id 分组，缺失时才回退文本键；子代理按派生实例归并，避免每个请求独占泳道。
- 自测从 5150 起选空端口并用 API 探活，mock 上游端口写入副本，避免固定端口被占时误测真实实例。
- 索引记录增加 schema 校验，版本不符先删除再重建，避免旧索引静默缺字段或反复追加。
- 自测样例补齐真实 system 块、会话头、用户元数据与子代理提醒，并覆盖同次派生多请求归一泳道。

### 文档

- 对齐 API 的体检、失败聚合、流式翻译与解读、usage 字段和代理状态；AI_USAGE 补维护提示，三语 README 补版本与导航，CLAUDE 修正已处理配置的历史说明。
- 新增界面导览、架构总览与文档维护策略，补充章节同步提示。
- CLAUDE 按速览、背景和开发约定重组，归纳反复故障、子代理判据与模块关系。
- 中文日志调整为书面表达，保留事实与技术标识，英文版本不变。
- 日志顶部增加项目速览，提供定位、状态和下一步；长期规则仍放开发约定。

### 新增

- 失败聚合按归一化错误消息分组，同时返回请求字段、类别和样例。输出有数量上限并报告截断；只整理证据，不调用 LLM。
- 配置体检检查上游、凭据与 effort 冲突，界面和 API 共用结果；启动遇错误级问题返回 409，可显式强制越过。体检只读、不自动修复，不确定情况不报错，兼容 macOS Keychain。

## v0.3.2 - 2026-07-19

### 修复

- 增加写时轻量索引，列表和 DAG 不再反复读取完整录制，也不再限制为 1000 条；详情按偏移读取，旧录制或落后索引可自动补建。
- LIVE 采用增量节点与连线更新，日期、过滤、泳道或节点档位变化才全量重建；增加隐藏工具循环和辅助调用开关，缩小 CSS 动画范围。

### 新增

- 同泳道连续至少两次错误可折叠成计数卡，显示时间范围和摘要，可展开收回；LIVE 原地增加计数，连线定位到折叠卡。
- 工具栏增加泳道选择器，逐条控制显隐并释放列宽，切换日期时重置选择。

## v0.3.1 - 2026-07-18

### 修复

- 阻止把代理自身当上游造成转发递归：启动按回环主机与自身端口检查，合法的其他本地端口仍允许；已污染的恢复记录不再写回自指地址，转发路径增加兜底守卫，发现上游仍指向自身时返回 502。

## v0.3.0 - 2026-07-17

### 新增

- 时序节点分用户消息轮、工具循环细条和纯对话轮三档，不凭语义猜测；错误节点不降档，图例补齐三语。
- 每 2 秒检测 settings.json 外部修改，发现绕过代理时显示断开并清除 marker，不回写用户新配置；提供重新接管，状态 API 返回 `external_change`。
- 运行日志记录启动、关窗、API 停止、收尾和信号等退出路径；孤儿恢复时说明上次未正常结束。

### 修复

- `run.log` 改用 UTF-8，避免中文 Windows 日志乱码；历史 GBK 内容不迁移。
- 发布工作流改为 checkout 后显式获取 annotated tag，避免重复拉取触发 tag 导致失败。

### 变更

- 发布说明改从对应 CHANGELOG 版本段提取，缺失时回退 tag 信息，不再依赖仅适合 PR 的自动摘要。

### 文档

- 增加中文 CHANGELOG，与英文版本同步。

## v0.2.0 - 2026-07-14

### 变更

- 合并为单一桌面二进制：双击打开 GUI，`serve` 启动无窗口服务与代理，agent 经 HTTP 操作；源码 CLI 保留但不打包。
- 移除独立 CLI 二进制，其发行用途由桌面二进制的 `serve` 替代。
- 移除未生效的头部脱敏开关，敏感头始终脱敏，不提供把凭据明文录入的选项。
- 删除独立 shell 取消后不再使用的 `config.read_port()`。

### 新增

- 内容块支持复制全文、自定义右键菜单与 Ctrl/Cmd+C，统一 Windows 和 macOS 的复制行为。
- 详情页增加响应头面板，显示已录制的限流、请求标识与重试等 wire 信息。
- `tools/lane_probe.py` 并列展示主线与子代理候选信号，便于用真实流量校准分类。
- 支持 `CCWA_HOME` 与 `CCWA_CLAUDE_SETTINGS` 双覆盖，增加 CLI 自测，在临时目录测试配置接管，不操作真实设置。

### 修复

- 恢复动作接到窗口同步 closing 事件，确保 macOS 红点关窗和 Cmd+Q 都还原 BASE_URL 并清除 marker。
- 孤儿恢复先核对配置当前值，只有仍等于本工具写入的地址才还原，避免旧 marker 覆盖用户后续修改。
- 启动时执行 `retention_days` 清理并返回结果，增加 `clear --older-than N`，保留天数设置不再空转。
- 非流式响应补齐 usage、内容块和停止原因解析，恢复安全分类器等请求的用量记录。
- 录制写入失败增加计数、日志、状态字段与红色提示；写盘失败仍不阻塞转发。
- 统一 `classifier.usage_norm`，修正 DAG 和 CLI 因读取错误 usage 键而丢失 token 统计。
- 界面展示连接与超时错误的 detail，不再只显示错误类别。
- 接通 `auto_start_proxy` 配置，启动行为遵从用户设置。
- 自测 SSE 改用真实 token 键，并补充非流式上游用例。
- 长文本翻译传入 `max_tokens`，超时增至 180 秒；错误留在结果区，并展示错误码、超时或上游停止原因，不再只弹通知后留白。
- 前端拦截 API Key 与 Base URL 中的非 ASCII 字符，指出问题字符，避免底层编码异常。
- 翻译和解读结果剥离泄漏的 `<text>`、`<content>` 定界符。

## v0.1.0

### 新增

- 发布首个开源版本。
