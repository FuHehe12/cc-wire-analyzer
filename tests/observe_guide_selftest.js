// Pure source-function test; this does not verify browser clipboard permissions.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../src/templates/index.html'),'utf8');
const dictionary=source.match(/const I18N = (\{[\s\S]*?\n\});/)[1];
const translate=source.slice(source.indexOf('function t18(key, params){'),source.indexOf('const THEME_IDS'));
const copy=source.slice(source.indexOf('function obCopyGuide(){'),source.indexOf('\nasync function anLoad',source.indexOf('function obCopyGuide(){')));
let count=0;
for(const language of ['zh','en','ja']) for(const existing of [false,true]){
 const scope={date:'2026-09-09',source:'fixture & source',session:'session/a',lane:'lane-1'};
 const values=[];
 const context={URLSearchParams,location:{origin:'http://127.0.0.1:8787'},OB:{state:existing?{id:'obs_123abcd',scope}:null},S:{date:scope.date,source:scope.source},copyAndReport:value=>values.push(value)};
 vm.runInNewContext('const I18N='+dictionary+';let LANG='+JSON.stringify(language)+';'+translate+'\n'+copy+'\nobCopyGuide();',context);
 assert.equal(values.length,1,'use common copyAndReport exactly once');
 const text=values[0];assert.equal(typeof text,'string');
 for(const term of ['http://127.0.0.1:8787/api/ai-guide','goal_flow_delta','current','task_id','initial','refine','turn','carryover','submission_id','409','view=dialog&include_aux=false','source=fixture+%26+source'])assert(text.includes(term),language+': '+term);
 assert(!/\{(?:base|q|id|scope|setup)\}/.test(text),'no unresolved interpolation');
 if(existing){assert(text.includes('/api/observations/obs_123abcd'));assert(text.includes('session=session%2Fa'));assert(!text.includes('OBSERVATION_ID'));}
 else{assert(text.includes('/api/dag?'));assert(text.includes('OBSERVATION_ID'));}
 count++;
}
console.log('PASS '+count+' actual obCopyGuide/t18 cases: common copy helper, three languages, existing/new scope and exact interpolation. Clipboard is stubbed, not browser-verified.');
