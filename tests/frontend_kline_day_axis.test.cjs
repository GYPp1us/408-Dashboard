const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/static/focus_kline.js'), 'utf8');
const exposed = source.replace(/\}\)\(\);\s*$/, 'globalThis.klineTest = { state, drawIntradayChart };})();');

test('full-page intraday chart pins midnight to midnight and retains prior jump markers', () => {
  const chartSeries = [];
  const markerGroups = [];
  const scale = {
    setVisibleLogicalRange(range) { this.range = range; },
    timeToCoordinate() { return 10; }, subscribeSizeChange() {}, subscribeVisibleLogicalRangeChange() {},
    fitContent() { throw new Error('intraday must not fit elapsed samples'); },
  };
  const chart = {
    timeScale: () => scale, applyOptions() {}, remove() {},
    addSeries(_type, options) {
      const series = { options, setData(data) { this.data = data; }, createPriceLine() {}, update() {} };
      chartSeries.push(series);
      return series;
    },
  };
  const host = {
    clientWidth: 600, clientHeight: 220, hidden: false,
    querySelector: () => null, closest: () => ({ classList: { toggle() {} } }), append() {},
  };
  const nodes = new Map([['#kline-intraday-chart', host]]);
  const document = {
    querySelector: (selector) => nodes.get(selector) || null,
    addEventListener() {},
    createElement: () => ({ style: {}, append() {}, setAttribute() {} }),
    documentElement: {},
  };
  const window = {
    LightweightCharts: {
      LineSeries: {}, ColorType: { Solid: 0 }, LineStyle: { Dashed: 2, Dotted: 1 },
      createChart: (_host, options) => {
        assert(options.timeScale.minBarSpacing <= 600 / 1441, 'all minute positions must fit the chart width');
        return chart;
      },
      createSeriesMarkers: (_series, markers) => markerGroups.push(markers),
    },
    clearTimeout() {}, clearInterval() {}, requestAnimationFrame: (fn) => fn(),
  };
  const sandbox = vm.createContext({
    document, window, Date, Intl,
    getComputedStyle: () => ({ getPropertyValue: () => '#dde2de' }),
    ResizeObserver: class { observe() {} disconnect() {} },
  });
  vm.runInContext(exposed, sandbox, { filename: 'focus_kline.js' });
  const day = '2026-09-29';
  const today = {
    date: day, open: 100, high: 101, low: 99, close: 100.5,
    previousClose: 100, intraday: [
      { time: `${day}T09:00:00+08:00`, value: 100, event: false, floorReset: false },
      { time: `${day}T09:01:00+08:00`, value: 100.1, event: true, floorReset: false },
      { time: `${day}T13:30:00+08:00`, value: 100.5, event: false, floorReset: true },
    ], tradingSessions: [],
  };
  sandbox.klineTest.state.selectedDate = day;
  sandbox.klineTest.drawIntradayChart({
    days: [today], today, limits: { low: 90, high: 110 }, initialIndex: 100,
    priceTick: .001, intradayDate: day, isFocusing: false, focusState: 'rest',
  });

  assert.equal(chartSeries[0].data.length, 1441);
  assert.equal(chartSeries[0].options.visible, true);
  assert.equal(chartSeries[0].options.color, 'transparent');
  assert.equal(scale.range.from, -.5);
  assert.equal(scale.range.to, 1440.5);
  assert.equal(markerGroups.flat().length, 2);
  assert.equal(markerGroups.flat().find((item) => item.text === '复位').shape, 'arrowUp');
});
