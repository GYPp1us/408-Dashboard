const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../android/app/src/main/assets/dashboard/focus-entry.js'), 'utf8');
const key = 'mutsumiFocusSlotsV071:42';
const items = [1, 2, 3, 4, 5].map(id => ({id, expected_minutes: id === 1 ? 75 : 0}));

function load(storage) {
  const window = {};
  const document = {body:{dataset:{role:'admin',viewerId:'42'}}, querySelector:()=>null, addEventListener(){}};
  vm.runInNewContext(source, {window, document, localStorage:storage});
  window.FocusEntry.render(items, {count:3, quickIds:[1, 2, 3]});
  return window.FocusEntry;
}

test('successful launches refresh separate quick and timed slots and evict the oldest slot', () => {
  const saved = new Map([[key, JSON.stringify({
    quick:[{id:1,minutes:0}, {id:2,minutes:0}, {id:3,minutes:0}],
    timed:[{id:1,minutes:75}, {id:2,minutes:60}, {id:3,minutes:120}],
  })]]);
  const storage = {getItem:key=>saved.get(key), setItem:(key,value)=>saved.set(key,value)};
  let entry = load(storage);
  entry.remember(1, 0);
  entry.remember(4, 0);
  entry.remember(2, 60);
  entry.remember(5, 47);
  entry = load(storage);
  entry.remember(5, 0);
  const slots = JSON.parse(saved.get(key));
  assert.deepEqual(slots.quick.map(slot=>slot.id), [1, 4, 5]);
  assert.deepEqual(slots.timed.map(slot=>[slot.id,slot.minutes]), [[5,47],[2,60],[3,120]]);
});
