/* Shared, proportional wall-clock axis for all intraday surfaces. */
(() => {
  "use strict";
  const parse = (value) => typeof value === "number" ? (value > 1e10 ? value / 1000 : value) : Date.parse(value) / 1000;
  const finite = (value, fallback = 0) => value !== null && value !== undefined && Number.isFinite(Number(value)) ? Number(value) : fallback;
  const offsetOf = (value) => /Z$/i.test(String(value || "")) ? "+00:00" : String(value || "").match(/([+-])(\d{2}):(\d{2})$/)?.[0] || "+08:00";
  const localIso = (timestamp, offset) => {
    const match = offset.match(/([+-])(\d{2}):(\d{2})/);
    const minutes = match ? (Number(match[2]) * 60 + Number(match[3])) * (match[1] === "-" ? -1 : 1) : 480;
    return new Date((timestamp + minutes * 60) * 1000).toISOString();
  };
  const clock = (timestamp, offset = "+08:00") => localIso(timestamp, offset).slice(11, 16);
  const clockSeconds = (timestamp, offset = "+08:00") => localIso(timestamp, offset).slice(11, 19);
  const dateAt = (timestamp, offset = "+08:00") => localIso(timestamp, offset).slice(0, 10);
  function market(date, sessions, reference) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
    const offset = offsetOf(sessions?.[0]?.start || reference);
    const fallback = [
      { name:"morning", start:`${date}T08:00:00${offset}`, end:`${date}T12:00:00${offset}` },
      { name:"afternoon", start:`${date}T13:30:00${offset}`, end:`${date}T22:00:00${offset}` },
    ];
    const sessionTime = (value) => /^\d{2}:\d{2}(:\d{2})?$/.test(String(value)) ? parse(`${date}T${value.length === 5 ? `${value}:00` : value}${offset}`) : parse(value);
    const windows = (Array.isArray(sessions) && sessions.length ? sessions : fallback)
      .map((item, index) => ({ name:String(item.name || index), start:sessionTime(item.start), end:sessionTime(item.end) }))
      .filter((item) => Number.isFinite(item.start) && Number.isFinite(item.end) && item.end > item.start)
      .sort((a, b) => a.start - b.start);
    if (!windows.length) return null;
    return { date, offset, windows, open:windows[0].start, close:windows.at(-1).end,
      asOf:parse(reference), receivedAt:Date.now() / 1000 };
  }
  function sessionIndex(session, time, includeClose = true) {
    return session?.windows.findIndex((window) => time >= window.start && (includeClose ? time <= window.end : time < window.end)) ?? -1;
  }
  function samples(session, raw, getTime, getValue) {
    const groups = session?.windows.map(() => []) || [];
    const events = session?.windows.map(() => []) || [];
    const ordered = (raw || []).map((item, index) => ({ item, index, time:parse(getTime(item)), value:Number(getValue(item)) }))
      .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
      .sort((a, b) => a.time - b.time || a.index - b.index);
    for (const point of ordered) {
      const group = sessionIndex(session, point.time);
      if (group < 0) continue;
      // Equal timestamps preserve both sides of a discrete jump at one x.
      groups[group].push({ time:point.time, value:point.value });
      if (point.item.changed || point.item.event || point.item.floor_reset || point.item.floorReset) {
        events[group].push({ time:point.time, value:point.value, floorReset:Boolean(point.item.floor_reset || point.item.floorReset) });
      }
    }
    return { groups, events };
  }
  function timeline(session) {
    let official = session.windows.map(() => []), tail = session.windows.map(() => []);
    let events = session.windows.map(() => []);
    return {
      reconcile(raw, getTime, getValue) {
        const next = samples(session, raw, getTime, getValue);
        official = next.groups;
        events = next.events;
        tail = tail.map((points, index) => {
          const lastOfficial = official[index].at(-1)?.time ?? session.windows[index].start;
          return points.filter((point) => point.time > lastOfficial && point.time < session.windows[index].end);
        });
        return this;
      },
      append(time, value) {
        const index = sessionIndex(session, time, false);
        if (index < 0) return -1;
        const formal = official[index].at(-1);
        const last = tail[index].at(-1);
        if ((formal && time <= formal.time) || (last && time < last.time)) return -1;
        if (last?.time === time) last.value = value;
        else tail[index].push({ time, value });
        if (tail[index].length > 90) tail[index].splice(0, tail[index].length - 90);
        return index;
      },
      get groups() { return official.map((points, index) => [...points, ...tail[index]]); },
      get events() { return events; },
    };
  }
  // Plot market breaks without changing the price samples used for statistics.
  // Hold the closing quote across the break, then jump at the reopening x.
  function breakSegments(session, points, asOf = Date.now() / 1000) {
    const segments = [];
    if (!session || !Number.isFinite(asOf)) return segments;
    for (let index = 0; index < session.windows.length - 1; index += 1) {
      const end = session.windows[index].end, start = session.windows[index + 1].start;
      if (start <= end || asOf <= end) continue;
      const closing = points.findLast((point) => point.time === end && Number.isFinite(point.value));
      if (!closing) continue;
      const segment = [{ time:end, value:closing.value }, { time:Math.min(asOf, start), value:closing.value }];
      if (asOf >= start) {
        const opening = points.find((point) => point.time === start && Number.isFinite(point.value));
        if (opening && opening.value !== closing.value) segment.push({ time:start, value:opening.value });
      }
      segments.push(segment);
    }
    return segments;
  }
  function project(snapshot, session, nowMs = Date.now()) {
    if (!snapshot) return null;
    const generated = parse(snapshot.generated_at || snapshot.updated_at);
    if (!Number.isFinite(generated)) return null;
    const age = Math.max(0, (nowMs - finite(snapshot.receivedAt, nowMs)) / 1000);
    const now = generated + age;
    const tick = snapshot.live_tick || {};
    const anchor = parse(tick.timestamp);
    const base = finite(tick.value_at, finite(snapshot.index?.current, 100));
    const serverGroup = sessionIndex(session, generated, false);
    const group = sessionIndex(session, now, false);
    const active = Boolean(snapshot.market_active && serverGroup >= 0 && group === serverGroup);
    const end = serverGroup >= 0 ? session.windows[serverGroup].end : generated;
    // The next server minute replaces the transient second samples. Freeze
    // after 20 seconds without a poll, and never project across a market break.
    const projectedAt = Math.min(generated + Math.min(age, 20), end - .001);
    const elapsed = Number.isFinite(anchor) ? Math.max(0, Math.min(60, projectedAt - anchor)) : 0;
    const raw = snapshot.market_active && serverGroup >= 0 ? base + finite(tick.per_second) * elapsed : finite(snapshot.index?.current, base);
    const value = Math.max(finite(snapshot.limit_down, -Infinity), Math.min(finite(snapshot.limit_up, Infinity), raw));
    return { value, now, time:Math.floor(projectedAt), active:active && age <= 20, stale:age > 20, group };
  }
  const pin = (chart, session) => { if (session) { chart.setMarket?.(session); chart.timeScale().setVisibleRange({ from:session.open, to:session.close }); } };
  const coordinate = (chart, time) => chart.timeScale().timeToCoordinate(time);

  // Lightweight Charts places timestamps on consecutive business indexes.
  // A small SVG renderer gives event seconds their real wall-clock position.
  let chartId = 0;
  function createChart(host, initialOptions = {}) {
    const NS = "http://www.w3.org/2000/svg";
    const node = (tag, attrs = {}, content = "") => {
      const element = document.createElementNS(NS, tag);
      Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
      if (content) element.textContent = content;
      return element;
    };
    const svg = node("svg", { class:"market-intraday-svg", "aria-hidden":"true", width:"100%", height:"100%", preserveAspectRatio:"none" });
    const tooltip = document.createElement("div");
    tooltip.className = "market-intraday-tooltip";
    tooltip.hidden = true;
    host.append(svg, tooltip);
    let options = initialOptions, range = null, removed = false, frame = null, session = null;
    const lines = [], listeners = new Set(), sizeListeners = new Set();
    const clipId = `market-clip-${++chartId}`;
    const geometry = () => {
      const width = Math.max(1, host.clientWidth || finite(options.width, 1));
      const height = Math.max(60, host.clientHeight || finite(options.height, 60));
      return { width, height, left:6, right:Math.max(7, width - 62), top:12, bottom:Math.max(13, height - 27) };
    };
    const xAt = (time) => {
      if (!range || !Number.isFinite(time) || range.to <= range.from) return null;
      const g = geometry();
      return g.left + (time - range.from) / (range.to - range.from) * (g.right - g.left);
    };
    function draw() {
      frame = null;
      if (removed) return;
      const g = geometry();
      svg.setAttribute("viewBox", `0 0 ${g.width} ${g.height}`);
      svg.replaceChildren();
      const textColor = options.layout?.textColor || "#738078";
      const fontFamily = options.layout?.fontFamily || "Arial, sans-serif";
      const label = (x, y, text, anchor = "start", color = textColor) => node("text", { x, y, fill:color, "font-size":10, "font-family":fontFamily, "text-anchor":anchor }, text);
      const values = lines.filter((line) => line.options.visible !== false).flatMap((line) => line.data).filter((point) => Number.isFinite(point.value)).map((point) => point.value);
      if (!range) return;
      const minimum = values.length ? Math.min(...values) : 100, maximum = values.length ? Math.max(...values) : 100;
      const padding = Math.max((maximum - minimum) * .14, Math.abs(values.at(-1) ?? 100) * .0004, .015);
      const low = minimum - padding, high = maximum + padding;
      const yAt = (value) => g.bottom - (value - low) / (high - low) * (g.bottom - g.top);
      const defs = node("defs"), clip = node("clipPath", { id:clipId });
      clip.append(node("rect", { x:g.left - 1, y:g.top - 4, width:g.right - g.left + 2, height:g.bottom - g.top + 8 }));
      defs.append(clip); svg.append(defs);
      for (let index = 0; index < 3; index += 1) {
        const value = low + (high - low) * index / 2, y = yAt(value);
        svg.append(node("line", { x1:g.left, x2:g.right, y1:y, y2:y, stroke:options.grid?.horzLines?.color || "#d9e1db", "stroke-opacity":.4, "stroke-width":.7 }));
        svg.append(label(g.right + 7, y + 3, value.toFixed(3)));
      }
      const duration = range.to - range.from;
      const targetTicks = Math.max(2, Math.floor((g.right - g.left) / 85));
      const step = [900, 1800, 3600, 7200, 10800, 14400, 21600].find((seconds) => duration / seconds <= targetTicks) || 21600;
      const offset = session?.offset || "+08:00";
      svg.append(label(g.left, g.height - 7, clock(range.from, offset)));
      for (let time = range.from + step; time < range.to; time += step) {
        const x = xAt(time);
        if (x - g.left > 42 && g.right - x > 42) svg.append(label(x, g.height - 7, clock(time, offset), "middle"));
      }
      svg.append(label(g.right, g.height - 7, clock(range.to, offset), "end"));
      const plot = node("g", { "clip-path":`url(#${clipId})` }), markerLayer = node("g");
      const visibleLines = lines.filter((line) => line.options.visible !== false && line.options.color !== "transparent");
      const breakPoints = visibleLines.flatMap((line) => line.data);
      const asOf = Number.isFinite(session?.asOf) ? session.asOf + Math.max(0, Date.now() / 1000 - session.receivedAt) : Date.now() / 1000;
      breakSegments(session, breakPoints, asOf).forEach((points) => {
        const line = visibleLines.find((item) => item.data.some((point) => point.time === points[0].time));
        const path = points.map((point, index) => `${index ? "L" : "M"}${xAt(point.time).toFixed(3)},${yAt(point.value).toFixed(3)}`).join(" ");
        plot.append(node("path", { class:"market-break-path", d:path, fill:"none", stroke:line?.options.color || "#8067b3", "stroke-width":Math.min(2, line?.options.lineWidth || 2), "stroke-linejoin":"miter", "stroke-linecap":"butt" }));
      });
      lines.forEach((line) => {
        if (line.options.visible === false) return;
        const points = line.data.filter((point) => Number.isFinite(point.value));
        const color = line.options.color || "#8067b3";
        if (color === "transparent" || !points.length) return;
        const path = points.map((point, index) => `${index ? "L" : "M"}${xAt(point.time).toFixed(3)},${yAt(point.value).toFixed(3)}`).join(" ");
        plot.append(node("path", { d:path, fill:"none", stroke:color, "stroke-width":Math.min(2, line.options.lineWidth || 2), "stroke-linejoin":"round", "stroke-linecap":"round" }));
        line.priceLines.forEach((priceLine) => {
          if (priceLine.price < low || priceLine.price > high) return;
          const y = yAt(priceLine.price);
          plot.append(node("line", { x1:g.left, x2:g.right, y1:y, y2:y, stroke:priceLine.color || textColor, "stroke-width":.7, "stroke-opacity":.55, "stroke-dasharray":"3 4" }));
        });
        line.markers.forEach((marker) => {
          const point = points.findLast((point) => point.time === marker.time && (marker.value === undefined || point.value === marker.value));
          if (!point) return;
          const x = xAt(marker.time), y = yAt(point.value), color = marker.color || "#b47a59";
          if (marker.shape === "arrowUp") markerLayer.append(node("path", { d:`M${x - 3},${y + 6} L${x},${y + 2} L${x + 3},${y + 6} M${x},${y + 2} L${x},${y + 11}`, fill:"none", stroke:color, "stroke-width":1.2 }));
          else markerLayer.append(node("circle", { cx:x, cy:y, r:2.5, fill:options.layout?.background?.color === "transparent" ? "#fff" : options.layout?.background?.color || "#fff", stroke:color, "stroke-width":1.1 }));
        });
        if (line.options.lastValueVisible !== false) {
          const last = points.at(-1), y = yAt(last.value);
          plot.append(node("circle", { cx:xAt(last.time), cy:y, r:2.1, fill:color }));
        }
      });
      svg.append(plot, markerLayer);
    }
    const schedule = () => {
      if (removed || frame !== null) return;
      if (typeof requestAnimationFrame === "function") { frame = -1; const id = requestAnimationFrame(draw); if (frame !== null) frame = id; }
      else draw();
    };
    const scale = {
      setVisibleRange(next) { range = next; schedule(); listeners.forEach((callback) => callback()); },
      timeToCoordinate:xAt,
      subscribeSizeChange(callback) { sizeListeners.add(callback); },
      subscribeVisibleLogicalRangeChange(callback) { listeners.add(callback); },
    };
    const move = (event) => {
      if (!range) return;
      const g = geometry(), rect = svg.getBoundingClientRect();
      const x = (event.clientX - rect.left) * g.width / Math.max(1, rect.width);
      if (x < g.left || x > g.right) { tooltip.hidden = true; return; }
      const time = range.from + (x - g.left) / (g.right - g.left) * (range.to - range.from);
      const points = lines.flatMap((line) => line.data).filter((point) => Number.isFinite(point.value));
      const nearest = points.reduce((best, point) => !best || Math.abs(point.time - time) <= Math.abs(best.time - time) ? point : best, null);
      if (!nearest) return;
      const marker = lines.flatMap((line) => line.markers).find((marker) => marker.time === nearest.time && (marker.value === undefined || marker.value === nearest.value));
      tooltip.textContent = `${clockSeconds(nearest.time, session?.offset || "+08:00")} · ${nearest.value.toFixed(3)}${marker ? marker.shape === "arrowUp" ? " · 收盘复位" : " · 专注状态切换" : ""}`;
      tooltip.style.left = `${Math.max(0, Math.min(g.width - 150, x - 75))}px`;
      tooltip.hidden = false;
    };
    svg.addEventListener("pointermove", move);
    svg.addEventListener("pointerdown", move);
    svg.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    return {
      linearTime:true,
      setMarket(next) { session = next; },
      timeScale:() => scale,
      addSeries(_type, seriesOptions = {}) {
        const line = { options:seriesOptions, data:[], markers:[], priceLines:[],
          setData(data) { this.data = data.map((point) => ({ ...point })); schedule(); },
          update(point) {
            const previous = this.data.at(-1);
            if (previous?.time === point.time) this.data[this.data.length - 1] = { ...point };
            else if (!previous || point.time > previous.time) this.data.push({ ...point });
            schedule();
          },
          applyOptions(next) { this.options = { ...this.options, ...next }; schedule(); },
          createPriceLine(next) { this.priceLines.push(next); schedule(); },
          setMarkers(markers) { this.markers = markers; schedule(); },
        };
        lines.push(line); return line;
      },
      applyOptions(next) {
        options = { ...options, ...next, layout:{ ...options.layout, ...next.layout }, grid:{ ...options.grid, ...next.grid } };
        schedule(); sizeListeners.forEach((callback) => callback());
      },
      remove() { removed = true; if (frame !== null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame); svg.remove(); tooltip.remove(); listeners.clear(); sizeListeners.clear(); },
    };
  }
  const createSeriesMarkers = (series, markers = []) => { series.setMarkers(markers); return { setMarkers:(next) => series.setMarkers(next) }; };
  window.IndexMarket = { parse, offsetOf, clock, clockSeconds, dateAt, market, sessionIndex, samples, timeline, breakSegments, project, pin, coordinate, createChart, createSeriesMarkers };
})();
