/* 界面走查探针（260827）——把"人肉看一眼"换成"量一遍"。
 *
 * 为什么需要它：260826-27 十天内，同一族问题修了三次——白板贴纸整族在浅色下是暗的、
 * 裸 `.chip` 在浅色下是白字白底、`.chip.agent` 在两套浅色下卡在 AA 线下面。
 * 三次都是**人真去点**才发现的，而 `doc_audit` 的 token 检查问的是"这个 token 在三套外观
 * 里都有取值吗"，答不了"它压在那块底色上读不读得出来"。这两个问题差着一整个层叠计算。
 *
 * 用法（改配色 / 改版式后必跑）：
 *   1. `uv run python src/app.py`，浏览器打开它
 *   2. 把本文件整个粘进 DevTools 控制台
 *   3. `await ccwaProbe()` —— 它会自己遍历三套外观并打印报告
 *      只想扫当前这一屏：`ccwaProbe.scan()`
 *   4. 每个视图都要过一遍（捕获 / 详情 / 时序 / 提示词对比 / 录制分析 / 设置），
 *      **展开态也要**（抽屉打开、子代理卡展开、树视图）——它只看得见此刻渲染出来的东西
 *
 * 判据：
 *   · 对比度 —— WCAG AA：小字 4.5:1、大字（≥24px 或 ≥18.66px 加粗）3:1
 *   · 字号   —— 同一"行级容器"内字号跨度 ≥1.3 倍，且最大的那个**不是标题元素**
 *              （标题本来就该更大；事故是某个没设字号的子元素继承到了卡片默认的 16px）
 *
 * 两个坑，都是实测踩出来的，改这个文件前先读：
 *   ① **必须先关掉过渡**。切外观时颜色是渐变的，采样太早读到的是过渡中间色——
 *      第一版每次只等 180ms，扫出 14 条，关掉过渡后只剩 9 条，差点去修 5 个不存在的问题。
 *   ② **背景要逐层合成**。半透明底叠在卡片上，名义底色和眼睛看到的底色能差 1.5:1；
 *      只读元素自己的 background-color 会把大量真问题算成达标。
 */
(function () {
  const NEED_SMALL = 4.5, NEED_LARGE = 3, SPAN = 1.3;
  const ROW_SEL = [
    '.an-step', '.an-toolrun', '.an-agent-head', '.an-turnhead', '.cap-row', '.arc-row',
    '.an-ana-sum', '.an-drawer-head', '.thead', '.tdid', '.an-chat-head', '.an-steps-head',
    '.dag-node', '.an-diff-head', '.an-pick-row', '.srow',
  ].join(',');

  const srgb = v => (v /= 255) <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  const lum = c => 0.2126 * srgb(c[0]) + 0.7152 * srgb(c[1]) + 0.0722 * srgb(c[2]);
  const nums = s => (s.match(/[\d.]+/g) || []).map(Number);
  const over = (fg, bg) => { const a = fg[3] === undefined ? 1 : fg[3];
    return [0, 1, 2].map(i => fg[i] * a + bg[i] * (1 - a)); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = c => '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase();
  const sig = el => el.tagName.toLowerCase() +
    (typeof el.className === 'string' && el.className ? '.' + el.className.trim().replace(/\s+/g, '.') : '');

  /* 逐层向上合成实际底色：半透明层要还原，不然算的是名义底色而不是眼睛看到的底色 */
  function effBg(el) {
    const stack = [];
    for (let n = el; n; n = n.parentElement) {
      const c = nums(getComputedStyle(n).backgroundColor);
      if (c.length >= 3) stack.push(c);
    }
    let bg = [255, 255, 255];
    for (let i = stack.length - 1; i >= 0; i--) {
      const c = stack[i];
      if (c.length === 4 && c[3] === 0) continue;
      bg = over(c, bg);
    }
    return bg;
  }

  function noAnim(on) {
    let st = document.getElementById('__ccwa_noanim');
    if (on && !st) {
      st = document.createElement('style');
      st.id = '__ccwa_noanim';
      st.textContent = '*,*::before,*::after{transition:none!important;animation:none!important;}';
      document.head.appendChild(st);
    } else if (!on && st) { st.remove(); }
  }

  function scan() {
    const contrast = {}, groups = new Map();
    document.querySelectorAll('body *').forEach(el => {
      if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;

      const cs = getComputedStyle(el);
      const fgA = nums(cs.color);
      if (fgA[3] === 0) return;
      const bg = effBg(el);
      const fg = fgA.length === 4 ? over(fgA, bg) : fgA.slice(0, 3);
      const px = parseFloat(cs.fontSize);
      const bold = parseInt(cs.fontWeight, 10) >= 700;
      const need = (px >= 24 || (px >= 18.66 && bold)) ? NEED_LARGE : NEED_SMALL;
      const cr = ratio(fg, bg);
      if (cr < need) {
        const k = sig(el);
        if (!contrast[k] || contrast[k].ratio > cr)
          contrast[k] = { ratio: +cr.toFixed(2), need, px, fg: hex(fg), bg: hex(bg),
                          text: el.textContent.trim().slice(0, 24) };
      }
      const row = el.closest(ROW_SEL);
      if (row) { if (!groups.has(row)) groups.set(row, []); groups.get(row).push(el); }
    });

    const sizes = {};
    groups.forEach((els, row) => {
      if (els.length < 2) return;
      const arr = els.map(e => ({ px: parseFloat(getComputedStyle(e).fontSize),
                                  s: sig(e), tag: e.tagName.toLowerCase(),
                                  t: e.textContent.trim().slice(0, 16) }));
      const min = Math.min(...arr.map(a => a.px)), max = Math.max(...arr.map(a => a.px));
      if (max / min < SPAN) return;
      // 标题元素本来就该更大；事故是"没设字号的元素继承到了卡片默认字号"
      const biggest = arr.filter(a => a.px === max && !/^(b|strong|h[1-6])$/.test(a.tag));
      if (!biggest.length) return;
      const k = sig(row);
      if (!sizes[k] || sizes[k].span < max / min)
        sizes[k] = { span: +(max / min).toFixed(2), min, max,
                     who: biggest.map(b => b.s + '「' + b.t + '」') };
    });
    return { contrast, sizes };
  }

  async function probe(themes) {
    themes = themes || ['dark', 'classic', 'light'];
    const root = document.documentElement;
    const before = root.getAttribute('data-theme');
    noAnim(true);
    const all = { contrast: {}, sizes: {} };
    for (const th of themes) {
      root.setAttribute('data-theme', th);
      await new Promise(r => setTimeout(r, 400));   // 关了过渡也留一帧给重排
      const r = scan();
      Object.entries(r.contrast).forEach(([k, v]) => {
        const key = k + '  [' + th + ']';
        if (!all.contrast[key] || all.contrast[key].ratio > v.ratio) all.contrast[key] = v;
      });
      Object.entries(r.sizes).forEach(([k, v]) => {
        const key = k + '  [' + th + ']';
        if (!all.sizes[key] || all.sizes[key].span < v.span) all.sizes[key] = v;
      });
    }
    if (before) root.setAttribute('data-theme', before); else root.removeAttribute('data-theme');
    noAnim(false);

    const c = Object.entries(all.contrast).sort((a, b) => a[1].ratio - b[1].ratio);
    const s = Object.entries(all.sizes).sort((a, b) => b[1].span - a[1].span);
    console.log('%c[对比度] ' + (c.length ? c.length + ' 处不达标' : '全部达标 ✓'),
                'font-weight:bold;color:' + (c.length ? '#F87171' : '#4ADE80'));
    c.forEach(([k, v]) => console.log('  %s  %s/%s  %spx  fg=%s bg=%s  「%s」',
                                      k, v.ratio, v.need, v.px, v.fg, v.bg, v.text));
    console.log('%c[字号] ' + (s.length ? s.length + ' 处行内跨度异常' : '全部一致 ✓'),
                'font-weight:bold;color:' + (s.length ? '#FBBF24' : '#4ADE80'));
    s.forEach(([k, v]) => console.log('  %s  %s×（%s→%s）  %s', k, v.span, v.min, v.max, v.who.join(' ')));
    return all;
  }

  probe.scan = scan;
  window.ccwaProbe = probe;
  console.log('ccwaProbe 已就绪：await ccwaProbe()  —— 每个视图、每个展开态都要各跑一次');
})();
