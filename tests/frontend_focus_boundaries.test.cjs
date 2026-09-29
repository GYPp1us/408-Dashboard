const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
const testSource = source.replace(/\}\)\(\);\s*$/, 'globalThis.focusTest = { state, canManageOwnFocus, initializeFocusIdentity, sendForegroundHeartbeat, startForegroundHeartbeat, notifyNativeFocusState, applyFocusState, refreshCurrentPage, revokeFocusIdentity, startRest, api };})();');
const active = { id: 9, user_id: 2, subject: '数学 · 二轮', started_at: new Date(Date.now() - 60000).toISOString(), ended_at: null, paused_at: null, paused_seconds: 0 };

function context({ page = 'home', role = 'admin', viewerId = '2', response, storage = new Map(), nodes = new Map() } = {}) {
  const calls = { fetch: [], native: [], clear: 0, intervals: [], timeouts: [], warnings: [] };
  const listeners = new Map();
  const classList = { toggle() {}, add() {}, remove() {}, contains() { return false; } };
  const window = {
    location: { href: `https://example.test/${page}`, pathname: `/${page}`, origin: 'https://example.test' },
    addEventListener() {},
    setTimeout(fn, delay) { calls.timeouts.push(delay); return calls.timeouts.length; }, clearTimeout() {},
    setInterval(fn, delay) { calls.intervals.push(delay); return calls.intervals.length; }, clearInterval() {},
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    MutsumiAndroid: { syncFocusState: raw => calls.native.push(JSON.parse(raw)), clearFocusState: () => calls.clear++ },
  };
  const document = {
    body: { dataset: { page, role, viewerId }, classList },
    documentElement: { dataset: { themePalette: 'clay' }, classList },
    visibilityState: 'visible',
    querySelector: selector => nodes.get(selector) ?? null,
    querySelectorAll: selector => selector === 'form[action="/logout"]' && nodes.has('logout') ? [nodes.get('logout')] : [],
    addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(fn); },
    dispatchEvent() {}, createTextNode: text => text,
  };
  const sandbox = vm.createContext({
    window, document, navigator: {}, URL, AbortController, CustomEvent: class {},
    HTMLElement: class {}, Element: class {},
    requestAnimationFrame: fn => fn(),
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    console: { warn: (...args) => calls.warnings.push(args) },
    fetch: async (url, options) => {
      calls.fetch.push({ url, options });
      return response ? response(url, options) : { ok: true, status: 200, json: async () => url === '/api/dashboard'
        ? { preferences: { viewer_id: Number(viewerId) }, focus: { active: null, recent: [] } }
        : { ok: true } };
    },
  });
  vm.runInContext(testSource, sandbox, { filename: 'app.js' });
  return { api: sandbox.focusTest, calls, window, document, storage, listeners };
}

test('guest cannot heartbeat, take ownership of viewed focus or trigger native reminders', async () => {
  const app = context({ role: 'guest', viewerId: '99' });
  const viewed = { ...active, user_id: 99, paused_at: new Date(Date.now() - 360000).toISOString() };
  app.api.initializeFocusIdentity();
  app.api.applyFocusState(viewed);
  app.api.notifyNativeFocusState(viewed);
  await app.api.sendForegroundHeartbeat(true);
  app.api.startForegroundHeartbeat();
  app.api.startRest();
  assert.equal(app.api.canManageOwnFocus(), false);
  assert.equal(app.calls.fetch.length, 0);
  assert.equal(app.calls.native.length, 0);
  assert.equal(app.calls.intervals.length, 0);
  assert.equal(app.calls.clear, 1);
  assert.equal(app.api.state.focusRecoverySessionId, null);
  assert.equal(app.api.state.restStartedAt, null);
});

test('anonymous site sends no focus API requests and clears previous native identity', async () => {
  const app = context({ page: 'site', viewerId: 'public' });
  app.api.initializeFocusIdentity();
  app.api.startForegroundHeartbeat();
  await app.api.sendForegroundHeartbeat();
  await app.api.refreshCurrentPage();
  app.api.notifyNativeFocusState(active);
  assert.equal(app.calls.clear, 1);
  assert.equal(app.calls.fetch.length, 0);
  assert.equal(app.calls.native.length, 0);
});

for (const page of ['settings', 'account', 'focus-kline']) {
  test(`${page} native refresh keeps route and draft inputs, synchronizes owner without home controls`, async () => {
    const draft = { value: 'unsaved value' };
    const app = context({ page, nodes: new Map([['[name="exam_date"]', draft]]), response: async () => ({
      ok: true, status: 200, json: async () => ({ preferences: { viewer_id: 2 }, focus: { active, recent: [] } }),
    }) });
    const url = app.window.location.href;
    await app.api.refreshCurrentPage();
    assert.equal(app.window.location.href, url);
    assert.equal(draft.value, 'unsaved value');
    assert.deepEqual(app.calls.fetch.map(call => call.url), ['/api/dashboard']);
    assert.equal(app.calls.native.length, 1);
    assert.equal(app.calls.native[0].mode, 'focusing');
    assert.equal(app.calls.native[0].sessionId, active.id);
    assert.equal(app.api.state.focusRecoverySessionId, active.id);
  });
}

test('owner state without optional home controls is safe and still reaches native timer', () => {
  const app = context();
  app.api.applyFocusState(active);
  assert.equal(app.calls.native[0].sessionId, active.id);
});

test('partial home markup preserves native synchronization without missing-control errors', () => {
  const app = context({ nodes: new Map([['#idle-mode-view', {}], ['#active-mode-view', {}]]) });
  app.api.applyFocusState(active);
  assert.equal(app.calls.native[0].sessionId, active.id);
});

test('foreign focus session is rejected before updating recovery or ended transition', () => {
  const app = context();
  app.api.applyFocusState({ ...active, user_id: 99 });
  assert.equal(app.calls.native.length, 0);
  assert.equal(app.calls.clear, 1);
  assert.equal(app.api.state.lastActiveSnapshot, null);
  assert.equal(app.api.state.focusRecoverySessionId, null);
});

test('heartbeat response arriving after logout cannot revive synchronization or recovery', async () => {
  let release;
  const response = new Promise(resolve => { release = resolve; });
  const app = context({ response: () => response });
  const heartbeat = app.api.sendForegroundHeartbeat();
  app.api.revokeFocusIdentity();
  release({ ok: true, status: 200, json: async () => ({ recovered: true }) });
  await heartbeat;
  assert.equal(app.calls.fetch.length, 1);
  assert.equal(app.calls.native.length, 0);
  assert.equal(app.api.state.heartbeatFailureSince, null);
  assert.equal(app.api.canManageOwnFocus(), false);
});

for (const status of [401, 403]) {
  test(`heartbeat ${status} clears identity without ended state, retry loop or offline warning`, async () => {
    const app = context({ response: async () => ({ ok: false, status }) });
    app.api.state.dashboard = { focus: { active } };
    await app.api.sendForegroundHeartbeat();
    await app.api.sendForegroundHeartbeat();
    app.api.notifyNativeFocusState(active);
    assert.equal(app.calls.fetch.length, 1);
    assert.equal(app.calls.clear, 1);
    assert.equal(app.calls.native.length, 0);
    assert.equal(app.api.state.heartbeatFailureSince, null);
    assert.equal(app.calls.timeouts.includes(10000), false);
    assert.equal(app.api.canManageOwnFocus(), false);
  });
}

test('account switch response cannot send another viewer focus to native', async () => {
  const app = context({ page: 'settings', response: async () => ({
    ok: true, status: 200, json: async () => ({ preferences: { viewer_id: 99 }, focus: { active: { ...active, user_id: 99 } } }),
  }) });
  await app.api.refreshCurrentPage();
  assert.equal(app.calls.native.length, 0);
  assert.equal(app.calls.clear, 1);
  assert.equal(app.api.canManageOwnFocus(), false);
});

test('identity change resets old native runtime before new owner starts, rest is account scoped', () => {
  const storage = new Map([['mutsumiNativeFocusViewer', '99'], ['mutsumiRestStartedAt:99', '123']]);
  const app = context({ storage });
  app.api.initializeFocusIdentity();
  assert.equal(app.calls.clear, 1);
  app.api.startRest();
  assert.equal(storage.get('mutsumiRestStartedAt:99'), '123');
  assert.ok(Number(storage.get('mutsumiRestStartedAt:2')) > 0);
  app.api.revokeFocusIdentity();
  assert.equal(storage.has('mutsumiRestStartedAt:2'), false);
  assert.equal(app.calls.native.some(call => call.mode === 'ended'), false);
});

test('logout submit clears native and stops focus actions before navigation', async () => {
  const events = new Map();
  const form = { addEventListener: (name, fn) => events.set(name, fn) };
  const app = context({ page: 'account', nodes: new Map([['logout', form]]) });
  await app.listeners.get('DOMContentLoaded')[0]();
  events.get('submit')({ defaultPrevented: false });
  assert.equal(app.api.canManageOwnFocus(), false);
  assert.equal(app.calls.clear, 1);
  assert.equal(app.calls.native.some(call => call.mode === 'ended'), false);
});
