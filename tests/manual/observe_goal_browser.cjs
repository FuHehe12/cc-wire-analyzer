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
 await page.locator('.om-goal-current').waitFor();
 assert.equal(await page.locator('#om-semantic').getAttribute('open'),null,'relations do not overwhelm the report');
 await page.screenshot({path:path.join(out,'overview.png'),fullPage:true});
 await page.locator('.om-main .om-goal-flow > details > summary').click();
 assert.equal(await page.locator('.om-main .om-goal-anchor').count(),1,'one initial understanding');
 assert.equal(await page.locator('.om-main .om-goal-event').count(),goal.goal_flow.iterations.length);
 assert((await page.locator('.om-main .om-goal-anchor').innerText()).includes(goal.goal_flow.anchor.user_text));
 const last=goal.goal_flow.iterations.at(-1),rid=last.evidence[0];
 await page.locator('.om-main .om-goal-event').last().locator('[data-om-id="'+rid+'"]').first().click();
 await page.waitForFunction(r=>document.querySelector('#om-detail-body')?.textContent.includes(r),rid);
 await page.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>!OB.loading);
 assert((await page.locator('#om-detail-body').innerText()).includes(rid),'refresh retains evidence selection');
 assert(await page.locator('.om-main .om-goal-flow > details').getAttribute('open')!==null,'refresh retains goal history');
 await page.addScriptTag({path:'tools/checks/contrast_probe.js'});
 const contrasts={};
 for(const theme of ['dark','classic','light']){
   await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);await page.waitForTimeout(350);
   contrasts[theme]=await page.evaluate(()=>ccwaProbe.scan());
   assert.deepEqual(Object.entries(contrasts[theme].contrast),[],'goal text contrast '+theme);
   await page.screenshot({path:path.join(out,'goal-'+theme+'.png'),fullPage:true});
 }
 for(const [lang,label] of [['en','How the goal changed'],['ja','目標はどう変わったか'],['zh','目标如何变化']]){
   await page.evaluate(l=>{LANG=l;obRender();},lang);
   assert.equal(await page.locator('.om-main .om-goal-flow > h2').innerText(),label);
 }
 for(const width of [768,390]){
   await page.setViewportSize({width,height:844});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'no overflow '+width);
   await page.locator('.om-main .om-goal-event').last().locator('[data-om-id="'+rid+'"]').first().click();
   const top=await page.locator('.om-detail').evaluate(e=>e.getBoundingClientRect().top);
   assert(top>=65 && top<694,'evidence visible after click: '+top);
   await page.screenshot({path:path.join(out,'goal-width-'+width+'.png'),fullPage:true});
 }
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({passed:true,events:goal.goal_flow.iterations.length,errors,contrasts},null,2));
 await browser.close();console.log('PASS goal history/evidence/refresh/languages/contrast/widths');
})().catch(e=>{console.error(e);process.exit(1)});
