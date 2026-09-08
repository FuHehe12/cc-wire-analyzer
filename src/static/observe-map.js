/* Observation reader. Captures are facts; semantic nodes and reviews are claims.
 * Public API: render(state), refresh(), clear(message). The host owns polling.
 * This module never executes recorded content or asks a model for coordinates. */
(() => {
  'use strict';
  const words = {
    zh: {
      trajectory:'语义轨迹', graph:'目标、阶段与交付', goal:'目标', phase:'阶段', artifact:'产物', check:'核验',
      finding:'发现', open:'未决', prediction:'预测', deviation:'偏差', outcomes:'产物与核验',
      observer:'外环判断', facts:'录制事实', detail:'证据与解释', select:'选择一个阶段、判断或请求，查看原文与依据。',
      graphNote:'连线仅来自已记录关系；列的位置用于阅读，不代表时序或已经达成依赖。',
      fallback:'尚无明确的阶段覆盖，按录制轮次阅读。证据锚点不等于阶段成员。',
      noKind:'尚未记录', coverage:'覆盖请求', uncovered:'未归入阶段的请求', turns:'录制轮次', steps:'请求',
      coveredNote:'覆盖由外环明确指定；同一步可以属于多个阶段。', noCoverage:'未指定覆盖范围；下方仅为证据锚点。',
      empty:'当前范围没有录制请求', loading:'读取中…', failed:'读取失败', retry:'重试', noScope:'缺少录制日期，无法读取轨迹。',
      scope:'范围', allScope:'未限定泳道或会话：显示当天全部录制。', anchors:'证据锚点', relations:'已记录关系',
      belongs_to:'属于', depends_on:'依赖', produces:'产出', supports:'支持', contradicts:'反证',
      missingItem:'关联条目已不在当前观测中', missingStep:'该请求不在当前范围，正在尝试读取原录制。',
      planned:'计划中', active:'进行中', blocked:'受阻', done:'外环标记完成', unknown:'进度未知',
      doneNote:'进度标记不代表验收成功；请查看独立核验与证据。',
      supported:'有依据', unresolved:'待解决', tentative:'暂定', retracted:'已撤回', status:'判断状态', progress:'执行进度',
      future:'预测与核对', noPrediction:'暂无预测。新的预测会在这里保留原判断和后续核对。',
      predictionNote:'支持与反证来自外环核对，界面不自动判定命中。', original:'原判断', reviews:'后续核对',
      evidenceSupport:'已有支持', evidenceCounter:'存在反证', conflicting:'支持与反证并存', beforeWindow:'未到窗口', pending:'待核对',
      windowUnknown:'未记录完整窗口，无法判定是否到期。', frontierMissing:'预测起点不在可用主线内，无法判定窗口。',
      windowPartial:'录制范围不完整，无法判定窗口。', after:'截止请求', horizon:'随后主线请求数', criterion:'判断条件',
      observed:'窗口内已录制', windowReached:'窗口已到', originalNote:'原判断与核对分开保留；修改记录可在历史中查阅。',
      noReview:'尚无有效核对', revision:'修订', cursor:'外环声明水位', updated:'外环更新', checkedAt:'最近读取',
      history:'改判历史', latest:'最新录制', partial:'起点未完整录制', expand:'展开请求', collapse:'收起请求',
      inspect:'查看证据', compact:'紧凑轨迹', compactNote:'每格为一轮；数字为请求数。点击可查看该轮全部请求。',
      response:'本步响应', actions:'本步工具调用与对应返回', noResult:'尚未在后续录制中找到对应返回。',
      resultAt:'返回所在请求', parameters:'调用参数', raw:'原始请求', rawNote:'原始请求可能包含历史；它不代表本步新增内容。',
      instructions:'录制文本仅供查阅，所有命令均不执行。', noResponse:'本步未记录响应正文。',
      outside:'覆盖列表中有当前范围外请求，仍可逐个回查。', noRelations:'尚无关系记录', other:'发现与未决',
      previous:'上一请求', next:'下一请求', unavailable:'未录到或已清理', error:'录制错误', more:'展开完整内容',
      unassigned:'未分组', copy:'复制内容', copied:'已复制', copyFailed:'复制失败，可选择文本后复制',
      recorded:'已录制', noSemantic:'还没有目标或阶段判断；下面保留完整轮次入口。',
      resultEmpty:'已找到对应返回，内容为空。', resultAmbiguous:'工具调用 ID 重复，无法唯一匹配返回。', previewOnly:'仅显示预览；完整返回请查看原请求。',
      attention:'需要留意', recordedCoverage:'覆盖的已录制请求', navigation:'阅读导航', legacyPhases:'旧阶段判断与证据锚点'
    },
    en: {
      trajectory:'Semantic trace', graph:'Goals, phases & delivery', goal:'Goal', phase:'Phase', artifact:'Artifact', check:'Check',
      finding:'Finding', open:'Open question', prediction:'Prediction', deviation:'Deviation', outcomes:'Artifacts & checks',
      observer:'Observer claim', facts:'Recorded fact', detail:'Evidence & interpretation', select:'Select a phase, claim or request to inspect its source and evidence.',
      graphNote:'Lines show recorded relationships only. Columns aid reading; they do not imply chronology or fulfilled dependencies.',
      fallback:'No explicit phase coverage yet. Read recorded turns below. Evidence anchors do not define phase membership.',
      noKind:'Not recorded', coverage:'Covered requests', uncovered:'Requests outside phase coverage', turns:'Recorded turns', steps:'requests',
      coveredNote:'Coverage is explicitly assigned by the observer. One request may belong to several phases.', noCoverage:'Coverage is unspecified. Only evidence anchors are listed below.',
      empty:'No recorded requests in this scope', loading:'Loading…', failed:'Read failed', retry:'Retry', noScope:'No capture date is set; the trace cannot be loaded.',
      scope:'Scope', allScope:'No lane or session selected: showing all captures for this date.', anchors:'Evidence anchors', relations:'Recorded relationships',
      belongs_to:'Belongs to', depends_on:'Depends on', produces:'Produces', supports:'Supports', contradicts:'Contradicts',
      missingItem:'Related item is no longer in this observation', missingStep:'This request is outside the current scope. Looking up its original capture.',
      planned:'Planned', active:'Active', blocked:'Blocked', done:'Observer marked done', unknown:'Progress unknown',
      doneNote:'A progress label is not a passed acceptance check. Inspect independent checks and evidence.',
      supported:'Supported', unresolved:'Unresolved', tentative:'Tentative', retracted:'Retracted', status:'Claim status', progress:'Execution progress',
      future:'Predictions & review', noPrediction:'No predictions yet. New predictions will keep their original claims and subsequent reviews here.',
      predictionNote:'Support and counterevidence come from observer reviews. The UI does not automatically score predictions.', original:'Original claim', reviews:'Subsequent review',
      evidenceSupport:'Support recorded', evidenceCounter:'Counterevidence recorded', conflicting:'Support and counterevidence', beforeWindow:'Window not reached', pending:'Needs review',
      windowUnknown:'No complete evaluation window was recorded; expiry is unknown.', frontierMissing:'The prediction frontier is not in the available main trace; its window is unknown.',
      windowPartial:'The capture scope is incomplete; the window cannot be determined.', after:'Frontier request', horizon:'Subsequent main requests', criterion:'Evaluation criterion',
      observed:'Recorded in window', windowReached:'Window reached', originalNote:'Original claims and reviews are separate. Revisions remain available in history.',
      noReview:'No active review yet', revision:'Revision', cursor:'Observer-declared cursor', updated:'Observer updated', checkedAt:'Last loaded',
      history:'Revision history', latest:'Latest capture', partial:'Incomplete beginning', expand:'Expand requests', collapse:'Collapse requests',
      inspect:'Inspect evidence', compact:'Compact trace', compactNote:'Each cell is a turn; the number is its request count. Select one to inspect all its requests.',
      response:'Response in this step', actions:'Tool calls and matched results', noResult:'No matching result found in subsequent captures yet.',
      resultAt:'Request carrying result', parameters:'Call parameters', raw:'Original request', rawNote:'The original request may contain history; it is not the new content of this step.',
      instructions:'Recorded content is display-only. Commands are never executed.', noResponse:'No response body was recorded for this step.',
      outside:'Some covered requests are outside this scope. Each can still be looked up.', noRelations:'No recorded relationships', other:'Findings & open questions',
      previous:'Previous request', next:'Next request', unavailable:'Not recorded or already cleaned up', error:'Capture error', more:'Show full content',
      unassigned:'Ungrouped', copy:'Copy content', copied:'Copied', copyFailed:'Copy failed; select the text to copy it',
      recorded:'Recorded', noSemantic:'No goal or phase claims yet. All recorded turns remain accessible below.',
      resultEmpty:'A matching result was recorded with empty content.', resultAmbiguous:'The tool-call ID is repeated; its result cannot be matched uniquely.', previewOnly:'Preview only. Inspect the original request for the full result.',
      attention:'Needs attention', recordedCoverage:'Covered recorded requests', navigation:'Reading navigation', legacyPhases:'Legacy phase claims and evidence anchors'
    },
    ja: {
      trajectory:'意味ベースの軌跡', graph:'目標・段階・成果', goal:'目標', phase:'段階', artifact:'成果物', check:'検証',
      finding:'発見', open:'未解決', prediction:'予測', deviation:'偏差', outcomes:'成果物と検証',
      observer:'観測者の判断', facts:'記録された事実', detail:'証拠と解釈', select:'段階・判断・リクエストを選択し、原文と根拠を確認します。',
      graphNote:'線は記録済みの関係だけを示します。列の配置は時系列や依存条件の達成を意味しません。',
      fallback:'段階の範囲が未定義のため、記録されたターンを表示します。証拠の参照点は段階の構成員ではありません。',
      noKind:'未記録', coverage:'対象リクエスト', uncovered:'段階に未分類のリクエスト', turns:'記録されたターン', steps:'リクエスト',
      coveredNote:'範囲は観測者が明示します。同じリクエストが複数の段階に属する場合があります。', noCoverage:'範囲が未定義です。以下は証拠の参照点のみです。',
      empty:'この範囲に記録されたリクエストはありません', loading:'読込中…', failed:'読込失敗', retry:'再試行', noScope:'記録日が未設定のため、軌跡を読み込めません。',
      scope:'範囲', allScope:'レーン・セッション未指定：当日の全記録を表示します。', anchors:'証拠の参照点', relations:'記録済みの関係',
      belongs_to:'所属先', depends_on:'依存先', produces:'生成', supports:'支持', contradicts:'反証',
      missingItem:'関連項目は現在の観測にありません', missingStep:'現在の範囲外のリクエストです。元の記録を照会します。',
      planned:'計画中', active:'進行中', blocked:'停止中', done:'観測者が完了と記録', unknown:'進捗不明',
      doneNote:'進捗表示は検証合格を意味しません。独立した検証と証拠を確認してください。',
      supported:'根拠あり', unresolved:'未解決', tentative:'暫定', retracted:'撤回済み', status:'判断の状態', progress:'実行の進捗',
      future:'予測と照合', noPrediction:'予測はまだありません。元の判断と後続の照合をここに保持します。',
      predictionNote:'支持・反証は観測者の照合によるものです。画面は的中を自動判定しません。', original:'元の判断', reviews:'後続の照合',
      evidenceSupport:'支持あり', evidenceCounter:'反証あり', conflicting:'支持と反証が共存', beforeWindow:'検証期間中', pending:'照合待ち',
      windowUnknown:'検証期間が未記録のため、期限を判定できません。', frontierMissing:'予測の起点が利用可能な主線にないため、期間を判定できません。',
      windowPartial:'記録範囲が不完全のため、期間を判定できません。', after:'起点リクエスト', horizon:'後続の主線リクエスト数', criterion:'判定条件',
      observed:'期間内の記録数', windowReached:'検証期間終了', originalNote:'元の判断と照合は別々に保持します。変更は履歴で確認できます。',
      noReview:'有効な照合はまだありません', revision:'改訂', cursor:'観測者申告の位置', updated:'観測者の更新', checkedAt:'最終読込',
      history:'改訂履歴', latest:'最新記録', partial:'開始部分が不完全', expand:'リクエストを展開', collapse:'リクエストを閉じる',
      inspect:'証拠を確認', compact:'コンパクトな軌跡', compactNote:'各枠はターン、数字はリクエスト数です。選択すると全リクエストを確認できます。',
      response:'このステップの応答', actions:'ツール呼出しと対応する結果', noResult:'後続の記録に対応する結果がまだ見つかりません。',
      resultAt:'結果を含むリクエスト', parameters:'呼出し引数', raw:'元のリクエスト', rawNote:'元のリクエストには履歴が含まれる場合があります。このステップの新規内容とは異なります。',
      instructions:'記録は閲覧専用です。コマンドは実行しません。', noResponse:'このステップの応答本文は未記録です。',
      outside:'現在の範囲外の対象リクエストがあります。個別に照会できます。', noRelations:'関係は未記録です', other:'発見と未解決',
      previous:'前のリクエスト', next:'次のリクエスト', unavailable:'未記録または削除済み', error:'記録エラー', more:'全文を表示',
      unassigned:'未分類', copy:'内容をコピー', copied:'コピーしました', copyFailed:'コピー失敗。テキストを選択してコピーしてください',
      recorded:'記録済み', noSemantic:'目標・段階の判断はまだありません。以下から全ターンを確認できます。',
      resultEmpty:'対応する結果は記録済みですが、内容は空です。', resultAmbiguous:'ツール呼出し ID が重複し、結果を一意に照合できません。', previewOnly:'プレビューのみです。全文は元のリクエストで確認してください。',
      attention:'確認が必要', recordedCoverage:'対象の記録済みリクエスト', navigation:'閲覧ナビゲーション', legacyPhases:'従来の段階判断と証拠の参照点'
    }
  };
  Object.assign(words.zh, {
    trajectory:'工作与目标变化', observer:'观察者判断', cursor:'保存的阅读位置',
    report:'工作概况', workDone:'做了什么', workResults:'产生什么结果', workLeft:'还剩什么',
    reportNote:'以下是观察者根据录制整理的判断。展开一件事可以查看解释与证据；未记录不代表没有发生。',
    allEntries:'查看其余条目', goalFlow:'目标如何变化', noGoalFlow:'尚未记录最初理解与目标变化。现有目标条目仍可查看，不能据此补猜历史。',
    initial:'A · 最初的理解', userWords:'用户原话', understanding:'AI 当时的理解', choices:'AI 自己作出的取舍，值得复核',
    goalNow:'当前目标', goalChanges:'展开目标变化过程', actor_user:'用户调整', actor_ai:'AI 自行调整', actor_user_ai:'用户提出、AI 决定具体做法',
    inferred:'观察者推断', explicit:'录制中有明确表述', beforeGoal:'原目标', afterGoal:'改为', trigger:'为什么改变',
    parents:'由这些目标演变', achieved:'已核验达成', verification:'达成依据', goalEvidence:'查看这次变化的依据',
    relationView:'展开目标、工作与结果的关系图', workBlock:'工作块', goalCorrection:'目标历史保留；状态核验与观察者订正单独记录。'
  });
  Object.assign(words.en, {
    trajectory:'Work & goal changes',
    report:'Understand this work', workDone:'What was done', workResults:'What came out of it', workLeft:'What remains',
    reportNote:'These are observer interpretations of the recording. Open an entry for its explanation and evidence. Unrecorded does not mean it never happened.',
    allEntries:'Show remaining entries', goalFlow:'How the goal changed', noGoalFlow:'The initial understanding and goal changes have not been recorded. Existing goals remain readable; their history cannot be inferred here.',
    initial:'A · Initial understanding', userWords:'User’s words', understanding:'AI’s initial understanding', choices:'AI’s own choices — worth checking',
    goalNow:'Current goal', goalChanges:'Expand goal changes', actor_user:'Changed by user', actor_ai:'Changed by AI', actor_user_ai:'User initiated, AI shaped',
    inferred:'Observer inference', explicit:'Explicit in recording', beforeGoal:'Previous goal', afterGoal:'Changed to', trigger:'Why it changed',
    parents:'Evolved from these goals', achieved:'Verified achievement', verification:'Achievement evidence', goalEvidence:'Inspect evidence for this change',
    relationView:'Expand relationships between goals, work and results', workBlock:'Work block', goalCorrection:'Goal history is preserved. Status, verification and observer corrections are recorded separately.'
  });
  Object.assign(words.ja, {
    trajectory:'作業と目標の変化',
    report:'この作業を理解する', workDone:'何をしたか', workResults:'どんな結果が出たか', workLeft:'何が残っているか',
    reportNote:'記録をもとにした観測者の判断です。項目を開くと説明と証拠を確認できます。未記録は未発生を意味しません。',
    allEntries:'残りの項目を表示', goalFlow:'目標はどう変わったか', noGoalFlow:'最初の理解と目標の変化は未記録です。既存の目標は閲覧できますが、履歴をここで推測しません。',
    initial:'A · 最初の理解', userWords:'ユーザーの原文', understanding:'AI の最初の理解', choices:'AI 自身の選択・要確認',
    goalNow:'現在の目標', goalChanges:'目標の変化を展開', actor_user:'ユーザーが変更', actor_ai:'AI が自ら変更', actor_user_ai:'ユーザーが提案・AI が具体化',
    inferred:'観測者の推論', explicit:'記録に明示', beforeGoal:'元の目標', afterGoal:'変更後', trigger:'変更の理由',
    parents:'これらの目標から派生', achieved:'達成を検証済み', verification:'達成の根拠', goalEvidence:'この変更の証拠を確認',
    relationView:'目標・作業・結果の関係図を展開', workBlock:'作業のまとまり', goalCorrection:'目標履歴を保持し、状態・検証・観測者の訂正を別に記録します。'
  });
  Object.assign(words.zh,{flowTab:'A→G 目标流',workTab:'工作与发现',recordsTab:'原始步骤',forecastTab:'预测核对',
    flowIntro:'从最初的理解，走到现在的目标。每次转向都说明是谁改变了方向，以及为什么。',
    flowLegend:'实线连接明确的前后目标；并列站点表示分支。点击站点查看原话、取舍与证据。',
    latestGoals:'现在走到哪里',linkedWork:'这段目标下的工作与发现',noLinked:'尚未关联工作或发现。可到“工作与发现”查看未归属条目。',
    unlinked:'尚未关联到目标阶段',anchorOnly:'只记录了最初理解，尚未记录目标。',viewAnchor:'查看最初理解',goLatest:'定位当前目标',
    initialGoal:'最初形成的目标',priorGoal:'此前目标，已继续演变',completedGoal:'观察者记录已达成',moreLinked:'查看全部关联',flowMissing:'尚未建立这场对话的 A→G',flowSetup:'点击上方“复制接入说明”，让观察 AI 先读最初输入、记录理解，再沿对话维护目标变化。已有记录在其他页签保留。'});
  Object.assign(words.en,{flowTab:'A→G goal flow',workTab:'Work & findings',recordsTab:'Recorded steps',forecastTab:'Forecast reviews',
    flowIntro:'From the initial understanding to the current goal. Every turn explains who changed direction and why.',
    flowLegend:'Lines connect explicitly related goals; parallel stations show branches. Select a station for quotes, choices and evidence.',
    latestGoals:'Where things stand',linkedWork:'Work and findings for this goal',noLinked:'No work or findings linked yet. Unassigned entries remain in Work & findings.',
    unlinked:'Not linked to a goal stage',anchorOnly:'Only the initial understanding has been recorded; no goal yet.',viewAnchor:'Inspect initial understanding',goLatest:'Locate current goals',
    initialGoal:'Initially formed goal',priorGoal:'Earlier goal, since evolved',completedGoal:'Observer recorded achievement',moreLinked:'Inspect all linked entries',flowMissing:'This conversation has no A→G yet',flowSetup:'Use Copy setup notes above. Ask the observer to read the initial input, record its understanding, then maintain goal changes. Existing entries remain in the other tabs.'});
  Object.assign(words.ja,{flowTab:'A→G 目標の流れ',workTab:'作業と発見',recordsTab:'記録ステップ',forecastTab:'予測の照合',
    flowIntro:'最初の理解から現在の目標まで。誰が、なぜ方向を変えたのかを示します。',
    flowLegend:'線は明示された前後の目標を結び、並列の地点は分岐です。選択すると原文・判断・証拠を確認できます。',
    latestGoals:'現在の到達点',linkedWork:'この目標に関連する作業と発見',noLinked:'関連する作業・発見はまだありません。未分類項目は「作業と発見」で確認できます。',
    unlinked:'目標の段階に未関連',anchorOnly:'最初の理解のみ記録され、目標はまだ未記録です。',viewAnchor:'最初の理解を確認',goLatest:'現在の目標へ',
    initialGoal:'最初に形成した目標',priorGoal:'以前の目標・変更後',completedGoal:'観測者が達成と記録',moreLinked:'すべての関連項目を確認',flowMissing:'この会話の A→G はまだありません',flowSetup:'上の「接続説明をコピー」を使い、観測 AI に最初の入力と理解を記録させ、その後の目標変更を維持してください。既存項目は別タブから確認できます。'});
  const tr = k => (words[typeof LANG === 'string' ? LANG : 'zh'] || words.zh)[k] || k;
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const short = (s, n=88) => {s=String(s || '').replace(/\s+/g,' ').trim(); return s.length>n ? s.slice(0,n)+'…' : s;};
  const list = x => Array.isArray(x) ? x : [];
  const M = {state:null, key:'', trace:null, nodes:new Map(), turns:[], items:new Map(), selected:null,
    open:new Set(), folds:new Set(), records:new Map(), rawOpen:new Set(), error:'', checked:'',
    generation:0, controller:null, pending:null, signature:'', binding:null, resize:null, panel:'flow'};
  const root = () => document.getElementById('obBody');
  const items = () => list(M.state?.items);
  const live = it => it.status !== 'retracted';
  const title = it => it.title || it.text || it.id;
  const isSelected = (kind,id) => M.selected?.kind===kind && M.selected.id===id;
  const badge = (label, cls='') => '<span class="om-tag '+cls+'">'+escape(label)+'</span>';
  const button = (action,id,label,cls='',extra='') => '<button type="button" class="'+cls+'" data-om-action="'+action+'" data-om-id="'+escape(id)+'" '+extra+'>'+label+'</button>';
  const note = text => '<p class="om-muted">'+escape(text)+'</p>';
  const errorText = error => typeof error==='string' ? error : tr(error?.key || 'failed')+(error?.detail?': '+error.detail:'');
  const refs = ids => '<div class="om-evidence">'+list(ids).map(id=>button('step',id,escape(id),'om-anchor')).join('')+'</div>';
  function query(sc, capture=false) {
    const q = new URLSearchParams();
    for (const k of capture ? ['date','source'] : ['date','source','lane','session']) if(sc[k]) q.set(k,sc[k]);
    return q;
  }
  async function json(url, signal) {
    const r = await fetch(url,{cache:'no-store',signal});
    let data; try {data=await r.json();} catch (_) {throw new Error('HTTP '+r.status);}
    if(!r.ok || data.error || data.ok===false) throw new Error(data.detail || data.error || 'HTTP '+r.status);
    return data;
  }
  function adoptTrace(data) {
    M.trace=data;
    const nodes=list(data.nodes).slice().sort((a,b)=>(a.seq ?? 0)-(b.seq ?? 0));
    data.nodes=nodes;
    M.nodes=new Map(nodes.map(n=>[n.id,n]));
    const meta=new Map(list(data.turns).map(t=>[t.turn_id || t.id,t])), groups=new Map();
    for(const n of nodes) {
      const key=n.turn || ('ungrouped:'+n.lane);
      if(!groups.has(key)) groups.set(key,[]);
      groups.get(key).push(n);
    }
    M.turns=[...groups].map(([id,ns])=>{
      const t=meta.get(id) || {};
      return {id,key:id,nodes:ns,head:t.head || ns[0].id,
        user:(t.user_text || ns[0].user_text || '').replace(/<local-command-caveat>[\s\S]*?<\/local-command-caveat>/g,'').trim(),
        partial:!!t.partial,lane:ns[0].lane,ts:ns[0].ts_start || ''};
    });
  }
  function reviews(pred) {
    return items().flatMap(it=>list(it.links).filter(l=>l.to===pred.id && ['supports','contradicts'].includes(l.type))
      .map(l=>({it,type:l.type})));
  }
  function windowOf(pred) {
    const f=pred.forecast;
    if(!f || !f.after_rid || !Number.isInteger(f.horizon_steps) || f.horizon_steps<1 || !f.criterion) return {state:'unknown',reason:'windowUnknown'};
    if(!M.trace || M.trace.truncated || M.trace.complete===false) return {state:'unknown',reason:'windowPartial'};
    const anchor=M.nodes.get(f.after_rid);
    if(!anchor || anchor.kind!=='main') return {state:'unknown',reason:'frontierMissing'};
    const lane=list(M.trace.nodes).filter(n=>n.kind==='main' && n.lane===anchor.lane);
    const i=lane.findIndex(n=>n.id===f.after_rid);
    const following=lane.slice(i+1,i+1+f.horizon_steps);
    if(anchor.missing || following.some(n=>n.missing)) return {state:'unknown',reason:'windowPartial'};
    return {state:following.length>=f.horizon_steps ? 'reached':'before',count:following.length,ids:following.map(n=>n.id)};
  }
  function predictionState(pred) {
    if(!live(pred)) return {label:'retracted',cls:''};
    const rs=reviews(pred).filter(r=>live(r.it));
    const support=rs.some(r=>r.type==='supports'), counter=rs.some(r=>r.type==='contradicts');
    if(support && counter) return {label:'conflicting',cls:'om-counter'};
    if(counter) return {label:'evidenceCounter',cls:'om-counter'};
    if(support) return {label:'evidenceSupport',cls:'om-support'};
    return {label:windowOf(pred).state==='before' ? 'beforeWindow':'pending',cls:''};
  }
  function stepHtml(n, i) {
    if(!n || !n.id) return '';
    return button('step',n.id,'<span class="om-step-number">'+(i+1)+'</span><span class="om-step-text">'+escape(short(n.label || n.summary || n.kind || n.id,120))+
      '<small>'+escape(n.id)+'</small></span>'+((n.has_error || n.has_tool_error) ? badge(tr('error'),'om-counter'):'')+
      '<span class="om-duration">'+escape(((n.total_ms || 0)/1000).toFixed(1))+'s</span>',
      'om-step'+(isSelected('step',n.id)?' is-selected':''),'aria-pressed="'+isSelected('step',n.id)+'"');
  }
  function coveredSteps(it) {
    const ids=list(it.covers);
    if(!ids.length) return note(tr('noCoverage'));
    return note(tr('coveredNote'))+(ids.some(id=>!M.nodes.has(id))?note(tr('outside')):'')+
      '<div class="om-detail-steps">'+ids.map((id,i)=>stepHtml(M.nodes.get(id) || {id,label:tr('unavailable')},i)).join('')+'</div>';
  }
  function nodeHtml(it) {
    const progress=it.progress || 'unknown';
    return '<article class="om-node om-node-'+escape(it.kind)+(isSelected('item',it.id)?' is-selected':'')+(!live(it)?' is-retracted':'')+'" data-om-node="'+escape(it.id)+'">'+
      button('item',it.id,badge(tr(it.kind))+'<strong>'+escape(short(title(it),112))+'</strong>', 'om-node-title','aria-pressed="'+isSelected('item',it.id)+'"')+
      '<div class="om-node-meta">'+badge(tr(live(it)?progress:'retracted'))+
      (list(it.covers).length ? button('coverage',it.id,escape(tr('coverage')+' '+it.covers.length),'om-count') : '')+'</div></article>';
  }
  function relationHtml(it) {
    const outgoing=list(it.links).map(l=>({from:it,to:M.items.get(l.to),id:l.to,type:l.type}));
    const incoming=items().flatMap(x=>list(x.links).filter(l=>l.to===it.id).map(l=>({from:x,to:it,id:x.id,type:l.type})));
    return [...outgoing,...incoming].map(l=>button('item',l.id,
      '<span>'+escape(short(title(l.from),70))+'</span><b>'+escape(tr(l.type))+'</b><span>'+escape(l.to?short(title(l.to),70):tr('missingItem'))+'</span>',
      'om-relation'+(!live(l.from)?' is-retracted':''))).join('') || note(tr('noRelations'));
  }
  function graphHtml() {
    const semantic=items().filter(it=>['goal','phase','artifact','check'].includes(it.kind));
    if(!semantic.length) return '<div class="om-notice" id="om-semantic">'+escape(tr('noSemantic'))+'</div>';
    const legacy=semantic.every(it=>it.kind==='phase' && !list(it.covers).length);
    const columns=[['goal',['goal']],['phase',['phase']],['outcomes',['artifact','check']]];
    const graph='<section class="om-semantic"><h2>'+escape(tr('graph'))+'</h2>'+note(tr('graphNote'))+
      '<div class="om-graph-scroll"><div class="om-graph"><svg class="om-wires" aria-hidden="true"></svg>'+columns.map(([label,kinds])=>
        '<section class="om-column"><h3>'+escape(tr(label))+'</h3>'+ (semantic.filter(it=>kinds.includes(it.kind)).map(nodeHtml).join('') || '<p class="om-empty-column">'+escape(tr('noKind'))+'</p>')+'</section>').join('')+'</div></div></section>';
    const key=legacy?'legacy-phases':'relations';
    return '<details id="om-semantic" class="om-disclosure om-legacy" data-om-fold="'+key+'"'+(M.folds.has(key)?' open':'')+'><summary>'+escape(tr(legacy?'legacyPhases':'relationView'))+' <b>'+semantic.length+'</b></summary>'+graph+'</details>';
  }
  function reportHtml() {
    const current=items().filter(live);
    const groups=[['workDone',current.filter(it=>it.kind==='phase')],
      ['workResults',current.filter(it=>['artifact','check'].includes(it.kind))],
      ['workLeft',current.filter(it=>it.kind==='open' || it.kind==='deviation' || it.progress==='blocked')]];
    const row=it=>button('item',it.id,'<strong>'+escape(title(it))+'</strong><span>'+escape(tr(it.progress || it.status || 'unknown'))+'</span>', 'om-report-row');
    return '<section class="om-report"><h2>'+escape(tr('report'))+'</h2>'+note(tr('reportNote'))+'<div class="om-report-columns">'+groups.map(([label,entries])=>
      '<section class="om-report-group"><h3>'+escape(tr(label))+' <small>'+entries.length+'</small></h3>'+
      (entries.length?entries.slice(0,3).map(row).join(''):note(tr('noKind')))+
      (entries.length>3?'<details class="om-disclosure" data-om-fold="report-'+label+'"'+(M.folds.has('report-'+label)?' open':'')+'><summary>'+escape(tr('allEntries'))+' '+(entries.length-3)+'</summary>'+entries.slice(3).map(row).join('')+'</details>':'')+'</section>').join('')+'</div></section>';
  }
  function goalEventHtml(event) {
    const current=goalEvents(event.id).filter(e=>e.kind==='status').at(-1), proof=current?current.verification:event.verification;
    return '<article class="om-goal-event om-goal-'+escape(event.actor)+'"><header>'+badge(escape(event.id))+' '+badge(tr(list(event.parent_ids).length?'actor_'+event.actor:'initialGoal'))+' '+badge(tr(event.basis))+'</header>'+
      '<dl class="om-goal-diff"><dt>'+escape(tr('beforeGoal'))+'</dt><dd><del>'+escape(event.before)+'</del></dd><dt>'+escape(tr('afterGoal'))+'</dt><dd><ins>'+escape(event.after)+'</ins></dd></dl>'+
      '<h4>'+escape(tr('trigger'))+'</h4><p class="om-prose">'+escape(event.trigger)+'</p>'+
      (list(event.parent_ids).length?note(tr('parents')+': '+event.parent_ids.join(', ')):'')+
      '<p>'+badge(tr(goalStatus(event)))+'</p>'+
      (proof?'<h4>'+escape(tr('verification'))+'</h4><p class="om-prose">'+escape(proof.text)+'</p>'+refs(proof.evidence):'')+
      '<h4>'+escape(tr('goalEvidence'))+'</h4>'+refs(event.evidence)+'</article>';
  }
  function goalFlowHtml(it, detailed=false) {
    if(!detailed) return flowDiagramHtml(it);
    const flow=it?.goal_flow;
    if(!flow) return detailed?'': '<section class="om-goal-flow"><h2>'+escape(tr('goalFlow'))+'</h2>'+note(tr('noGoalFlow'))+'</section>';
    const events=list(flow.iterations), used=new Set(events.flatMap(e=>list(e.parent_ids))), heads=events.filter(e=>!used.has(e.id));
    const anchor=flow.anchor || {}, key='goal-flow:'+it.id;
    const anchorHtml='<article class="om-goal-anchor"><h3>'+escape(tr('initial'))+'</h3>'+badge(tr(anchor.basis))+
      '<div class="om-goal-pair"><section><h4>'+escape(tr('userWords'))+'</h4><blockquote>'+escape(anchor.user_text)+'</blockquote></section><section><h4>'+escape(tr('understanding'))+'</h4><p class="om-prose">'+escape(anchor.understanding)+'</p></section></div>'+
      (list(anchor.choices).length?'<h4>'+escape(tr('choices'))+'</h4><ul>'+anchor.choices.map(c=>'<li>'+escape(c)+'</li>').join('')+'</ul>':'')+refs(anchor.evidence)+'</article>';
    return '<section class="om-goal-flow"><h2>'+escape(tr('goalFlow'))+'</h2>'+note(tr('goalCorrection'))+
      '<div class="om-goal-current"><h3>'+escape(tr('goalNow'))+'</h3>'+(heads.length?heads.map(e=>'<p>'+badge(e.id)+' '+badge(tr(e.status || 'active'))+' '+badge(tr(e.basis))+'</p><p class="om-prose">'+escape(e.after)+'</p>').join(''):note(tr('noKind')))+'</div>'+
      '<details class="om-disclosure" data-om-fold="'+escape(key)+'"'+(detailed || M.folds.has(key)?' open':'')+'><summary>'+escape(tr('goalChanges'))+' <b>'+events.length+'</b></summary><div class="om-goal-track">'+anchorHtml+events.map(goalEventHtml).join('')+'</div></details></section>';
  }
  const flowItem = () => items().find(it=>live(it) && it.goal_flow);
  const associated = id => items().filter(it=>live(it) && it.goal_iteration===id);
  for(const [lang,values] of Object.entries({zh:{closeDetail:'关闭详情',changesLane:'调整与原因',goalsLane:'目标如何演变',findingsLane:'发现与核验',statusEvent:'状态与核验记录',correctionEvent:'观察者订正',superseded:'已被后续目标替换',flowHint:'点击目标或发现查看证据；可横向滚动画布。'},en:{closeDetail:'Close details',changesLane:'Changes & reasons',goalsLane:'Evolution of goals',findingsLane:'Findings & checks',statusEvent:'Status & verification',correctionEvent:'Observer correction',superseded:'Superseded',flowHint:'Select a goal or finding for evidence. Scroll the canvas horizontally.'},ja:{closeDetail:'詳細を閉じる',changesLane:'変更と理由',goalsLane:'目標の変遷',findingsLane:'発見と検証',statusEvent:'状態と検証の記録',correctionEvent:'観測者の訂正',superseded:'後続目標に置換',flowHint:'目標や発見を選択して証拠を確認。図は横スクロールできます。'}})) Object.assign(words[lang],values);
  const goalEvents = id => list(flowItem()?.goal_flow?.events).filter(e=>e.target===id);
  function goalStatus(event) {
    const status=goalEvents(event.id).filter(e=>e.kind==='status').at(-1)?.status || event.status || 'active';
    if(status==='achieved') return 'completedGoal';
    if(status==='active' && list(flowItem()?.goal_flow?.iterations).some(e=>list(e.parent_ids).includes(event.id))) return 'priorGoal';
    return status;
  }
  function flowLayers(events) {
    const depth=new Map(), rows=[];
    for(const event of events) {
      const level=Math.max(0,...list(event.parent_ids).map(id=>(depth.get(id) ?? -1)+1));
      depth.set(event.id,level);(rows[level] ||= []).push(event);
    }
    return rows;
  }
  const AG_RIGHT=230, AG_RIGHT_OPEN=430, AG_DETAIL_H=360;
  /** Which goal row shows the detail in place, or null when the floating panel is used.

      Only the flow tab reads a third lane, so only it expands in place; the other
      tabs keep the floating aside. 260908: the aside was fixed to the right edge,
      which is exactly where the findings lane sits, so opening a goal hid the very
      findings and checks that goal is judged by. */
  function inlineTarget() {
    if(M.panel!=='flow' || !M.detailOpen) return null;
    const flow=flowItem()?.goal_flow, s=M.selected; if(!flow || !s) return null;
    const ids=new Set(list(flow.iterations).map(e=>e.id));
    if(s.kind==='goal-event' && ids.has(s.id)) return s.id;
    if(s.kind==='item') {const g=M.items.get(s.id)?.goal_iteration; return g && ids.has(g)?g:'@anchor';}
    return '@anchor';
  }
  function flowDiagramHtml(it) {
    const f=it?.goal_flow;
    if(!f) return '<section class="ag-empty"><h2>'+escape(tr('flowMissing'))+'</h2><p>'+escape(tr('noGoalFlow'))+'</p><p>'+escape(tr('flowSetup'))+'</p>'+button('panel','work',escape(tr('workTab')),'om-action')+'</section>';
    const events=list(f.iterations),parents=new Set(events.flatMap(e=>list(e.parent_ids))),heads=events.filter(e=>!parents.has(e.id));
    const rows=flowLayers(events), lanes=Math.max(1,...rows.map(r=>r.length)), centerWidth=lanes===1?320:lanes*252+20;
    const inline=inlineTarget(), rightWidth=inline?AG_RIGHT_OPEN:AG_RIGHT, rightX=326+centerWidth, width=rightX+rightWidth+24;
    const detailBox=top=>'<aside class="ag-inline-detail" aria-label="'+escape(tr('detail'))+'" style="left:'+rightX+'px;top:'+top+'px;width:'+rightWidth+'px;height:'+AG_DETAIL_H+'px">'+
      button('close-detail','',escape(tr('closeDetail'))+' ×','ag-close')+'<h2>'+escape(tr('detail'))+'</h2>'+detailHtml()+'</aside>';
    let y=inline==='@anchor'?Math.max(172,48+AG_DETAIL_H+16):172, detailTop=inline==='@anchor'?48:null;
    const stations=rows.map(row=>{
      const top=y, hasDetail=row.some(e=>e.id===inline);
      if(hasDetail) detailTop=top;
      y+=Math.max(hasDetail?AG_DETAIL_H+16:0,112,row.length*66+12);
      const columns=row.length===1?320:252;
      return row.map((e,i)=>{
        const x=290+(centerWidth-row.length*columns-(row.length-1)*12)/2+i*(columns+12);
        const work=associated(e.id), observations=work.filter(x=>['finding','check','deviation','open'].includes(x.kind));
        const content='<span class="ag-label"><b>'+escape(e.id)+'</b><span>'+escape(tr(goalStatus(e)))+'</span></span><strong>'+escape(short(e.after,100))+'</strong><span class="ag-count">'+escape(tr(e.basis))+(work.length?' · '+work.length+' '+escape(tr('workTab')):'')+'</span>';
        const change=button('goal-event',e.id,'<span class="ag-who">'+escape(tr(list(e.parent_ids).length?'actor_'+e.actor:'initialGoal'))+'</span><span>'+escape(short(e.trigger,row.length>1?55:100))+'</span>','ag-change ag-'+escape(e.actor),'style="left:24px;top:'+(top+i*66)+'px;width:230px"');
        // The open detail already lists this goal's work, so the lane is not doubled up.
        const finding=hasDetail?'':observations.slice(0,row.length>1?1:2).map((o,j)=>button('item',o.id,'<span>'+escape(tr(o.kind))+'</span><strong>'+escape(short(title(o),row.length>1?55:65))+'</strong>','ag-observation ag-'+escape(o.kind),'style="left:'+rightX+'px;top:'+(top+i*66+j*52)+'px;width:230px"')).join('');
        return change+'<article class="ag-station ag-'+escape(e.actor)+(isSelected('goal-event',e.id)?' is-selected':'')+'" data-ag-node="'+escape(e.id)+'" style="left:'+x+'px;top:'+top+'px;width:'+columns+'px">'+button('goal-event',e.id,content,'ag-goal-button','aria-pressed="'+isSelected('goal-event',e.id)+'"')+'</article>'+finding;
      }).join('');
    }).join('');
    return '<section class="ag-flow"><div class="ag-heading"><p>'+escape(tr('flowIntro'))+'</p>'+button('goal-latest',heads.at(-1)?.id || '',escape(tr('goLatest')),'om-action')+'</div><nav class="ag-lane-nav">'+[['left','changesLane'],['center','goalsLane'],['right','findingsLane']].map(([id,key])=>button('flow-lane',id,escape(tr(key)),'om-action')).join('')+'</nav>'+
      '<div class="ag-canvas-scroll" tabindex="0" aria-label="'+escape(tr('flowTab'))+'"><div class="ag-canvas" style="width:'+width+'px;height:'+(y+18)+'px">'+
      '<div class="ag-lane-label" style="left:24px">'+escape(tr('changesLane'))+'</div><div class="ag-lane-label" style="left:290px">'+escape(tr('goalsLane'))+'</div><div class="ag-lane-label" style="left:'+rightX+'px">'+escape(tr('findingsLane'))+'</div><svg class="ag-wires" aria-hidden="true"></svg>'+
      '<article class="ag-anchor" data-ag-node="@anchor" style="left:'+(290+(centerWidth-320)/2)+'px;top:48px;width:320px">'+button('goal-anchor','@anchor','<span class="ag-label"><b>'+escape(tr('initial'))+'</b></span><strong>'+escape(short(f.anchor.user_text,75))+'</strong><span class="ag-anchor-reading">'+escape(f.anchor.understanding)+'</span>','ag-goal-button','aria-label="'+escape(tr('viewAnchor'))+'"')+'</article>'+stations+
      (detailTop==null?'':detailBox(detailTop))+'</div></div><p class="ag-footnote">'+escape(tr('flowHint'))+'</p></section>';
  }
  function goalJournal(id) {
    return goalEvents(id).map(e=>'<section class="om-review"><h4>'+escape(tr(e.kind==='correction'?'correctionEvent':'statusEvent'))+(e.status?' · '+escape(tr(e.status==='achieved'?'completedGoal':e.status)):'')+'</h4><p class="om-prose">'+escape(e.text)+'</p>'+refs(e.evidence)+(e.verification?'<p class="om-prose">'+escape(e.verification.text)+'</p>'+refs(e.verification.evidence):'')+'</section>').join('');
  }
  function goalDetail(id) {
    const flow=flowItem()?.goal_flow;if(!flow) return note(tr('noGoalFlow'));
    if(id==='@anchor') {
      const a=flow.anchor;
      return badge(tr('observer'))+'<h3>'+escape(tr('initial'))+'</h3>'+badge(tr(a.basis))+'<h4>'+escape(tr('userWords'))+'</h4><p class="om-prose">'+escape(a.user_text)+'</p><h4>'+escape(tr('understanding'))+'</h4><p class="om-prose">'+escape(a.understanding)+'</p>'+
        '<h4>'+escape(tr('choices'))+'</h4>'+(list(a.choices).length?'<ul>'+a.choices.map(c=>'<li>'+escape(c)+'</li>').join('')+'</ul>':note(tr('noKind')))+refs(a.evidence)+goalJournal(id);
    }
    const event=list(flow.iterations).find(e=>e.id===id);if(!event) return note(tr('missingItem'));
    const work=associated(id);
    return badge(tr('observer'))+goalEventHtml(event)+goalJournal(id)+'<h3>'+escape(tr('linkedWork'))+'</h3>'+
      (work.length?work.map(x=>button('item',x.id,badge(tr(x.kind))+escape(title(x)),'om-finding')).join(''):note(tr('noLinked')));
  }
  function drawGoalFlow() {
    const canvas=root()?.querySelector('.ag-canvas'),svg=canvas?.querySelector('.ag-wires');if(!svg || !canvas.offsetWidth) return;
    const box=canvas.getBoundingClientRect(),nodes=new Map([...canvas.querySelectorAll('[data-ag-node]')].map(n=>[n.dataset.agNode,n]));
    svg.setAttribute('viewBox','0 0 '+canvas.offsetWidth+' '+canvas.offsetHeight);
    const paths=[];
    for(const e of list(flowItem()?.goal_flow?.iterations)) for(const p of list(e.parent_ids).length?e.parent_ids:['@anchor']) {
      const a=nodes.get(p)?.getBoundingClientRect(),b=nodes.get(e.id)?.getBoundingClientRect();if(!a || !b) continue;
      const x1=a.left+a.width/2-box.left,y1=a.bottom-box.top,x2=b.left+b.width/2-box.left,y2=b.top-box.top,mid=(y1+y2)/2;
      paths.push('<path class="ag-wire" d="M '+x1+' '+y1+' C '+x1+' '+mid+' '+x2+' '+mid+' '+x2+' '+y2+'" marker-end="url(#ag-arrow)" data-ag-from="'+escape(p)+'" data-ag-to="'+escape(e.id)+'"/>');
    }
    svg.innerHTML='<defs><marker id="ag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10z"/></marker></defs>'+paths.join('');
  }
  function overviewHtml() {
    const current=items().filter(live), phases=current.filter(it=>it.kind==='phase');
    const covered=new Set(phases.flatMap(it=>list(it.covers)).filter(id=>M.nodes.has(id)));
    const opens=current.filter(it=>it.kind==='open');
    const stats=[['phase',phases.length,'om-semantic'],['recordedCoverage',covered.size,covered.size?'om-coverage':'om-compact'],
      ['open',opens.length,opens.length?'om-findings':'om-future'],['prediction',current.filter(it=>it.kind==='prediction').length,'om-future']];
    return '<nav class="om-stat-nav" aria-label="'+escape(tr('navigation'))+'">'+stats.map(([key,count,id])=>
      button('section',id,'<strong>'+count+'</strong><span>'+escape(tr(key))+'</span>','om-stat-link')).join('')+'</nav>';
  }
  function turnHtml(t,i) {
    const open=M.open.has('turn:'+t.key);
    return '<section class="om-turn" data-om-turn="'+escape(t.key)+'"><div class="om-turn-header">'+
      button('toggle-turn',t.key,'<span aria-hidden="true">'+(open?'▾':'▸')+'</span><strong>'+escape(short(t.user || t.lane || tr('unassigned'),115))+'</strong>'+badge(t.nodes.length+' '+tr('steps')),
        'om-turn-toggle','aria-expanded="'+open+'"')+button('turn',t.key,escape(tr('inspect')),'om-turn-inspect')+'</div>'+
      '<div class="om-turn-meta">'+escape((i+1)+' · '+t.ts.slice(11,19))+(t.partial?' · '+escape(tr('partial')):'')+'</div>'+
      (open?'<div class="om-steps">'+t.nodes.map(stepHtml).join('')+'</div>':'')+'</section>';
  }
  function windowHtml(pred, detailed=false) {
    const f=pred.forecast,w=windowOf(pred);
    if(!f) return note(tr('windowUnknown'));
    return '<div class="om-window"><div>'+escape(tr('after'))+' '+button('step',f.after_rid,escape(f.after_rid),'om-anchor')+'</div>'+
      '<div>'+escape(tr('horizon'))+' <strong>'+escape(f.horizon_steps)+'</strong></div>'+
      (w.state==='unknown'?note(tr(w.reason)):'<p>'+escape(tr('observed')+' '+w.count+' / '+f.horizon_steps)+' · '+escape(tr(w.state==='before'?'beforeWindow':'windowReached'))+'</p>')+
      (detailed?'<h4>'+escape(tr('criterion'))+'</h4><p class="om-prose">'+escape(f.criterion)+'</p>'+refs(w.ids):'')+'</div>';
  }
  function predictionHtml(pred) {
    const st=predictionState(pred), rs=reviews(pred);
    return '<article class="om-prediction'+(!live(pred)?' is-retracted':'')+'">'+
      '<div class="om-prediction-head">'+badge(tr('original'))+badge(tr(st.label),st.cls)+'</div>'+
      button('item',pred.id,'<strong>'+escape(short(title(pred),200))+'</strong>','om-prediction-title')+
      windowHtml(pred)+ (rs.length?'<div class="om-review-strip">'+rs.map(r=>button('item',r.it.id,
        badge(tr(r.type),r.type==='contradicts'?'om-counter':'om-support')+escape(short(title(r.it),100))+(!live(r.it)?badge(tr('retracted')):''),
        'om-review-link'+(!live(r.it)?' is-retracted':''))).join('')+'</div>':note(tr('noReview')))+'</article>';
  }
  function paint() {
    const r=root(); if(!r || !M.state) return;
    const lang=typeof LANG==='string'?LANG:'zh';
    const signature=JSON.stringify([M.state,M.trace,lang,M.error,[...M.open],M.selected,[...M.rawOpen],M.panel,M.detailOpen]);
    const clock=r.querySelector('[data-om-clock]'); if(clock) clock.textContent=tr('checkedAt')+' '+M.checked;
    if(signature===M.signature) return;
    M.signature=signature;
    const active=r.contains(document.activeElement)?document.activeElement:null;
    const focus=active?.dataset.omAction ? {action:active.dataset.omAction,id:active.dataset.omId}:null;
    const detailScroll=r.querySelector('.om-detail')?.scrollTop || 0;
    const flowScroll=r.querySelector('.ag-canvas-scroll')?.scrollTop || 0;
    const priorFlow=r.querySelector('.ag-canvas-scroll');
    const flowLeft=priorFlow?.offsetWidth?priorFlow.scrollLeft:M.flowLeft;
    M.flowLeft=flowLeft;
    const sc=M.state.scope || {}, phases=items().filter(it=>it.kind==='phase'), preds=items().filter(it=>it.kind==='prediction');
    const hasCoverage=phases.some(it=>live(it) && list(it.covers).length);
    const covered=new Set(phases.filter(live).flatMap(it=>list(it.covers)));
    const uncovered=[...M.nodes.values()].filter(n=>!covered.has(n.id));
    const other=items().filter(it=>!['goal','phase','artifact','check','prediction'].includes(it.kind));
    r.innerHTML='<div class="om-shell'+(inlineTarget()?' ag-inline':'')+'"><main class="om-main"><header class="om-header"><div><h2>'+escape(tr('trajectory'))+'</h2><p class="om-muted">'+escape([sc.date,sc.source,sc.lane || sc.session].filter(Boolean).join(' · '))+'</p></div><span class="om-muted" data-om-clock>'+escape(tr('checkedAt')+' '+M.checked)+'</span></header>'+
      (M.error?'<div class="om-error" role="alert">'+escape(errorText(M.error))+' '+button('retry','',escape(tr('retry')),'om-action')+'</div>':'')+
      (!sc.lane && !sc.session?note(tr('allScope')):'')+'<nav class="ag-tabs" aria-label="'+escape(tr('navigation'))+'">'+[['flow','flowTab'],['work','workTab'],['records','recordsTab'],['forecast','forecastTab']].map(([id,key])=>button('panel',id,escape(tr(key)),'ag-tab','aria-pressed="'+(M.panel===id)+'"')).join('')+'</nav>'+
      '<div class="ag-panel"'+(M.panel!=='flow'?' hidden':'')+'>'+goalFlowHtml(flowItem())+'</div>'+
      '<div class="ag-panel"'+(M.panel!=='work'?' hidden':'')+'>'+reportHtml()+graphHtml()+'<h3>'+escape(tr('unlinked'))+'</h3>'+items().filter(x=>live(x) && x.kind!=='goal' && !x.goal_iteration).map(x=>button('item',x.id,badge(tr(x.kind))+escape(title(x)),'om-finding')).join('')+'</div>'+
      '<div class="ag-panel"'+(M.panel!=='records'?' hidden':'')+'>'+
      (M.trace?'<section id="om-compact" class="om-compact"><h3>'+escape(tr('compact'))+'</h3><div class="om-ribbon">'+M.turns.map((t,i)=>
        button('turn',t.key,'<span>'+escape(i+1)+'</span><b>'+escape(t.nodes.length)+'</b>','om-bead','title="'+escape(short(t.user || t.lane,160))+'" aria-label="'+escape(tr('turns')+' '+(i+1)+', '+t.nodes.length+' '+tr('steps'))+'"')).join('')+'</div>'+note(tr('compactNote'))+'</section>':note(tr('loading')))+
      (!hasCoverage?'<div class="om-notice">'+escape(tr('fallback'))+'</div><section class="om-turns">'+M.turns.map(turnHtml).join('')+'</section>':
        '<details id="om-coverage" class="om-disclosure" data-om-fold="coverage"'+(M.folds.has('coverage')?' open':'')+'><summary>'+escape(tr('recordedCoverage'))+' <b>'+[...M.nodes.keys()].filter(id=>covered.has(id)).length+'</b></summary><div class="om-steps">'+[...M.nodes.values()].filter(n=>covered.has(n.id)).map(stepHtml).join('')+'</div></details>'+
        '<details class="om-disclosure" data-om-fold="uncovered"'+(M.folds.has('uncovered')?' open':'')+'><summary>'+escape(tr('uncovered'))+' <b>'+uncovered.length+'</b></summary><div class="om-steps">'+uncovered.map(stepHtml).join('')+'</div></details>')+
      (M.trace && !M.nodes.size?note(tr('empty')):'')+'</div><div class="ag-panel"'+(M.panel!=='work'?' hidden':'')+'>'+
      (other.length?'<details id="om-findings" class="om-disclosure" data-om-fold="findings"'+(M.folds.has('findings')?' open':'')+'><summary>'+escape(tr('other'))+' <b>'+other.length+'</b></summary>'+other.map(it=>button('item',it.id,badge(tr(it.kind))+escape(short(title(it),180)),
        'om-finding'+(!live(it)?' is-retracted':''))).join('')+'</details>':'')+
      '</div><section id="om-future" class="ag-panel om-future"'+(M.panel!=='forecast'?' hidden':'')+'><h2>'+escape(tr('future'))+'</h2>'+note(tr('predictionNote'))+(preds.length?preds.map(predictionHtml).join(''):note(tr('noPrediction')))+'</section></main>'+
      '<aside class="om-detail"'+(!M.detailOpen?' hidden':'')+' aria-label="'+escape(tr('detail'))+'">'+button('close-detail','',escape(tr('closeDetail'))+' ×','ag-close')+'<h2>'+escape(tr('detail'))+'</h2><div id="om-detail-body"></div></aside></div>';
    paintDetail();
    r.querySelector('.om-detail').scrollTop=detailScroll;
    const flowViewport=r.querySelector('.ag-canvas-scroll');if(flowViewport) {flowViewport.scrollTop=flowScroll;flowViewport.scrollLeft=flowLeft ?? Math.max(0,(flowViewport.scrollWidth-flowViewport.clientWidth)/2);}
    if(focus) [...r.querySelectorAll('[data-om-action]')].find(e=>e.dataset.omAction===focus.action && e.dataset.omId===focus.id)?.focus({preventScroll:true});
    bind(); requestAnimationFrame(drawRelations);
  }
  function fold(key,label,value,open=false) {
    if(value==null || value==='') return '';
    const s=typeof value==='string'?value:JSON.stringify(value,null,2);
    return '<details class="om-raw" data-om-fold="'+escape(key)+'"'+(M.folds.has(key)||open?' open':'')+'><summary>'+escape(label)+' <small>'+s.length.toLocaleString()+'</small></summary><pre class="om-copy-block">'+escape(s)+'</pre>'+button('copy',key,escape(tr('copy')),'om-action')+'</details>';
  }
  function recordHtml(rid,rec) {
    const blocks=list(rec.response?.content_blocks);
    return '<h4>'+escape(tr('response'))+'</h4>'+(blocks.length?blocks.map((b,i)=>fold(rid+':response:'+i,b.name || b.type,b.type==='tool_use'?b.input:b.text || b.thinking || b)).join(''):note(tr('noResponse')))+
      note(tr('rawNote'))+fold(rid+':request',tr('raw'),rec.request?.body);
  }
  function stepDetail(rid) {
    const n=M.nodes.get(rid), cache=M.records.get(rid), raw=M.rawOpen.has(rid), ns=[...M.nodes.values()];
    const index=ns.findIndex(x=>x.id===rid);
    return badge(tr('facts'))+'<h3>'+escape(n?.label || rid)+'</h3><p class="om-id">'+escape(rid)+'</p>'+
      (!n?note(tr('missingStep')):'')+(n?.missing?note(tr('unavailable')):'')+
      '<div class="om-step-nav">'+(index>0?button('step',ns[index-1].id,escape(tr('previous')),'om-action'):'')+
      (index>=0 && index<ns.length-1?button('step',ns[index+1].id,escape(tr('next')),'om-action'):'')+'</div>'+
      note([n?.ts_start,n?.model,n?.kind].filter(Boolean).join(' · '))+
      (n?.has_error?'<p class="om-error">'+escape(tr('error'))+'</p>':'')+
      (n?.text_preview?'<p class="om-prose">'+escape(n.text_preview)+'</p>':'')+
      (list(n?.actions).length?'<h4>'+escape(tr('actions'))+'</h4>'+n.actions.map(a=>'<div class="om-result'+(a.result_error?' om-result-error':'')+'"><strong>'+escape(a.label || a.name)+'</strong><p class="om-id">'+escape(a.tool_call_id || '')+'</p><pre class="om-copy-block">'+escape(a.result_ambiguous?tr('resultAmbiguous'):a.result_available?(a.result_preview || tr('resultEmpty')):tr('noResult'))+'</pre>'+
        (a.result_truncated?note(tr('previewOnly')):'')+
        (a.result_record_id?button('step',a.result_record_id,escape(tr('resultAt')+' '+a.result_record_id),'om-anchor'):'')+'</div>').join(''):'')+
      note(tr('instructions'))+
      (raw ? (!cache || cache.loading?note(tr('loading')):cache.error?'<div class="om-error" role="alert">'+escape(errorText(cache.error))+' '+button('retry-step',rid,escape(tr('retry')),'om-action')+'</div>':recordHtml(rid,cache.data)):
        button('raw',rid,escape(tr('parameters')+' / '+tr('response')+' / '+tr('raw')),'om-action'));
  }
  function itemDetail(it) {
    const isPred=it.kind==='prediction';
    const st=isPred?predictionState(it):null;
    return badge(tr('observer'))+badge(tr(it.kind))+(st?badge(tr(st.label),st.cls):'')+
      '<h3>'+escape(it.title || (isPred?tr('original'):tr(it.kind)))+'</h3><p class="om-prose">'+escape(it.text)+'</p>'+
      '<dl class="om-meta"><dt>'+escape(tr('status'))+'</dt><dd>'+escape(tr(it.status || 'tentative'))+'</dd>'+
      (it.progress?'<dt>'+escape(tr('progress'))+'</dt><dd>'+escape(tr(it.progress))+'</dd>':'')+'</dl>'+
      (it.progress==='done'?'<div class="om-notice">'+escape(tr('doneNote'))+'</div>':'')+
      (it.reason?'<p class="om-prose">'+escape(it.reason)+'</p>':'')+
      (isPred?windowHtml(it,true)+note(tr('originalNote')):'')+
      (it.goal_flow?goalFlowHtml(it,true):'')+
      '<h4>'+escape(tr('anchors'))+'</h4>'+refs(it.evidence)+
      (it.kind==='phase' || list(it.covers).length?'<h4>'+escape(tr('coverage'))+'</h4>'+coveredSteps(it):'')+
      '<h4>'+escape(tr('relations'))+'</h4>'+relationHtml(it)+
      (isPred?'<h4>'+escape(tr('reviews'))+'</h4>'+ (reviews(it).map(r=>'<div class="om-review'+(!live(r.it)?' is-retracted':'')+'">'+badge(tr(r.type),r.type==='contradicts'?'om-counter':'om-support')+
        (!live(r.it)?badge(tr('retracted')):'')+button('item',r.it.id,escape(title(r.it)),'om-review-link')+refs(r.it.evidence)+'</div>').join('') || note(tr('noReview'))):'')+
      list(it.history).map((h,i)=>fold(it.id+':history:'+i,tr('history')+' · '+(h.at || h.updated || ''),h)).join('');
  }
  /** The same body serves the floating panel and the flow tab's in-place column. */
  function detailHtml() {
    const s=M.selected;
    if(!s) return note(tr('select'))+'<dl class="om-meta">'+['revision','cursor','updated'].map(k=>'<dt>'+escape(tr(k))+'</dt><dd>'+escape(M.state[k])+'</dd>').join('')+'</dl>';
    if(s.kind==='goal-event' || s.kind==='goal-anchor') return goalDetail(s.id);
    if(s.kind==='item') return M.items.has(s.id)?itemDetail(M.items.get(s.id)):note(tr('missingItem'));
    if(s.kind==='turn') {
      const t=M.turns.find(x=>x.key===s.id);
      return t?badge(tr('facts'))+'<h3>'+escape(t.user || t.lane || tr('unassigned'))+'</h3>'+badge(t.nodes.length+' '+tr('steps'))+(t.partial?badge(tr('partial')):'')+'<div class="om-detail-steps">'+t.nodes.map(stepHtml).join('')+'</div>':note(tr('unavailable'));
    }
    return stepDetail(s.id);
  }
  function paintDetail() {
    const el=document.getElementById('om-detail-body'); if(!el) return;
    el.innerHTML=detailHtml();
    requestAnimationFrame(drawRelations);
  }
  function drawRelations() {
    drawGoalFlow();
    const graph=root()?.querySelector('.om-graph'), svg=graph?.querySelector('.om-wires'); if(!svg) return;
    const bounds=graph.getBoundingClientRect(); if(!bounds.width) return;
    const nodes=new Map([...graph.querySelectorAll('[data-om-node]')].map(el=>[el.dataset.omNode,el]));
    const width=graph.offsetWidth,height=graph.offsetHeight, sx=width/bounds.width,sy=height/bounds.height;
    svg.setAttribute('viewBox','0 0 '+width+' '+height);
    const paths=[];
    for(const it of items()) for(const l of list(it.links)) {
      const from=nodes.get(it.id),to=nodes.get(l.to); if(!from || !to || from===to) continue;
      const a=from.getBoundingClientRect(),b=to.getBoundingClientRect();
      const same=Math.abs(a.left-b.left)<2,forward=a.left<b.left;
      const x1=((same || forward?a.right:a.left)-bounds.left)*sx, y1=(a.top+a.height/2-bounds.top)*sy;
      const x2=((same?b.right:forward?b.left:b.right)-bounds.left)*sx, y2=(b.top+b.height/2-bounds.top)*sy;
      const bend=same?x1+18:(x1+x2)/2;
      const selected=M.selected?.kind==='item' && [it.id,l.to].includes(M.selected.id);
      paths.push('<path class="om-wire'+(selected?' is-selected':'')+(!live(it)?' is-retracted':'')+'" d="M '+x1+' '+y1+' C '+bend+' '+y1+', '+bend+' '+y2+', '+x2+' '+y2+'" marker-end="url(#om-arrow)"><title>'+escape(title(it)+' '+tr(l.type)+' '+(M.items.get(l.to)?title(M.items.get(l.to)):l.to))+'</title></path>');
    }
    svg.innerHTML='<defs><marker id="om-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path class="om-arrow" d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>'+paths.join('');
  }
  async function loadRecord(rid, retry=false) {
    M.rawOpen.add(rid); const old=M.records.get(rid);
    if(old && !retry) {paintDetail();return;}
    const generation=M.generation,signal=M.controller?.signal;
    M.records.set(rid,{loading:true}); paintDetail();
    try {
      const data=await json('/api/captures/'+encodeURIComponent(rid)+'?'+query(M.state.scope || {},true),signal);
      if(generation!==M.generation) return;
      M.records.set(rid,{data});
    } catch(e) {
      if(generation!==M.generation || e.name==='AbortError') return;
      M.records.set(rid,{error:{key:'failed',detail:e.message}});
    }
    if(isSelected('step',rid)) paintDetail();
  }
  function revealDetail() {
    const opening=!M.detailOpen;M.detailOpen=true;paint();
    if(opening) root()?.querySelector('.ag-close')?.focus({preventScroll:true});
  }
  function chooseStep(rid) {
    M.selected={kind:'step',id:rid}; paint(); revealDetail();
    if(!M.nodes.has(rid)) loadRecord(rid);
  }
  function bind() {
    const r=root(); if(!r || M.binding===r) return;
    M.binding=r;
    r.addEventListener('keydown',event=>{
      if(event.key==='Escape' && M.detailOpen) {event.preventDefault();r.querySelector('.ag-close')?.click();}
    });
    r.addEventListener('click',event=>{
      const b=event.target.closest('[data-om-action]'); if(!b || !r.contains(b)) return;
      const id=b.dataset.omId,action=b.dataset.omAction;
      if(action==='close-detail') {M.detailOpen=false;paint();root()?.querySelector('[data-ag-node="'+CSS.escape(M.selected?.id || '@anchor')+'"] button')?.focus({preventScroll:true});return;}
      if(action==='flow-lane') {const canvas=r.querySelector('.ag-canvas-scroll');if(canvas) canvas.scrollLeft=id==='left'?0:id==='right'?canvas.scrollWidth:(canvas.scrollWidth-canvas.clientWidth)/2;return;}
      if(action==='panel') {M.panel=id;M.detailOpen=false;paint();return;}
      if(action==='goal-event' || action==='goal-anchor' || action==='goal-latest') {
        M.selected={kind:action==='goal-anchor'?'goal-anchor':'goal-event',id:id || '@anchor'};paint();
        if(action==='goal-latest') root().querySelector('[data-ag-node="'+CSS.escape(id)+'"]')?.scrollIntoView({block:'nearest'});
        else revealDetail();return;
      }
      if(action==='section') {
        const target=document.getElementById(id);
        if(target?.tagName==='DETAILS') {target.open=true;M.folds.add(target.dataset.omFold);}
        target?.scrollIntoView({block:'start'});requestAnimationFrame(drawRelations);return;
      }
      if(action==='retry') {refresh(); return;}
      if(action==='step') {chooseStep(id);return;}
      if(action==='raw' || action==='retry-step') {loadRecord(id,action==='retry-step'); return;}
      if(action==='copy') {
        const text=b.parentElement.querySelector('.om-copy-block')?.textContent || '';
        Promise.resolve().then(()=>typeof copyText==='function'?copyText(text):navigator.clipboard.writeText(text))
          .then(ok=>{b.textContent=tr(ok===false?'copyFailed':'copied');},()=>{b.textContent=tr('copyFailed');});return;
      }
      if(action==='item' || action==='coverage') M.selected={kind:'item',id};
      if(action==='turn') M.selected={kind:'turn',id};
      if(action==='toggle-turn') {const key='turn:'+id;if(M.open.has(key)) M.open.delete(key);else M.open.add(key);}
      paint();
      if(['item','coverage','turn'].includes(action)) revealDetail();
      if(action==='coverage' && !window.matchMedia('(max-width:1100px)').matches) document.getElementById('om-detail-body')?.scrollIntoView({block:'nearest'});
    });
    r.addEventListener('toggle',event=>{
      const el=event.target;if(!el.dataset?.omFold) return;
      if(el.open) M.folds.add(el.dataset.omFold); else M.folds.delete(el.dataset.omFold);
      if(el.open) requestAnimationFrame(drawRelations);
    },true);
    if(typeof ResizeObserver!=='undefined') {M.resize=new ResizeObserver(()=>requestAnimationFrame(drawRelations));M.resize.observe(r);}
  }
  function clear(message='') {
    M.controller?.abort(); M.generation++;M.controller=null;M.pending=null;M.state=null;M.key='';M.trace=null;
    M.nodes.clear();M.items.clear();M.turns=[];M.selected=null;M.open.clear();M.folds.clear();M.records.clear();M.rawOpen.clear();M.signature='';M.error='';M.panel='flow';M.detailOpen=false;M.flowLeft=undefined;
    const r=root();if(r) r.innerHTML=message?'<p class="om-error" role="alert">'+escape(message)+'</p>':'';
  }
  function render(state) {
    if(!state) {clear();return Promise.resolve();}
    const key=JSON.stringify([state.id,state.scope]);
    if(key!==M.key) {clear();M.key=key;M.controller=new AbortController();}
    M.state=state;M.items=new Map(list(state.items).map(it=>[it.id,it]));
    if(!M.selected && flowItem()) M.selected={kind:'goal-anchor',id:'@anchor'};
    paint();
    return refresh();
  }
  function refresh() {
    if(!M.state) return Promise.resolve();
    if(M.pending) return M.pending;
    if(!M.state.scope?.date) {M.error={key:'noScope'};paint();return Promise.resolve();}
    const generation=M.generation,signal=M.controller.signal;
    const promise=(async()=>{
      try {
        const data=await json('/api/observations/trace?'+query(M.state.scope),signal);
        if(generation!==M.generation) return;
        adoptTrace(data);M.error='';M.checked=new Date().toLocaleTimeString();paint();
      } catch(e) {
        if(generation!==M.generation || e.name==='AbortError') return;
        M.error={key:'failed',detail:e.message};paint();
      } finally {if(generation===M.generation) M.pending=null;}
    })();
    M.pending=promise;return promise;
  }
  window.ObserveMap={render,refresh,clear};
})();
