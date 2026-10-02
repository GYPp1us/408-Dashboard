const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { harness, sessions } = require('./frontend_market_harness.cjs');
const source = fs.readFileSync(path.join(__dirname, '../app/static/dashboard-index.js'), 'utf8');
const exposed = source.replace(/\}\)\(\);\s*$/, 'globalThis.v041 = { full:refreshFull, live:refreshLive, tick:liveSecond, quote:updateQuote, stats:dayStatistics, data:() => latest };})();');
const iso = second => `2026-09-30T09:01:${String(second).padStart(2, '0')}+08:00`;
async function setup() {
  let held = null, generated = iso(0), active = true, slope = .001;
  const calls = [], day = { date:'2026-09-30', open:100, high:100.1, low:99.9, close:100, trading_sessions:sessions };
  const intraday = [{ timestamp:'2026-09-30T09:00:00+08:00', price:99.9 }, { timestamp:iso(0), price:100 }];
  const full = { candles:[day], today:day, intraday_date:day.date, intraday, previous_close:100, index:{ current:100 }, updated_at:iso(0), today_focus_seconds:60 };
  const env = harness({ fetch:async url => {
    calls.push(url);
    if (!url.endsWith('/live')) return { ok:true, json:async () => full };
    if (held) { const promise = held; held = null; return promise; }
    return { ok:true, json:async () => ({ today:day, intraday_date:day.date, intraday, previous_close:100, index:{ current:100 }, generated_at:generated, market_active:active, live_tick:{ timestamp:iso(0), value_at:100, per_second:slope }, today_focus_seconds:60 }) };
  } });
  vm.runInContext(exposed, env.context, { filename:'dashboard-index.js' });
  const api = env.context.v041; await api.full(); await api.live();
  return { ...env, api, calls, day, intraday, setGenerated:value => { generated = value; }, closed:() => { active = false; }, flat:() => { slope = 0; }, hold:() => { let release; held = new Promise(resolve => { release = resolve; }); return release; } };
}

test('one-second live requests adopt real motion, serialize in-flight work and leave full history at its original frequency', async () => {
  const env = await setup(), fullCount = env.calls.filter(url => !url.endsWith('/live')).length;
  for (let second = 1; second <= 3; second++) {
    env.clock.now += 1000; env.setGenerated(iso(second)); await env.api.live(); env.api.tick();
    assert.equal(env.get('[data-index-points]').textContent, (100 + second * .001).toFixed(3));
    assert.equal(env.get('[data-index-points]').classList.contains('is-tick-up'), true);
  }
  assert.equal(env.calls.filter(url => !url.endsWith('/live')).length, fullCount);
  assert.equal(env.intervals.filter(timer => timer.delay === 1000).length, 2);
  env.clock.now += 1000; const release = env.hold(); const pending = env.api.live(); const before = env.calls.length;
  env.clock.now += 1000; env.api.live(); env.api.live(); assert.equal(env.calls.length, before);
  release({ ok:false, status:503 }); await pending;
});

test('percent arithmetic stays unchanged and a flat or closed market never fabricates a flash', async () => {
  const env = await setup();
  env.api.quote(110, 100);
  assert.equal(env.get('[data-index-change]').textContent, '+10.000');
  assert.equal(env.get('[data-index-percent]').textContent, '(+10.00%)');
  const target = env.get('[data-index-points]'); target.classList.remove('is-tick-up', 'is-tick-down');
  env.api.quote(110, 100); assert.equal(target.classList.contains('is-tick-up'), false);
  env.flat(); await env.api.live(true); target.classList.remove('is-tick-up', 'is-tick-down');
  env.clock.now += 1000; env.api.tick(); assert.equal(target.classList.contains('is-tick-up'), false); assert.equal(target.classList.contains('is-tick-down'), false);
  env.closed(); await env.api.live(true); target.classList.remove('is-tick-up', 'is-tick-down');
  env.clock.now += 1000; env.api.tick(); assert.equal(target.classList.contains('is-tick-up'), false); assert.equal(target.classList.contains('is-tick-down'), false);
});

test('today high low open and mean combine official OHLC with the bounded real current quote', async () => {
  const env = await setup();
  assert.equal(env.get('[data-index-high]').textContent, '100.100');
  assert.equal(env.get('[data-index-low]').textContent, '99.900');
  assert.equal(env.get('[data-index-open]').textContent, '100.000');
  assert.equal(env.get('[data-index-average]').textContent, '99.950');
  const stats = env.api.stats(env.api.data(), 100.2, { active:true, time:Date.parse(iso(1)) / 1000 });
  assert.equal(stats.high, 100.2); assert.equal(stats.low, 99.9);
  assert.ok(Math.abs(stats.average - (99.95 * 60 + 100.1) / 61) < 1e-10);
});

test('time-weighted mean excludes lunch and preserves both sides of same-time jumps without counting an event twice', async () => {
  const env = await setup();
  const trading = [{ name:'am', start:'2026-09-30T08:00:00+08:00', end:'2026-09-30T09:00:00+08:00' }, { name:'pm', start:'2026-09-30T10:00:00+08:00', end:'2026-09-30T11:00:00+08:00' }];
  const data = { ...env.api.data(), day:{ ...env.day, high:200, low:100, trading_sessions:trading }, candles:[], intraday:[{ timestamp:trading[0].start, price:100 }, { timestamp:trading[0].end, price:100 }, { timestamp:trading[1].start, price:100 }, { timestamp:trading[1].start, price:200, changed:true }, { timestamp:trading[1].end, price:200 }] };
  const stats = env.api.stats(data, 200);
  assert.equal(stats.average, 150); assert.equal(stats.open, 100); assert.equal(stats.high, 200);
  const prior = { ...data, intraday_date:'2026-09-29', day:{ ...data.day, date:'2026-09-29' }, today:null };
  assert.equal(env.api.stats(prior, 200), null);
});
