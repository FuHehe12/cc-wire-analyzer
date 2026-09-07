const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('playwright');
const base=process.env.CCWA_TEST_URL || 'http://127.0.0.1:53908';
const oid=process.env.CCWA_OBSERVATION_ID;
if(!oid || !['127.0.0.1','localhost'].includes(new URL(base).hostname)) throw Error('Set CCWA_OBSERVATION_ID and a loopback CCWA_TEST_URL');
const out=process.env.CCWA_QA_OUTPUT || 'local/artifacts/observe-review/browser-qa';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:process.env.CCWA_BROWSER || 'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const state=await (await page.request.get(base+'/api/observations?id='+oid)).json();
 const phases=state.items.filter(i=>i.kind==='phase' && i.covers?.length);
 assert(phases.length>0,'Use a semantic sample with explicit coverage');
 await page.goto(base);await page.getByRole('tab',{name:'实时分析',exact:true}).click();
 await page.getByLabel('观测',{exact:true}).selectOption(oid);
 await page.waitForFunction(()=>document.querySelectorAll('.om-wire').length>0);
 await page.screenshot({path:path.join(out,'01-semantic-overview.png'),fullPage:true});
 assert.equal(await page.locator('.om-node-phase').count(),phases.length);
 await page.locator('[data-om-action="coverage"][data-om-id="'+phases[0].id+'"]').click();
 assert.equal(await page.locator('.om-detail-steps .om-step').count(),phases[0].covers.length);
 await page.locator('.om-detail-steps .om-step').first().click();
 const chosen=await page.locator('#om-detail-body').innerText();assert(chosen.includes(phases[0].covers[0]));
 await page.getByRole('button',{name:'刷新',exact:true}).click();
 await page.waitForFunction(()=>!OB.loading);
 assert((await page.locator('#om-detail-body').innerText()).includes(phases[0].covers[0]),'refresh retains selection');
 await page.screenshot({path:path.join(out,'02-action-evidence.png'),fullPage:true});
 // Simulate an incoming state revision through the read response, no disk writes.
 await page.route('**/api/observations?id='+oid,async route=>{
   const reply=await route.fetch(),data=await reply.json();data.revision+=1;
   await route.fulfill({response:reply,json:data});
 });
 await page.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>!OB.loading);
 assert((await page.locator('#om-detail-body').innerText()).includes(phases[0].covers[0]),'new revision retains selection');
 await page.unroute('**/api/observations?id='+oid);
 const forecasts=state.items.filter(i=>i.kind==='prediction');
 if(forecasts.length){await page.locator('.om-prediction-title').first().click();await page.screenshot({path:path.join(out,'03-forecast-review.png'),fullPage:true});}
 await page.addScriptTag({path:'tools/checks/contrast_probe.js'});
 const contrast={};
 for(const theme of ['dark','classic','light']){
   await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);
   await page.waitForTimeout(350);
   contrast[theme]=await page.evaluate(()=>ccwaProbe.scan());
   await page.screenshot({path:path.join(out,'theme-'+theme+'.png'),fullPage:true});
 }
 fs.writeFileSync(path.join(out,'contrast.json'),JSON.stringify(contrast,null,2));
 for(const [lang,title] of [['en','Semantic trace'],['ja','意味ベースの軌跡'],['zh','语义轨迹']]){
   await page.evaluate(l=>{LANG=l;obRender();},lang);
   const text=await page.locator('.om-header h2').innerText();assert.equal(text,title);
   console.log('language',lang,text);
 }
 for(const width of [1280,768,390]){
   await page.setViewportSize({width,height:844});
   const dims=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:innerWidth}));
   await page.screenshot({path:path.join(out,'width-'+width+'.png'),fullPage:true});
   assert(dims.scroll<=dims.viewport+2,'page overflow at '+width+': '+JSON.stringify(dims));
   if(width<=768){
     await page.locator('.om-node-phase .om-node-title').first().click();
     const detailTop=await page.locator('.om-detail').evaluate(el=>el.getBoundingClientRect().top);
     assert(detailTop>=65 && detailTop<250,'narrow-screen selection must reveal the detail panel');
   }
 }
 if(process.env.CCWA_LONG_OBSERVATION_ID){
   await page.setViewportSize({width:1280,height:900});
   const longId=process.env.CCWA_LONG_OBSERVATION_ID;
   const longState=await (await page.request.get(base+'/api/observations?id='+longId)).json();
   const trace=await (await page.request.get(base+'/api/observations/trace?'+new URLSearchParams(longState.scope))).json();
   await page.getByLabel('观测',{exact:true}).selectOption(longId);
   await page.waitForFunction(count=>document.querySelectorAll('.om-turn').length===count,trace.turns.length);
   assert.equal(await page.locator('.om-turn .om-step').count(),0,'long trace starts folded');
   const height=await page.evaluate(()=>document.body.scrollHeight);assert(height<5000,'long legacy view must stay compressed');
   await page.screenshot({path:path.join(out,'long-trace.png'),fullPage:true});
   console.log('long trace',trace.nodes.length,trace.turns.length,height);
 }
 for(const [theme,result] of Object.entries(contrast)){
   const failures=Object.entries(result.contrast);
   assert.deepEqual(failures,[],'observation contrast failures in '+theme);
 }
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({passed:true,phases:phases.length,forecasts:forecasts.length,errors,contrast},null,2));
 console.log('PASS browser semantic/coverage/selection/forecast/languages/viewports');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
