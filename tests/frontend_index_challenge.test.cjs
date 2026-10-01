const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { harness, Element, sessions } = require('./frontend_market_harness.cjs');
const source = fs.readFileSync(path.join(__dirname, '../app/static/index-challenge.js'), 'utf8');
const homeSource = fs.readFileSync(path.join(__dirname, '../app/static/dashboard-index.js'), 'utf8');
const fullSource = fs.readFileSync(path.join(__dirname, '../app/static/focus_kline.js'), 'utf8');
const policy = (overrides = {}) => ({ desired_enabled:false, active_today:false, pending_disable:false, effective_at:null, effective_date:null, ordinary_limit_percent:10, current_limit_percent:10, revision:0, as_of:'2026-09-30T09:01:00+08:00', ...overrides });
const enabled = (revision = 1, overrides = {}) => policy({ desired_enabled:true, active_today:true, current_limit_percent:20, revision, ...overrides });
const response = value => ({ ok:true, json:async () => JSON.parse(JSON.stringify(value)) });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
async function flush() { for (let count = 0; count < 25; count++) await Promise.resolve(); }

function setup(fetcher, { role = 'admin', viewerId = '2' } = {}) {
  const calls = [], events = [], timeouts = new Map();
  const env = harness({ fetch:(url, options = {}) => { calls.push({ url:String(url), options }); return fetcher(url, options); } });
  env.document.body.dataset.role = role; env.document.body.dataset.viewerId = viewerId;
  const listeners = new Map(), windowListeners = new Map();
  const add = (map, type, fn) => { if (!map.has(type)) map.set(type, new Set()); map.get(type).add(fn); };
  env.document.addEventListener = (type, fn) => add(listeners, type, fn);
  env.document.removeEventListener = (type, fn) => listeners.get(type)?.delete(fn);
  env.document.dispatchEvent = event => { events.push(event); for (const fn of [...(listeners.get(event.type) || [])]) fn(event); };
  env.window.addEventListener = (type, fn) => add(windowListeners, type, fn);
  env.window.removeEventListener = (type, fn) => windowListeners.get(type)?.delete(fn);
  env.window.setTimeout = (fn, delay) => { const id = timeouts.size + 1; timeouts.set(id, { fn, delay, active:true }); return id; };
  env.window.clearTimeout = id => { if (timeouts.has(id)) timeouts.get(id).active = false; };
  const host = new Element(), button = new Element('button'), status = new Element('span'), feedback = new Element('p'), badge = new Element('small');
  const controls = new Map([['[data-index-challenge-toggle]', button], ['[data-index-challenge-status]', status], ['[data-index-challenge-feedback]', feedback]]);
  host.querySelector = selector => controls.get(selector) || null;
  host.querySelectorAll = selector => selector === '[data-index-challenge-toggle]' ? [button] : [];
  env.document.querySelectorAll = selector => selector === '[data-index-challenge]' ? [host] : selector === '[data-index-challenge-toggle]' ? [button] : selector === '[data-index-challenge-badge]' ? [badge] : [];
  vm.runInContext(source, env.context, { filename:'index-challenge.js' });
  const api = env.window.IndexChallenge;
  const changes = () => events.filter(event => event.type === 'dashboard:challenge-updated');
  return { ...env, api, calls, changes, host, button, status, feedback, badge, timeouts, emit:type => env.document.dispatchEvent({ type }), show:() => [...(windowListeners.get('pageshow') || [])].forEach(fn => fn({ persisted:true })) };
}

test('revision and account-midnight guards reject old policy while accepting identical older policy without regressing as_of', () => {
  const env = setup(async () => response({ challenge:policy() }));
  assert.equal(env.api.accept(enabled(4, { as_of:'2026-09-30T23:59:59+08:00' })), true);
  assert.equal(env.api.accept(enabled(3, { as_of:'2026-10-01T00:02:00+08:00' })), false);
  assert.equal(env.api.accept(enabled(4, { as_of:'2026-09-30T23:50:00+08:00' })), true);
  assert.equal(env.api.getState().as_of, '2026-09-30T23:59:59+08:00');
  const pending = enabled(5, { desired_enabled:false, pending_disable:true, effective_at:'2026-10-01T00:00:00+08:00' });
  env.api.accept(pending);
  env.api.accept(policy({ revision:5, as_of:'2026-10-01T00:01:00+08:00' }));
  assert.equal(env.api.accept({ ...pending, as_of:'2026-09-30T23:59:59+08:00' }), false);
  assert.equal(env.api.getState().current_limit_percent, 10);
  assert.equal(env.badge.hidden, true);
});

test('pending disable keeps today twenty and reenable changes the authoritative action to close', () => {
  const env = setup(async () => response({ challenge:policy() }));
  env.api.accept(enabled());
  assert.equal(env.button.textContent, '关闭挑战');
  env.api.accept(enabled(2, { desired_enabled:false, pending_disable:true, effective_at:'2026-10-01T00:00:00+08:00' }));
  assert.equal(env.button.textContent, '继续挑战');
  assert.equal(env.badge.textContent, '今日 ±20%');
  assert.match(env.status.textContent, /本日 ±20%.*明日/);
  assert.match(env.status.title, /2026-10-01T00:00:00\+08:00/);
  env.api.accept(enabled(3));
  assert.equal(env.button.textContent, '关闭挑战');
  assert.equal(env.badge.textContent, '挑战 · ±20%');
});

test('actual toggle shows pending before PATCH, serializes duplicate presses and adopts only the server response', async () => {
  const patch = deferred(); let server = policy();
  const env = setup(async (_url, options) => options.method === 'PATCH' ? patch.promise : response({ challenge:server }));
  env.api.accept(server); const dispose = env.api.mount();
  env.button.listeners.get('click')();
  const waiting = env.api.setEnabled(true);
  assert.equal(env.api.setEnabled(false), waiting);
  assert.equal(env.button.disabled, true); assert.equal(env.host.getAttribute('aria-busy'), 'true');
  assert.equal(env.api.getState().desired_enabled, false);
  await flush();
  const writes = env.calls.filter(call => call.options.method === 'PATCH');
  assert.equal(writes.length, 1); assert.deepEqual(JSON.parse(writes[0].options.body), { enabled:true });
  server = enabled(); patch.resolve(response({ challenge:server }));
  assert.equal(await waiting, true); await flush();
  assert.equal(env.api.getState().desired_enabled, true); assert.equal(env.button.disabled, false);
  assert.equal(env.changes().length, 1);
  dispose(); assert.equal(env.button.listeners.has('click'), false);
});

test('PATCH begins while an old GET is held; the old response cannot undo the toggle or suppress queued reconciliation', async () => {
  const oldRead = deferred(), write = deferred(); let gets = 0, server = policy();
  const env = setup(async (_url, options) => options.method === 'PATCH' ? write.promise : ++gets === 1 ? oldRead.promise : response({ challenge:server }));
  env.api.accept(server); const reading = env.api.refresh(); const writing = env.api.setEnabled(true);
  await flush(); assert.equal(env.calls.filter(call => call.options.method === 'PATCH').length, 1);
  server = enabled(7); write.resolve(response({ challenge:server })); await writing;
  oldRead.resolve(response({ challenge:policy({ as_of:'2026-09-30T09:02:00+08:00' }) }));
  await reading; await flush();
  assert.equal(env.api.getState().revision, 7); assert.equal(env.api.getState().desired_enabled, true);
  assert.equal(gets, 2); assert.equal(env.changes().length, 1);
});

test('guest and public identity guards hide editing and never issue PATCH', async () => {
  for (const identity of [{ role:'guest', viewerId:'2' }, { role:'admin', viewerId:'public' }]) {
    const env = setup(async () => response({ challenge:enabled() }), identity);
    env.api.accept(enabled()); env.api.mount();
    assert.equal(env.button.hidden, true); assert.equal(env.button.disabled, true);
    assert.equal(await env.api.setEnabled(false), false);
    assert.equal(env.calls.length, 0); assert.match(env.status.title, /访客仅可查看/);
  }
});

test('PATCH timeout recovers pending feedback and rereads persisted state without optimistic enable', async () => {
  const env = setup(async (_url, options) => {
    if (options.method !== 'PATCH') return response({ challenge:policy() });
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted'))));
  });
  env.api.accept(policy()); const writing = env.api.setEnabled(true); await flush();
  const timeout = [...env.timeouts.values()].find(timer => timer.active);
  assert.equal(timeout.delay, 15000); timeout.fn();
  assert.equal(await writing, false); await flush();
  assert.equal(env.api.getState().desired_enabled, false); assert.equal(env.button.disabled, false);
  assert.equal(env.feedback.hidden, false); assert.match(env.feedback.textContent, /重新读取服务端/);
  assert.equal(env.calls.filter(call => call.options.method !== 'PATCH').length, 1);
});

test('independent poll and visible/pageshow sync emit once per actual cross-client or account-day policy change', async () => {
  let server = enabled(2);
  const env = setup(async () => response({ challenge:server }));
  env.emit('DOMContentLoaded'); await flush();
  assert.equal(env.changes().length, 0); assert.equal(env.button.textContent, '关闭挑战');
  server = enabled(3, { desired_enabled:false, pending_disable:true, as_of:'2026-09-30T23:59:59+08:00' });
  await env.intervals.find(timer => timer.delay === 15000).fn();
  assert.equal(env.changes().length, 1);
  server = { ...server, as_of:'2026-09-30T23:59:59.500+08:00' }; await env.api.refresh();
  assert.equal(env.changes().length, 1);
  env.document.hidden = true; await env.api.refresh(true); const before = env.calls.length;
  server = policy({ revision:3, as_of:'2026-10-01T00:00:01+08:00' });
  env.document.hidden = false; env.emit('visibilitychange'); await flush();
  assert.equal(env.calls.length, before + 1); assert.equal(env.changes().length, 2); assert.equal(env.button.textContent, '开启挑战');
  env.show(); await flush(); assert.equal(env.changes().length, 2);
  const secondClient = setup(async () => response({ challenge:server })); await secondClient.api.refresh();
  assert.equal(secondClient.api.getState().revision, 3); assert.equal(secondClient.api.getState().active_today, false);
});

function quotes(challenge = policy()) {
  const day = { date:'2026-09-30', open:100, high:100, low:100, close:100, trading_sessions:sessions };
  const intraday = [{ timestamp:'2026-09-30T09:01:00+08:00', price:100 }];
  const shared = { challenge, previous_close:100, intraday_date:day.date, intraday, index:{ current:100 }, today_focus_seconds:60, limit_down:90, limit_up:110 };
  return { full:{ ...shared, candles:[day], today:day, updated_at:challenge.as_of }, live:{ ...shared, generated_at:challenge.as_of, market_active:true, is_focusing:true, live_tick:{ timestamp:challenge.as_of, value_at:100, per_second:.001 } } };
}

test('Home challenge change freezes the old projection while hidden and forces full/live on return without old caps rewriting state', async () => {
  let payload = quotes(), held = null; const policyState = enabled(1);
  const env = setup(async (url) => {
    if (String(url).includes('/challenge')) return response({ challenge:policyState });
    if (held) { const waiting = held; held = null; return waiting.promise; }
    return response(String(url).endsWith('/live') ? payload.live : payload.full);
  });
  const exposed = homeSource.replace(/\}\)\(\);\s*$/, 'globalThis.homeTest = { full:refreshFull, live:refreshLive, tick:liveSecond, data:() => latest };})();');
  vm.runInContext(exposed, env.context, { filename:'dashboard-index.js' });
  await env.context.homeTest.full(); await env.context.homeTest.live();
  const old = deferred(); held = old; const pending = env.context.homeTest.live(true);
  env.document.hidden = true; env.api.accept(policyState); env.clock.now += 1000;
  env.context.homeTest.tick(); assert.equal(env.context.homeTest.data().current, 100);
  old.resolve(response(payload.live)); await pending;
  payload = quotes(policyState); payload.full.limit_up = payload.live.limit_up = 120; payload.full.limit_down = payload.live.limit_down = 80;
  env.document.hidden = false; env.emit('visibilitychange'); await flush();
  await env.context.homeTest.full(); await env.context.homeTest.live();
  assert.equal(env.context.homeTest.data().challenge.revision, 1);
  assert.equal(env.context.homeTest.data().limit_up, 120);
  assert.equal(env.context.homeTest.data().limit_down, 80);
});

test('full-page summary rejects stale challenge quote and preserves historical selection/range during policy reconciliation', async () => {
  let payload = quotes().live;
  const env = setup(async () => response(payload));
  env.api.accept(enabled(6));
  const exposed = fullSource.replace(/\}\)\(\);\s*$/, 'globalThis.fullTest = { state, normalizePayload, refreshSummary };})();');
  vm.runInContext(exposed, env.context, { filename:'focus_kline.js' });
  const api = env.context.fullTest;
  api.state.payload = api.normalizePayload(quotes(enabled(6)).full);
  api.state.selectedDate = '2026-09-29'; api.state.rangeDays = 30;
  const before = api.state.payload; payload.index.current = 109;
  await api.refreshSummary(true);
  assert.equal(api.state.payload, before); assert.equal(api.state.payload.current, 100);
  payload = quotes(enabled(6, { as_of:'2026-09-30T09:02:00+08:00' })).live;
  payload.limit_down = 80; payload.limit_up = 120; payload.is_paused = true;
  await api.refreshSummary(true);
  assert.equal(api.state.payload.limits.high, 120); assert.equal(env.get('#kline-focus-status').textContent, '已暂停');
  assert.equal(api.state.selectedDate, '2026-09-29'); assert.equal(api.state.rangeDays, 30);
});
