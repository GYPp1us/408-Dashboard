const test = require('node:test'), assert = require('node:assert/strict');
const { model } = require('../app/static/day-timeline.js');
const start = Date.parse('2026-10-19T00:00:00+08:00');
const data = { windows: { morning: { start:'08:30', end:'11:40' }, library: { start:'13:30', end:'22:45' } }, focus:{ today:[] } };
const at = seconds => model(data, start + seconds * 1000, seconds, start);
test('continuous wall-clock track includes all lunch time and changes labels at exact boundaries', () => {
  assert.equal(at(8*3600).position, 0);
  assert.equal(at(8.5*3600).label, '距离午休');
  assert.equal(at(11*3600+40*60).label, '距离下午开盘');
  assert.equal(at(13.5*3600).label, '距离闭馆');
  assert.equal(at(22*3600+45*60).position, 1);
  assert.equal(at(23*3600).remaining, 9.5*3600);
  assert.equal(at(12*3600).span, 14.25*3600);
  assert.ok(Math.abs(at(12*3600).lunchWidth - 110/855) < 1e-12);
});
test('focus segments retain pauses and clip to the same continuous account-day axis', () => {
  const input = {...data, focus:{today:[{subject:'数学', segments:[
    {started_at:'2026-10-19T08:00:00+08:00', ended_at:'2026-10-19T09:00:00+08:00'},
    {started_at:'2026-10-19T13:45:00+08:00', ended_at:null}]}]}};
  const result = model(input, start+14*3600000, 14*3600, start);
  assert.equal(result.segments.length, 2);
  assert.equal(result.segments[0].left, 0);
  assert.equal(result.segments[0].width, 30/855);
  assert.equal(result.segments[1].width, 15/855);
});
