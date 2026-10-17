const assert=require('node:assert/strict');
const test=require('node:test');
const {harness,Element,sessions}=require('./frontend_market_harness.cjs');
const origin=Date.parse('2026-09-30T09:01:00+08:00');
const iso=ms=>new Date(origin+ms).toISOString();

function snapshot(ms,price,trades=[]) {
  return {intraday_date:'2026-09-30',generated_at:iso(ms),market_active:true,index:{current:price},
    live_tick:{kind:'executions',timestamp:iso(ms),per_second:99,direction:trades.at(-1)?.direction || 0},
    exchange:{model:'focus-exchange-v1',session:'am'},trades};
}
function trade(ms,price,direction) { return {id:(origin+ms)/100,timestamp_ms:origin+ms,price,direction,session:'am'}; }

test('real execution quotes never use the old slope to invent future prices',()=>{
  const {Market}=harness();
  const market=Market.market('2026-09-30',sessions,iso(0));
  const data={...snapshot(0,100),receivedAt:origin};
  assert.equal(Market.project(data,market,origin+1000).value,100);
});

test('both directions of a net-zero packet are shown as individual authentic executions',()=>{
  const {Market}=harness(),market=Market.market('2026-09-30',sessions,iso(0)),tape=Market.tradeTape();
  tape.accept(snapshot(0,100),origin);
  tape.accept(snapshot(1000,100,[trade(100,100.001,1),trade(900,100,-1)]),origin+1000);
  assert.equal(tape.step(market,origin+1099).value,100);
  const up=tape.step(market,origin+1100); assert.equal(up.value,100.001); assert.equal(up.direction,1); assert(up.executed);
  assert.equal(tape.step(market,origin+1150).executed,false);
  const down=tape.step(market,origin+1900); assert.equal(down.value,100); assert.equal(down.direction,-1); assert(down.executed);
  tape.accept(snapshot(1000,100,[trade(100,100.001,1),trade(900,100,-1)]),origin+2000);
  assert.equal(tape.step(market,origin+2100).executed,false);
});

test('missing execution ranges and stale connections reconcile without fabricated catch-up trades',()=>{
  const {Market}=harness(),market=Market.market('2026-09-30',sessions,iso(0)),tape=Market.tradeTape();
  tape.accept(snapshot(0,100),origin);
  tape.accept(snapshot(1000,102,[trade(900,102,1)]),origin+1000);
  const reset=tape.step(market,origin+1100); assert.equal(reset.value,102); assert.equal(reset.executed,false);
  const stale=tape.step(market,origin+4101); assert(stale.stale); assert.equal(stale.executed,false); assert.equal(stale.value,102);
  const closed={...snapshot(5000,103,[trade(4900,102.001,1)]),market_active:false};
  tape.accept(closed,origin+5000);
  assert.equal(tape.step(market,origin+5000).value,103,'closing auction adopts the actual settled quote');
});

test('quote styling follows the last trade rather than the daily net change and remains steady while flat',()=>{
  const {Market}=harness(),quote=new Element('strong'); quote.textContent='110.000';
  Market.paintQuote(quote,109.999,-1);
  assert(quote.classList.contains('is-tick-down')); assert(!quote.classList.contains('is-tick-up'));
  Market.paintQuote(quote,109.999,0);
  assert(quote.classList.contains('is-tick-down'));
  assert.equal(quote.textContent,'109.999');
});
