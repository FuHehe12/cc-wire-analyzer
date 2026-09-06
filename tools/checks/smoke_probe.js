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
    ['分析·录制（含抽屉/子代理/八视图）', async () => {
      anShow('rec'); await sleep(700);
      const c = (AN.items || []).filter(x => x.kind === 'capture');
      if (!c.length) return 'skip:没有录制快照';
      anPick('c', c[0].sid); await sleep(6000);
      document.querySelectorAll('.an-agent').forEach(d => { d.open = true; });
      await sleep(600);
      const step = document.querySelector('.an-step[data-step]');
      if (step) { step.click(); await sleep(2000); }
      /* 八视图档：iframe 嵌入 + 高度桥。**光看没报错不够**——桥断了页面照样安静，
         只是那块变成一条 620px 的默认高度。所以这里断言父页真收到了子页报的高度。 */
      anStepView('tree'); await sleep(6000);
      const fr = document.querySelector('.an-traj iframe');
      if (!fr) return 'fail:八视图档没渲染出 iframe';
      const doc = fr.contentDocument;
      if (!doc) return 'fail:读不到八视图页';
      if (doc.documentElement.dataset.theme !== currentTheme())
        return 'fail:八视图外观没跟上主界面';
      /* 当日数据已归档的录制出不了图，后端给的是同款外观的错误页——那是**对的行为**，
         不是失败。但**只测到错误页等于没测八视图**：往下换一条录制再试，
         最多试三条（新机器上可能确实一条都出不了图，那才 skip）。 */
      let d2 = doc, tried = 1;
      while (d2 && d2.getElementById('trajerr') && tried < Math.min(c.length, 3)) {
        anPick('c', c[tried].sid); await sleep(5000);
        anStepView('tree'); await sleep(6000);
        const f2 = document.querySelector('.an-traj iframe');
        d2 = f2 && f2.contentDocument; tried++;
      }
      if (!d2) return 'fail:换录制后读不到八视图页';
      if (d2.getElementById('trajerr')) return 'skip:试过的录制当日数据都已归档';
      if (!d2.getElementById('nav')) return 'fail:八视图页既没导航也没错误页（后端多半回了裸 JSON）';
      const fr2 = document.querySelector('.an-traj iframe');
      if (parseInt(fr2.style.height || '0', 10) < 421) return 'fail:高度桥没生效（iframe 高度还是默认值）';
      d2.querySelectorAll('.tab').forEach((t, i) => { if (i === 7) t.click(); });
      await sleep(1500);
      anStepView('list'); await sleep(800);
      return 'ok';
    }],
    ['设置', async () => { showView('settings'); await sleep(1800); return 'ok'; }],
    ['三套外观切换', async () => {
      /* 走 setTheme 而不是直接改 data-theme：换肤要连带重渲的东西（泳道色板、
         八视图子页的取值内联色）都挂在它上面，绕过它等于没测那一半。 */
      const was = currentTheme();
      for (const t of ['dark', 'classic', 'light']) { setTheme(t, false); await sleep(500); }
      setTheme(was, false);
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
