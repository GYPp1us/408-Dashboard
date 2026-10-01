const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { harness, Element, sessions } = require('./frontend_market_harness.cjs');

const source = fs.readFileSync(path.join(__dirname, '../app/static/focus_kline.js'), 'utf8');
const exposed = source.replace(/\}\)\(\);\s*$/, 'globalThis.klineTest = { state, bind, refreshSummary, drawIntradayChart, normalizePayload, formatTime, chartDate, chartTimeLabel, lightweightOptions, startLiveTicks, stopLiveTicks };})();');
const appSource = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
const appExposed = appSource.replace(/\}\)\(\);\s*$/, 'globalThis.nativeTest = { state, refreshVisiblePage, bindNativePageBridge };})();');
const unix = value => Date.parse(value) / 1000;
const nearly = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} should equal ${expected}`);
const walk = node => [node, ...node.children.flatMap(walk)];

function pathDay() {
  return {
    date:'2026-09-30', open:100, high:101, low:9.2, close:10, previousClose:100,
    tradingSessions:sessions, intraday:[
      { time:'2026-09-30T09:00:17+08:00', value:100 },
      { time:'2026-09-30T09:00:17+08:00', value:101, event:true },
      { time:sessions[0].end, value:100.7 },
      { time:sessions[1].start, value:100.5 },
      { time:sessions[1].end, value:9.2 },
      { time:sessions[1].end, value:10, floorReset:true },
    ],
  };
}

function fullChart(day = pathDay()) {
  const env = harness({ now:'2026-10-01T09:01:00+08:00' });
  vm.runInContext(exposed, env.context, { filename:'focus_kline.js' });
  env.context.klineTest.state.selectedDate = day.date;
  env.context.klineTest.drawIntradayChart({ days:[day], today:day, limits:{ low:90, high:110 }, initialIndex:100, priceTick:.001, updatedAt:'2026-09-30T20:30:49+08:00' });
  return { ...env, view:env.context.klineTest.state.liveIntraday };
}

test('full page fixes the entire configured market day and leaves proportional wall-clock lunch space', () => {
  const env = fullChart(), { market, chart, series } = env.view;
  assert.equal(chart.linearTime, true);
  const scale = chart.timeScale(), openX = scale.timeToCoordinate(market.open), closeX = scale.timeToCoordinate(market.close);
  assert.equal(openX, 6); assert.equal(closeX, 538);
  for (const at of [market.open + 1, unix(sessions[0].end), unix(sessions[1].start), market.close - 1]) {
    nearly((scale.timeToCoordinate(at) - openX) / (closeX - openX), (at - market.open) / (market.close - market.open));
  }
  assert.ok(scale.timeToCoordinate(unix(sessions[1].start)) > scale.timeToCoordinate(unix(sessions[0].end)));
  assert.equal(series.length, 2);
  assert.equal(series[0].data.at(-1).time, unix(sessions[0].end));
  assert.equal(series[1].data[0].time, unix(sessions[1].start));
  const labels = walk(env.get('#kline-intraday-chart')).filter(node => node.tagName === 'text').map(node => node.textContent);
  assert.ok(labels.includes('08:15')); assert.ok(labels.includes('20:30'));
  assert.equal(labels.includes('00:00'), false);
});

test('event seconds and both sides of exact-time jumps survive full-page rendering and inspection', () => {
  const env = fullChart(), { chart, series } = env.view;
  assert.equal(series[0].data[0].time, series[0].data[1].time);
  assert.equal(series[0].data[0].value, 100); assert.equal(series[0].data[1].value, 101);
  assert.equal(series[1].data.at(-2).time, series[1].data.at(-1).time);
  assert.equal(series[1].data.at(-2).value, 9.2); assert.equal(series[1].data.at(-1).value, 10);
  assert.equal(series.flatMap(line => line.markers).length, 2);
  const host = env.get('#kline-intraday-chart'), svg = host.children.find(node => node.tagName === 'svg');
  svg.listeners.get('pointerdown')({ clientX:chart.timeScale().timeToCoordinate(series[0].data[1].time) });
  assert.match(host.children.find(node => node.className === 'market-intraday-tooltip').textContent, /09:00:17.*101\.000.*专注状态切换/);
  const before = chart.timeScale().timeToCoordinate(unix(sessions[1].start));
  series[0].setData([...series[0].data, { time:unix(sessions[0].end) - .1, value:100.8 }]);
  assert.equal(chart.timeScale().timeToCoordinate(unix(sessions[1].start)), before);
});

test('empty intraday charts still show the configured opening and closing endpoints', () => {
  const day = pathDay(); day.intraday = [];
  const env = fullChart(day), host = env.get('#kline-intraday-chart');
  assert.equal(host.hidden, false);
  const labels = walk(host).filter(node => node.tagName === 'text').map(node => node.textContent);
  assert.ok(labels.includes('08:15')); assert.ok(labels.includes('20:30'));
  assert.equal(env.get('#kline-intraday-empty').hidden, false);
  nearly(env.view.chart.timeScale().timeToCoordinate(env.view.market.open + 17), 6 + 532 * 17 / (env.view.market.close - env.view.market.open));
});

test('shared market clock respects configured offsets and non-minute session endpoints', () => {
  const { Market } = harness();
  const market = Market.market('2026-09-30', [{ start:'2026-09-30T08:15:17+05:30', end:'2026-09-30T20:30:49+05:30' }]);
  assert.equal(Market.clockSeconds(market.open, market.offset), '08:15:17');
  assert.equal(Market.clockSeconds(market.close, market.offset), '20:30:49');
  assert.equal(Market.dateAt(market.open, market.offset), '2026-09-30');
  assert.equal(Market.sessionIndex(market, market.close, false), -1);
  assert.equal(Market.sessionIndex(market, market.close), 0);
  const configured = Market.market('2026-09-30', [{ start:'07:45', end:'19:15' }], '2026-09-30T09:00:00+08:00');
  assert.equal(Market.clock(configured.open, configured.offset), '07:45');
  assert.equal(Market.clock(configured.close, configured.offset), '19:15');
});

test('shared projection is bounded, limit-clamped, frozen when closed and never crosses lunch', () => {
  const { Market } = harness(), market = Market.market('2026-09-30', sessions);
  const receivedAt = Date.parse('2026-09-30T09:01:00+08:00');
  const snapshot = { generated_at:'2026-09-30T09:01:00+08:00', receivedAt, market_active:true, index:{ current:100 }, limit_down:90, limit_up:110, live_tick:{ timestamp:'2026-09-30T09:01:00+08:00', value_at:100, per_second:.01 } };
  nearly(Market.project(snapshot, market, receivedAt + 1000).value, 100.01);
  assert.equal(Market.project(snapshot, market, receivedAt + 1000).time, receivedAt / 1000 + 1);
  const atTwenty = Market.project(snapshot, market, receivedAt + 20_000), lost = Market.project(snapshot, market, receivedAt + 120_000);
  assert.equal(lost.value, atTwenty.value); assert.equal(lost.time, atTwenty.time);
  assert.equal(lost.active, false); assert.equal(lost.stale, true);
  assert.equal(Market.project({ ...snapshot, limit_up:100.005 }, market, receivedAt + 1000).value, 100.005);
  assert.equal(Market.project({ ...snapshot, market_active:false, index:{ current:99.7 } }, market, receivedAt + 1000).value, 99.7);
  const beforeLunch = { ...snapshot, generated_at:'2026-09-30T12:00:20+08:00', receivedAt:Date.parse('2026-09-30T12:00:20+08:00'), live_tick:{ ...snapshot.live_tick, timestamp:'2026-09-30T11:59:23+08:00' } };
  const lunch = Market.project(beforeLunch, market, beforeLunch.receivedAt + 10_000);
  assert.equal(lunch.active, false); assert.ok(lunch.time < unix(sessions[0].end));
  const preOpen = { ...snapshot, generated_at:'2026-09-30T07:00:00+08:00', receivedAt:Date.parse('2026-09-30T07:00:00+08:00') };
  assert.equal(Market.project(preOpen, market, preOpen.receivedAt + 1000).active, false);
});

test('server reconciliation replaces provisional seconds but preserves formal same-time event jumps', () => {
  const { Market } = harness(), market = Market.market('2026-09-30', sessions);
  const raw = [{ time:'2026-09-30T09:01:00+08:00', value:100 }];
  const timeline = Market.timeline(market).reconcile(raw, item => item.time, item => item.value);
  timeline.append(unix(raw[0].time) + 1, 100.001); timeline.append(unix(raw[0].time) + 2, 100.002);
  assert.equal(timeline.groups[0].length, 3);
  timeline.reconcile([...raw, { time:'2026-09-30T09:02:00+08:00', value:99.9 }, { time:'2026-09-30T09:02:00+08:00', value:100.2, changed:true }], item => item.time, item => item.value);
  assert.equal(timeline.groups[0].length, 3);
  assert.equal(timeline.groups[0].at(-2).time, timeline.groups[0].at(-1).time);
  assert.equal(timeline.groups[0].at(-2).value, 99.9); assert.equal(timeline.groups[0].at(-1).value, 100.2);
  assert.equal(timeline.events[0].length, 1);
  assert.equal(timeline.append(unix(sessions[0].end) + 1, 100), -1);
});

test('full-page timestamp and business-date labels retain the API account timezone on a UTC device', () => {
  const env = harness();
  vm.runInContext(exposed, env.context, { filename:'focus_kline.js' });
  const api = env.context.klineTest;
  assert.equal(api.formatTime('2026-09-30T19:00:00+08:00'), '19:00');
  assert.equal(api.formatTime('2026-09-30T09:10:20-04:00'), '09:10');
  assert.equal(api.chartTimeLabel('2026-10-01'), '10/01');
  assert.equal(api.chartTimeLabel({ year:2026, month:10, day:1 }), '10/01');
});

test('full-page daily tick and crosshair formatters support BusinessDay objects and ISO date strings', () => {
  const env = harness();
  vm.runInContext(exposed, env.context, { filename:'focus_kline.js' });
  const api = env.context.klineTest, options = api.lightweightOptions(new Element());
  for (const value of [{ year:2026, month:10, day:1 }, '2026-10-01', '2026-10-01T00:10:00+08:00']) {
    assert.equal(Number.isNaN(api.chartDate(value).getTime()), false);
    assert.equal(options.timeScale.tickMarkFormatter(value), '10/01');
    assert.equal(options.localization.timeFormatter(value), '10/01');
  }
  assert.equal(options.timeScale.tickMarkFormatter(unix('2026-09-30T19:00:00+08:00')), '19:00');
  assert.equal(options.localization.timeFormatter(unix('2026-09-30T19:00:00+08:00')), '19:00');
});

async function liveFullPage({ nativeBridge = false, initialSlope = 0 } = {}) {
  let snapshot, nextFetch = null, dashboardFocus = null;
  const calls = [];
  const env = harness({ fetch:async url => {
    calls.push(url);
    if (url === '/api/dashboard') return { ok:true, json:async () => ({ now:'2026-09-30T09:01:00+08:00', preferences:{ viewer_id:2 }, focus:{ active:dashboardFocus, today:[] } }) };
    if (nextFetch) { const waiting = nextFetch; nextFetch = null; return waiting; }
    return { ok:true, json:async () => JSON.parse(JSON.stringify(snapshot)) };
  } });
  vm.runInContext(exposed, env.context, { filename:'focus_kline.js' });
  const api = env.context.klineTest;
  const day = { date:'2026-09-30', open:100, high:100, low:100, close:100, previousClose:100, tradingSessions:sessions, intraday:[{ time:'2026-09-30T09:01:00+08:00', value:100 }] };
  const market = env.Market.market(day.date, sessions);
  const timeline = env.Market.timeline(market).reconcile(day.intraday, item => item.time, item => item.value);
  const chart = env.Market.createChart(env.get('#kline-intraday-chart'));
  chart.setMarket(market); env.Market.pin(chart, market);
  const series = timeline.groups.map(group => { const line = chart.addSeries({}, { color:'#8067b3' }); line.setData(group); return line; });
  api.state.liveIntraday = { chart, market, timeline, series, markers:[] };
  const makeSnapshot = (value, time = '2026-09-30T09:01:00+08:00', perSecond = 0) => ({
    generated_at:time, intraday_date:day.date, intraday:[{ timestamp:time, price:value }],
    index:{ current:value }, previous_close:100, limit_down:90, limit_up:110,
    market_active:true, status:'rest', is_focusing:false, today_focus_seconds:60,
    live_tick:{ timestamp:time, value_at:value, per_second:perSecond },
  });
  snapshot = makeSnapshot(100, '2026-09-30T09:01:00+08:00', initialSlope);
  await api.startLiveTicks({ today:day, days:[day], limits:{ low:90, high:110 }, initialIndex:100, priceTick:.001 }, day, series[0], { time:unix(day.intraday[0].time), value:100 });
  const hold = () => {
    let release, reject;
    nextFetch = new Promise((resolve, fail) => { reject = fail; release = body => resolve({ ok:true, json:async () => JSON.parse(JSON.stringify(body)) }); });
    return { release, reject };
  };
  const refreshTasks = [];
  if (nativeBridge) {
    env.document.body.classList = new Element().classList;
    Object.assign(env.document.body.dataset, { role:'admin', viewerId:'2' });
    env.document.dispatchEvent = event => {
      const task = env.listeners.get(event.type)?.(event);
      if (event.type === 'dashboard:focus-refreshed') refreshTasks.push(task);
      return true;
    };
    vm.runInContext(appExposed, env.context, { filename:'app.js' });
    env.context.nativeTest.bindNativePageBridge();
  }
  return { ...env, api, calls, makeSnapshot, hold, setSnapshot:body => { snapshot = body; }, setFocus:active => { dashboardFocus = active; }, settleNative:() => Promise.all(refreshTasks.splice(0)) };
}

test('full page fetches immediately on foreground return and pageshow after a long background', async () => {
  const env = await liveFullPage(), resume = env.listeners.get('visibilitychange');
  assert.equal(typeof resume, 'function');
  env.document.hidden = true; await resume();
  assert.equal(env.calls.length, 1, 'entering the background does not start a request');
  env.clock.now += 600_000;
  env.setSnapshot(env.makeSnapshot(100.2, '2026-09-30T09:11:00+08:00'));
  env.document.hidden = false; await resume();
  assert.equal(env.calls.length, 2, 'returning does not wait for the fifteen-second interval');
  assert.equal(env.get('#kline-current').textContent, '100.200');
  assert.equal(env.api.state.liveSnapshot.generated_at, '2026-09-30T09:11:00+08:00');
  await env.windowListeners.get('pageshow')();
  assert.equal(env.calls.length, 3, 'restoring the page also reconciles immediately');
});

test('full-page resume events coalesce behind an in-flight request and reject its old direction', async () => {
  const env = await liveFullPage({ initialSlope:.01 }), held = env.hold(), before = env.calls.length;
  const running = env.windowListeners.get('pageshow')();
  const queued1 = env.listeners.get('visibilitychange')(), queued2 = env.windowListeners.get('pageshow')();
  env.clock.now += 1000;
  env.intervals.find(item => item.delay === 1000).fn();
  assert.equal(env.get('#kline-current').textContent, '100.000', 'a superseded snapshot cannot keep projecting while refresh waits');
  assert.equal(env.calls.length, before + 1);
  env.setSnapshot(env.makeSnapshot(100.4, '2026-09-30T09:01:01+08:00'));
  held.release(env.makeSnapshot(99, '2026-09-30T09:01:00+08:00', -1));
  await Promise.all([running, queued1, queued2]);
  assert.equal(env.calls.length, before + 2, 'all newer resume events share one follow-up fetch');
  assert.equal(env.get('#kline-current').textContent, '100.400');
  assert.equal(env.api.state.liveSnapshot.index.current, 100.4);
});

test('disposing full-page live charts revokes pending resume requests, callbacks and queue drains', async () => {
  for (const fail of [false, true]) {
    const env = await liveFullPage(), held = env.hold();
    const resume = env.windowListeners.get('pageshow'), tick = env.intervals.find(item => item.delay === 1000).fn;
    const running = resume(), queued = env.listeners.get('visibilitychange')();
    const quote = env.get('#kline-current').textContent, updated = env.get('#kline-last-updated').textContent, before = env.calls.length;
    env.api.stopLiveTicks();
    assert.equal(env.listeners.has('visibilitychange'), false);
    assert.equal(env.windowListeners.has('pageshow'), false);
    if (fail) held.reject(new Error('cancelled network')); else held.release(env.makeSnapshot(101));
    await Promise.all([running, queued]);
    await resume(); tick();
    assert.equal(env.calls.length, before, 'neither an obsolete queue nor a captured callback starts another request');
    assert.equal(env.api.state.liveIntraday, null);
    assert.equal(env.api.state.liveSnapshot, null);
    assert.equal(env.get('#kline-current').textContent, quote);
    assert.equal(env.get('#kline-last-updated').textContent, updated, 'a revoked failure must not overwrite the new page status');
  }
});

test('native refresh applies the owner focus response and immediately reconciles full-page live data', async () => {
  const env = await liveFullPage({ nativeBridge:true });
  const active = { id:169, user_id:2, subject:'数学', started_at:'2026-09-30T08:55:00+08:00', paused_at:'2026-09-30T09:01:00+08:00' };
  const before = env.calls.length;
  env.setFocus(active);
  env.setSnapshot({ ...env.makeSnapshot(99.9), is_paused:true });
  await env.window.MutsumiWeb.refresh(); await env.settleNative();
  assert.deepEqual(env.calls.slice(before), ['/api/dashboard', '/api/focus-kline/live']);
  assert.equal(env.context.nativeTest.state.dashboard.focus.active.id, 169);
  assert.equal(env.document.body.classList.contains('is-paused'), true);
  assert.equal(env.get('#kline-current').textContent, '99.900');
  assert.equal(env.get('#kline-focus-status').textContent, '已暂停');
  const after = env.calls.length;
  env.clock.now += 1000; env.intervals.find(item => item.delay === 1000).fn();
  assert.equal(env.calls.length, after, 'elapsed/tick updates do not dispatch another native reconciliation');
});

test('native state refreshes queue behind an in-flight live request and reject its superseded direction', async () => {
  const env = await liveFullPage({ nativeBridge:true, initialSlope:.01 }), held = env.hold();
  const before = env.calls.filter(url => url.endsWith('/live')).length;
  await env.window.MutsumiWeb.refresh();
  await env.window.MutsumiWeb.refresh(); await env.window.MutsumiWeb.refresh();
  assert.equal(env.calls.filter(url => url.endsWith('/live')).length, before + 1);
  env.clock.now += 1000; env.intervals.find(item => item.delay === 1000).fn();
  assert.equal(env.get('#kline-current').textContent, '100.000');
  env.setSnapshot(env.makeSnapshot(100.4, '2026-09-30T09:01:01+08:00'));
  held.release(env.makeSnapshot(99, '2026-09-30T09:01:00+08:00', -1));
  await env.settleNative();
  assert.equal(env.calls.filter(url => url.endsWith('/live')).length, before + 2);
  assert.equal(env.get('#kline-current').textContent, '100.400');
  assert.equal(env.api.state.liveSnapshot.index.current, 100.4);
});

test('native refresh while hidden retains a forced reconciliation and freezes the obsolete snapshot', async () => {
  const env = await liveFullPage({ nativeBridge:true, initialSlope:.01 }), before = env.calls.filter(url => url.endsWith('/live')).length;
  env.document.hidden = true;
  await env.window.MutsumiWeb.refresh(); await env.window.MutsumiWeb.refresh(); await env.settleNative();
  assert.equal(env.calls.filter(url => url.endsWith('/live')).length, before);
  env.clock.now += 1000; env.document.hidden = false;
  env.intervals.find(item => item.delay === 1000).fn();
  assert.equal(env.get('#kline-current').textContent, '100.000', 'hidden forced refresh invalidates the old projection before it can resume');
  env.setSnapshot(env.makeSnapshot(99.8, '2026-09-30T09:01:01+08:00'));
  await env.listeners.get('visibilitychange')();
  assert.equal(env.calls.filter(url => url.endsWith('/live')).length, before + 1);
  assert.equal(env.get('#kline-current').textContent, '99.800');
});

test('native bridge cannot revive a disposed full-page live listener or drain its old requests', async () => {
  const env = await liveFullPage({ nativeBridge:true }), held = env.hold();
  const captured = env.listeners.get('dashboard:focus-refreshed');
  await env.window.MutsumiWeb.refresh(); await env.window.MutsumiWeb.refresh();
  const before = env.calls.filter(url => url.endsWith('/live')).length;
  env.api.stopLiveTicks();
  assert.equal(env.listeners.has('dashboard:focus-refreshed'), false);
  held.release(env.makeSnapshot(101)); await env.settleNative();
  await env.window.MutsumiWeb.refresh(); await env.settleNative(); await captured();
  assert.equal(env.calls.filter(url => url.endsWith('/live')).length, before);
  assert.equal(env.api.state.liveSnapshot, null);
  assert.equal(env.api.state.liveIntraday, null);
  assert.equal(env.get('#kline-current').textContent, '100.000');
});

test('native focus refresh remains disabled for a public profile', async () => {
  const env = await liveFullPage({ nativeBridge:true }), before = env.calls.length;
  env.document.body.dataset.role = 'guest';
  await env.window.MutsumiWeb.refresh(); await env.settleNative();
  assert.equal(env.calls.length, before);
});

function historicalFullPage() {
  const today = '2026-10-01', now = `${today}T01:55:00+08:00`;
  let snapshot = { generated_at:now, intraday_date:today, index:{ current:10 },
    previous_close:10, limit_down:9, limit_up:11, market_active:false,
    status:'closed', is_focusing:false, is_paused:false, today_focus_seconds:60 };
  let nextFetch = null, nextDashboard = null, dashboardFocus = null;
  const calls = [], refreshTasks = [];
  const env = harness({ now, fetch:async url => {
    calls.push(url);
    if (url === '/api/dashboard') {
      if (nextDashboard) { const held = nextDashboard; nextDashboard = null; return held; }
      return { ok:true, json:async () => ({ now,
        preferences:{ viewer_id:2 }, focus:{ active:dashboardFocus, today:[] } }) };
    }
    if (nextFetch) { const held = nextFetch; nextFetch = null; return held; }
    return { ok:true, json:async () => JSON.parse(JSON.stringify(snapshot)) };
  } });
  vm.runInContext(exposed, env.context, { filename:'focus_kline.js' });
  const api = env.context.klineTest, history = pathDay();
  const current = { ...history, date:today, open:10, high:10, low:10, close:10,
    previousClose:10, intraday:[], tradingSessions:sessions.map(session => ({
      ...session, start:session.start.replace(history.date, today), end:session.end.replace(history.date, today),
    })) };
  api.state.payload = { days:[history, current], today:current, current:10,
    focusSeconds:60, isFocusing:false, isPaused:false, focusState:'rest', status:'rest',
    limits:{ low:9, high:11 }, initialIndex:100, priceTick:.001, updatedAt:now,
    intraday:history.intraday, intradayDate:history.date };
  api.state.selectedDate = history.date;
  api.drawIntradayChart(api.state.payload);
  assert.equal(api.state.liveResumeDispose, null, 'historical view has no current-day live controller');
  api.bind();
  env.document.body.classList = new Element().classList;
  Object.assign(env.document.body.dataset, { role:'admin', viewerId:'2' });
  env.document.dispatchEvent = event => {
    const task = env.listeners.get(event.type)?.(event);
    if (event.type === 'dashboard:focus-refreshed') refreshTasks.push(task);
    return true;
  };
  vm.runInContext(appExposed, env.context, { filename:'app.js' });
  env.context.nativeTest.bindNativePageBridge();
  return { ...env, api, calls, setSnapshot:body => { snapshot = body; },
    setFocus:active => { dashboardFocus = active; }, snapshot:() => ({ ...snapshot }),
    settleNative:() => Promise.all(refreshTasks.splice(0)), holdDashboard:() => {
      let release;
      nextDashboard = new Promise(resolve => { release = active => resolve({ ok:true, json:async () => ({
        now, preferences:{ viewer_id:2 }, focus:{ active, today:[] },
      }) }); });
      return release;
    }, hold:() => {
      let release;
      nextFetch = new Promise(resolve => { release = body => resolve({ ok:true, json:async () => body }); });
      return release;
    } };
}

test('real native bridge reconciles pre-open summary while preserving the selected historical chart', async () => {
  const env = historicalFullPage(), chart = env.api.state.liveIntraday;
  const history = JSON.stringify(chart.timeline.groups);
  env.setFocus({ id:184, user_id:2, subject:'408', started_at:'2026-10-01T01:40:00+08:00', paused_at:'2026-10-01T01:55:00+08:00' });
  env.setSnapshot({ ...env.snapshot(), index:{ current:10.1 }, is_paused:true,
    today_focus_seconds:900, limit_down:8, limit_up:12 });
  await env.window.MutsumiWeb.refresh(); await env.settleNative();
  assert.deepEqual(env.calls, ['/api/dashboard', '/api/focus-kline/live']);
  assert.equal(env.get('#kline-focus-status').textContent, '已暂停');
  assert.equal(env.get('#kline-current').textContent, '10.100');
  assert.equal(env.get('#kline-focus-total').textContent, '00:15:00');
  assert.equal(env.get('#kline-limit-low').textContent, '8.000');
  assert.equal(env.api.state.selectedDate, '2026-09-30');
  assert.equal(env.api.state.liveIntraday, chart);
  assert.equal(JSON.stringify(chart.timeline.groups), history);
});

test('non-home visible-page reconciliation returns immediately after a background interval', async () => {
  const env = historicalFullPage();
  env.document.hidden = true; env.clock.now += 21_000;
  env.setFocus({ id:184, user_id:2, subject:'408', started_at:'2026-10-01T01:40:00+08:00' });
  env.setSnapshot({ ...env.snapshot(), is_focusing:true, today_focus_seconds:921 });
  env.document.hidden = false;
  await env.context.nativeTest.refreshVisiblePage(); await env.settleNative();
  assert.deepEqual(env.calls, ['/api/dashboard', '/api/focus-kline/live']);
  assert.equal(env.get('#kline-focus-status').textContent, '专注中');
  assert.equal(env.api.state.selectedDate, '2026-09-30');
  await env.windowListeners.get('pageshow')();
  assert.equal(env.calls.length, 3, 'historical summary pageshow does not wait for a polling interval');
});

test('historical summary queues hidden native changes and rejects an older in-flight state', async () => {
  const env = historicalFullPage();
  env.document.hidden = true;
  await env.window.MutsumiWeb.refresh(); await env.settleNative();
  assert.deepEqual(env.calls, ['/api/dashboard']);
  env.document.hidden = false;
  const release = env.hold();
  const first = env.listeners.get('visibilitychange')();
  const queued = env.windowListeners.get('pageshow')();
  env.setSnapshot({ ...env.snapshot(), is_paused:true, today_focus_seconds:1000 });
  release({ ...env.snapshot(), is_paused:false, is_focusing:true, today_focus_seconds:10 });
  await Promise.all([first, queued]);
  assert.equal(env.calls.filter(url => url.endsWith('/live')).length, 2);
  assert.equal(env.get('#kline-focus-status').textContent, '已暂停');
  assert.equal(env.get('#kline-focus-total').textContent, '00:16:40');
  assert.equal(env.api.state.selectedDate, '2026-09-30');
});

test('overlapping native lifecycle hooks cannot restore an older owner focus response', async () => {
  const env = historicalFullPage(), release = env.holdDashboard();
  const older = env.window.MutsumiWeb.refresh();
  env.setFocus({ id:184, user_id:2, subject:'408', started_at:'2026-10-01T01:40:00+08:00' });
  env.setSnapshot({ ...env.snapshot(), is_focusing:true });
  await env.window.MutsumiWeb.refresh(); await env.settleNative();
  release({ id:184, user_id:2, subject:'408', started_at:'2026-10-01T01:40:00+08:00', paused_at:'2026-10-01T01:55:00+08:00' });
  await older; await env.settleNative();
  assert.equal(env.document.body.classList.contains('is-paused'), false);
  assert.equal(env.get('#kline-focus-status').textContent, '专注中');
  assert.equal(env.calls.filter(url => url.endsWith('/live')).length, 1,
    'only the newest owner response emits the chart refresh');
});
