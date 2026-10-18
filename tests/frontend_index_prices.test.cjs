const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { harness, Element, sessions } = require('./frontend_market_harness.cjs');

const read = name => fs.readFileSync(path.join(__dirname, '../app/static', name), 'utf8');
const expose = (name, api) => read(name).replace(/\}\)\(\);\s*$/, `globalThis.priceTest = { ${api} };})();`);
const prices = [10, 9.9, 9.95];
const intraday = prices.map((price, index) => ({
  timestamp:`2026-09-30T09:0${index}:00+08:00`, price, value:10 - index * .002,
  changed:index === 1, state:'idle', session:'am',
}));
const day = { date:'2026-09-30', open:10, high:10, low:9.9, close:9.95, trading_sessions:sessions };
const full = { candles:[day], today:day, intraday_date:day.date, intraday, previous_close:10,
  index:{ current:9.95 }, updated_at:'2026-09-30T09:02:00+08:00' };
const live = { ...full, generated_at:full.updated_at, market_active:true,
  live_tick:{ kind:'executions', timestamp:full.updated_at, direction:1 },
  exchange:{ model:'focus-exchange-v1', session:'am' }, trades:[] };
const response = data => ({ ok:true, json:async () => JSON.parse(JSON.stringify(data)) });
const values = series => Array.from(series.data, point => point.value);
const all = node => [node, ...node.children.flatMap(all)];
const baselines = host => all(host).filter(node => node.getAttribute('class') === 'market-open-line');

async function home() {
  const env = harness({ now:full.updated_at, fetch:async url => response(url.endsWith('/live') ? live : full) });
  vm.runInContext(expose('dashboard-index.js', 'full:refreshFull, chart:() => homeChart, data:() => latest, createChart, setLine, stats:dayStatistics'), env.context);
  const api = env.context.priceTest;
  await api.full();
  for (let i = 0; i < 10; i++) await Promise.resolve();
  return { ...env, api };
}

test('home and drawer plot execution prices when minute samples also carry a value anchor', async () => {
  const { api } = await home();
  assert.deepEqual(values(api.chart().lines[0]), prices);
  const drawer = api.createChart(new Element());
  api.setLine(drawer, api.data());
  assert.deepEqual(values(drawer.lines[0]), prices);
  assert.equal(drawer.lines[0].markers[0].value, 9.9);
});

test('the time-weighted mean uses execution prices instead of the value anchor', async () => {
  const { api } = await home();
  assert.equal(api.stats(api.data(), 9.95).average, 9.9375);
});

test('standalone initial chart and live refresh both keep execution prices and event positions', async () => {
  const nextPoint = { timestamp:'2026-09-30T09:03:00+08:00', price:9.8, value:9.994, changed:true };
  const next = { ...live, intraday:[...intraday, nextPoint], index:{ current:9.8 },
    generated_at:nextPoint.timestamp, live_tick:{ ...live.live_tick, timestamp:nextPoint.timestamp } };
  const env = harness({ now:full.updated_at, fetch:async () => response(next) });
  vm.runInContext(expose('focus_kline.js', 'normalizePayload, drawIntradayChart, state'), env.context);
  const api = env.context.priceTest, data = api.normalizePayload(full);
  api.drawIntradayChart(data);
  assert.deepEqual(values(api.state.liveIntraday.series[0]), prices);
  for (let i = 0; i < 20; i++) await Promise.resolve();
  assert.deepEqual(values(api.state.liveIntraday.series[0]), [...prices, 9.8]);
  assert.equal(api.state.liveIntraday.series[0].markers.at(-1).value, 9.8);
});

test('standalone still accepts older value-only minute data', () => {
  const env = harness();
  vm.runInContext(expose('focus_kline.js', 'normalizePoint'), env.context);
  assert.equal(env.context.priceTest.normalizePoint({ timestamp:full.updated_at, value:9.7 }, 0).value, 9.7);
});

test('home and drawer baseline follow the selected day opening through live changes and date switches', async () => {
  const {api}=await home(), drawer=api.createChart(new Element());
  for (const chart of [api.chart(), drawer]) {
    const selected={...day,open:9.8};
    api.setLine(chart,{...api.data(),candles:[selected],previous_close:20});
    assert.equal(baselines(chart.host).length,1);
    assert.equal(baselines(chart.host)[0].getAttribute('data-price'),'9.8');
    chart.timeline.append(Date.parse('2026-09-30T09:03:00+08:00')/1000,9.7);
    chart.lines[0].setData(chart.timeline.groups[0]);
    assert.equal(baselines(chart.host)[0].getAttribute('data-price'),'9.8');
    const historical={...day,date:'2026-09-29',open:10.4,trading_sessions:sessions.map(s=>({...s,start:s.start.replace('09-30','09-29'),end:s.end.replace('09-30','09-29')}))};
    api.setLine(chart,{...api.data(),intraday_date:historical.date,candles:[historical],intraday:intraday.map(p=>({...p,timestamp:p.timestamp.replace('09-30','09-29')}))});
    assert.equal(baselines(chart.host).length,1);
    assert.equal(baselines(chart.host)[0].getAttribute('data-price'),'10.4');
  }
});

test('opening line remains horizontal and visible outside the current trading range and clears with missing opening data',()=>{
  const env=harness(),host=new Element(),chart=env.Market.createChart(host);
  env.Market.pin(chart,env.Market.market(day.date,sessions,full.updated_at));
  chart.addSeries({},{}).setData([{time:Date.parse(full.updated_at)/1000,value:9.5}]);
  chart.setOpeningPrice(10);
  const line=baselines(host)[0];
  assert.equal(line.getAttribute('y1'),line.getAttribute('y2'));
  assert.equal(line.getAttribute('stroke-dasharray'),'3 4');
  assert(Number(line.getAttribute('y1'))>=12 && Number(line.getAttribute('y1'))<=193);
  chart.setOpeningPrice(null);assert.equal(baselines(host).length,0);
});

test('standalone baseline uses the daily opening instead of initial index and reconciles an updated server opening',async()=>{
  const next={...live,today:{...day,open:9.85}};
  const env=harness({now:full.updated_at,fetch:async()=>response(next)});
  vm.runInContext(expose('focus_kline.js','normalizePayload, drawIntradayChart, state'),env.context);
  const api=env.context.priceTest,data=api.normalizePayload({...full,today:{...day,open:9.8},candles:[{...day,open:9.8}],initial_index:100});
  api.drawIntradayChart(data);
  const host=env.get('#kline-intraday-chart');
  assert.equal(baselines(host)[0].getAttribute('data-price'),'9.8');
  assert(!api.state.liveIntraday.series[0].priceLines.some(line=>line.title==='基准'));
  for(let i=0;i<20;i++)await Promise.resolve();
  assert.equal(baselines(host).length,1);assert.equal(baselines(host)[0].getAttribute('data-price'),'9.85');
});
