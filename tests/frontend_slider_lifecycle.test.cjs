const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// Run the actual app in isolation, using the same IIFE export seam as the focus
// boundaries tests. The doubles below model DOM/input/animation, not slider logic.
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
const testSource = source.replace(/\}\)\(\);\s*$/, `globalThis.sliderTest = {
  state, commitSliders, bindCommitSlider, bindSliderLifecycle,
  refreshCommitSliders, resetCommitSlider, updateFocusLockControl,
  markHeartbeatSuccess, initDragLaunchers, commitFocusStart, api
};})();`);

function classList() {
  const values = new Set();
  return {
    add: (...names) => names.forEach(name => values.add(name)),
    remove: (...names) => names.forEach(name => values.delete(name)),
    contains: name => values.has(name),
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : Boolean(force);
      enabled ? values.add(name) : values.delete(name);
      return enabled;
    },
  };
}

function eventTarget(properties = {}) {
  const listeners = new Map();
  return Object.assign({
    listeners,
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(callback);
    },
    removeEventListener(name, callback) {
      listeners.set(name, (listeners.get(name) || []).filter(item => item !== callback));
    },
    dispatchEvent(event) {
      for (const callback of [...(listeners.get(event.type) || [])]) callback(event);
      return !event.defaultPrevented;
    },
  }, properties);
}

function slider(id = 'test-slider') {
  const style = { setProperty(name, value) { this[name] = value; } };
  const thumb = eventTarget({
    x: 0, offsetWidth: 26, clientWidth: 26, style: { ...style },
    classList: classList(), dataset: {}, isConnected: true,
    setAttribute(name, value) { this[name] = value; },
  });
  const fill = { style: { ...style } };
  const label = { classList: classList(), textContent: '' };
  const track = eventTarget({
    id, clientWidth: 230, offsetWidth: 230, hidden: false, isConnected: true,
    dataset: { focusItemId: '3' }, classList: classList(), style: { ...style },
    querySelector: selector => ({ '.drag-thumb': thumb, '.drag-fill': fill, '.drag-label': label })[selector] || null,
    setAttribute(name, value) { this[name] = value; },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 230, height: 32, right: 230, bottom: 32 }),
    getClientRects: () => [{ width: 230, height: 32 }],
    contains: target => target === thumb || target === track,
    closest: () => track,
  });
  thumb.closest = () => track;
  thumb.parentElement = track;
  thumb.parentNode = track;
  thumb.getBoundingClientRect = () => ({ left: thumb.x + 2, top: 2, width: 26, height: 26 });
  thumb.getClientRects = () => [{ width: 26, height: 26 }];
  return { track, thumb, fill, label, max: 200 };
}

function harness({ response, nodes = new Map(), launchers = [] } = {}) {
  const calls = { sets: [], tweens: [], fetch: [], warnings: [], clearedTimers: [], reloads: 0 };
  const timers = new Map();
  const frames = new Map();
  const instances = new Map();
  let nextId = 1;
  const storage = new Map();
  const window = eventTarget({
    location: { href: 'https://example.test/', pathname: '/', origin: 'https://example.test', reload: () => calls.reloads++ },
    matchMedia: () => ({ matches: false }),
    crypto: { randomUUID: () => 'slider-test-token' },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    setTimeout(callback, delay) { const id = nextId++; timers.set(id, { callback, delay }); return id; },
    clearTimeout(id) { calls.clearedTimers.push(id); timers.delete(id); },
    setInterval: () => nextId++, clearInterval() {},
  });
  const document = eventTarget({
    body: { dataset: { page: 'home', role: 'admin', viewerId: '2' }, classList: classList(), style: {} },
    documentElement: { dataset: { themePalette: 'clay' }, classList: classList(), style: {} },
    visibilityState: 'visible', hidden: false,
    querySelector: selector => nodes.get(selector) ?? null,
    querySelectorAll: selector => selector === '.drag-launch' ? launchers : [],
    createTextNode: text => text,
  });
  const gsap = {
    getProperty: (target, property) => target[property] || 0,
    set(target, properties) {
      calls.sets.push({ target, properties });
      if (properties.x !== undefined) target.x = Number(properties.x);
    },
    to(target, properties) {
      const tween = { target, properties, killed: false, completed: false,
        kill() { this.killed = true; }, isActive() { return !this.killed && !this.completed; } };
      calls.tweens.push(tween);
      return tween;
    },
    killTweensOf(target) {
      calls.tweens.filter(tween => tween.target === target && !tween.completed).forEach(tween => tween.kill());
    },
    isTweening: target => calls.tweens.some(tween => tween.target === target && tween.isActive()),
  };
  const Draggable = {
    get: thumb => instances.get(thumb),
    create(thumb, options) {
      const drag = {
        target: thumb, vars: options, x: thumb.x, isPressed: false, isDragging: false,
        pointerEvent: null, updates: 0, enabledValue: true,
        update() { this.x = thumb.x; this.updates++; return this; },
        applyBounds() { return this.update(); },
        endDrag(event) {
          this.isPressed = this.isDragging = false;
          if (event) this.pointerEvent = event;
          options.onRelease?.call(this, this.pointerEvent);
        },
        enable() { this.enabledValue = true; return this; },
        disable() { this.enabledValue = false; this.isPressed = this.isDragging = false; return this; },
        enabled(value) { if (value !== undefined) this.enabledValue = value; return this.enabledValue; },
        kill() { instances.delete(thumb); this.disable(); },
      };
      instances.set(thumb, drag);
      return [drag];
    },
  };
  window.gsap = gsap;
  window.Draggable = Draggable;
  const requestAnimationFrame = callback => { const id = nextId++; frames.set(id, callback); return id; };
  window.requestAnimationFrame = requestAnimationFrame;
  window.cancelAnimationFrame = id => frames.delete(id);
  const sandbox = vm.createContext({
    window, document, gsap, Draggable, navigator: {}, URL, AbortController, TypeError,
    crypto: window.crypto, HTMLElement: class {}, Element: class {},
    CustomEvent: class { constructor(type, options = {}) { this.type = type; Object.assign(this, options); } },
    requestAnimationFrame, cancelAnimationFrame: window.cancelAnimationFrame,
    getComputedStyle: () => ({ getPropertyValue: () => '', display: 'block', visibility: 'visible' }),
    console: { warn: (...args) => calls.warnings.push(args), error() {} },
    fetch: async (url, options) => {
      calls.fetch.push({ url, options });
      return response ? response(url, options) : { ok: true, status: 200, json: async () => ({ ok: true }) };
    },
  });
  vm.runInContext(testSource, sandbox, { filename: 'app.js' });
  const app = sandbox.sliderTest;
  function complete(tween, evenIfKilled = false) {
    if (tween.completed || (tween.killed && !evenIfKilled)) return;
    tween.completed = true;
    if (tween.properties.x !== undefined) tween.target.x = Number(tween.properties.x);
    tween.properties.onUpdate?.();
    tween.properties.onComplete?.();
  }
  async function settleAnimations() {
    // Drain full promise chains between animation steps, including fetch JSON,
    // launcher cleanup, and the shared controller's finally callback.
    for (let turn = 0; turn < 3; turn++) {
      for (const tween of [...calls.tweens]) complete(tween);
      await new Promise(resolve => setImmediate(resolve));
    }
  }
  function emit(type, target = window, properties = {}) {
    const event = { type, target, pointerId: 1, repeat: false, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, ...properties };
    target.dispatchEvent?.(event);
    if (target !== document && target !== window) document.dispatchEvent(event);
    if (target !== window) window.dispatchEvent(event);
    return event;
  }
  function gesture(parts, ratio) {
    const drag = instances.get(parts.thumb);
    drag.isPressed = true;
    drag.pointerEvent = { type: 'pointerdown', target: parts.thumb, pointerId: 1 };
    drag.vars.onPressInit?.call(drag, drag.pointerEvent);
    drag.vars.onPress?.call(drag, drag.pointerEvent);
    parts.thumb.x = drag.x = parts.max * ratio;
    drag.isDragging = true;
    drag.vars.onDrag?.call(drag, { type: 'pointermove', target: parts.thumb, pointerId: 1 });
    drag.isPressed = drag.isDragging = false;
    drag.pointerEvent = { type: 'pointerup', target: parts.thumb, pointerId: 1 };
    drag.vars.onRelease?.call(drag, drag.pointerEvent);
    return drag;
  }
  function flushFrames() {
    for (const [id, callback] of [...frames]) { frames.delete(id); callback(); }
  }
  return { app, calls, document, window, timers, instances, complete, settleAnimations, emit, gesture, flushFrames };
}

function lockHarness() {
  const parts = slider('lock-focus');
  const status = { classList: classList(), querySelector: () => ({ textContent: '' }) };
  const app = harness({ nodes: new Map([['#lock-focus', parts.track], ['#focus-trust-state', status]]) });
  app.app.state.dashboard = { focus: { active: { id: 9, trusted: true, focus_locked: false } } };
  app.app.bindCommitSlider(parts.track, () => true, async () => {},
    () => app.app.state.dashboard.focus.active.focus_locked ? parts.max : 0);
  return { ...app, ...parts, drag: app.instances.get(parts.thumb) };
}

for (const busy of ['pressed', 'dragging', 'animating', 'pending', 'locking']) {
  test(`successful heartbeat preserves the lock thumb while ${busy}`, () => {
    const app = lockHarness();
    app.thumb.x = app.drag.x = 75;
    if (busy === 'pressed') app.drag.isPressed = true;
    else if (busy === 'dragging') app.drag.isDragging = true;
    else if (busy === 'locking') app.app.state.locking = true;
    else app.app.commitSliders.get(app.track).phase = busy;
    app.calls.sets.length = 0;
    app.app.markHeartbeatSuccess();
    assert.equal(app.thumb.x, 75, 'status synchronization must not overwrite an owned gesture or commit');
    assert.equal(app.calls.sets.filter(call => call.target === app.thumb && call.properties.x === 0).length, 0);
  });
}

test('an idle lock thumb follows the authoritative unlocked and locked state', () => {
  const app = lockHarness();
  app.thumb.x = app.drag.x = 75;
  app.app.updateFocusLockControl(app.app.state.dashboard.focus.active);
  assert.equal(app.thumb.x, 0);
  app.app.state.dashboard.focus.active.focus_locked = true;
  app.app.updateFocusLockControl(app.app.state.dashboard.focus.active);
  assert.equal(app.thumb.x, app.max);
  assert.equal(app.track.classList.contains('locked'), true);
});

for (const { ratio, allowed, expected } of [
  { ratio: .81, allowed: true, expected: 0 },
  { ratio: .82, allowed: true, expected: 1 },
  { ratio: .95, allowed: false, expected: 0 },
]) {
  test(`shared slider at ${ratio} with permission ${allowed} commits ${expected} times`, async () => {
    const parts = slider();
    const app = harness();
    let commits = 0;
    app.app.bindCommitSlider(parts.track, () => allowed, async () => { commits++; });
    app.gesture(parts, ratio);
    await app.settleAnimations();
    assert.equal(commits, expected);
  });
}

test('release and keyboard reentry cannot duplicate an animating or pending commit', async () => {
  const parts = slider();
  const app = harness();
  let resolveCommit;
  let commits = 0;
  const pending = new Promise(resolve => { resolveCommit = resolve; });
  app.app.bindCommitSlider(parts.track, () => true, async () => { commits++; await pending; });
  const drag = app.gesture(parts, .9);
  drag.vars.onRelease.call(drag, drag.pointerEvent);
  app.emit('keydown', parts.thumb, { key: 'Enter' });
  app.emit('keydown', parts.thumb, { key: 'Enter', repeat: true });
  await app.settleAnimations();
  assert.equal(commits, 1);
  drag.vars.onRelease.call(drag, drag.pointerEvent);
  app.emit('keydown', parts.thumb, { key: ' ' });
  await app.settleAnimations();
  assert.equal(commits, 1);
  resolveCommit();
  await app.settleAnimations();
  assert.equal(parts.thumb.x, 0);
});

for (const type of ['pointercancel', 'dashboard:viewport', 'pagehide']) {
  test(`${type} invalidates a pending snap animation before it can commit`, async () => {
    const parts = slider();
    const app = harness();
    let commits = 0;
    app.app.bindCommitSlider(parts.track, () => true, async () => { commits++; });
    app.app.bindSliderLifecycle();
    app.gesture(parts, .9);
    const snap = app.calls.tweens.find(tween => tween.target === parts.thumb && tween.properties.x === parts.max);
    assert.ok(snap, 'a committed gesture should first animate to the endpoint');
    app.emit(type, type === 'pointercancel' ? parts.thumb : app.window);
    app.flushFrames();
    // Even an already queued completion callback must honor cancellation.
    app.complete(snap, true);
    await app.settleAnimations();
    assert.equal(commits, 0);
  });
}

test('an old canceled completion cannot submit the next gesture while it is animating', async () => {
  const parts = slider();
  const app = harness();
  let commits = 0;
  app.app.bindCommitSlider(parts.track, () => true, async () => { commits++; });
  app.app.bindSliderLifecycle();
  app.gesture(parts, .9);
  const firstSnap = app.calls.tweens.at(-1);
  app.emit('pointercancel', parts.thumb);
  app.gesture(parts, .9);
  const nextSnap = app.calls.tweens.at(-1);
  assert.notEqual(firstSnap, nextSnap);
  app.complete(firstSnap, true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(commits, 0, 'an older callback must not borrow the new gesture\'s animating phase');
  app.complete(nextSnap);
  await app.settleAnimations();
  assert.equal(commits, 1);
});

test('pressing during the snap recovers after Draggable kills the tween before onPress', async () => {
  const parts = slider();
  const app = harness();
  let commits = 0;
  app.app.bindCommitSlider(parts.track, () => true, async () => { commits++; });
  const drag = app.gesture(parts, .9);
  const snap = app.calls.tweens.at(-1);
  assert.equal(app.app.commitSliders.get(parts.track).phase, 'animating');

  // GSAP Draggable's actual press sequence kills conflicting active x tweens
  // before invoking the application's onPress callback.
  app.window.gsap.killTweensOf(parts.thumb);
  drag.isPressed = true;
  drag.pointerEvent = { type: 'pointerdown', target: parts.thumb, pointerId: 1 };
  drag.vars.onPress.call(drag, drag.pointerEvent);
  assert.equal(snap.killed, true);
  assert.equal(app.app.commitSliders.get(parts.track).phase, 'idle');
  assert.equal(parts.thumb.x, 0);

  snap.properties.onComplete?.();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(commits, 0, 'the canceled snap must not submit from a queued completion');
  app.gesture(parts, .9);
  await app.settleAnimations();
  assert.equal(commits, 1, 'the following deliberate gesture must work without a page refresh');
  assert.equal(parts.thumb.x, 0);
});

for (const success of [true, false]) {
  test(`the same launcher is reusable after ${success ? 'success' : 'failure'}`, async () => {
    const parts = slider('launcher');
    const session = { id: 9, user_id: 2, subject: '数学', started_at: new Date().toISOString(), paused_at: null };
    const app = harness({ launchers: [parts.track], response: async () => ({
      ok: success, status: success ? 200 : 503,
      json: async () => success ? { session } : { error: 'try again' },
    }) });
    app.app.state.dashboard = { focus: { active: null, today: [] } };
    app.app.initDragLaunchers();
    for (let attempt = 0; attempt < 2; attempt++) {
      app.gesture(parts, .9);
      await app.settleAnimations();
      assert.equal(parts.thumb.x, 0, 'retaining this DOM must not retain the previous endpoint');
      assert.equal(app.app.state.starting, false);
      // The user's previous session has finished; reuse the identical track.
      app.app.state.dashboard.focus.active = null;
    }
    assert.equal(app.calls.fetch.filter(call => call.url === '/api/focus/start').length, 2);
  });
}

for (const stalledAt of ['connection', 'response body']) {
  test(`API deadline aborts a stalled ${stalledAt} and clears its timer`, async () => {
    const app = harness({ response: () => stalledAt === 'connection'
      ? new Promise(() => {})
      : { ok: true, status: 200, json: () => new Promise(() => {}) } });
    const result = app.app.api('/api/dashboard').then(value => ({ value }), error => ({ error }));
    await Promise.resolve();
    const [timerId, timer] = [...app.timers][0];
    assert.ok(app.calls.fetch[0].options.signal, 'requests must have a cancellation signal');
    timer.callback();
    const outcome = await result;
    assert.ok(outcome.error, 'the UI must regain control even if fetch ignores abort');
    assert.equal(app.calls.fetch[0].options.signal.aborted, true);
    assert.equal(app.timers.has(timerId), false);
    assert.equal(app.calls.clearedTimers.includes(timerId), true);
    assert.equal(app.calls.reloads, 0);
  });
}

for (const ok of [true, false]) {
  test(`API ${ok ? 'success' : 'HTTP failure'} clears the deadline timer`, async () => {
    const app = harness({ response: async () => ({ ok, status: ok ? 200 : 503,
      json: async () => ok ? { result: 'ready' } : { error: 'service unavailable' } }) });
    const result = app.app.api('/api/dashboard').then(value => ({ value }), error => ({ error }));
    const deadlineId = [...app.timers.keys()][0];
    const outcome = await result;
    assert.equal(Boolean(outcome.error), !ok);
    assert.equal(app.timers.has(deadlineId), false);
    assert.equal(app.calls.clearedTimers.includes(deadlineId), true);
    assert.equal(app.calls.fetch[0].options.signal.aborted, false);
    assert.equal(app.calls.reloads, 0);
  });
}

test('an uncertain focus POST timeout warns and reloads to reconcile server state', async () => {
  const toast = { textContent: '', classList: classList() };
  const app = harness({ nodes: new Map([['#toast', toast]]), response: () => new Promise(() => {}) });
  const result = app.app.api('/api/focus/end', { method: 'POST' }).then(value => ({ value }), error => ({ error }));
  const [deadlineId, deadline] = [...app.timers][0];
  deadline.callback();
  assert.ok((await result).error);
  assert.equal(app.calls.fetch[0].options.signal.aborted, true);
  assert.equal(app.timers.has(deadlineId), false);
  assert.notEqual(toast.textContent, '');
  for (const timer of [...app.timers.values()]) timer.callback();
  assert.equal(app.calls.reloads, 1);
});

test('caller cancellation clears the API deadline without scheduling a recovery reload', async () => {
  const toast = { textContent: '', classList: classList() };
  const app = harness({ nodes: new Map([['#toast', toast]]), response: (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('caller canceled'), { name: 'AbortError' })), { once: true });
  }) });
  const caller = new AbortController();
  const request = app.app.api('/api/focus/start', { method: 'POST', signal: caller.signal });
  const rejected = assert.rejects(request);
  const deadlineId = [...app.timers.keys()][0];
  caller.abort();
  await rejected;
  assert.equal(app.timers.has(deadlineId), false);
  assert.equal(toast.textContent, '');
  assert.equal(app.calls.reloads, 0);
  assert.equal(app.timers.size, 0);
});

for (const { url, method, shouldReconcile } of [
  { url: '/api/focus/start', method: 'POST', shouldReconcile: true },
  { url: '/api/focus/end', method: 'POST', shouldReconcile: true },
  { url: '/api/focus/pause', method: 'POST', shouldReconcile: true },
  { url: '/api/focus/lock', method: 'POST', shouldReconcile: true },
  { url: '/api/daily-settlement', method: 'POST', shouldReconcile: true },
  { url: '/api/focus/start', method: 'GET', shouldReconcile: false },
  { url: '/api/dashboard', method: 'GET', shouldReconcile: false },
  { url: '/api/settings', method: 'POST', shouldReconcile: false },
]) {
  test(`${method} ${url} ${shouldReconcile ? 'reconciles an uncertain write' : 'does not schedule a focus recovery reload'}`, async () => {
    const toast = { textContent: '', classList: classList() };
    const app = harness({ nodes: new Map([['#toast', toast]]), response: async () => { throw new TypeError('network disconnected'); } });
    await assert.rejects(app.app.api(url, { method }));
    assert.equal(Boolean(toast.textContent), shouldReconcile);
    for (const timer of [...app.timers.values()]) timer.callback();
    assert.equal(app.calls.reloads, shouldReconcile ? 1 : 0);
  });
}
