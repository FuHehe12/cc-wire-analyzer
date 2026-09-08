// Run against an isolated observation with goal_flow. No writes to observations.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('playwright');
const base=process.env.CCWA_TEST_URL,oid=process.env.CCWA_OBSERVATION_ID;
if(!base || !oid || !['127.0.0.1','localhost'].includes(new URL(base).hostname)) throw Error('Set loopback CCWA_TEST_URL and CCWA_OBSERVATION_ID');
const out=process.env.CCWA_QA_OUTPUT || 'local/artifacts/observe-goal-browser';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:process.env.CCWA_BROWSER || 'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const state=await (await page.request.get(base+'/api/observations?id='+oid)).json();
 const goal=state.items.find(i=>i.goal_flow && i.status!=='retracted');assert(goal);
 await page.goto(base);await page.getByRole('tab',{name:'实时分析',exact:true}).click();
 await page.getByLabel('观测',{exact:true}).selectOption(oid);
 await page.locator('.ag-canvas').waitFor();
 assert.equal(await page.locator('.om-detail').isVisible(),false,'details do not occupy the overview');
 assert.equal(await page.locator('.om-report').isVisible(),false,'flow replaces the report as the main view');
 assert.equal(await page.locator('.ag-station').count(),goal.goal_flow.iterations.length);
 await page.waitForFunction(()=>document.querySelectorAll('.ag-wire').length>0);
 const expectedEdges=goal.goal_flow.iterations.flatMap(e=>(e.parent_ids.length?e.parent_ids:['@anchor']).map(p=>[p,e.id]));
 const edges=await page.locator('.ag-wire').evaluateAll(ns=>ns.map(n=>[n.dataset.agFrom,n.dataset.agTo]));
 assert.deepEqual(edges,expectedEdges,'forks and joins use recorded parent links');
 await page.screenshot({path:path.join(out,'overview.png'),fullPage:true});
 assert.equal(await page.locator('.ag-anchor').count(),1,'one initial understanding');
 await page.locator('[data-om-action="goal-anchor"]').click();
 assert((await page.locator('#om-detail-body').innerText()).includes(goal.goal_flow.anchor.user_text));
 await page.locator('[data-om-action="close-detail"]').click();
 const last=goal.goal_flow.iterations.at(-1),rid=last.evidence[0];
 await page.locator('.ag-station [data-om-id="'+last.id+'"]').first().click();
 assert((await page.locator('#om-detail-body').innerText()).includes(last.before));
 const linked=state.items.filter(i=>i.status!=='retracted' && i.goal_iteration===last.id);
 for(const it of linked) assert((await page.locator('#om-detail-body').innerText()).includes(it.title || it.text));
 await page.locator('#om-detail-body [data-om-id="'+rid+'"]').first().click();
 await page.waitForFunction(r=>document.querySelector('#om-detail-body')?.textContent.includes(r),rid);
 await page.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>!OB.loading);
 assert((await page.locator('#om-detail-body').innerText()).includes(rid),'refresh retains evidence selection');
 assert(await page.locator('.ag-flow').isVisible(),'refresh retains selected view');
 await page.evaluate(()=>{navigator.clipboard.writeText=async text=>{window.qaPrompt=text;};});
 await page.getByRole('button',{name:'复制接入说明',exact:true}).click();
 const prompt=await page.evaluate(()=>window.qaPrompt);
 assert(prompt.includes('goal_iteration') && prompt.includes('events') && prompt.includes(oid) && prompt.includes(base),'copied observer prompt has model and concrete connection');
 assert(!/\{base\}|\{q\}|\{id\}|\{scope\}/.test(prompt),'no unresolved placeholders');
 await page.addScriptTag({path:'tools/checks/contrast_probe.js'});
 const contrasts={};
 for(const theme of ['dark','classic','light']){
   await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);await page.waitForTimeout(350);
   contrasts[theme]=await page.evaluate(()=>ccwaProbe.scan());
   fs.writeFileSync(path.join(out,'contrast.json'),JSON.stringify(contrasts,null,2));
   assert.deepEqual(Object.entries(contrasts[theme].contrast),[],'goal text contrast '+theme+' '+JSON.stringify(contrasts[theme].contrast));
   await page.screenshot({path:path.join(out,'goal-'+theme+'.png'),fullPage:true});
 }
 for(const [lang,label] of [['en','A→G goal flow'],['ja','A→G 目標の流れ'],['zh','A→G 目标流']]){
   await page.evaluate(l=>{LANG=l;obRender();},lang);
   assert.equal(await page.locator('.ag-tab[data-om-id="flow"]').innerText(),label);
 }
 for(const width of [768,390]){
   await page.setViewportSize({width,height:844});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'no overflow '+width);
   if(await page.locator('.om-detail').isVisible()) await page.locator('[data-om-action="close-detail"]').click();
   await page.locator('.ag-station [data-om-id="'+last.id+'"]').first().click();
   await page.locator('#om-detail-body [data-om-id="'+rid+'"]').first().click();
   const top=await page.locator('.om-detail').evaluate(e=>e.getBoundingClientRect().top);
   assert(top>=65 && top<694,'evidence visible after click: '+top);
   await page.screenshot({path:path.join(out,'goal-width-'+width+'.png'),fullPage:true});
   if(width===390){
     const scroller=page.locator('.ag-canvas-scroll');
     await scroller.evaluate(e=>{e.scrollLeft=e.scrollWidth;});
     const left=await scroller.evaluate(e=>e.scrollLeft);assert(left>0,'narrow branches are scrollable');
     await page.route('**/api/observations?id='+oid,async route=>{
       const response=await route.fetch(),data=await response.json();data.revision+=1;
       await route.fulfill({response,json:data});
     });
     await page.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>!OB.loading);
     assert.equal(await scroller.evaluate(e=>e.scrollLeft),left,'new revision preserves horizontal branch position');
     await page.unroute('**/api/observations?id='+oid);
   }
 }
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({passed:true,events:goal.goal_flow.iterations.length,errors,contrasts},null,2));
 await browser.close();console.log('PASS goal history/evidence/refresh/languages/contrast/widths');
})().catch(e=>{console.error(e);process.exit(1)});
