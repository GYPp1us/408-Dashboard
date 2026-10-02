const assert = require('node:assert/strict');
const test = require('node:test');
const { harness, Element, sessions } = require('./frontend_market_harness.cjs');
const at = value => Date.parse(value) / 1000;
const pairs = segments => Array.from(segments, segment => Array.from(segment, point => [point.time, point.value]));

test('lunch is flat and its net price change is a vertical jump exactly at reopening', () => {
  const env = harness({ now:sessions[1].start });
  const market = env.Market.market('2026-09-30', sessions, sessions[1].start);
  const close = at(sessions[0].end), open = at(sessions[1].start);
  const raw = [{ timestamp:sessions[0].end, price:9.015 }, { timestamp:'2026-09-30T12:30:00+08:00', price:9.8 }, { timestamp:sessions[1].start, price:9.3 }];
  const samples = env.Market.timeline(market).reconcile(raw, item => item.timestamp, item => item.price);
  const before = JSON.stringify(samples.groups);
  assert.deepEqual(pairs(env.Market.breakSegments(market, samples.groups.flat(), open)), [[[close,9.015], [open,9.015], [open,9.3]]]);
  assert.equal(JSON.stringify(samples.groups), before, 'display bridge must not add lunch duration to weighted statistics');
});

test('before reopening the break ends at the current time and exposes no future opening quote', () => {
  const env = harness();
  const market = env.Market.market('2026-09-30', sessions);
  const close = at(sessions[0].end), open = at(sessions[1].start), now = at('2026-09-30T12:45:00+08:00');
  const points = [{ time:close, value:9.015 }, { time:open, value:9.3 }];
  assert.deepEqual(pairs(env.Market.breakSegments(market, points, now)), [[[close,9.015], [now,9.015]]]);
  assert.equal(env.Market.breakSegments(market, points, close - 1).length, 0);
});

test('an unchanged reopening stays horizontal and an unknown close is not invented', () => {
  const env = harness();
  const market = env.Market.market('2026-09-30', sessions);
  const close = at(sessions[0].end), open = at(sessions[1].start);
  assert.deepEqual(pairs(env.Market.breakSegments(market, [{ time:close, value:10 }, { time:open, value:10 }], open)), [[[close,10], [open,10]]]);
  assert.equal(env.Market.breakSegments(market, [{ time:close - 60, value:10 }, { time:open, value:11 }], open).length, 0);
});

test('shared SVG renderer draws a flat break and same-x jump without mutating either trading series', () => {
  const env = harness({ now:sessions[1].start }), host = new Element();
  const market = env.Market.market('2026-09-30', sessions, sessions[1].start);
  const chart = env.Market.createChart(host);
  chart.setMarket(market); env.Market.pin(chart, market);
  const am = chart.addSeries({}, { color:'#123456' }), pm = chart.addSeries({}, { color:'#123456' });
  const close = at(sessions[0].end), open = at(sessions[1].start);
  am.setData([{ time:close, value:9.015 }]); pm.setData([{ time:open, value:9.3 }]);
  const all = element => [element, ...element.children.flatMap(all)];
  const bridge = all(host).find(element => element.getAttribute('class') === 'market-break-path');
  assert.ok(bridge);
  const coords = bridge.getAttribute('d').match(/[ML][\d.-]+,[\d.-]+/g).map(value => value.slice(1).split(',').map(Number));
  assert.equal(coords.length, 3); assert.equal(coords[0][1], coords[1][1]); assert.equal(coords[1][0], coords[2][0]);
  assert.notEqual(coords[1][1], coords[2][1]);
  assert.equal(am.data.length, 1); assert.equal(pm.data.length, 1);
});
