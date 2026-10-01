const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { harness, Element, sessions } = require('./frontend_market_harness.cjs');

const source = fs.readFileSync(path.join(__dirname, '../app/static/dashboard-index.js'), 'utf8');
const exposed = source.replace(/\}\)\(\);\s*$/, 'globalThis.indexTest = { full:refreshFull, live:refreshLive, tick:liveSecond, chart:() => homeChart, data:() => latest, createChart };})();');

function payloads() {
  const day = { date:'2026-09-30', open:100, high:100.1, low:99.9, close:100.002, trading_sessions:sessions };
  const intraday = [
    { timestamp:'2026-09-30T09:00:17+08:00', price:100 },
    { timestamp:'2026-09-30T09:00:17+08:00', price:99.95, changed:true },
    { timestamp:'2026-09-30T09:01:00+08:00', price:100.002 },
  ];
  return {
    full:{ candles:[day], today:day, intraday_date:day.date, intraday, previous_close:100, index:{ current:100.002 }, today_focus_seconds:60, updated_at:'2026-09-30T09:01:00+08:00' },
    live:{ intraday_date:day.date, intraday, previous_close:100, index:{ current:100.002 }, limit_down:90, limit_up:110, generated_at:'2026-09-30T09:01:00+08:00', market_active:true, is_focusing:true, today_focus_seconds:60, live_tick:{ timestamp:'2026-09-30T09:01:00+08:00', value_at:100.002, per_second:.001 } },
  };
}

async function home() {
  const data = payloads(), calls = [];
  let live = data.live, unavailable = false, nextLive = null, nextFull = null;
  const env = harness({ fetch:async url => {
    calls.push(url);
    const override = url.endsWith('/live') ? nextLive : nextFull;
    if (override) {
      if (url.endsWith('/live')) nextLive = null; else nextFull = null;
      return override();
    }
    if (unavailable && url.endsWith('/live')) throw new Error('offline');
    return { ok:true, json:async () => JSON.parse(JSON.stringify(url.endsWith('/live') ? live : data.full)) };
  } });
  vm.runInContext(exposed, env.context, { filename:'dashboard-index.js' });
  const api = env.context.indexTest;
  await api.full(); await api.live();
  const hold = (kind) => {
    let release;
    const waiting = new Promise(resolve => { release = payload => resolve({ ok:true, json:async () => JSON.parse(JSON.stringify(payload)) }); });
    if (kind === 'live') nextLive = () => waiting; else nextFull = () => waiting;
    return release;
  };
  return { ...env, api, calls, data, setLive:next => { live = next; }, holdLive:() => hold('live'), holdFull:() => hold('full'), offline:() => { unavailable = true; } };
}

test('home uses configured open-to-close proportions, preserves equal-time jumps and removes event dots', async () => {
  const env = await home(), chart = env.api.chart();
  const scale = chart.chart.timeScale();
  const open = Date.parse(sessions[0].start) / 1000, close = Date.parse(sessions[1].end) / 1000;
  assert.equal(chart.chart.linearTime, true);
  assert.equal(scale.timeToCoordinate(open), 6);
  assert.equal(scale.timeToCoordinate(close), 538);
  const noon = Date.parse(sessions[0].end) / 1000;
  assert.ok(Math.abs((scale.timeToCoordinate(noon) - 6) / 532 - (noon - open) / (close - open)) < 1e-12);
  const first = chart.lines[0].data;
  assert.equal(first[0].time, first[1].time);
  assert.deepEqual(Array.from(first.slice(0, 2), item => item.value), [100, 99.95]);
  assert.equal(scale.timeToCoordinate(first[0].time), scale.timeToCoordinate(first[1].time));
  assert.equal(chart.lines.flatMap(line => line.markers).length, 0);
  assert.equal(env.calls.filter(url => !url.endsWith('/live')).length, 1);
});

test('home appends one-second points and briefly flashes the quote without reloading full history', async () => {
  const env = await home(), initialCalls = env.calls.length;
  env.clock.now += 1000; env.api.tick();
  const first = env.api.chart().lines[0].data;
  assert.equal(first.at(-1).time, Date.parse('2026-09-30T09:01:01+08:00') / 1000);
  assert.equal(first.at(-1).value, 100.003);
  assert.equal(env.get('[data-index-points]').textContent, '100.003');
  assert.equal(env.get('[data-index-points]').classList.contains('is-tick-up'), true);
  assert.equal(env.calls.length, initialCalls);
  assert.equal(env.intervals.find(item => item.delay === 15000).delay, 15000);
});

test('home freezes a lost-network projection after twenty seconds and keeps the existing path', async () => {
  const env = await home();
  env.clock.now += 20_000; env.api.tick();
  const value = env.get('[data-index-points]').textContent;
  const lastTime = env.api.chart().lines[0].data.at(-1).time;
  env.offline(); await env.api.live(true);
  env.clock.now += 60_000; env.api.tick();
  assert.equal(env.get('[data-index-points]').textContent, value);
  assert.equal(env.api.chart().lines[0].data.at(-1).time, lastTime);
  assert.match(env.get('[data-index-updated]').textContent, /最近数据/);
});

test('closed-market snapshots show the server close and never append motion', async () => {
  const env = await home(), before = env.api.chart().lines[0].data.length;
  env.setLive({ ...env.data.live, market_active:false, index:{ current:100.1 }, live_tick:{ ...env.data.live.live_tick, per_second:99 } });
  await env.api.live(true); env.clock.now += 1000; env.api.tick();
  assert.equal(env.get('[data-index-points]').textContent, '100.100');
  assert.equal(env.api.chart().lines[0].data.length, before);
});

test('index update labels use the supplied account offset rather than the device default timezone', async () => {
  const env = await home();
  assert.match(env.get('[data-index-updated]').textContent, /09:01:00/);
  const market = env.api.chart().market;
  env.clock.now += 1000; env.api.tick();
  assert.equal(env.Market.clockSeconds(env.api.chart().lines[0].data.at(-1).time, market.offset), '09:01:01');
});

test('rapid forced state refreshes coalesce after an in-flight response and never resume its superseded direction', async () => {
  const env = await home(), release = env.holdLive(), before = env.calls.length;
  const running = env.api.live(true);
  env.clock.now += 1000; env.api.tick();
  assert.equal(env.get('[data-index-points]').textContent, '100.002', 'the old slope freezes immediately while forced reconciliation waits');
  const queued1 = env.api.live(true), queued2 = env.api.live(true);
  assert.equal(env.calls.length, before + 1);
  const fresh = { ...env.data.live, index:{ current:100.4 }, live_tick:{ ...env.data.live.live_tick, value_at:100.4, per_second:0 }, is_paused:false };
  env.setLive(fresh);
  release({ ...env.data.live, index:{ current:99 }, live_tick:{ ...env.data.live.live_tick, value_at:99, per_second:-1 } });
  await Promise.all([running, queued1, queued2]);
  assert.equal(env.calls.length, before + 2, 'one follow-up request handles all newer state changes');
  assert.equal(env.get('[data-index-points]').textContent, '100.400');
});

test('pause and resume while the index tab is hidden retain one forced refresh until the view returns', async () => {
  const env = await home(), view = env.get('#activity-index-view'), before = env.calls.length;
  view.hidden = true;
  await env.api.live(true); await env.api.live(true);
  assert.equal(env.calls.length, before);
  env.setLive({ ...env.data.live, index:{ current:99.9 }, live_tick:{ ...env.data.live.live_tick, value_at:99.9, per_second:0 } });
  view.hidden = false;
  await env.api.live();
  assert.equal(env.calls.length, before + 1);
  assert.equal(env.get('[data-index-points]').textContent, '99.900', 'the cached quote is replaced immediately, before the fifteen-second throttle');
});

test('forced full-history refresh while pending coalesces and rejects the superseded full response', async () => {
  const env = await home(), release = env.holdFull(), before = env.calls.filter(url => !url.endsWith('/live')).length;
  const running = env.api.full(true), queued = env.api.full(true);
  env.data.full = { ...env.data.full, index:{ current:100.6 } };
  release({ ...env.data.full, index:{ current:99 } });
  await Promise.all([running, queued]); await env.api.live();
  assert.equal(env.calls.filter(url => !url.endsWith('/live')).length, before + 2);
  assert.equal(env.api.data().index.current, 100.6);
});

test('a full-history response from before midnight cannot overwrite the newly requested account day', async () => {
  const env = await home(), release = env.holdFull(), oldFull = env.data.full;
  const running = env.api.full(true);
  const advance = value => JSON.parse(JSON.stringify(value).replaceAll('2026-09-30', '2026-10-01'));
  env.data.full = advance(oldFull);
  env.data.full.index.current = 100.2;
  const nextLive = advance(env.data.live); nextLive.index.current = 100.2; nextLive.live_tick.value_at = 100.2;
  nextLive.generated_at = '2026-10-01T00:00:01+08:00'; nextLive.market_active = false;
  env.setLive(nextLive);
  env.clock.now = Date.parse('2026-10-01T00:00:01+08:00');
  env.listeners.get('dashboard:updated')({ detail:{ now:'2026-10-01T00:00:01+08:00', focus:{ active:null }, today_focus:{ count:0 } } });
  release(oldFull);
  await running; await env.api.live();
  assert.equal(env.api.data().day.date, '2026-10-01');
  assert.equal(env.api.data().index.current, 100.2);
  assert.ok(env.calls.some(url => url.includes('date=2026-10-01')));
});

test('daily drawer leaves BusinessDay tick and crosshair formatting to the chart library', async () => {
  const env = await home(), applied = [];
  let options;
  env.window.LightweightCharts.createChart = (_host, config) => {
    options = config;
    return {
      addSeries:() => ({ setData() {}, applyOptions() {} }),
      applyOptions:config => applied.push(config),
      remove() {},
    };
  };
  const daily = env.api.createChart(new Element(), true);
  assert.equal(daily.daily, true);
  assert.equal(options.localization.locale, 'zh-CN');
  assert.equal(Object.hasOwn(options.timeScale, 'tickMarkFormatter'), false, 'BusinessDay ticks must retain the library date formatter instead of the intraday blank label');
  assert.equal(Object.hasOwn(options.localization, 'timeFormatter'), false, 'BusinessDay crosshairs must retain date formatting instead of String(object)');
  assert.ok(applied.some(config => config.timeScale?.timeVisible === false));
});
