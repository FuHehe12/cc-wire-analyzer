/* 前端冒烟测试（260827）——把"人真去点一遍"固化下来。
 *
 * 为什么需要它：改前端的三道闸门（node --check / check_refs / check_i18n_js）**全是读代码**，
 * 没有一道跑代码。于是"语法没错、一跑就死"这一整类问题只能等人去点——两天内它出现了三次：
 *   · renderDiff 读了一个被删掉的参数 `into` → 提示词对比整个功能报错，界面只剩一行红字；
 *   · var(--x) 指向一个谁都没定义的 token → 21 处颜色静默失效，两周多没人发现；
 *   · data-i18n 指向一个三张表都没有的键 → 设置页把键名原样印给用户。
 * 三次都是人肉发现的。这个脚本做的就是那件人肉的事。
 *
 * 用法（改前端后跑，和 contrast_probe.js 一起）：
 *   1. `uv run python src/app.py`，浏览器打开它
 *   2. 把本文件整个粘进 DevTools 控制台
 *   3. `await ccwaSmoke()`
 *
 * 判据：**控制台出现任何一条 error / warn 即失败**，外加未捕获异常与未处理的 Promise 拒绝。
 * 敢把判据定得这么死，是因为实测**界面代码里 console.error/warn/log 出现 0 次**——
 * 没有"正常噪声"需要豁免，任何一条输出都是外来的。
 * ⚠️ 反过来说：**将来谁往界面里加 console 输出，就是在给这个闸门开洞**。真要加，
 *    先想清楚它凭什么该被豁免，并把豁免写进下面的 IGNORE。
 *
 * 边界——只做只读动作：切视图、点列表行、选贴纸、展开卡片、开抽屉、切外观。
 *   **绝不碰**删除 / 归档 / 清理 / 「AI 归纳」：那些要么改数据、要么花钱。
 *   冒烟测试的价值在于能随手跑一百遍；一旦它有副作用，就没人敢跑了。
 *
 * 没有数据时 SKIP 不算失败：新机器上没有录制、没有快照是常态，
 * 一个会因为环境空而变红的检查等于没有检查。
 */
(function () {
  /* 已知可豁免的控制台噪声（正则）。**默认空**——今天一条都不需要。
     往这里加东西之前先问：它凭什么不算问题？ */
  const IGNORE = [];

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const $ = id => document.getElementById(id);

  function collector() {
    const hits = [];
    const push = (kind, text) => {
      text = String(text || '').slice(0, 300);
      if (IGNORE.some(re => re.test(text))) return;
      hits.push({ kind, text });
    };
    const onErr = e => push('uncaught', e.message + ' @' + (e.filename || '').split('/').pop() + ':' + e.lineno);
    const onRej = e => push('rejection', (e.reason && (e.reason.message || e.reason)) || 'unknown');
    const origErr = console.error, origWarn = console.warn;
    console.error = function (...a) { push('console.error', a.join(' ')); return origErr.apply(this, a); };
    console.warn = function (...a) { push('console.warn', a.join(' ')); return origWarn.apply(this, a); };
    window.addEventListener('error', onErr);
    window.addEventListener('unhandledrejection', onRej);
    return {
      hits,
      stop() {
        console.error = origErr; console.warn = origWarn;
        window.removeEventListener('error', onErr);
        window.removeEventListener('unhandledrejection', onRej);
      },
    };
  }

  /* 每一步：跑一个只读动作，返回 'ok' / 'skip:原因'。抛异常本身也算失败。 */
  const STEPS = [
    ['捕获列表', async () => {
      showView('captures'); await sleep(1500);
      /* 默认落在今天，而今天很可能还没录到东西。**自己挑一天有数据的**——
         否则在大多数机器上这一步和"捕获详情"永远 SKIP，等于少测两个视图，
         而它们恰恰是最常用的两个。 */
      if (!document.querySelector('.cap-row')) {
        const days = (S.dates || []).slice().sort().reverse();
        for (const d of days) {
          S.date = d; await fetchCaptures(d); await sleep(1200);
          if (document.querySelector('.cap-row')) return 'ok:回落到 ' + d;
        }
        return 'skip:一天录制都没有';
      }
      return 'ok';
    }],
    ['捕获详情', async () => {
      const row = document.querySelector('.cap-row');
      if (!row) return 'skip:没有可点开的行';
      row.click(); await sleep(2500);
      return 'ok';
    }],
    ['时序 DAG', async () => { showView('dag'); await sleep(4000); return 'ok'; }],
    ['分析·提示词对比', async () => {
      showView('analyze'); await sleep(600);
      anShow('diff'); await sleep(800);
      const p = (AN.items || []).filter(x => x.kind === 'prompt');
      if (p.length < 2) return 'skip:提示词快照不足两张';
      anPick('p', p[0].sid); await sleep(300);
      anPick('p', p[1].sid); await sleep(3500);
      return 'ok';
    }],
    ['分析·录制（含抽屉/子代理/树视图）', async () => {
      anShow('rec'); await sleep(700);
      const c = (AN.items || []).filter(x => x.kind === 'capture');
      if (!c.length) return 'skip:没有录制快照';
      anPick('c', c[0].sid); await sleep(6000);
      document.querySelectorAll('.an-agent').forEach(d => { d.open = true; });
      await sleep(600);
      const step = document.querySelector('.an-step[data-step]');
      if (step) { step.click(); await sleep(2000); }
      anStepView('tree'); await sleep(1200);
      anStepView('list'); await sleep(800);
      return 'ok';
    }],
    ['设置', async () => { showView('settings'); await sleep(1800); return 'ok'; }],
    ['三套外观切换', async () => {
      const root = document.documentElement;
      const was = root.getAttribute('data-theme');
      for (const t of ['dark', 'classic', 'light']) { root.setAttribute('data-theme', t); await sleep(400); }
      if (was) root.setAttribute('data-theme', was); else root.removeAttribute('data-theme');
      return 'ok';
    }],
    ['三语切换', async () => {
      if (typeof setLang !== 'function') return 'skip:没有 setLang';
      const was = (typeof S === 'object' && S.lang) || 'zh';
      for (const l of ['zh', 'en', 'ja']) { setLang(l); await sleep(500); }
      setLang(was); await sleep(500);
      return 'ok';
    }],
  ];

  async function smoke() {
    const col = collector();
    const report = [];
    for (const [name, fn] of STEPS) {
      const before = col.hits.length;
      let outcome;
      try { outcome = await fn(); }
      catch (e) { outcome = 'threw:' + e.message; }
      const newHits = col.hits.slice(before);
      report.push({ name, outcome, hits: newHits });
    }
    col.stop();

    const failed = report.filter(r => r.hits.length || r.outcome.startsWith('threw'));
    console.log('%c[冒烟] ' + (failed.length ? failed.length + '/' + report.length + ' 步有问题'
                                             : report.length + ' 步全过 ✓'),
                'font-weight:bold;color:' + (failed.length ? '#F87171' : '#4ADE80'));
    report.forEach(r => {
      const tag = r.hits.length || r.outcome.startsWith('threw') ? 'FAIL'
                : r.outcome.startsWith('skip') ? 'SKIP' : ' OK ';
      console.log('  [%s] %s%s', tag, r.name,
                  r.outcome.startsWith('skip') ? '  （' + r.outcome.slice(5) + '）' : '');
      if (r.outcome.startsWith('threw')) console.log('        动作本身抛错：' + r.outcome.slice(6));
      r.hits.forEach(h => console.log('        %s: %s', h.kind, h.text));
    });
    return { ok: !failed.length, report };
  }

  /* 自检：故意制造一次未捕获异常，确认这个闸门真的会响。
     一个"从来不响的检查"和"没有检查"在效果上完全一样。 */
  smoke.selfTest = async function () {
    const col = collector();
    setTimeout(() => { throw new Error('ccwa-smoke-selftest'); }, 0);
    await sleep(300);
    col.stop();
    const caught = col.hits.some(h => /ccwa-smoke-selftest/.test(h.text));
    console.log(caught ? '%c[自检] 闸门会响 ✓' : '%c[自检] 闸门没响 —— 它挡不住任何东西 ✗',
                'font-weight:bold;color:' + (caught ? '#4ADE80' : '#F87171'));
    return caught;
  };

  window.ccwaSmoke = smoke;
  console.log('ccwaSmoke 已就绪：await ccwaSmoke()   自检：await ccwaSmoke.selfTest()');
})();
