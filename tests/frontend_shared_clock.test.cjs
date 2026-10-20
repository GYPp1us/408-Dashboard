const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/static/dashboard-clock.js'), 'utf8');

function environment() {
  const epoch = Date.parse('2026-10-21T08:00:00.250+08:00');
  let wall = epoch, mono = 0, nextId = 1;
  const timers = new Map(), events = new Map(), errors = [];
  class FakeDate extends Date { static now() { return wall; } }
  const document = { hidden:false, addEventListener:(name, fn) => events.set(name, fn) };
  const window = { performance:{ now:() => mono }, console:{ error:err => errors.push(err) },
    setTimeout(fn, delay) { const id=nextId++; timers.set(id,{fn,at:mono+delay}); return id; },
    clearTimeout:id => timers.delete(id) };
  const context = vm.createContext({window,document,Date:FakeDate});
  vm.runInContext(source, context);
  function advance(ms) {
    const target=mono+ms;
    for (;;) {
      const next=[...timers].filter(([,timer]) => timer.at<=target).sort((a,b) => a[1].at-b[1].at)[0];
      if (!next) break;
      wall+=next[1].at-mono; mono=next[1].at; timers.delete(next[0]); next[1].fn();
    }
    wall+=target-mono;mono=target;
  }
  return {clock:window.DashboardClock,context,window,document,events,errors,timers,advance,
    jump:delta => {wall+=delta;}, at:() => mono, epoch};
}

test('server seconds and newly registered components share the same immutable frame', () => {
  const env=environment(), samples=[];
  env.clock.calibrate('2026-10-21T08:00:00.600+08:00');
  env.clock.subscribe('a',frame => samples.push(['a',frame]));
  env.clock.start(); env.advance(160);
  env.clock.subscribe('b',frame => samples.push(['b',frame]));
  assert.equal(samples.at(-1)[1].nowEpochMs, Date.parse('2026-10-21T08:00:00.600+08:00'));
  assert.equal([...env.timers.values()][0].at,401);
  env.advance(241);
  const pair=samples.slice(-2);
  assert.deepEqual(pair.map(row=>row[0]),['a','b']);
  assert.equal(pair[0][1],pair[1][1]);
  assert.ok(Object.isFrozen(pair[0][1]));
  assert.equal(pair[0][1].nowEpochMs,Date.parse('2026-10-21T08:00:01.001+08:00'));
});

test('device wall-clock jumps do not move a running business clock or local rest duration', () => {
  const env=environment();env.clock.calibrate('2026-10-21T08:00:00.600+08:00');
  const before=env.clock.now(); assert.equal(env.clock.elapsedLocal(env.epoch-42_000),42);
  env.jump(300_000);env.advance(1400);
  assert.equal(env.clock.now()-before,1400);
  assert.equal(env.clock.elapsedLocal(env.epoch-42_000),43);
  env.jump(-600_000);env.advance(1000);
  assert.equal(env.clock.now()-before,2400);
});

test('late responses cannot replace newer time samples and small corrections do not go backwards', () => {
  const env=environment();env.clock.calibrate('2026-10-21T08:00:00.600+08:00',{sequence:2});
  assert.equal(env.clock.calibrate('2026-10-21T07:59:00+08:00',{sequence:1}),false);
  const before=env.clock.now();
  env.clock.calibrate('2026-10-21T08:00:00.300+08:00',{sequence:3});
  assert.equal(env.clock.now(),before);
  const samples=[];env.clock.subscribe('time',frame=>samples.push(frame.nowEpochMs));env.clock.start();
  for(let i=0;i<50;i++)env.advance(250);
  for(let i=1;i<samples.length;i++)assert.ok(samples[i]>=samples[i-1]);
});

test('poll responses coalesce until the next second while real state transitions paint immediately', () => {
  const env=environment(), painted=[];let value=0;
  env.clock.calibrate('2026-10-21T08:00:00.600+08:00');
  env.clock.subscribe('view',frame=>painted.push([value,frame.nowEpochMs]));env.clock.start();painted.length=0;
  env.clock.stage('data',()=>{value=1;});env.advance(100);
  env.clock.stage('data',()=>{value=2;});assert.equal(painted.length,0);
  env.advance(301);assert.equal(painted.length,1);assert.equal(painted[0][0],2);
  env.clock.stage('data',()=>{value=3;});env.clock.cancel('data');
  env.clock.commit(()=>{value=4;});assert.equal(painted.at(-1)[0],4);
});

test('hidden pages stop ticking and resume in one current frame without replay', () => {
  const env=environment(), painted=[];
  env.clock.subscribe('view',frame=>painted.push(frame.nowEpochMs));env.clock.start();painted.length=0;
  env.document.hidden=true;env.events.get('visibilitychange')();assert.equal(env.timers.size,0);
  env.advance(90_000);assert.equal(painted.length,0);
  env.clock.stage('data',()=>{});env.document.hidden=false;env.events.get('visibilitychange')();
  assert.equal(painted.length,1);assert.equal(painted[0],env.epoch+90_000);
});

test('one failed component does not stop other components or the next tick', () => {
  const env=environment();let paints=0;
  env.clock.subscribe('good',()=>paints++);env.clock.start();
  env.clock.commit(()=>env.clock.subscribe('bad',()=>{throw Error('broken component');}));
  const before=paints;env.advance(1100);assert.ok(paints>before);assert.ok(env.errors.length>0);
});

test('APK and browser use identical clock and timeline modules', () => {
  for(const name of ['dashboard-clock.js','day-timeline.js']) assert.equal(
    fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8'),
    fs.readFileSync(path.join(__dirname,'../android/app/src/main/assets/dashboard',name),'utf8'));
});

function appEnvironment(apk = false) {
  const env = environment(), requests = [];
  Object.assign(env.document, { documentElement:{dataset:{}}, body:{dataset:{page:'home',role:'admin',viewerId:'1'}},
    visibilityState:'visible', querySelector:()=>null, querySelectorAll:()=>[], dispatchEvent(){} });
  env.window.addEventListener=()=>{};
  let reads=0;
  env.runtime={mode:'focusing',revision:1,busy:false,sessionId:1,startedAtEpochMs:env.epoch-12500,pausedSeconds:0,timer:'00:00:12'};
  env.window.MutsumiAndroid={getFocusRuntime:()=>{reads++;return JSON.stringify(env.runtime);}};
  Object.assign(env.context, {AbortController,console,CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}},
    fetch:(url)=>new Promise(resolve=>requests.push({url,complete:(data)=>resolve({ok:true,status:200,json:async()=>data})}))});
  const file=apk?'../android/app/src/main/assets/dashboard/app.js':'../app/static/app.js';
  const exposed=fs.readFileSync(path.join(__dirname,file),'utf8').replace(/\}\)\(\);\s*$/,
    'globalThis.appTest = {state,api,dashboardResponseCurrent,dashboardSignature,syncDashboard,responseTimes'+(apk?',nativeRuntime':'')+'};})();');
  vm.runInContext(exposed,env.context);
  return {...env,app:env.context.appTest,requests,reads:()=>reads};
}

for (const apk of [false,true]) test(`${apk?'APK':'web'} rejects dashboard reads started before or during a focus write`,async()=>{
  const env=appEnvironment(apk),{app,requests}=env;
  const before=app.api('/api/dashboard');
  const write=app.api('/api/focus/pause',{method:'POST'});
  const during=app.api('/api/dashboard');
  requests[1].complete({session:{id:1}});await write;
  requests[0].complete({now:'2026-10-21T08:00:00+08:00'});
  requests[2].complete({now:'2026-10-21T08:00:01+08:00'});
  assert.equal(app.dashboardResponseCurrent(await before),false);
  assert.equal(app.dashboardResponseCurrent(await during),false);
  const after=app.api('/api/dashboard');requests[3].complete({now:'2026-10-21T08:00:02+08:00'});
  assert.equal(app.dashboardResponseCurrent(await after),true);
});

test('APK reads native runtime once per frame and projects its focus timer on the shared server clock',()=>{
  const env=appEnvironment(true),samples=[];
  env.clock.calibrate('2026-10-21T08:00:00.600+08:00');env.jump(300000);
  env.clock.subscribe('first',()=>samples.push(env.app.nativeRuntime()));
  const before=env.reads();
  env.clock.subscribe('second',()=>samples.push(env.app.nativeRuntime()));
  assert.equal(env.reads(),before);assert.equal(samples[0],samples[1]);
  assert.equal(samples[1].timer,'00:00:12');
  env.clock.start();env.advance(401);
  assert.equal(samples.at(-1).timer,'00:00:13');
  assert.equal(samples.at(-1),samples.at(-2));
  assert.equal(env.reads(),before+2);
});

test('APK discards staged data if a native transition occurs before the next shared second',async()=>{
  const env=appEnvironment(true),base={now:'2026-10-21T08:00:00.600+08:00',focus:{active:null},today_focus:{seconds:0}};
  env.app.state.dashboard=base;env.app.state.dashboardSignature=env.app.dashboardSignature(base);
  env.clock.calibrate(base.now);env.clock.start();
  const syncing=env.app.syncDashboard();
  env.requests[0].complete({...base,today_focus:{seconds:42}});await syncing;
  env.runtime.revision=2;env.advance(401);
  assert.equal(env.app.state.dashboard.today_focus.seconds,0);
});
