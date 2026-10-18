const assert=require('node:assert/strict'),test=require('node:test'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/static/island-context.js'),'utf8');
test('only an authenticated own dashboard supplies display-only island context to the native bridge',()=>{
  const listeners=new Map(),sent=[],body={role:'admin',viewerId:'2'};
  const context={timezone:'Asia/Shanghai',sessions:[{start:'08:30:00',end:'11:40:00'},{start:'13:30:00',end:'22:45:00'}],checkins:[]};
  vm.runInNewContext(source,{document:{body:{dataset:body},addEventListener:(name,fn)=>listeners.set(name,fn)},
    window:{MutsumiAndroid:{syncIslandContext:raw=>sent.push(JSON.parse(raw))}},console});
  const update=listeners.get('dashboard:updated'),data={preferences:{viewer_id:2},island_context:context};
  update({detail:data});assert.deepEqual(sent,[context]);
  body.role='guest';update({detail:data});assert.equal(sent.length,1);
  body.role='admin';update({detail:{...data,preferences:{viewer_id:3}}});assert.equal(sent.length,1);
  update({detail:{...data,island_context:null}});assert.equal(sent.length,1);
});
