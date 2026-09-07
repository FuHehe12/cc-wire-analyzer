/* No dependencies. Run: node tests/observe_map_selftest.js
 * Exercises the production reader in a VM without browser or network access.
 * Geometry and interaction still require the browser acceptance checks. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const project = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(project, 'src/static/observe-map.js'), 'utf8');
// Test-only access to the actual pure reader functions, not a second algorithm.
const seam = 'window.ObserveMap={render,refresh,clear};';
assert.equal(source.split(seam).length, 2, 'reader API seam must be unique');
const code = source.replace(seam, seam + '\nwindow.audit={words,M,windowOf,predictionState,adoptTrace,stepDetail,predictionHtml,itemDetail,graphHtml,overviewHtml,errorText};');
const context = {window:{}, document:{getElementById:()=>null}, URLSearchParams, AbortController, LANG:'en'};
vm.createContext(context);
vm.runInContext(code, context, {filename:'observe-map.js'});
const {words,M,windowOf,predictionState,adoptTrace,stepDetail,predictionHtml,itemDetail,graphHtml,overviewHtml,errorText} = context.window.audit;
let passed = 0;
function test(name, fn) {fn(); passed++; console.log('PASS ' + name);}
function pred(extra={}) {
  return {id:'forecast',kind:'prediction',text:'The next two main requests will contain a source lookup.',
    forecast:{after_rid:'frontier',horizon_steps:2,criterion:'A recorded source lookup occurs.'}, ...extra};
}
function trace(nodes, extra={}) {
  adoptTrace({order:'recording',truncated:false,nodes:nodes.map((n,i)=>({seq:i,kind:'main',lane:'main-lane',...n})),...extra});
}
function reset(p=pred()) {M.state={items:[p]}; M.items=new Map([[p.id,p]]); M.records.clear();M.rawOpen.clear();return p;}

test('all UI keys are translated in three languages',()=>{
  assert.deepEqual(Object.keys(words.en).sort(), Object.keys(words.zh).sort());
  assert.deepEqual(Object.keys(words.ja).sort(), Object.keys(words.zh).sort());
  for(const lang of ['zh','en','ja']) for(const [key,value] of Object.entries(words[lang])) assert(value.trim(),lang+'.'+key);
});
test('window counts subsequent main requests in the frontier lane only',()=>{
  const p=reset();trace([{id:'frontier'},{id:'sub',kind:'subagent'},{id:'other-main',lane:'another-lane'},{id:'main-1'}]);
  assert.equal(windowOf(p).state,'before');assert.equal(windowOf(p).count,1);
  assert.equal(predictionState(p).label,'beforeWindow');
});
test('window is reached at the declared request count, without inferring a hit',()=>{
  const p=reset();trace([{id:'frontier'},{id:'main-1'},{id:'main-2'},{id:'main-3'}]);
  assert.equal(windowOf(p).state,'reached');assert.equal(windowOf(p).count,2);
  assert.deepEqual(Array.from(windowOf(p).ids),['main-1','main-2']);
  assert.equal(predictionState(p).label,'pending');
});
test('recording order is authoritative even when transport node order differs',()=>{
  const p=reset();trace([{id:'main-2',seq:3},{id:'frontier',seq:1},{id:'main-1',seq:2}]);
  assert.deepEqual(Array.from(windowOf(p).ids),['main-1','main-2']);
});
test('missing frontier, missing window records and truncated trace cannot establish a window',()=>{
  const p=reset();trace([{id:'main-1'}]);assert.equal(windowOf(p).state,'unknown');
  trace([{id:'frontier',missing:true},{id:'main-1'},{id:'main-2'}]);assert.equal(windowOf(p).state,'unknown');
  trace([{id:'frontier'},{id:'main-1',missing:true},{id:'main-2'}]);assert.equal(windowOf(p).state,'unknown');
  trace([{id:'frontier'},{id:'main-1'},{id:'main-2'}],{truncated:true});assert.equal(windowOf(p).state,'unknown');
});
test('legacy predictions stay reviewable without invented windows',()=>{
  const p=reset(pred({forecast:undefined}));trace([{id:'frontier'},{id:'main-1'},{id:'main-2'}]);
  assert.equal(windowOf(p).state,'unknown');assert.equal(predictionState(p).label,'pending');
});
test('support and counterevidence coexist; retracted reviews do not establish support',()=>{
  const p=reset();
  const support={id:'support',kind:'finding',text:'Lookup recorded',links:[{to:p.id,type:'supports'}]};
  const counter={id:'counter',kind:'deviation',text:'Source unavailable',links:[{to:p.id,type:'contradicts'}]};
  M.state.items.push(support,counter);
  assert.equal(predictionState(p).label,'conflicting');
  counter.status='retracted';assert.equal(predictionState(p).label,'evidenceSupport');
  support.status='retracted';assert.equal(predictionState(p).label,'pending');
});
test('reviewed predictions do not say they are still awaiting review',()=>{
  const p=reset();trace([{id:'frontier'},{id:'main-1'},{id:'main-2'}]);
  M.state.items.push({id:'review',kind:'check',text:'Observed lookup',links:[{to:p.id,type:'supports'}]});
  for(const lang of ['zh','en','ja']) {
    context.LANG=lang;
    const html=predictionHtml(p);
    assert(html.includes(words[lang].windowReached));assert(html.includes(words[lang].evidenceSupport));
    assert(!html.includes(words[lang].noReview));assert(!/awaiting review|等待核对|照合待ち/.test(html));
  }
  context.LANG='en';
});
test('empty results and ambiguous IDs are distinct from a result not yet observed',()=>{
  reset();trace([{id:'tool-step',actions:[{name:'Tool',result_available:true,result_preview:''}]}]);
  assert(stepDetail('tool-step').includes(words.en.resultEmpty));
  M.nodes.get('tool-step').actions[0].result_ambiguous=true;
  assert(stepDetail('tool-step').includes(words.en.resultAmbiguous));
  M.nodes.get('tool-step').actions[0]={name:'Tool',result_available:false};
  assert(stepDetail('tool-step').includes(words.en.noResult));
});
test('a done progress label does not assert acceptance success',()=>{
  const phase={id:'phase',kind:'phase',text:'Build completed',progress:'done',covers:['tool-step']};
  reset();M.items.set(phase.id,phase);
  const html=itemDetail(phase);assert(html.includes(words.en.doneNote));
});
test('recorded markup stays escaped rather than becoming executable UI',()=>{
  const p=reset(pred({text:'<img src=x onerror=alert(1)>'}));
  const html=itemDetail(p);assert(!html.includes('<img'));assert(html.includes('&lt;img'));
});
test('legacy phase anchors stay collapsed until semantic coverage is available',()=>{
  reset();M.folds.clear();
  M.state.items=[{id:'legacy',kind:'phase',text:'Old phase',evidence:['frontier']}];
  let html=graphHtml();
  assert(html.startsWith('<details '));assert(!html.split('>')[0].includes(' open'));
  M.folds.add('legacy-phases');assert(graphHtml().split('>')[0].includes(' open'));
  M.state.items[0].covers=['frontier'];assert(!graphHtml().startsWith('<details '));
  M.state.items[0].covers=[];M.state.items.push({id:'goal',kind:'goal',text:'Goal'});
  assert(!graphHtml().startsWith('<details '));
});
test('overview counts unique recorded coverage and surfaces at most three live open claims',()=>{
  reset();trace([{id:'frontier'},{id:'main-1'}]);
  M.state.items=[{id:'phase-1',kind:'phase',covers:['frontier','not-in-scope']},
    {id:'phase-2',kind:'phase',covers:['frontier','main-1']},
    ...[1,2,3,4].map(i=>({id:'open-'+i,kind:'open',title:'Issue '+i,text:'Details '+i})),
    {id:'retracted',kind:'open',title:'Hidden issue',status:'retracted'}];
  const html=overviewHtml();
  assert.equal((html.match(/class="om-attention-link"/g)||[]).length,3);
  assert(html.includes('Issue 1'));assert(!html.includes('Issue 4'));assert(!html.includes('Hidden issue'));
  assert(html.includes('<strong>2</strong><span>'+words.en.recordedCoverage));
  assert(html.includes('<strong>4</strong><span>'+words.en.open));
});
test('errors retain specific transport and API explanations',()=>{
  assert.equal(errorText('HTTP 403: source unavailable'),'HTTP 403: source unavailable');
  assert.equal(errorText({key:'failed',detail:'capture missing'}),words.en.failed+': capture missing');
  assert.equal(errorText({key:'noScope'}),words.en.noScope);
});
test('component color tokens exist in the host theme system',()=>{
  const css=fs.readFileSync(path.join(project,'src/static/observe-map.css'),'utf8');
  const host=fs.readFileSync(path.join(project,'src/templates/index.html'),'utf8');
  const defined=new Set([...host.matchAll(/(--[\w-]+)\s*:/g)].map(m=>m[1]));
  const missing=[...css.matchAll(/var\((--[\w-]+)/g)].map(m=>m[1]).filter(t=>!defined.has(t));
  assert.deepEqual(missing,[]);
});
console.log('\n'+passed+' observation reader checks passed.');
