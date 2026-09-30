const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/static/dashboard-index.js'), 'utf8');
const exposed = source.replace(/\}\)\(\);\s*$/, 'globalThis.indexTest = { full: refreshFull, live: refreshLive, tick: liveSecond, chart: () => homeChart };})();');

test('home index keeps a 24-hour axis and projects one-second quotes without refetching history', async () => {
  const calls = [];
  const intervals = [];
  const charts = [];
  const nodes = new Map();
  const clock = { now: Date.parse('2026-09-30T09:01:00+08:00') };
  class ClockDate extends Date { static now() { return clock.now; } }
  const classList = { toggle() {}, add() {}, remove() {} };
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {
      textContent: '', hidden: false, style: {}, classList, clientWidth: 600, clientHeight: 220,
      isConnected: true, getClientRects: () => [1], append(child) { this.child = child; },
      addEventListener() {},
    });
    return nodes.get(selector);
  };
  const view = { hidden: false, getClientRects: () => [1], querySelector: node };
  const document = {
    hidden: false, documentElement: {}, getElementById: (id) => id === 'activity-index-view' ? view : null,
    addEventListener() {}, createElement: () => ({ style: {}, hidden: false, innerHTML: '' }),
  };
  const full = {
    candles: [], today: { date: '2026-09-30', open: 100, high: 100.1, low: 99.9, close: 100.002 },
    intraday_date: '2026-09-30', previous_close: 100, index: { current: 100.002 },
    intraday: [
      { timestamp: '2026-09-30T09:00:00+08:00', price: 100, changed: true },
      { timestamp: '2026-09-30T09:01:00+08:00', price: 100.002 },
    ],
    today_focus_seconds: 60, updated_at: '2026-09-30T09:01:00+08:00',
  };
  const live = {
    intraday_date: '2026-09-30', intraday: full.intraday,
    index: { current: 100.002 }, previous_close: 100, limit_down: 90, limit_up: 110,
    generated_at: '2026-09-30T09:01:00+08:00', market_active: true, is_focusing: true,
    today_focus_seconds: 60,
    live_tick: { timestamp: '2026-09-30T09:01:00+08:00', value_at: 100.002, per_second: .001 },
  };
  const library = {
    LineSeries: {}, CandlestickSeries: {},
    createSeriesMarkers: () => ({ setMarkers(markers) { this.markers = markers; } }),
    createChart: (_host, options) => {
      assert(options.timeScale.minBarSpacing <= 600 / 1441, 'all 1441 minute positions must fit a 600px chart');
      const scale = {
        setVisibleLogicalRange(range) { this.range = range; },
        timeToCoordinate(time) { return time / 60; },
        fitContent() { throw new Error('intraday must not fit elapsed data'); },
      };
      const chart = {
        series: [], scale, applyOptions() {}, timeScale: () => scale, remove() {},
        addSeries(_type, options) {
          const series = { options, data: [], updates: [], applyOptions() {}, setData(data) { this.data = data; }, update(point) { this.updates.push(point); } };
          this.series.push(series);
          return series;
        },
      };
      charts.push(chart);
      return chart;
    },
  };
  const sandbox = vm.createContext({
    Date: ClockDate, document, window: { LightweightCharts: library, DashboardDetails: { register() {} } },
    fetch: async (url) => { calls.push(url); return { ok: true, json: async () => url.endsWith('/live') ? live : full }; },
    getComputedStyle: () => ({ fontFamily: 'serif', getPropertyValue: () => '' }),
    ResizeObserver: class { observe() {} disconnect() {} }, MutationObserver: class { observe() {} },
    requestAnimationFrame: (fn) => fn(), setInterval: (fn) => { intervals.push(fn); },
    AbortController, URL, console,
  });
  vm.runInContext(exposed, sandbox, { filename: 'dashboard-index.js' });
  await sandbox.indexTest.full();
  await sandbox.indexTest.live();

  assert.equal(charts.length, 1);
  assert.equal(charts[0].series[1].options.visible, true);
  assert.equal(charts[0].series[1].options.color, 'transparent');
  assert.equal(charts[0].series[1].data.length, 1441);
  assert.equal(charts[0].scale.range.from, -.5);
  assert.equal(charts[0].scale.range.to, 1440.5);
  assert.equal(sandbox.indexTest.chart().markers.markers.length, 1);
  assert.equal(calls.filter((url) => url === '/api/focus-kline').length, 1);

  clock.now += 1000;
  intervals[0]();
  assert.equal(node('[data-index-points]').textContent, '100.003');
  assert.equal(charts[0].series[0].updates.at(-1).value, 100.003);
  assert.equal(calls.filter((url) => url === '/api/focus-kline').length, 1);
});
