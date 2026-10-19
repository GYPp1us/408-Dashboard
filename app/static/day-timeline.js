(() => {
  "use strict";
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const seconds = value => String(value).split(":").reduce((sum, part, index) => sum + Number(part) * (index === 0 ? 3600 : index === 1 ? 60 : 1), 0);
  function model(data, now, current, dayStart) {
    const morning = data.windows.morning, afternoon = data.windows.library;
    const start = seconds(morning.start), lunch = seconds(morning.end), reopen = seconds(afternoon.start), end = seconds(afternoon.end);
    const span = Math.max(1, end - start), position = value => clamp((value - start) / span, 0, 1);
    const boundary = current < start ? ["距离上午开盘", start] : current < lunch ? ["距离午休", lunch]
      : current < reopen ? ["距离下午开盘", reopen] : current < end ? ["距离闭馆", end] : ["距离上午开盘", 86400 + start];
    const segments = (data.focus?.today || []).flatMap(session => (session.segments?.length ? session.segments : [session]).map(segment => {
      const from = clamp((Date.parse(segment.started_at) - dayStart) / 1000, start, end);
      const to = clamp((Math.min(now, segment.ended_at ? Date.parse(segment.ended_at) : now) - dayStart) / 1000, start, end);
      return { left: position(from), width: Math.max(0, (to - from) / span), name: session.subject || "专注" };
    })).filter(segment => segment.width > 0);
    return { start, end, span, position: position(current), lunch: position(lunch), lunchWidth: Math.max(0, position(reopen) - position(lunch)),
      label: boundary[0], remaining: Math.max(0, Math.ceil(boundary[1] - current)), segments };
  }
  let latest = null, observed = null;
  function place() {
    const panel = document.querySelector("#day-timeline"), label = document.querySelector("#timeline-label");
    if (!panel || !label || !latest) return;
    const padding = parseFloat(getComputedStyle(panel).paddingLeft) || 14;
    const available = panel.clientWidth - padding * 2;
    const marker = padding + available * latest.position;
    const width = label.offsetWidth;
    const left = clamp(marker + 10 + width > panel.clientWidth - padding ? marker - width - 10 : marker + 10,
      padding, Math.max(padding, panel.clientWidth - width - padding));
    label.style.left = `${left}px`;
    panel.style.setProperty("--timeline-now", `${marker}px`);
    // At minimum panel width there may be insufficient space on either side.
    // End the stem below the complete label instead of drawing through digits.
    panel.style.setProperty("--timeline-stem-top", `${marker >= left && marker <= left + width ? label.offsetTop + label.offsetHeight + 4 : padding}px`);
    const ticks = document.querySelector("#timeline-ticks");
    ticks.replaceChildren();
    const spacing = available < 420 ? 4 * 3600 : available < 700 ? 3 * 3600 : 2 * 3600;
    for (let time = Math.ceil(latest.start / spacing) * spacing; time < latest.end; time += spacing) {
      const x = (time - latest.start) / latest.span;
      if (x * available < 56 || (1 - x) * available < 56) continue;
      const tick = document.createElement("span"); tick.style.left = `${x * 100}%`;
      tick.textContent = `${String(Math.floor(time / 3600)).padStart(2, "0")}:00`; ticks.append(tick);
    }
  }
  function render(data, { now, current, dayStart, format }) {
    const panel = document.querySelector("#day-timeline"); if (!panel) return;
    latest = model(data, now, current, dayStart);
    document.querySelector("#timeline-title").textContent = latest.label;
    document.querySelector("#timeline-clock").textContent = format(latest.remaining);
    document.querySelector("#timeline-start").textContent = data.windows.morning.start;
    document.querySelector("#timeline-end").textContent = data.windows.library.end;
    document.querySelector("#timeline-progress").style.width = `${latest.position * 100}%`;
    const lunch = document.querySelector("#timeline-lunch"); lunch.style.left = `${latest.lunch * 100}%`; lunch.style.width = `${latest.lunchWidth * 100}%`;
    const history = document.querySelector("#timeline-history"); history.replaceChildren();
    for (const segment of latest.segments) {
      const node = document.createElement("span"); node.style.left = `${segment.left * 100}%`; node.style.width = `${segment.width * 100}%`;
      node.title = segment.name; history.append(node);
    }
    panel.setAttribute("aria-label", `${latest.label}，${format(latest.remaining)}；全天 ${data.windows.morning.start} 至 ${data.windows.library.end}`);
    if (observed !== panel && window.ResizeObserver) { new ResizeObserver(place).observe(panel); observed = panel; }
    place();
  }
  if (typeof module !== "undefined") module.exports = { model };
  if (typeof window !== "undefined") {
    window.DayTimeline = { render, model };
    let data = null, skew = 0, offset = 0, timer = null;
    const format = value => [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60].map(part => String(part).padStart(2, "0")).join(":");
    function tick() {
      clearTimeout(timer); timer = null;
      if (!data || document.hidden) return;
      const now = Date.now() + skew, local = now + offset;
      const dayStart = Math.floor(local / 86400000) * 86400000 - offset;
      render(data, { now, current: Math.floor((now - dayStart) / 1000), dayStart, format });
      timer = setTimeout(tick, 1000 - (now % 1000) + 5);
    }
    document.addEventListener("dashboard:updated", event => {
      if (!event.detail?.windows || !document.querySelector("#day-timeline")) return;
      data = event.detail; skew = Date.parse(data.now) - Date.now();
      const zone = String(data.now).match(/([+-])(\d{2}):?(\d{2})$/);
      offset = zone ? (zone[1] === "-" ? -1 : 1) * (Number(zone[2]) * 60 + Number(zone[3])) * 60000 : 0;
      tick();
    });
    document.addEventListener("visibilitychange", tick);
  }
})();
