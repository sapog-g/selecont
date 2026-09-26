// Execute the real delivered script against controlled browser events/network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('apps/api/selecont/web.py','utf8').split('ACCESS_WATCH_JS = """')[1].split('"""')[0];
async function scenario(response) {
  const events = {}, timers = new Map(); let counter = 0, cleared = false, reloads = 0, redirect = '';
  const root = {dataset:{accessCheck:'/access/test',accessFallback:'/u/test'},replaceChildren(){cleared=true}};
  const element = () => ({append(){}});
  const document = {body:root,hidden:false,createElement:element,addEventListener:(n,f)=>events[n]=f};
  const window = {addEventListener:(n,f)=>events[n]=f,setInterval(){},setTimeout:f=>{timers.set(++counter,f);return counter},clearTimeout:n=>timers.delete(n),location:{reload(){reloads++},replace(v){redirect=v}}};
  vm.runInNewContext(source,{document,window,AbortController,fetch:response});
  const settle = async () => {await Promise.resolve();await Promise.resolve();};
  await settle();
  return {document,events,timers,settle,get cleared(){return cleared},get reloads(){return reloads},get redirect(){return redirect}};
}
(async()=>{
  let s=await scenario(async()=>({status:204}));
  assert.equal(s.cleared,false);
  s.document.hidden=true;s.events.visibilitychange();assert.equal(s.cleared,true);
  s.document.hidden=false;s.events.visibilitychange();await s.settle();assert.equal(s.reloads,1);
  s=await scenario(async()=>({status:404}));assert.equal(s.cleared,true);assert.equal(s.redirect,'/u/test');
  s=await scenario(()=>new Promise(()=>{}));assert.equal(s.cleared,false);
  for(const timeout of s.timers.values())timeout();assert.equal(s.cleared,true);
  s=await scenario(async()=>({status:204}));s.events.pagehide();assert.equal(s.cleared,true);
  s=await scenario(async()=>{throw Error('offline')});assert.equal(s.cleared,true);
  console.log('Access watcher: 5 event/network scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1});
