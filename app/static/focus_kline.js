(() => {
  "use strict";

  const DEFAULT_PARAMETERS = {
    a_low_hours: 4,
    a_mid_hours: 7,
    a_high_hours: 9,
    k_low_percent_per_hour: 3.33,
    k_high_percent_per_hour: 5,
  };
  const state = { payload: null, charts: [], resizeObservers: [], resizeTimer: null, rangeDays: 0, selectedDate: null, liveTickTimer: null, livePollTimer: null, liveTickClearTimer: null, nowMarkerTimer: null, liveTickGeneration: 0, liveResumeDispose: null, liveDailySeries: null, liveDailyCandle: null, liveIntraday: null, liveSnapshot: null };
  const Market = window.IndexMarket;
  const acceptPolicy = (data) => !data.challenge || !window.IndexChallenge || window.IndexChallenge.accept(data.challenge);
  let summaryPending = null, summaryRefreshDue = false, summaryRequestVersion = 0;
  let loadRequestVersion = 0, challengeLoadDue = false;
  const $ = (selector) => document.querySelector(selector);
  const finite = (value, fallback = 0) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  };
  const point = (value) => finite(value, 0).toFixed(3);
  const signedPoint = (value) => {
    const number = finite(value, 0);
    return `${Math.abs(number) < 0.0005 ? "±" : number > 0 ? "+" : "−"}${Math.abs(number).toFixed(3)}`;
  };
  const signedPercent = (value) => `${finite(value, 0) >= 0 ? "+" : "−"}${Math.abs(finite(value, 0)).toFixed(2)}%`;
  const formatSeconds = (value) => {
    const total = Math.max(0, Math.floor(finite(value, 0)));
    return [Math.floor(total / 3600), Math.floor((total % 3600) / 60), total % 60].map((part) => String(part).padStart(2, "0")).join(":");
  };
  const formatTime = (value) => {
    const timestamp = Market.parse(value);
    return Number.isFinite(timestamp) ? Market.clock(timestamp, Market.offsetOf(value)) : String(value || "").slice(11, 16) || "—";
  };
  const dateLabel = (value) => {
    const text = String(value || "");
    return text.length >= 10 ? text.slice(5, 10).replace("-", "/") : text;
  };

  function setText(selector, value) {
    const target = $(selector);
    if (target) target.textContent = value;
  }

  function readParameters(source = {}) {
    const aliases = {
      a_low_hours: ["a_low_hours", "a_low", "low_anchor_hours"],
      a_mid_hours: ["a_mid_hours", "a_mid", "mid_anchor_hours"],
      a_high_hours: ["a_high_hours", "a_high", "high_anchor_hours"],
      k_low_percent_per_hour: ["k_low_percent_per_hour", "k_low", "low_rate_percent_per_hour"],
      k_high_percent_per_hour: ["k_high_percent_per_hour", "k_high", "high_rate_percent_per_hour"],
    };
    return Object.fromEntries(Object.entries(DEFAULT_PARAMETERS).map(([key, fallback]) => {
      const candidate = aliases[key].map((name) => source[name]).find((value) => value !== undefined && value !== null && value !== "");
      return [key, finite(candidate, fallback)];
    }));
  }

  function normalizeStatus(value) {
    const text = String(value || "").trim().toLowerCase();
    if (["focus", "focused", "active", "专注", "进行中"].includes(text)) return "focus";
    if (["rest", "resting", "idle", "paused", "inactive", "休息", "未专注", "空闲", "closed"].includes(text)) return "rest";
    return text ? "rest" : "unknown";
  }

  function normalizeDay(item, index, previousClose = 100) {
    const source = item || {};
    const close = finite(source.close ?? source.c ?? source.value ?? source.index ?? previousClose, previousClose);
    const open = finite(source.open ?? source.o ?? previousClose, previousClose);
    const high = Math.max(open, close, finite(source.high ?? source.h, Math.max(open, close)));
    const low = Math.min(open, close, finite(source.low ?? source.l, Math.min(open, close)));
    const intraday = Array.isArray(source.intraday) ? source.intraday : [];
    return {
      date: String(source.date ?? source.day ?? source.trading_date ?? source.time ?? "").slice(0, 10) || `D-${index + 1}`,
      open, high, low, close,
      focusSeconds: finite(source.focus_seconds ?? source.total_seconds ?? source.seconds ?? source.focus, 0),
      status: normalizeStatus(source.status ?? source.state),
      focusState: normalizeStatus(source.focus_state ?? source.focus_status ?? source.focusStatus),
      isFocusing: source.is_focusing ?? source.isFocusing ?? null,
      delisted: Boolean(source.delisted) || String(source.status || "").toLowerCase() === "delisted",
      change: finite(source.change ?? source.delta, close - open),
      changePct: finite(source.change_pct ?? source.change_percent ?? source.pct, open ? (close - open) / open * 100 : 0),
      previousClose: finite(source.previous_close ?? source.previousClose, previousClose),
      limitUp: finite(source.limit_up, open * 1.1),
      limitDown: finite(source.limit_down, open * .9),
      tradingSessions: source.trading_sessions || source.tradingSessions || [],
      intraday,
    };
  }

  function normalizePoint(item, index, fallbackValue = 100) {
    const source = item || {};
    return {
      time: source.time ?? source.at ?? source.timestamp ?? source.created_at ?? index,
      value: finite(source.value ?? source.price ?? source.index ?? source.market ?? source.close, fallbackValue),
      status: normalizeStatus(source.status ?? source.state ?? source.mode),
      event: Boolean(source.event || source.transition || source.marker || source.changed),
      floorReset: Boolean(source.floor_reset || source.floorReset),
      label: source.label || source.note || "",
    };
  }

  function normalizePayload(raw) {
    const source = raw?.data && typeof raw.data === "object" ? raw.data : raw || {};
    const rawDays = source.candles ?? source.daily ?? source.history ?? source.days ?? source.daily_candles ?? [];
    const days = Array.isArray(rawDays) ? rawDays.reduce((result, item, index) => {
      const previous = result.at(-1)?.close ?? 100;
      result.push(normalizeDay(item, index, previous));
      return result;
    }, []) : [];
    const latestSource = source.today ?? source.latest ?? source.current ?? days.at(-1) ?? {};
    const latest = normalizeDay(latestSource, days.length, days.at(-2)?.close ?? 100);
    latest.intraday = latest.intraday.map((item, index) => normalizePoint(item, index, latest.open));
    days.forEach((day) => { day.intraday = day.intraday.map((item, index) => normalizePoint(item, index, day.open)); });
    const current = finite(source.index?.current ?? source.current_index ?? source.index_value ?? latest.close, latest.close);
    latest.close = current;
    latest.high = Math.max(latest.high, current);
    latest.low = Math.min(latest.low, current);
    const rawIntraday = source.intraday ?? source.timeline ?? source.today_intraday ?? latest.intraday ?? [];
    const intraday = Array.isArray(rawIntraday) ? rawIntraday.map((item, index) => normalizePoint(item, index, latest.open)) : [];
    const latestStatus = source.latest_status ?? source.status ?? intraday.at(-1)?.status ?? latest.status;
    const rawIsFocusing = source.is_focusing ?? source.isFocusing ?? latest.isFocusing;
    const focusState = normalizeStatus(source.focus_state ?? source.focus_status ?? source.today_focus_state ?? latest.focusState);
    const isFocusing = rawIsFocusing === null || rawIsFocusing === undefined ? (focusState === "focus" ? true : focusState === "rest" ? false : null) : Boolean(rawIsFocusing);
    const latestLimits = {
      low: finite(source.limit_down ?? latest.limitDown, 90),
      high: finite(source.limit_up ?? latest.limitUp, 110),
    };
    const intradayDate = String(source.intraday_date ?? source.selected_date ?? latest.date);
    const selected = days.find((day) => day.date === intradayDate);
    if (selected) selected.intraday = intraday;
    const today = { ...latest, intraday:intradayDate === latest.date ? intraday : latest.intraday };
    const parameters = readParameters(source.parameters ?? source.params ?? {});
    return {
      days: days.length ? days : [today],
      today,
      intraday,
      current,
      status: normalizeStatus(latestStatus),
      focusState,
      isFocusing,
      isPaused: Boolean(source.is_paused),
      focusSeconds: finite(source.today_focus_seconds ?? source.focus_seconds ?? latest.focusSeconds, latest.focusSeconds),
      updatedAt: source.updated_at ?? source.generated_at ?? source.now ?? new Date().toISOString(),
      intradayDate,
      limits: latestLimits,
      parameters,
      initialIndex: finite(source.initial_index, 100),
      priceTick: finite(source.price_tick, .001),
      challenge: source.challenge,
    };
  }

  function demoPayload() {
    const now = new Date();
    const days = [];
    let previous = 99.18;
    for (let index = 27; index >= 0; index -= 1) {
      const date = new Date(now);
      date.setDate(now.getDate() - index);
      const focus = 3.2 * 3600 + Math.round(Math.sin(index * .77) * 1.4 * 3600) + (index % 4) * 2100;
      const close = Math.max(90, Math.min(110, previous + (focus / 3600 - 7) * .34 + Math.sin(index * 1.9) * .72));
      const open = previous + Math.sin(index * 2.2) * .3;
      const intraday = [];
      for (let bar = 0; bar < 29; bar += 1) {
        const at = new Date(date);
        at.setHours(8 + Math.floor(bar / 2), bar % 2 ? 30 : 0, 0, 0);
        const status = (bar >= 3 && bar <= 9) || (bar >= 15 && bar <= 24) ? "focus" : "rest";
        intraday.push({ timestamp: at.toISOString(), price: Math.max(90, Math.min(110, open + Math.sin(bar * .72) * .7 + (status === "focus" ? bar * .045 : -bar * .022))), state: status, changed: [3, 10, 15, 25].includes(bar) });
      }
      days.push({ date: date.toISOString().slice(0, 10), open, high: Math.min(110, Math.max(open, close) + .62 + (index % 3) * .12), low: Math.max(90, Math.min(open, close) - .51), close, focus_seconds: focus, change: close - open, change_pct: (close - open) / open * 100, status: index ? "closed" : "active", intraday });
      previous = close;
    }
    return normalizePayload({ candles: days, latest: days.at(-1), parameters: DEFAULT_PARAMETERS, initial_index: 100, price_tick: .001, updated_at: now.toISOString() });
  }

  function chartDate(time) {
    if (typeof time === "number") return new Date(time * 1000);
    if (typeof time === "string") return new Date(`${time.slice(0, 10)}T00:00:00+08:00`);
    if (time && typeof time === "object" && time.year) return new Date(Date.UTC(time.year, time.month - 1, time.day));
    return new Date(NaN);
  }

  function chartTimeLabel(time, market = null) {
    const date = chartDate(time);
    if (Number.isNaN(date.getTime())) return "";
    if (typeof time === "number") return Market.clock(time, market?.offset || "+08:00");
    const businessDate = typeof time === "string" ? time.slice(0, 10) : time?.year ? `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}` : "";
    return businessDate ? businessDate.slice(5).replace("-", "/") : "";
  }

  function stopLiveTicks() {
    state.liveResumeDispose?.();
    state.liveResumeDispose = null;
    window.clearInterval(state.liveTickTimer);
    window.clearInterval(state.livePollTimer);
    window.clearTimeout(state.liveTickClearTimer);
    state.liveTickTimer = null;
    state.livePollTimer = null;
    state.liveTickClearTimer = null;
    state.liveIntraday = null;
    state.liveSnapshot = null;
    state.liveTickGeneration += 1;
    const quote = $("#kline-current");
    quote?.classList.remove("is-tick-up", "is-tick-down");
    const tape = $("#kline-tick-tape");
    if (tape) {
      tape.hidden = true;
      tape.classList.remove("is-up", "is-down");
      tape.removeAttribute("data-tick-direction");
      tape.removeAttribute("data-tick-price");
    }
  }

  function applyLiveTrade(data, selected, series, tickTime, price, direction, tickCount, liveHigh, liveLow) {
    if (series) series.update({ time: tickTime, value: price });
    const previousClose = finite(selected.previousClose, selected.open);
    const change = price - previousClose;
    const changePct = previousClose ? change / previousClose * 100 : 0;
    setText("#kline-current", point(price));
    setText("#kline-change", signedPoint(change));
    setText("#kline-change-pct", signedPercent(changePct));
    setText("#focus-kline-points", point(price));
    setText("#focus-kline-change", signedPercent(changePct));
    const changeLine = $(".kline-change-line");
    changeLine?.classList.toggle("is-up", change > .0005);
    changeLine?.classList.toggle("is-down", change < -.0005);
    const dayChange = $("#kline-day-change");
    if (dayChange) {
      dayChange.textContent = `${signedPoint(change)} · ${signedPercent(changePct)}`;
      dayChange.classList.toggle("is-up", change > .0005);
      dayChange.classList.toggle("is-down", change < -.0005);
    }
    if (state.liveDailySeries && state.liveDailyCandle) {
      state.liveDailyCandle.high = Math.max(state.liveDailyCandle.high, price);
      state.liveDailyCandle.low = Math.min(state.liveDailyCandle.low, price);
      state.liveDailyCandle.close = price;
      state.liveDailySeries.update(state.liveDailyCandle);
    }

    const quote = $("#kline-current");
    if (direction) {
      quote?.classList.remove("is-tick-up", "is-tick-down");
      if (quote) void quote.offsetWidth;
      quote?.classList.add(direction > 0 ? "is-tick-up" : "is-tick-down");
      window.clearTimeout(state.liveTickClearTimer);
      state.liveTickClearTimer = window.setTimeout(() => quote?.classList.remove("is-tick-up", "is-tick-down"), 480);
    }

    setText("#kline-high", point(liveHigh));
    setText("#kline-low", point(liveLow));
    setText("#kline-close", point(price));
    setText("#kline-amplitude", `${selected.open ? ((liveHigh - liveLow) / selected.open * 100).toFixed(2) : "0.00"}%`);
  }

  function startLiveTicks(data, selected, series, latestPoint) {
    if (!selected || selected.date !== data.today.date || selected.date !== Market.dateAt(Date.now() / 1000, state.liveIntraday?.market.offset)) return;
    const generation = state.liveTickGeneration;
    let lastPrice = latestPoint?.value ?? selected.close;
    let tickCount = 0;
    let liveHigh = selected.high, liveLow = selected.low, polling = false, refreshDue = false, requestVersion = 0, pollPending = null;
    const run = () => {
      const snapshot = state.liveSnapshot;
      if (document.hidden || generation !== state.liveTickGeneration || !snapshot || snapshot.requestVersion !== requestVersion) return;
      const view = state.liveIntraday;
      const projection = Market.project(snapshot, view?.market);
      if (!projection) return;
      const price = projection.value;
      const group = projection.active ? view.timeline.append(projection.time, price) : -1;
      if (group >= 0) {
        view.series[group].setData(view.timeline.groups[group]);
        view.series.forEach((line, index) => line.applyOptions({ lastValueVisible:index === group }));
        $("#kline-intraday-empty").hidden = true;
        $("#kline-intraday-chart").closest(".kline-intraday-card")?.classList.toggle("is-empty", false);
      }
      const direction = point(price) === point(lastPrice) ? 0 : price > lastPrice ? 1 : -1;
      if (direction) tickCount += 1;
      lastPrice = price;
      liveHigh = Math.max(liveHigh, price); liveLow = Math.min(liveLow, price);
      applyLiveTrade(data, selected, null, projection.time, price, direction, tickCount, liveHigh, liveLow);
      setText("#kline-last-updated", projection.stale ? "实时更新暂不可用 · 显示最近数据" : projection.active ? `逐秒 ${Market.clockSeconds(projection.now, view.market.offset)}` : `更新 ${Market.clockSeconds(Market.parse(snapshot.generated_at || snapshot.updated_at), view.market.offset)}`);
    };
    const poll = async (force = false) => {
      if (generation !== state.liveTickGeneration) return;
      if (force) { refreshDue = true; requestVersion += 1; }
      if (document.hidden) return;
      if (polling) return pollPending;
      const version = requestVersion;
      refreshDue = false;
      polling = true;
      pollPending = (async () => {
      try {
        const response = await fetch("/api/focus-kline/live", { credentials:"same-origin", cache:"no-store" });
        if (!response.ok) throw new Error("live unavailable");
        const body = await response.json();
        if (generation !== state.liveTickGeneration || version !== requestVersion) return;
        const snapshot = body.data || body;
        if (!acceptPolicy(snapshot) || generation !== state.liveTickGeneration || version !== requestVersion) return;
        snapshot.receivedAt = Date.now();
        snapshot.requestVersion = version;
        if (snapshot.intraday_date !== selected.date) { loadKline(); return; }
        state.liveSnapshot = snapshot;
        data.challenge = snapshot.challenge || data.challenge;
        data.limits = { low:finite(snapshot.limit_down, data.limits.low), high:finite(snapshot.limit_up, data.limits.high) };
        setText("#kline-limit-low", point(data.limits.low)); setText("#kline-limit-high", point(data.limits.high));
        selected.previousClose = finite(snapshot.previous_close, selected.previousClose);
        setText("#kline-focus-total", formatSeconds(snapshot.today_focus_seconds));
        setText("#focus-kline-hours", formatSeconds(snapshot.today_focus_seconds));
        setText("#kline-focus-status", snapshot.is_paused ? "已暂停" : snapshot.is_focusing ? "专注中" : "休息 / 未专注");
        renderStatus({ ...data, status:normalizeStatus(snapshot.status) });
        if (Array.isArray(snapshot.intraday) && state.liveIntraday) {
          const view = state.liveIntraday;
          const samples = view.timeline.reconcile(snapshot.intraday, (item) => item.time ?? item.at ?? item.timestamp, (item) => item.value ?? item.price ?? item.close);
          const hasPoints = samples.groups.some((group) => group.length);
          $("#kline-intraday-empty").hidden = hasPoints;
          $("#kline-intraday-chart").closest(".kline-intraday-card")?.classList.toggle("is-empty", !hasPoints);
          samples.groups.forEach((group, index) => {
            view.series[index].setData(group);
            view.markers[index]?.setMarkers(samples.events[index].map((event) => ({ time:event.time, value:event.value, position:event.floorReset ? "belowBar" : "aboveBar", shape:event.floorReset ? "arrowUp" : "circle", color:event.floorReset ? "#8067b3" : "#b47a59", text:event.floorReset ? "复位" : "" })));
          });
          Market.pin(view.chart, view.market);
        }
        run();
      } catch (_error) {
        if (generation === state.liveTickGeneration && version === requestVersion) setText("#kline-last-updated", "实时更新暂不可用 · 显示最近数据");
      } finally {
        polling = false; pollPending = null;
        if (refreshDue && !document.hidden && generation === state.liveTickGeneration) return poll();
      }
      })();
      return pollPending;
    };
    // Returning from suspension always reconciles before projecting again.
    const resume = () => !document.hidden ? poll(true) : undefined;
    const refreshFocus = () => poll(true);
    document.addEventListener("visibilitychange", resume);
    document.addEventListener("dashboard:focus-refreshed", refreshFocus);
    window.addEventListener("pageshow", resume);
    state.liveResumeDispose = () => {
      document.removeEventListener("visibilitychange", resume);
      document.removeEventListener("dashboard:focus-refreshed", refreshFocus);
      window.removeEventListener("pageshow", resume);
    };
    state.liveTickTimer = window.setInterval(run, 1000);
    state.livePollTimer = window.setInterval(poll, 15000);
    return poll();
  }

  function destroyCharts() {
    stopLiveTicks();
    window.clearInterval(state.nowMarkerTimer);
    state.nowMarkerTimer = null;
    state.liveDailySeries = null;
    state.liveDailyCandle = null;
    state.resizeObservers.forEach((observer) => observer.disconnect());
    state.resizeObservers = [];
    state.charts.forEach((chart) => chart.remove?.());
    state.charts = [];
  }

  const chartTheme = (key) => getComputedStyle(document.documentElement).getPropertyValue(key).trim();

  function lightweightOptions(host, overrides = {}) {
    const library = window.LightweightCharts;
    const solid = library.ColorType?.Solid ?? 0;
    const base = {
      width: Math.max(300, host.clientWidth),
      height: Math.max(220, host.clientHeight),
      layout: { background: { type: solid, color: chartTheme("--surface") }, textColor: chartTheme("--muted"), fontFamily: chartTheme("--font-index") || 'Arial, sans-serif', fontSize: 11 },
      grid: { vertLines: { color: chartTheme("--line") }, horzLines: { color: chartTheme("--line") } },
      rightPriceScale: { borderColor: chartTheme("--line"), scaleMargins: { top: .08, bottom: .08 } },
      timeScale: { borderColor: chartTheme("--line"), rightOffset: 3, barSpacing: 12, fixLeftEdge: true, lockVisibleTimeRangeOnResize: true, tickMarkFormatter: (time) => chartTimeLabel(time) },
      crosshair: { vertLine: { color: "#a997c8", width: 1, style: 3, labelBackgroundColor: "#8067b3" }, horzLine: { color: "#a997c8", width: 1, style: 3, labelBackgroundColor: "#8067b3" } },
      localization: { priceFormatter: (value) => point(value), timeFormatter: (time) => chartTimeLabel(time) },
    };
    return { ...base, ...overrides, timeScale: { ...base.timeScale, ...(overrides.timeScale || {}) }, localization: { ...base.localization, ...(overrides.localization || {}) } };
  }

  function addLimitLines(series, data) {
    const library = window.LightweightCharts;
    const dashed = library.LineStyle?.Dashed ?? 2;
    series.createPriceLine({ price: data.limits.high, color: "#d78c7d", lineWidth: 1, lineStyle: dashed, axisLabelVisible: true, title: "涨停" });
    series.createPriceLine({ price: data.limits.low, color: "#78a58f", lineWidth: 1, lineStyle: dashed, axisLabelVisible: true, title: "跌停" });
    series.createPriceLine({ price: data.initialIndex, color: "#b7c1bc", lineWidth: 1, lineStyle: library.LineStyle?.Dotted ?? 1, axisLabelVisible: false, title: "基准" });
  }

  function observeChart(host, chart, reapplyRange = null) {
    if (!window.ResizeObserver) return;
    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: Math.max(300, host.clientWidth), height: Math.max(220, host.clientHeight) });
      if (reapplyRange) window.requestAnimationFrame?.(() => reapplyRange());
    });
    observer.observe(host);
    state.resizeObservers.push(observer);
  }

  function pinVisibleLogicalRange(chart, range) {
    const apply = () => chart.timeScale().setVisibleLogicalRange(range);
    apply();
    // The first chart layout can happen after createChart() (and after the
    // first ResizeObserver callback). Re-apply on the next two frames so a
    // late width calculation cannot drop the opening candle/bar.
    window.requestAnimationFrame?.(apply);
    window.requestAnimationFrame?.(() => window.requestAnimationFrame?.(apply));
  }

  function selectedDay(data) {
    const requested = data.days.find((day) => day.date === state.selectedDate);
    if (requested) return requested;
    const latestWithPath = [...data.days].reverse().find((day) => day.intraday.length);
    const fallback = latestWithPath || data.days.at(-1) || data.today;
    state.selectedDate = fallback.date;
    return fallback;
  }

  function dayCaption(data, day) {
    if (!day) return "暂无可回看的交易日";
    return day.date === data.today.date ? "今日盘中路径；点击日 K 可回看历史" : `回看 ${day.date} · 点击其他蜡烛切换日期`;
  }

  function dayBadge(data, day) {
    return day?.date === data.today.date ? "今日" : `回看 ${day?.date || "—"}`;
  }

  function refreshCharts(data) {
    destroyCharts();
    renderOhlc(data, selectedDay(data));
    drawDailyChart(data);
    drawIntradayChart(data);
  }

  function drawDailyChart(data) {
    const host = $("#kline-daily-chart");
    const empty = $("#kline-daily-empty");
    if (!host || !window.LightweightCharts) return;
    const days = state.rangeDays > 0 ? data.days.slice(-state.rangeDays) : data.days;
    if (empty) empty.hidden = Boolean(days.length);
    host.hidden = !days.length;
    if (!days.length) return;
    const library = window.LightweightCharts;
    const chart = library.createChart(host, lightweightOptions(host, { timeScale: { borderColor: chartTheme("--line"), rightOffset: 4, barSpacing: Math.max(7, Math.min(15, host.clientWidth / days.length)), fixLeftEdge: true, lockVisibleTimeRangeOnResize: true } }));
    const series = chart.addSeries(library.CandlestickSeries, { upColor: "#d66c58", downColor: "#4d8a73", borderVisible: false, wickUpColor: "#d66c58", wickDownColor: "#4d8a73", priceFormat: { type: "price", precision: 3, minMove: data.priceTick } });
    series.setData(days.map((item) => ({ time: item.date, open: item.open, high: item.high, low: item.low, close: item.close })));
    const liveDay = days.find((item) => item.date === data.today.date);
    if (liveDay) {
      state.liveDailySeries = series;
      state.liveDailyCandle = { time: liveDay.date, open: liveDay.open, high: liveDay.high, low: liveDay.low, close: liveDay.close };
    }
    addLimitLines(series, data);
    // A sub-10 close is followed by a fresh 10-point opening on the next day.
    const lastResetDate = [...days].reverse().find((item) => item.delisted)?.date || "";
    const selected = selectedDay(data);
    const markerDates = new Set([days.at(-1)?.date, lastResetDate, selected.date]);
    const markers = days.filter((item) => markerDates.has(item.date)).map((item) => {
      const isReset = item.date === lastResetDate;
      const isSelected = item.date === selected.date;
      const isToday = item.date === data.today.date;
      return {
        time: item.date,
        position: isReset ? "belowBar" : "aboveBar",
        color: isReset ? "#758079" : isSelected ? "#8067b3" : "#b47a59",
        shape: isReset ? "arrowUp" : isSelected ? "circle" : "square",
        text: isReset ? "收盘复位" : isSelected && !isToday ? "回看" : isToday ? "今日" : "",
      };
    });
    if (markers.length) library.createSeriesMarkers(series, markers);
    chart.subscribeClick((param) => {
      if (window.ChartGestures?.shouldIgnoreClick(host)) return;
      const value = param?.time;
      const date = typeof value === "string" ? value : value && typeof value === "object" ? `${value.year}-${String(value.month).padStart(2, "0")}-${String(value.day).padStart(2, "0")}` : "";
      if (date && data.days.some((item) => item.date === date)) {
        const clickedDay = data.days.find((item) => item.date === date);
        state.selectedDate = date;
        if (clickedDay?.intraday.length) {
          refreshCharts(data);
        } else {
          const url = new URL(window.location.href);
          url.searchParams.set("date", date);
          window.history.replaceState(null, "", url);
          loadKline();
        }
      }
    });
    chart.timeScale().fitContent();
    // Keep the complete selected candle range visible, including the first
    // 100-point opening candle when “全部” is selected.  A logical range is
    // used instead of relying solely on fitContent(), whose right offset and
    // fixed edge options can otherwise clip the earliest business day.
    const dailyRange = days.length > 1 ? { from: -0.5, to: days.length - 0.5 } : null;
    if (dailyRange) pinVisibleLogicalRange(chart, dailyRange);
    state.charts.push(chart);
    observeChart(host, chart, dailyRange ? () => pinVisibleLogicalRange(chart, dailyRange) : null);
  }

  function drawIntradayChart(data) {
    const host = $("#kline-intraday-chart");
    const empty = $("#kline-intraday-empty");
    if (!host || !window.LightweightCharts) return;
    host.querySelector(".kline-noon-marker")?.remove();
    host.querySelector(".kline-now-marker")?.remove();
    const selected = selectedDay(data);
    const market = Market.market(selected.date, selected.tradingSessions, data.updatedAt);
    if (!market) return;
    const samples = Market.timeline(market).reconcile(selected.intraday, (item) => item.time, (item) => item.value);
    const points = samples.groups.flat().sort((a, b) => a.time - b.time);
    const card = host.closest(".kline-intraday-card");
    card?.classList.toggle("is-empty", !points.length);
    setText("#kline-intraday-caption", dayCaption(data, selected));
    setText("#kline-selected-day", dayBadge(data, selected));
    setText("#kline-intraday-empty", `${selected.date} 暂无盘中记录`);
    if (empty) empty.hidden = Boolean(points.length);
    host.hidden = false;
    const library = window.LightweightCharts;
    const chart = Market.createChart(host, lightweightOptions(host));
    chart.setMarket(market);
    if (selected.date === Market.dateAt(Date.now() / 1000, market.offset)) {
      const marker = document.createElement("div");
      marker.className = "kline-now-marker";
      marker.innerHTML = "<span>现在</span>";
      marker.title = `当前市场时间；横轴 ${Market.clock(market.open, market.offset)}–${Market.clock(market.close, market.offset)}`;
      host.append(marker);
      const alignNow = () => {
        const now = Market.project(state.liveSnapshot, market)?.now ?? Date.now() / 1000;
        const x = Market.coordinate(chart, now);
        marker.hidden = x === null || now < market.open || now > market.close;
        if (!marker.hidden) marker.style.left = `${x}px`;
      };
      state.nowMarkerTimer = window.setInterval(alignNow, 1000);
      chart.timeScale().subscribeSizeChange(alignNow);
      window.requestAnimationFrame?.(() => window.requestAnimationFrame?.(alignNow));
    }
    const seriesOptions = { color: "#8067b3", lineWidth: 2, lineType: library.LineType?.Simple ?? 0, pointMarkersVisible: false, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: "price", precision: 3, minMove: data.priceTick } };
    // One series per configured session leaves genuine gaps at every break.
    const lastGroup = [...samples.groups].findLastIndex((group) => group.length);
    const lineSeries = samples.groups.map((group, index) => {
      const series = chart.addSeries(library.LineSeries, { ...seriesOptions, lastValueVisible:index === lastGroup });
      series.setData(group);
      return series;
    });
    const markerGroups = lineSeries.map((series, index) => Market.createSeriesMarkers(series, samples.events[index].map((event) => ({
      time:event.time, value:event.value, position:event.floorReset ? "belowBar" : "aboveBar", shape:event.floorReset ? "arrowUp" : "circle", color:event.floorReset ? "#8067b3" : "#b47a59", text:event.floorReset ? "复位" : "",
    }))) || null);
    const priceSeries = lineSeries[Math.max(0, lastGroup)];
    if (priceSeries) addLimitLines(priceSeries, data);
    const breakClose = market.windows.length > 1 ? market.windows[0].end : null;
    if (breakClose && samples.groups[0].length) {
      const marker = document.createElement("div");
      const label = document.createElement("span");
      marker.className = "kline-noon-marker";
      marker.setAttribute("aria-label", `${Market.clock(breakClose, market.offset)} 休市`);
      label.textContent = `${Market.clock(breakClose, market.offset)} 休市`;
      marker.append(label);
      host.append(marker);
      const alignNoonMarker = () => {
        const x = chart.timeScale().timeToCoordinate(breakClose);
        marker.hidden = x === null || x < 0 || x > host.clientWidth;
        if (!marker.hidden) marker.style.left = `${Math.round(x)}px`;
      };
      chart.timeScale().subscribeVisibleLogicalRangeChange(alignNoonMarker);
      chart.timeScale().subscribeSizeChange(alignNoonMarker);
      window.requestAnimationFrame?.(() => window.requestAnimationFrame?.(alignNoonMarker));
    }
    Market.pin(chart, market);
    state.charts.push(chart);
    observeChart(host, chart, () => Market.pin(chart, market));
    state.liveIntraday = { chart, market, series:lineSeries, markers:markerGroups, timeline:samples };
    const latestPoint = points.at(-1);
    startLiveTicks(data, selected, lineSeries[Math.max(0, lastGroup)], latestPoint);
  }

  function renderStatus(data) {
    const dot = $("[data-kline-state-dot]");
    dot?.classList.toggle("is-focus", data.status === "focus");
    dot?.classList.toggle("is-rest", data.status === "rest");
    setText("#kline-state", data.status === "focus" ? "专注中" : data.status === "rest" ? "休息 / 未专注" : "等待数据");
    setText("#kline-session-state", data.status === "focus" ? "LIVE · 专注中" : data.status === "rest" ? "休息中" : "等待开盘");
    $("#kline-session-state")?.classList.toggle("is-live", data.status === "focus");
  }

  function renderQuote(data) {
    const change = finite(data.today.change, data.current - data.today.open);
    const changePct = finite(data.today.changePct, data.today.open ? change / data.today.open * 100 : 0);
    setText("#kline-current", point(data.current));
    setText("#kline-change", signedPoint(change));
    setText("#kline-change-pct", signedPercent(changePct));
    setText("#focus-kline-points", point(data.current));
    setText("#focus-kline-change", signedPercent(changePct));
    setText("#focus-kline-hours", formatSeconds(data.focusSeconds));
    const changeLine = $(".kline-change-line");
    changeLine?.classList.toggle("is-up", change > .0005);
    changeLine?.classList.toggle("is-down", change < -.0005);
    setText("#kline-market-date", data.today.date);
    setText("#kline-last-updated", `更新于 ${formatTime(data.updatedAt)}`);
    setText("#kline-focus-total", formatSeconds(data.focusSeconds));
    const focusStatus = data.isPaused ? "已暂停" : data.isFocusing === true || data.focusState === "focus" ? "专注中" : data.isFocusing === false || data.focusState === "rest" ? "休息 / 未专注" : "暂无状态";
    setText("#kline-focus-status", focusStatus);
    setText("#kline-limit-low", point(data.limits.low));
    setText("#kline-limit-high", point(data.limits.high));
  }

  async function refreshSummary(force = false) {
    if (force) { summaryRefreshDue = true; summaryRequestVersion += 1; }
    // Historical charts keep their selected date. The quote and today's focus
    // state still reconcile immediately, including before the market opens.
    if (document.hidden || state.liveResumeDispose || !state.payload) return summaryPending;
    if (summaryPending) return summaryPending;
    const version = summaryRequestVersion;
    summaryRefreshDue = false;
    summaryPending = (async () => {
      try {
        const response = await fetch("/api/focus-kline/live", { credentials:"same-origin", cache:"no-store" });
        if (!response.ok) throw new Error("summary unavailable");
        const body = await response.json(), snapshot = body.data || body;
        if (version !== summaryRequestVersion || state.liveResumeDispose || !state.payload) return;
        if (!acceptPolicy(snapshot) || version !== summaryRequestVersion || state.liveResumeDispose || !state.payload) return;
        if (document.hidden) { summaryRefreshDue = true; return; }
        const data = state.payload;
        const current = finite(snapshot.index?.current, data.current);
        const previous = finite(snapshot.previous_close, data.today.previousClose);
        const next = {
          ...data, current, status:normalizeStatus(snapshot.status),
          challenge:snapshot.challenge || data.challenge,
          isFocusing:Boolean(snapshot.is_focusing), isPaused:Boolean(snapshot.is_paused),
          focusState:snapshot.is_focusing && !snapshot.is_paused ? "focus" : "rest",
          focusSeconds:finite(snapshot.today_focus_seconds, data.focusSeconds),
          updatedAt:snapshot.generated_at || snapshot.updated_at || data.updatedAt,
          limits:{ low:finite(snapshot.limit_down, data.limits.low), high:finite(snapshot.limit_up, data.limits.high) },
          today:{ ...data.today, date:snapshot.intraday_date || data.today.date,
            previousClose:previous, close:current, change:current - previous,
            changePct:previous ? (current - previous) / previous * 100 : 0 },
        };
        state.payload = next;
        renderStatus(next); renderQuote(next);
      } catch (_error) {
        if (version === summaryRequestVersion) setText("#kline-last-updated", "实时更新暂不可用 · 显示最近数据");
      } finally {
        summaryPending = null;
        if (summaryRefreshDue && !document.hidden && !state.liveResumeDispose && state.payload) return refreshSummary();
      }
    })();
    return summaryPending;
  }

  function renderOhlc(data, selected = selectedDay(data)) {
    const day = selected || data.today;
    setText("#kline-day-label", day.date === data.today.date ? `${day.date} · 今日` : `${day.date} · 历史回看`);
    setText("#kline-open", point(day.open));
    setText("#kline-high", point(day.high));
    setText("#kline-low", point(day.low));
    setText("#kline-close", point(day.close));
    setText("#kline-amplitude", `${day.open ? ((day.high - day.low) / day.open * 100).toFixed(2) : "0.00"}%`);
    const dayChange = $("#kline-day-change");
    if (dayChange) {
      dayChange.textContent = `${signedPoint(day.change)} · ${signedPercent(day.changePct)}`;
      dayChange.classList.toggle("is-up", day.change > .0005);
      dayChange.classList.toggle("is-down", day.change < -.0005);
    }
    setText("#kline-focus-meter-value", formatSeconds(day.focusSeconds));
    const meter = $("#kline-focus-meter-fill");
    if (meter) meter.style.width = `${Math.min(100, Math.max(0, day.focusSeconds / (7 * 3600) * 100))}%`;
  }

  function renderParameters(parameters) {
    const values = readParameters(parameters);
    Object.entries(values).forEach(([name, value]) => {
      const input = document.querySelector(`[name="${name}"]`);
      if (input) input.value = value;
    });
  }

  function showFeedback(selector, message, type = "") {
    const target = $(selector);
    if (!target) return;
    target.textContent = message;
    target.className = target.className.replace(/\bis-(?:error|ok)\b/g, "").trim();
    if (type) target.classList.add(`is-${type}`);
  }

  function readFormParameters() {
    const form = $("#kline-params-form");
    if (!form) return { ...DEFAULT_PARAMETERS };
    return Object.fromEntries(Object.keys(DEFAULT_PARAMETERS).map((name) => [name, finite(form.elements[name]?.value, DEFAULT_PARAMETERS[name])]));
  }

  async function saveParameters(event) {
    event.preventDefault();
    const button = $(".kline-save-button");
    const values = readFormParameters();
    if (!(values.a_low_hours < values.a_mid_hours && values.a_mid_hours < values.a_high_hours)) {
      showFeedback("#kline-param-feedback", "锚点需满足 A_low < A_mid < A_high。", "error");
      return;
    }
    if (button) button.disabled = true;
    showFeedback("#kline-param-feedback", "正在保存参数…");
    try {
      const response = await fetch("/api/focus-kline/settings", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      if (!response.ok) throw new Error(`save_${response.status}`);
      const result = await response.json();
      renderParameters(result.parameters ?? values);
      showFeedback("#kline-param-feedback", "参数已应用，历史指数已重算。", "ok");
      await loadKline();
    } catch (error) {
      showFeedback("#kline-param-feedback", error.message === "save_403" ? "访客模式不可修改参数。" : "参数保存失败，请稍后重试。", "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function loadKline() {
    const page = $(".focus-kline-page");
    if (!page) return;
    const version = ++loadRequestVersion;
    challengeLoadDue = false;
    let data;
    const query = new URL(window.location.href).searchParams;
    const requestedDate = query.get("date") || state.selectedDate;
    if (query.get("demo") === "1") {
      data = demoPayload();
      showFeedback("#kline-data-feedback", "本地演示数据 · 接入 /api/focus-kline 后将自动替换为真实历史。", "ok");
    } else {
      showFeedback("#kline-data-feedback", "正在读取专注历史…");
      try {
        const apiUrl = new URL(page.dataset.klineApi || "/api/focus-kline", window.location.href);
        if (requestedDate) apiUrl.searchParams.set("date", requestedDate);
        const response = await fetch(apiUrl, { credentials: "same-origin" });
        if (!response.ok) throw new Error(`load_${response.status}`);
        data = normalizePayload(await response.json());
        if (version !== loadRequestVersion || !acceptPolicy(data) || version !== loadRequestVersion) return;
        showFeedback("#kline-data-feedback", "");
      } catch (error) {
        if (version !== loadRequestVersion) return;
        showFeedback("#kline-data-feedback", error.message === "load_404" ? "K 线接口尚未启用，请先完成服务端数据计算。" : "历史数据读取失败，请稍后重试。", "error");
        data = normalizePayload({});
      }
    }
    if (version !== loadRequestVersion) return;
    state.selectedDate = requestedDate && data.days.some((day) => day.date === requestedDate)
      ? requestedDate
      : data.days.some((day) => day.date === data.intradayDate) ? data.intradayDate : null;
    destroyCharts();
    state.payload = data;
    renderStatus(data);
    renderQuote(data);
    renderOhlc(data, selectedDay(data));
    renderParameters(data.parameters);
    drawDailyChart(data);
    drawIntradayChart(data);
    if (!state.liveResumeDispose) refreshSummary();
  }

  function bind() {
    document.addEventListener("dashboard:challenge-updated", () => {
      stopLiveTicks();
      summaryRequestVersion += 1;
      loadRequestVersion += 1;
      challengeLoadDue = true;
      if (!document.hidden) loadKline();
    });
    document.addEventListener("dashboard:focus-refreshed", () => {
      if (!state.liveResumeDispose) return refreshSummary(true);
    });
    const resumeSummary = () => {
      if (!document.hidden && challengeLoadDue) return loadKline();
      if (!document.hidden && !state.liveResumeDispose) return refreshSummary(true);
    };
    document.addEventListener("visibilitychange", resumeSummary);
    window.addEventListener("pageshow", resumeSummary);
    window.setInterval(() => {
      if (!state.liveResumeDispose) refreshSummary();
    }, 15000);
    $("#kline-params-form")?.addEventListener("submit", saveParameters);
    $("#kline-reset-defaults")?.addEventListener("click", () => {
      renderParameters(DEFAULT_PARAMETERS);
      showFeedback("#kline-param-feedback", "已恢复默认值；点击“应用参数”后保存。", "ok");
    });
    document.querySelectorAll("[data-kline-range]").forEach((button) => button.addEventListener("click", () => {
      state.rangeDays = Number(button.dataset.klineRange) || 0;
      document.querySelectorAll("[data-kline-range]").forEach((item) => item.classList.toggle("is-active", item === button));
      if (!state.payload) return;
      refreshCharts(state.payload);
    }));
    window.addEventListener("resize", () => {
      window.clearTimeout(state.resizeTimer);
      state.resizeTimer = window.setTimeout(() => {
        if (state.payload) refreshCharts(state.payload);
      }, 120);
    });
  }

  document.addEventListener("dashboard:appearance", () => {
    const appearance = { layout: { background: { type: "solid", color: chartTheme("--surface") }, textColor: chartTheme("--muted") }, grid: { vertLines: { color: chartTheme("--line") }, horzLines: { color: chartTheme("--line") } }, rightPriceScale: { borderColor: chartTheme("--line") }, timeScale: { borderColor: chartTheme("--line") } };
    state.charts.forEach((chart) => chart.applyOptions(appearance));
  });

  document.addEventListener("DOMContentLoaded", () => {
    if (document.body.dataset.page !== "focus-kline" && document.body.dataset.page !== "focus_kline") return;
    if (!window.LightweightCharts) {
      showFeedback("#kline-data-feedback", "图表库加载失败，无法显示行情。", "error");
      return;
    }
    bind();
    loadKline();
  });
})();
