/* Shared business clock. Network sampling, UI seconds and animation timers are separate. */
(function (root, create) {
  if (typeof module === "object" && module.exports) module.exports = { create };
  else if (!root.DashboardClock) root.DashboardClock = create(root, document);
})(typeof window === "undefined" ? globalThis : window, function (host, document) {
  "use strict";
  const mono = () => host.performance?.now?.() ?? Date.now();
  const tasks = new Map(), pending = new Map();
  const localStarts = new Map();
  let anchorMono = mono(), anchorEpoch = Date.now(), correction = 0;
  let calibrated = false, sampleSequence = -1, timer = null, started = false;
  let frame = null, activeFrame = null, revision = 0;
  const hidden = () => document.hidden === true || document.visibilityState === "hidden";
  const read = (at = mono()) => {
    const elapsed = Math.max(0, at - anchorMono);
    return anchorEpoch + elapsed + correction * Math.min(1, elapsed / 10000);
  };
  const makeFrame = reason => {
    const monotonicMs = mono(), nowEpochMs = read(monotonicMs);
    return Object.freeze({ id: ++revision, nowEpochMs, monotonicMs, secondId: Math.floor(nowEpochMs / 1000), reason });
  };
  const report = error => host.console?.error?.("dashboard_clock_task_failed", error);
  function schedule() {
    host.clearTimeout(timer); timer = null;
    if (!started || hidden()) return;
    const at = mono(), now = read(at);
    const rate = 1 + (at - anchorMono < 10000 ? correction / 10000 : 0);
    const delay = (1000 - ((now % 1000 + 1000) % 1000)) / rate;
    timer = host.setTimeout(tick, Math.max(1, Math.ceil(delay) + 1));
  }
  function dispatch(next, update) {
    if (activeFrame) return update?.();
    activeFrame = next;
    try {
      update?.();
      if (!hidden()) {
        const jobs = [...pending.values()]; pending.clear();
        for (const job of jobs) job();
        // Read subscriptions after staged data has installed the new renderers.
        for (const name of [...tasks.keys()]) {
          try { tasks.get(name)?.(next); } catch (error) { report(error); }
        }
      }
      frame = next;
    } finally { activeFrame = null; schedule(); }
  }
  function tick() {
    if (hidden()) return schedule();
    const next = makeFrame("second");
    if (frame?.secondId === next.secondId) return schedule();
    dispatch(next);
  }
  const api = {
    now: () => activeFrame?.nowEpochMs ?? read(),
    monotonicNow: mono,
    currentFrame: () => activeFrame,
    lastFrame: () => frame,
    calibrate(reference, { sequence, receivedMono = mono() } = {}) {
      const epoch = Date.parse(reference);
      if (!Number.isFinite(epoch) || (Number.isFinite(sequence) && sequence <= sampleSequence)) return false;
      if (Number.isFinite(sequence)) sampleSequence = sequence;
      const current = read(receivedMono), delta = epoch - current;
      anchorMono = receivedMono;
      // Small corrections change speed, not the current displayed instant.
      // Large corrections are applied together at the next complete frame.
      anchorEpoch = !calibrated || Math.abs(delta) >= 2000 ? epoch : current;
      correction = !calibrated || Math.abs(delta) >= 2000 ? 0 : delta;
      calibrated = true;
      schedule();
      return true;
    },
    subscribe(name, task) {
      tasks.set(name, task);
      // Initial/rebuilt UI uses the last shared instant, never a private sample.
      if (!activeFrame && !hidden()) {
        frame ??= makeFrame("initial");
        activeFrame = frame;
        try { task(frame); } finally { activeFrame = null; }
      }
      return () => { if (tasks.get(name) === task) tasks.delete(name); };
    },
    unsubscribe: name => tasks.delete(name),
    elapsedLocal(start) {
      if (!Number.isFinite(start) || start <= 0) return 0;
      if (!localStarts.has(start)) {
        if (localStarts.size >= 8) localStarts.delete(localStarts.keys().next().value);
        localStarts.set(start, mono() - Math.max(0, Date.now() - start));
      }
      return Math.max(0, Math.floor(((activeFrame?.monotonicMs ?? mono()) - localStarts.get(start)) / 1000));
    },
    stage: (name, update) => pending.set(name, update),
    cancel: name => pending.delete(name),
    commit: update => dispatch(makeFrame("state"), update),
    refresh: () => dispatch(makeFrame("resume")),
    start() { if (!started) { started = true; api.refresh(); } },
    stop() { started = false; host.clearTimeout(timer); timer = null; },
  };
  document.addEventListener("visibilitychange", () => {
    if (hidden()) schedule();
    else if (started) api.refresh();
  });
  return api;
});
