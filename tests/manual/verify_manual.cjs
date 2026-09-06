const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'dist/manual'),qa=path.join(root,'build/manual-qa');
(async()=>{
 fs.mkdirSync(qa,{recursive:true});
 const isolated=fs.mkdtempSync(path.join(qa,'standalone-'));
 const file=path.join(isolated,'产品说明书.html');fs.copyFileSync(path.join(out,'index.html'),file);
 assert.deepEqual(fs.readdirSync(isolated),['产品说明书.html']);
 const b=await chromium.launch({headless:true}),p=await b.newPage({acceptDownloads:true});
 const url=pathToFileURL(file).href,external=[],errors=[];
 p.on('pageerror',e=>errors.push(e.message));
 await p.route('**/*',r=>{if(r.request().url()===url)return r.continue();external.push(r.request().url());return r.abort();});
 await p.goto(url);assert.equal(await p.locator('script[src]').count(),0);
 const collaborationKey='AI_三类文档与项目协作.md';
 await p.locator('#collaboration').click();
 assert.equal(await p.locator('#bookSelect').inputValue(),collaborationKey);
 assert.equal(await p.evaluate(k=>BOOK.documents[k].text,collaborationKey),fs.readFileSync(path.join(root,'docs/product/reading',collaborationKey),'utf8').replace(/\r\n/g,'\n'));
 for(const width of [1440,390,320]){
  await p.setViewportSize({width,height:960});
  assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert(await p.locator('#bookDialog').evaluate(d=>d.scrollWidth<=d.clientWidth));
  await p.screenshot({path:path.join(qa,`book-collaboration-${width}.png`)});
 }
 await p.keyboard.press('Escape');
 assert.equal(await p.evaluate(()=>document.activeElement.id),'collaboration');
 await p.goto(url+'#doc='+encodeURIComponent(collaborationKey));
 assert.equal(await p.locator('#bookSelect').inputValue(),collaborationKey);
 assert(await p.locator('#bookDialog').isVisible());
 await p.keyboard.press('Escape');
 await p.locator('#collaboration').click();assert(await p.locator('#bookDialog').isVisible());
 await p.keyboard.press('Escape');
 await p.locator('#manual').click();
 assert.equal(await p.locator('#manual').getAttribute('aria-pressed'),'true');
 assert.equal(await p.locator('#tree details[id^="manual-"]').count(),9);
 for(const width of [1440,390,320]){
  await p.setViewportSize({width,height:960});
  await p.locator('#search').fill('manual-analyze');
  await p.locator('#manual-analyze').scrollIntoViewIfNeeded();
  assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await p.screenshot({path:path.join(qa,`book-manual-${width}.png`)});
 }
 await p.locator('#reset').click();await p.locator('#evidence').click();
 for(const img of await p.locator('.evidence-shot img').all()){
  await img.scrollIntoViewIfNeeded();await img.evaluate(i=>i.decode());assert(await img.evaluate(i=>i.naturalWidth>0));
 }
 await p.locator('.reference').click();
 const keys=await p.locator('#bookSelect option').evaluateAll(os=>os.map(o=>o.value));
 assert.deepEqual(keys.sort(),['AI_三类文档与项目协作.md','AI_内容整合与阅读路径.md','AI_术语与范围.md','AI_阅读说明.md','第三方声明.md','API契约.md','开发约定.md','架构总览.md','界面导览.md','报文解读.md'].sort());
 const model=await p.locator('#data').textContent();
 assert(!model.includes('验收条件：'));
 assert(!/D:[\\/]|C:[\\/]Users[\\/]|AI_历史决策复核|AI_存量矛盾裁定/.test(model),'model must exclude internal paths and obsolete adjudication');
 for(const [folder,key] of [['development','开发约定.md'],['development','架构总览.md'],['usage','API契约.md'],['usage','界面导览.md'],['usage','报文解读.md']]){
  assert.equal(await p.evaluate(k=>BOOK.documents[k].text,key),fs.readFileSync(path.join(root,'docs',folder,key),'utf8'),key+' source parity');
 }
 assert.equal(await p.locator('a').filter({hasText:'项目官网'}).count(),0);
 for(const key of keys){await p.locator('#bookSelect').selectOption(key);assert((await p.locator('#bookText').innerText()).length>20);}
 assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await p.screenshot({path:path.join(qa,'book-archive-320.png')});
 await p.keyboard.press('Escape');assert(!(await p.locator('#bookDialog').isVisible()));
 await p.locator('#reset').click();await p.locator('#search').fill('cap-C-04');
 await p.locator('#cap-C-04 [data-basis]').click();assert(await p.locator('#cap-C-04-basis').isVisible());
 for(const a of await p.locator('.downloads a[download]').all()){
  const name=await a.getAttribute('download');const event=p.waitForEvent('download');await a.click();const dl=await event;
  const temp=await dl.path();assert(fs.readFileSync(temp).equals(fs.readFileSync(path.join(out,name))),name);
 }
 assert.deepEqual(external,[]);assert.deepEqual(errors,[]);await b.close();
 fs.writeFileSync(path.join(qa,'book-qa.json'),JSON.stringify({standalone:true,isolated,bytes:fs.statSync(file).size,manuals:9,documents:keys.length,widths:[1440,390,320],externalRequests:external,errors,checks:['single copied HTML','collaboration entry and source parity','collaboration deep link and reopen','dialog fit and focus restoration','inline scripts','all images decode','manual filter','source archive','Escape close','basis toggle','export byte equality']},null,2));
 console.log('PASS: standalone HTML, 9 manuals, public images and reference documents, downloads; zero external requests');
})().catch(e=>{console.error(e);process.exit(1)});
