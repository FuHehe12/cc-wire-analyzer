const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const http = require('node:http');
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const root = path.resolve(__dirname, '..');
const qa = path.resolve(process.env.CCWA_SITE_QA || path.join(root, '.site-qa'));
const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.png': 'image/png', '.svg': 'image/svg+xml', '.ttf': 'font/ttf' };
const widths = [1600, 2560, 390, 320];
const sections = ['read', 'flow', 'compare', 'reading-assistance', 'agent', 'start'];
let server, browser;

(async () => {
  fs.mkdirSync(qa, { recursive: true });
  server = http.createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (!pathname.startsWith('/cc-wire-analyzer/')) return res.writeHead(404).end();
    let file = path.resolve(root, 'site', pathname.slice('/cc-wire-analyzer/'.length) || 'index.html');
    if (!file.startsWith(path.join(root, 'site') + path.sep)) return res.writeHead(403).end();
    try {
      if (fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
      res.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
      res.end(fs.readFileSync(file));
    } catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}/cc-wire-analyzer/`;
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));

  for (const locale of ['en', 'zh']) {
    const url = base + (locale === 'zh' ? 'zh/' : '');
    await page.goto(url);
    await page.evaluate(() => document.fonts.ready);
    for (const img of await page.locator('img[src]').all()) {
      await img.evaluate(i => { i.loading = 'eager'; return i.decode(); });
    }
    assert.equal(await page.locator('a[download]').count(), 0, 'manual is read online');
    for (const id of sections) assert(await page.locator(`#${id}`).isVisible(), `${locale} ${id}`);
    for (const width of widths) {
      await page.setViewportSize({ width, height: 1000 });
      const overflow = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth, elements: [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1).slice(0, 8).map(e => e.tagName + '.' + e.className) }));
      if (overflow.scroll > overflow.width) errors.push(`${locale} overflow at ${width}: ${JSON.stringify(overflow)}`);
      await page.screenshot({ path: path.join(qa, `${locale}-${width}.png`), fullPage: true });
      if (locale === 'zh' && [1600, 390].includes(width)) {
        await page.evaluate(() => scrollTo(0, 0));
        await page.screenshot({ path: path.join(qa, `zh-${width}-hero.png`) });
      }
    }

    const zooms = page.locator('[data-zoom]');
    assert.equal(await zooms.count(), 4);
    for (let i = 0; i < 4; i++) {
      const link = zooms.nth(i);
      const expected = await link.evaluate(a => a.href);
      await link.click();
      const viewer = page.locator('#image-viewer');
      await viewer.waitFor({ state: 'visible' });
      assert.equal(await viewer.locator('img').evaluate(i => i.src), expected);
      await viewer.locator('img').evaluate(i => i.decode());
      await page.keyboard.press('Escape');
      await viewer.waitFor({ state: 'hidden' });
      assert(await link.evaluate(a => a === document.activeElement), 'lightbox returns focus');
    }

    const copy = page.locator('.copy-button');
    const example = await page.locator('#agent-request').innerText();
    await copy.click();
    await page.waitForFunction(() => document.querySelector('.copy-button').textContent === document.querySelector('.copy-button').dataset.done);
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), example);
    await page.evaluate(() => Object.defineProperty(navigator.clipboard, 'writeText', {
      configurable: true, value: async () => { throw new Error('test denied clipboard'); }
    }));
    await copy.click();
    await page.waitForFunction(() => document.querySelector('.copy-button').textContent === document.querySelector('.copy-button').dataset.fallback);
    assert.equal(await page.evaluate(() => getSelection().toString()), example, 'clipboard fallback selects complete prompt');

    const faqs = page.locator('details');
    assert((await faqs.count()) > 0);
    for (let i = 0; i < await faqs.count(); i++) {
      const faq = faqs.nth(i);
      await faq.locator('summary').click();
      assert(await faq.evaluate(d => d.open), 'FAQ expands');
      assert((await faq.innerText()).length > (await faq.locator('summary').innerText()).length);
      await faq.locator('summary').click();
      assert(!(await faq.evaluate(d => d.open)), 'FAQ collapses');
    }
    await page.locator('a[href$="manual.html#manual-agent"]').click();
    await page.locator('#manual-agent > .content').waitFor({ state: 'visible' });
    assert(page.url().startsWith(base + 'manual.html#'), 'manual opens on this site');
    await page.goBack();
    await page.locator('.lang-link').click();
    assert.equal(await page.locator('html').getAttribute('lang'), locale === 'zh' ? 'en' : 'zh-CN');
  }

  const plain = await browser.newPage({ javaScriptEnabled: false });
  for (const locale of ['en', 'zh']) {
    await plain.goto(base + (locale === 'zh' ? 'zh/' : ''));
    for (const id of sections) assert(await plain.locator(`#${id}`).isVisible(), `no JS ${locale} ${id}`);
    assert.equal(await plain.locator('a[download]').count(), 0);
    assert.equal(await plain.locator('[data-zoom]').count(), 4);
    for (const link of await plain.locator('[data-zoom]').all()) {
      const href = await link.evaluate(a => a.href);
      const response = await context.request.get(href);
      assert(response.ok() && response.headers()['content-type'].startsWith('image/png'), 'no-JS image fallback URL');
    }
    await plain.locator('[data-zoom]').first().click();
    assert(plain.url().endsWith('.png'), 'no-JS screenshot opens original image');
  }
  await plain.close();
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(qa, 'report.json'), JSON.stringify({ languages: 2, widths, screenshots: 4, errors, checks: ['six visible capability sections', 'images decode', 'no horizontal overflow', 'lightbox and Escape focus', 'clipboard success and selected-text fallback', 'FAQ expand/collapse', 'online manual deep link', 'no HTML download', 'language switch', 'no-JS content and image fallback'] }, null, 2));
  console.log('PASS: bilingual responsive site, lightbox, clipboard, FAQ, online manual and no-JS reading');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server) server.close();
});
