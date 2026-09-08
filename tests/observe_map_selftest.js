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
const code = source.replace(seam, seam + '\nwindow.audit={words,M,windowOf,predictionState,adoptTrace,stepDetail,predictionHtml,itemDetail,graphHtml,overviewHtml,errorText,reportHtml,goalFlowHtml,flowDiagramHtml,flowLayers,goalDetail};');
const context = {window:{}, document:{getElementById:()=>null}, URLSearchParams, AbortController, LANG:'en'};
vm.createContext(context);
vm.runInContext(code, context, {filename:'observe-map.js'});
const {words,M,windowOf,predictionState,adoptTrace,stepDetail,predictionHtml,itemDetail,graphHtml,overviewHtml,errorText,reportHtml,goalFlowHtml} = context.window.audit;
const {flowDiagramHtml,flowLayers,goalDetail}=context.window.audit;
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
test('relationships start folded and retain explicit expansion for legacy and semantic records',()=>{
  reset();M.folds.clear();
  M.state.items=[{id:'legacy',kind:'phase',text:'Old phase',evidence:['frontier']}];
  let html=graphHtml();
  assert(html.startsWith('<details '));assert(!html.split('>')[0].includes(' open'));
  M.folds.add('legacy-phases');assert(graphHtml().split('>')[0].includes(' open'));
  M.state.items[0].covers=['frontier'];assert(graphHtml().startsWith('<details '));
  assert(!graphHtml().split('>')[0].includes(' open'));
  M.folds.add('relations');assert(graphHtml().split('>')[0].includes(' open'));
  M.state.items[0].covers=[];M.state.items.push({id:'goal',kind:'goal',text:'Goal'});
  assert(graphHtml().startsWith('<details '));
});

test('report preserves overflow entries and excludes retracted claims',()=>{
  reset();M.state.items=[...[1,2,3,4].map(i=>({id:'p'+i,kind:'phase',title:'Work '+i})),
    {id:'bad',kind:'phase',text:'Withdrawn claim',status:'retracted'},
    {id:'blocked',kind:'goal',text:'Waiting for input',progress:'blocked'}];
  const html=reportHtml();
  assert(html.includes('Work 4'));assert(html.includes('data-om-fold="report-workDone"'));
  assert(!html.includes('Withdrawn claim'));assert(html.includes('Waiting for input'));
});

test('goal flow preserves one anchor, explicit branches, inference and original evidence',()=>{
  reset();M.folds.clear();
  const event=(id,after,parent_ids)=>({id,after,parent_ids,before:'Inspect only',actor:'ai',trigger:'A check failed',basis:'inferred',status:'active',evidence:['req_change']});
  const it={id:'g',kind:'goal',goal_flow:{anchor:{user_text:'<script>user</script>',understanding:'Inspect project',choices:['Scope chosen by AI'],basis:'inferred',evidence:['req_start']},
    iterations:[event('G0','Inspect',[]),event('G1a','Repair',['G0']),event('G1b','Explain',['G0'])]}};
  const html=goalFlowHtml(it,true);
  assert.equal((html.match(/class="om-goal-anchor"/g)||[]).length,1);
  const current=html.split('class="om-goal-current"')[1].split('<details')[0];
  assert(current.includes('Repair'));assert(current.includes('Explain'));assert(!current.includes('Inspect'));
  assert(html.includes(words.en.inferred));assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));
  assert(html.includes('data-om-id="req_start"'));assert(html.includes('data-om-id="req_change"'));
  assert(html.includes('<del>Inspect only</del>'));assert(html.includes('<ins>Repair</ins>'));
  assert(goalFlowHtml(null).includes(words.en.noGoalFlow));
});
test('overview counts unique recorded coverage without duplicating report entries',()=>{
  reset();trace([{id:'frontier'},{id:'main-1'}]);
  M.state.items=[{id:'phase-1',kind:'phase',covers:['frontier','not-in-scope']},
    {id:'phase-2',kind:'phase',covers:['frontier','main-1']},
    ...[1,2,3,4].map(i=>({id:'open-'+i,kind:'open',title:'Issue '+i,text:'Details '+i})),
    {id:'retracted',kind:'open',title:'Hidden issue',status:'retracted'}];
  const html=overviewHtml();
  assert.equal((html.match(/class="om-attention-link"/g)||[]).length,0);
  assert(!html.includes('Hidden issue'));
  assert(html.includes('<strong>2</strong><span>'+words.en.recordedCoverage));
  assert(html.includes('<strong>4</strong><span>'+words.en.open));
});
test('errors retain specific transport and API explanations',()=>{
  assert.equal(errorText('HTTP 403: source unavailable'),'HTTP 403: source unavailable');
  assert.equal(errorText({key:'failed',detail:'capture missing'}),words.en.failed+': capture missing');
  assert.equal(errorText({key:'noScope'}),words.en.noScope);
});
test('goal flow lays out explicit forks and joins, with no automatic work attribution',()=>{
  reset();
  const e=(id,parents)=>({id,parent_ids:parents,actor:'ai',before:'Inspect',after:'Goal '+id,trigger:'Discovery '+id,evidence:['req_'+id],basis:'inferred'});
  const events=[e('G0',[]),e('G1',['G0']),e('G2a',['G1']),e('G2b',['G1']),e('G3',['G2a','G2b'])];
  const g={id:'goal',kind:'goal',goal_flow:{anchor:{user_text:'Check project',understanding:'Full audit',choices:[],basis:'inferred',evidence:['req_start']},iterations:events}};
  M.state.items=[g,{id:'related',kind:'finding',text:'Original plan is outdated',goal_iteration:'G2a'},
    {id:'unrelated',kind:'phase',text:'Must not infer from evidence',evidence:['req_G2a']}];
  assert.deepEqual(JSON.parse(JSON.stringify(flowLayers(events))).map(row=>row.map(x=>x.id)),[['G0'],['G1'],['G2a','G2b'],['G3']]);
  const html=flowDiagramHtml(g);assert.equal((html.match(/data-ag-node="@anchor"/g)||[]).length,1);
  assert.equal((html.match(/data-ag-node="G/g)||[]).length,5);assert(!html.includes('<details'));
  assert(html.includes('Original plan is outdated'));assert(!html.includes('Must not infer'));
  assert(goalDetail('G2a').includes('Original plan is outdated'));assert(!goalDetail('G2b').includes('Original plan is outdated'));
  assert(goalDetail('@anchor').includes('Full audit'));
  assert(goalDetail('G0').includes(words.en.priorGoal));
  assert(goalDetail('G0').includes(words.en.initialGoal));
  assert(!goalDetail('G3').includes(words.en.priorGoal));
});

test('component color tokens exist in the host or component theme system',()=>{
  const css=fs.readFileSync(path.join(project,'src/static/observe-map.css'),'utf8');
  const host=fs.readFileSync(path.join(project,'src/templates/index.html'),'utf8');
  const defined=new Set([...(host+css).matchAll(/(--[\w-]+)\s*:/g)].map(m=>m[1]));
  const missing=[...css.matchAll(/var\((--[\w-]+)/g)].map(m=>m[1]).filter(t=>!defined.has(t));
  assert.deepEqual(missing,[]);
  for(const theme of ['classic','light']) assert(css.includes('[data-theme='+theme+'] .om-shell{--ag-user:'));
});
console.log('\n'+passed+' observation reader checks passed.');
