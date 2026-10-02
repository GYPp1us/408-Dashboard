const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/static/daily-report.js'), 'utf8');
const exposed = source.replace(/\}\)\(\);\s*$/, 'globalThis.reportTest = { validReport, reportHtml, seconds };})();');
const snapshot = {
  version: 1, snapshot_kind: 'settled', date: '2026-10-02', timezone: 'Asia/Shanghai', username: 'reader',
  total_seconds: 30240, target_seconds: 25200, completion: 1.2, completion_percent: 120,
  yesterday_seconds: 20000, delta_seconds: 10240, session_count: 4, longest_session_seconds: 7200,
  trusted_seconds: 30240, untrusted_seconds: 0, trust_note: '暂停时间不计入', rank: 1, percentile: 100, day_count: 9,
  subject_breakdown_complete: true, subject_totals: [{ subject: '数学', seconds: 30240, percent: 100 }],
  challenge: { active_today: true, pending_disable: false, current_limit_percent: 20 },
  index: { open: 1000, current: 1120, previous_close: 1000, return_percent: 12, is_market_closed: false, note: '主动收官时的快照' },
  achievements: [{ id: 'goal_met', label: '目标达成', detail: '达到当日目标' }], closing_note: '今天的投入已经收好。',
};

function context() {
  const calls = { back: 0, focused: 0, shown: 0 };
  const listeners = new Map();
  const classList = { add() {}, remove() {}, toggle() {} };
  class HTMLElement {
    constructor() { this.isConnected = true; }
    closest() { return null; }
    matches() { return true; }
    focus() { calls.focused++; }
  }
  const trigger = new HTMLElement();
  const dialog = { open: false, classList, addEventListener() {}, showModal() { this.open = true; calls.shown++; }, close() { this.open = false; } };
  const content = { innerHTML: '', classList, setAttribute() {}, scrollTop: 0 };
  const closeButton = new HTMLElement();
  closeButton.addEventListener = () => {};
  const nodes = new Map([['daily-report-modal', dialog], ['daily-report-content', content], ['close-daily-report', closeButton]]);
  const window = {
    MutsumiViewport: { wide: true, logicalHeight: 655 },
    history: { state: null, pushState(state) { this.state = state; }, back() { calls.back++; this.state = null; } },
    addEventListener(name, callback) { listeners.set(name, callback); },
  };
  const document = { activeElement: trigger, getElementById: id => nodes.get(id), querySelector: () => trigger, addEventListener() {} };
  const sandbox = vm.createContext({ window, document, HTMLElement, requestAnimationFrame: callback => callback(), AbortController, Intl });
  vm.runInContext(exposed, sandbox, { filename: 'daily-report.js' });
  return { api: window.DailyReport, helpers: sandbox.reportTest, calls, dialog, content, trigger, window, listeners };
}

test('report keeps the actual over-target percentage while its progress track stops at 100', () => {
  const app = context();
  app.api.open(snapshot, app.trigger);
  assert.match(app.content.innerHTML, /120%/);
  assert.match(app.content.innerHTML, /aria-valuenow="100"/);
  assert.match(app.content.innerHTML, /08:24:00/);
  assert.match(app.content.innerHTML, /\+12(?:\.00)?%/);
});

test('snapshot text and achievement details are escaped in card text and attributes', () => {
  const app = context();
  const report = { ...snapshot, username: '<img onerror=alert(1)>', subject_totals: [{ subject: '<script>bad()</script>', seconds: 1, percent: 1 }], achievements: [{ label: '<b>x</b>', detail: '" onmouseover="bad()' }] };
  app.api.open(report, app.trigger);
  assert.doesNotMatch(app.content.innerHTML, /<script>|<img|title="" onmouseover/);
  assert.match(app.content.innerHTML, /&lt;script&gt;/);
  assert.match(app.content.innerHTML, /&quot; onmouseover=&quot;bad\(\)/);
});

test('report index points preserve the three decimal places used by the dashboard quote', () => {
  const app = context();
  app.api.open({ ...snapshot, index: { ...snapshot.index, current: 9.015, open: 9.001, previous_close: 9.003 } }, app.trigger);
  assert.match(app.content.innerHTML, />9\.015<\/strong>/);
  assert.match(app.content.innerHTML, />9\.001<\/b>/);
  assert.match(app.content.innerHTML, />9\.003<\/b>/);
  assert.match(app.content.innerHTML, /\+12(?:\.00)?%/);
});

test('legacy report leaves unknown evidence empty and does not claim a complete subject distribution', () => {
  const app = context();
  const legacy = { ...snapshot, snapshot_kind: 'legacy_summary', subject_breakdown_complete: false,
    longest_session_seconds: null, trusted_seconds: null, untrusted_seconds: null, rank: null, percentile: null,
    index: null, challenge: null, achievements: [], subject_totals: [{ subject: '旧主要事项', seconds: 1000, percent: 50 }] };
  app.api.open(legacy, app.trigger);
  assert.match(app.content.innerHTML, /已存主要事项/);
  assert.match(app.content.innerHTML, /未保存完整科目比例/);
  assert.doesNotMatch(app.content.innerHTML, /daily-report-subject-track|<small>50%|#1|全程可信/);
  assert.match(app.content.innerHTML, /没有保存指数快照/);
  assert.match(app.content.innerHTML, /未保存当日挑战状态/);
  assert.equal(app.helpers.seconds(null), '—');
});

test('closing a pending transaction restores focus and completion does not reopen a dismissed card', () => {
  const app = context();
  app.api.pending(snapshot.date, app.trigger);
  assert.equal(app.dialog.open, true);
  app.api.close();
  app.api.complete(snapshot, app.trigger);
  assert.equal(app.dialog.open, false);
  assert.equal(app.calls.shown, 1);
  assert.equal(app.calls.back, 1);
  assert.ok(app.calls.focused >= 2);
});

test('browser back closes only the report without navigating again', () => {
  const app = context();
  app.api.open(snapshot, app.trigger);
  app.window.history.state = null;
  app.listeners.get('popstate')();
  assert.equal(app.dialog.open, false);
  assert.equal(app.calls.back, 0);
});

test('an unconfirmed object cannot render a successful settlement card', () => {
  const app = context();
  assert.equal(app.helpers.validReport({ date: snapshot.date, total_seconds: 0 }), false);
  assert.throws(() => app.api.open({ ...snapshot, version: 99 }), /尚未确认/);
  app.api.pending(snapshot.date, app.trigger);
  app.api.complete({ ...snapshot, snapshot_kind: 'live_preview' }, app.trigger);
  assert.match(app.content.innerHTML, /结算尚未确认/);
});
