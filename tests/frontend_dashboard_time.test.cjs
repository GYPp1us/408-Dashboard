const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { Element } = require('./frontend_market_harness.cjs');
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
const exposed = source.replace(/\}\)\(\);\s*$/, 'globalThis.timeTest = { state, syncServerClock, serverNow, accountClock, accountDateKey, renderClock, renderWindows, renderHomeWindow, workWindowProgress, dateMinutes, renderWindowHistory, focusElapsedSeconds };})();');

function utcDevice(reference = '2026-09-30T19:00:00+08:00') {
  const clock = { now:Date.parse(reference) }, nodes = new Map();
  class DeviceDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock.now])); }
    static now() { return clock.now; }
    getHours() { return this.getUTCHours(); } getMinutes() { return this.getUTCMinutes(); } getSeconds() { return this.getUTCSeconds(); }
    getFullYear() { return this.getUTCFullYear(); } getMonth() { return this.getUTCMonth(); } getDate() { return this.getUTCDate(); }
    getTimezoneOffset() { return 0; }
    toLocaleTimeString(locale, options = {}) { return super.toLocaleTimeString(locale, { timeZone:'UTC', ...options }); }
    toLocaleDateString(locale, options = {}) { return super.toLocaleDateString(locale, { timeZone:'UTC', ...options }); }
  }
  const get = selector => {
    if (!nodes.has(selector)) {
      const node = new Element(); node.style.setProperty = () => {};
      node.replaceChildren = (...children) => { node.textContent = children.map(child => child.textContent ?? child).join(''); };
      nodes.set(selector, node);
    }
    return nodes.get(selector);
  };
  const document = { documentElement:{ dataset:{} }, body:{ dataset:{ page:'home', role:'admin', viewerId:'2' } }, querySelector:get, querySelectorAll:() => [], addEventListener() {}, createTextNode:text => ({ textContent:text }) };
  const window = { clearInterval() {}, clearTimeout() {}, setTimeout() {}, addEventListener() {} };
  const context = vm.createContext({ Date:DeviceDate, window, document, navigator:{}, Intl, URL, AbortController, console, getComputedStyle:() => ({ getPropertyValue:() => '' }), requestAnimationFrame:fn => fn() });
  vm.runInContext(exposed, context, { filename:'app.js' });
  const api = context.timeTest;
  const data = { now:reference, windows:{ morning:{ start:'08:30', end:'11:40', total_seconds:11400, remaining_seconds:0 }, library:{ start:'13:30', end:'22:45', total_seconds:33300, remaining_seconds:13500 } }, focus:{ today:[] } };
  api.state.dashboard = data; api.state.dashboardFetchedAt = clock.now; api.syncServerClock(reference, clock.now);
  return { api, data, clock, get, DeviceDate };
}

test('UTC device renders the account clock and all study-window state on the server +08 timeline', () => {
  const env = utcDevice(); env.api.renderClock(); env.api.renderWindows(env.data);
  assert.equal(new env.DeviceDate().getHours(), 11, 'the device really exposes UTC hour eleven');
  assert.equal(env.get('#current-time').textContent, '19:00:00');
  assert.equal(env.get('#home-window-label').textContent, '下午学习窗口');
  assert.equal(env.get('#home-window-action').textContent, '距离闭馆');
  assert.equal(env.get('#home-window-countdown').textContent, '03:45:00');
  assert.equal(env.get('#library-clock').textContent, '03:45:00');
  assert.equal(env.get('#library-percent').textContent, '59%');
  assert.equal(env.get('#lunch-percent').textContent, '100%');
  assert.ok(Math.abs(env.api.workWindowProgress(new env.DeviceDate(env.api.serverNow()), env.data.windows) - 31200 / 44700) < 1e-12);
});

test('account date advances before the UTC device date and server clock anchors survive repeated syncs', () => {
  const env = utcDevice('2026-10-01T00:00:03+08:00'); env.api.renderClock();
  assert.equal(new env.DeviceDate().getUTCDate(), 30);
  assert.equal(env.api.accountDateKey(), '2026-10-01');
  assert.match(env.get('#today-date').textContent, /2026.*10.*01/);
  env.clock.now += 500;
  env.api.syncServerClock('2026-10-01T00:00:03.500+08:00', env.clock.now);
  env.clock.now += 1500; env.api.state.secondTasks.get('clock')(env.clock.now);
  assert.equal(env.get('#current-time').textContent, '00:00:05');
  assert.equal(env.api.accountClock(Date.parse('2026-09-30T15:30:00Z'), false), '23:30');
});

test('window history clips to the account day and open-session progress uses the server instant', () => {
  const env = utcDevice();
  assert.equal(env.api.dateMinutes('2026-09-30T00:00:00Z'), 480);
  assert.equal(env.api.dateMinutes('2026-09-29T15:59:59Z'), 0);
  assert.equal(env.api.dateMinutes('2026-09-30T16:00:00Z'), 1440);
  env.api.renderWindowHistory('library', env.data.windows.library, [{ subject:'数学', started_at:'2026-09-30T10:30:00Z' }]);
  const match = env.get('#library-history').innerHTML.match(/left:([\d.]+)%;width:([\d.]+)%/);
  assert.ok(match);
  assert.ok(Math.abs(Number(match[1]) - 300 / 555 * 100) < 1e-12);
  assert.ok(Math.abs(Number(match[2]) - 30 / 555 * 100) < 1e-12);
  assert.equal(env.api.focusElapsedSeconds({ started_at:'2026-09-30T10:30:00Z' }, Date.parse('2026-09-30T11:00:00Z')), 1800, 'durations remain real epoch differences');
});

test('a non-Shanghai account offset remains authoritative on a UTC device', () => {
  const env = utcDevice('2026-09-30T09:10:20-04:00'); env.api.renderClock(); env.api.renderWindows(env.data);
  assert.equal(env.get('#current-time').textContent, '09:10:20');
  assert.equal(env.get('#home-window-label').textContent, '上午学习窗口');
  assert.equal(env.get('#home-window-countdown').textContent, '02:29:40');
  assert.equal(env.api.accountClock(Date.parse('2026-09-30T13:00:00Z'), false), '09:00');
});
