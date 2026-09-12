// Current A→G manual probe. Requires an isolated fixture with tasks and current.
// Run manually against loopback only; this script reads data and does not write observations.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('playwright');
const base=process.env.CCWA_TEST_URL,oid=process.env.CCWA_OBSERVATION_ID;
if(!base || !oid || !['127.0.0.1','localhost'].includes(new URL(base).hostname)) throw Error('Set loopback CCWA_TEST_URL and CCWA_OBSERVATION_ID');
const out=process.env.CCWA_QA_OUTPUT || 'local/artifacts/observe-goal-browser';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:process.env.CCWA_BROWSER || 'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const response=await (await page.request.get(base+'/api/observations?id='+oid)).json();
 const state=response.state || response;
 const goal=state.items.find(i=>i.goal_flow && i.status!=='retracted');assert(goal);
 const flow=goal.goal_flow;
 assert(flow.current && flow.tasks?.length>=2,'Use a current fixture with two tasks, current understanding and situation');
 const last=flow.iterations.find(i=>i.id===flow.current.goal_ids.at(-1));assert(last);
 await page.goto(base);await page.getByRole('tab',{name:'实时分析',exact:true}).click();
 await page.getByLabel('观测',{exact:true}).selectOption(oid);
 await page.locator('.ag-canvas').waitFor();
 assert.equal(await page.locator('.ag-tabs').count(),0,'removed work/records/forecast tabs are not part of current view');
 const reading=page.locator('.ag-flow > .ag-reading');
 // 比对去掉空白后的正文：页面在 ①②③ 前补换行、按行拆段（260912 反馈「1、2 这种混在一起」），
 // 加的只是空白，一个字都不会改——守住的仍是「页面不篡改观察者写的内容」。
 const flat=s=>s.replace(/\s+/g,'');
 assert(flat(await reading.innerText()).includes(flat(flow.current.understanding)));
 assert(flat(await reading.innerText()).includes(flat(flow.current.situation)));
 if(flow.current.carryover) assert(flat(await reading.innerText()).includes(flat(flow.current.carryover)));
 assert.equal(await page.locator('.ag-anchor').count(),1,'one fixed starting point');
 const collapsed=page.locator('[data-om-action="task-toggle"][aria-expanded="false"]');
 for(let n=0;await collapsed.count();n++){
  assert(n<flow.tasks.length,'task expansion must make progress');await collapsed.first().click();
 }
 assert.equal(await page.locator('.ag-station').count(),flow.iterations.length);
 for(const task of flow.tasks) assert((await page.locator('.ag-task-heading').allTextContents()).some(t=>t.includes(task.title)));
 // 260909 用户口径：G 是整体目标，T 是 G 的内环。换一件交付（turn）不产生新的 G。
 const declared=flow.iterations.filter(i=>i.change==='goal').length;
 assert.equal(await page.locator('.ag-goal-heading').count(),declared+1,'one band per overall goal: the initial one plus each declared change');
 assert((await page.locator('.ag-station .ag-label b').allTextContents()).every(l=>/^T\d+·\d+$/.test(l)),'expanded cards are numbered inside their own task, not as goals');
 for(const key of ['A','G','T']) assert((await page.locator('.ag-glossary').innerText()).includes(key),'the page explains '+key+' in place');
 await page.waitForFunction(()=>document.querySelectorAll('.ag-wire').length>0);
 const expectedEdges=flow.iterations.flatMap(e=>((e.parent_ids || []).length?e.parent_ids:['@anchor']).map(p=>[p,e.id]));
 const edges=await page.locator('.ag-wire').evaluateAll(ns=>ns.map(n=>[n.dataset.agFrom,n.dataset.agTo]));
 assert.deepEqual(edges,expectedEdges,'expanded task history keeps explicit parent links');
 await page.screenshot({path:path.join(out,'overview.png'),fullPage:true});
 // A 卡片里的那个：首个 G 段没有显式的目标变化可指，它的段头也挂 goal-anchor（260909 起如此），
 // 光按 action 选会同时选中两个。
 await page.locator('.ag-anchor [data-om-action="goal-anchor"]').click();
 assert((await page.locator('.ag-inline-body').innerText()).includes(flow.anchor.user_text));
 assert.equal(await page.locator('.om-detail').isVisible(),false,'goal details use the inline third column');
 await page.locator('.ag-station [data-om-id="'+last.id+'"]').first().click();
 assert((await page.locator('.ag-inline-body').innerText()).includes(last.before));
 const rid=last.evidence[0];
 await page.locator('.ag-inline-body [data-om-id="'+rid+'"]').first().click();
 await page.waitForFunction(r=>document.querySelector('.ag-inline-body')?.textContent.includes(r),rid);
 await page.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>!OB.loading);
 assert((await page.locator('.ag-inline-body').innerText()).includes(rid),'refresh retains evidence in the same column');
 // 260909 反馈①②③④：跳转互链、滚轮不被画布吞掉、详情内字号统一。
 const wheelBox=await page.locator('.ag-canvas-scroll').boundingBox();
 await page.mouse.move(wheelBox.x+wheelBox.width/2,wheelBox.y+120);
 await page.mouse.wheel(0,600);await page.waitForTimeout(400);
 assert(await page.evaluate(()=>scrollY)>0,'wheel over the flow canvas still scrolls the page');
 await page.evaluate(()=>scrollTo(0,0));
 // .om-id 是等宽的请求编号，故意更小；正文段落、列表与引用必须同一号，强调靠色条与字重。
 const sizes=await page.locator('.ag-inline-detail').evaluate(d=>[...d.querySelectorAll('p:not(.om-id),li,blockquote')].map(e=>getComputedStyle(e).fontSize));
 assert.deepEqual([...new Set(sizes)],['12px'],'detail body keeps one type size: '+sizes);
 assert(await page.locator('[data-om-action="open-capture"]').count()>0,'evidence offers a jump back to the capture');
 const labels=await page.locator('#obSel option').allTextContents();
 assert(labels.every(x=>/^\d{4}-\d{2}-\d{2} · /.test(x)),'observation labels lead with their scope: '+labels[0]);
 const jump=await page.evaluate(async rid=>{
  const r=await fetch('/api/observations?rid='+rid+'&date='+OB.state.scope.date);const j=await r.json();
  return {scope:j.capture_scope,matches:j.matches};
 },rid);
 assert.equal(jump.scope.date,state.scope.date);
 assert(jump.matches.includes(oid),'the observation covering this evidence is reachable from its capture');
 await page.evaluate(()=>{navigator.clipboard.writeText=async text=>{window.qaPrompt=text;};});
 await page.getByRole('button',{name:'复制接入说明',exact:true}).click();
 const prompt=await page.evaluate(()=>window.qaPrompt);
 for(const text of ['goal_flow_delta','current','task_id','carryover',oid,base]) assert(prompt.includes(text),'copied taskbook includes '+text);
 assert(!/\{base\}|\{q\}|\{id\}|\{scope\}|\{setup\}/.test(prompt),'no unresolved placeholders');
 await page.addScriptTag({path:'tools/checks/contrast_probe.js'});
 const contrasts={};
 for(const theme of ['dark','classic','light']){
  await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);await page.waitForTimeout(350);
  contrasts[theme]=await page.evaluate(()=>ccwaProbe.scan());
  assert.deepEqual(Object.entries(contrasts[theme].contrast),[],'goal contrast '+theme);
  await page.screenshot({path:path.join(out,'goal-'+theme+'.png'),fullPage:true});
 }
 for(const [lang,title] of [['en','How it understands your request'],['ja','依頼をどう理解しているか'],['zh','它对你要求的理解']]){
  await page.evaluate(l=>{LANG=l;obRender();},lang);
  assert.equal(await reading.locator('h3').first().innerText(),title);
 }
 await page.evaluate(()=>{LANG='zh';obRender();});
 for(const width of [768,390]){
  await page.setViewportSize({width,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'no page overflow '+width);
  // goal-latest only locates the goal; evidence opened above keeps this detail open.
  const detail=page.locator('.ag-inline-detail');assert(await detail.isVisible(),'prior evidence selection remains open');
  await page.locator('[data-om-action="goal-latest"]').click();
  await page.locator('[data-om-action="flow-lane"][data-om-id="right"]').click();
  await page.waitForTimeout(350);
  const box=await detail.boundingBox();assert(box && box.x<width && box.x+box.width>0,'third-column detail can be reached '+width);
  await page.screenshot({path:path.join(out,'goal-width-'+width+'.png'),fullPage:true});
 }
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({scope:'current A→G tasks/current/inline evidence/capture links/scroll/type sizes',passed:true,tasks:flow.tasks.length,iterations:flow.iterations.length,errors,contrasts},null,2));
 await browser.close();console.log('PASS understanding/tasks/inline evidence/capture links/scroll chaining/type sizes/refresh/languages/contrast/widths');
})().catch(e=>{console.error(e);process.exit(1)});
