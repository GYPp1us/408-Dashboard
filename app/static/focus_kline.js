(() => {
  "use strict";

  const DEFAULT_PARAMETERS = {
    a_low_hours: 4,
    a_mid_hours: 7,
    a_high_hours: 9,
    k_low_percent_per_hour: 3.33,
    k_high_percent_per_hour: 5,
  };
  const state = { payload: null, charts: [], resizeObservers: [], resizeTimer: null, rangeDays: 0, selectedDate: null, liveTickTimer: null, liveTickClearTimer: null, liveTickGeneration: 0, liveDailySeries: null, liveDailyCandle: null };
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
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value || "").slice(11, 16) || "—";
    return date.toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false });
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
    if (["delisted", "退市"].includes(text)) return "delisted";
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
      tradingSessions: Array.isArray(source.trading_sessions) ? source.trading_sessions : [],
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
    const latestSource = source.latest ?? source.current ?? days.at(-1) ?? {};
    const latest = normalizeDay(latestSource, days.length, days.at(-2)?.close ?? 100);
    days.forEach((day) => { day.intraday = day.intraday.map((item, index) => normalizePoint(item, index, day.open)); });
    const current = finite(source.current_index ?? source.index_value ?? latest.close, latest.close);
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
    const today = { ...latest, intraday };
    const parameters = readParameters(source.parameters ?? source.params ?? {});
    return {
      days: days.length ? days : [today],
      today,
      intraday,
      current,
      status: normalizeStatus(latestStatus),
      focusState,
      isFocusing,
      focusSeconds: finite(source.today_focus_seconds ?? source.focus_seconds ?? latest.focusSeconds, latest.focusSeconds),
      updatedAt: source.updated_at ?? source.generated_at ?? source.now ?? new Date().toISOString(),
      intradayDate: String(source.intraday_date ?? source.selected_date ?? ""),
      limits: latestLimits,
      parameters,
      initialIndex: finite(source.initial_index, 100),
      priceTick: finite(source.price_tick, .001),
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

  function toUnixSeconds(value) {
    if (typeof value === "number" && Number.isFinite(value)) return Math.floor(value > 10_000_000_000 ? value / 1000 : value);
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : 0;
  }

  function chartDate(time) {
    if (typeof time === "number") return new Date(time * 1000);
    if (typeof time === "string") return new Date(`${time.slice(0, 10)}T00:00:00+08:00`);
    if (time && typeof time === "object" && time.year) return new Date(Date.UTC(time.year, time.month - 1, time.day));
    return new Date(NaN);
  }

  function chartTimeLabel(time) {
    const date = chartDate(time);
    if (Number.isNaN(date.getTime())) return "";
    if (typeof time === "number") return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
    return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit" }).format(date).replace("月", "/").replace("日", "");
  }

  function shanghaiMinutes(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 0;
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
    return finite(parts.find((part) => part.type === "hour")?.value, 0) * 60 + finite(parts.find((part) => part.type === "minute")?.value, 0);
  }

  function stopLiveTicks() {
    window.clearTimeout(state.liveTickTimer);
    window.clearTimeout(state.liveTickClearTimer);
    state.liveTickTimer = null;
    state.liveTickClearTimer = null;
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

  function isLiveMarketMinute(data, selected, latestPoint) {
    if (!selected || selected.date !== data.today.date || selected.delisted || !latestPoint) return false;
    const now = Date.now();
    if (selected.tradingSessions.length) {
      return selected.tradingSessions.some((session) => {
        const start = Date.parse(session.start);
        const end = Date.parse(session.end);
        return Number.isFinite(start) && Number.isFinite(end) && start <= now && now < end;
      });
    }
    return Math.abs(now - latestPoint.unix * 1000) < 90_000;
  }

  function applyLiveTrade(data, selected, series, latestPoint, price, direction, tickCount, liveHigh, liveLow) {
    series.update({ time: latestPoint.unix, value: price });
    const previousClose = finite(selected.previousClose, selected.open);
    const change = price - previousClose;
    const changePct = previousClose ? change / previousClose * 100 : 0;
    setText("#kline-current", point(price));
    setText("#kline-change", signedPoint(change));
    setText("#kline-change-pct", signedPercent(changePct));
    setText("#focus-kline-points", point(price));
    setText("#focus-kline-change", signedPercent(changePct));
    setText("#kline-last-updated", `逐笔 ${new Date().toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}`);
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
    quote?.classList.remove("is-tick-up", "is-tick-down");
    if (quote) void quote.offsetWidth;
    quote?.classList.add(direction > 0 ? "is-tick-up" : "is-tick-down");
    window.clearTimeout(state.liveTickClearTimer);
    state.liveTickClearTimer = window.setTimeout(() => quote?.classList.remove("is-tick-up", "is-tick-down"), 480);

    const tape = $("#kline-tick-tape");
    if (tape) {
      tape.hidden = false;
      tape.textContent = `${direction > 0 ? "▲" : "▼"} ${point(price)}`;
      tape.classList.toggle("is-up", direction > 0);
      tape.classList.toggle("is-down", direction < 0);
      tape.dataset.tickDirection = direction > 0 ? "up" : "down";
      tape.dataset.tickPrice = point(price);
      tape.dataset.tickCount = String(tickCount);
    }

    setText("#kline-high", point(liveHigh));
    setText("#kline-low", point(liveLow));
    setText("#kline-close", point(price));
    setText("#kline-amplitude", `${selected.open ? ((liveHigh - liveLow) / selected.open * 100).toFixed(2) : "0.00"}%`);
  }

  function startLiveTicks(data, selected, series, latestPoint) {
    stopLiveTicks();
    if (!series || !isLiveMarketMinute(data, selected, latestPoint)) return;
    const generation = state.liveTickGeneration;
    const minuteStarted = Math.floor(Date.now() / 60_000);
    const tickSize = Math.max(.001, finite(data.priceTick, .001));
    const basePrice = latestPoint.value;
    const maxOffset = Math.max(tickSize * 36, basePrice * .00045);
    let livePrice = basePrice;
    let liveHigh = selected.high;
    let liveLow = selected.low;
    let tickCount = 0;

    const schedule = () => {
      state.liveTickTimer = window.setTimeout(run, 720 + Math.random() * 1280);
    };
    const run = () => {
      if (generation !== state.liveTickGeneration) return;
      if (Math.floor(Date.now() / 60_000) !== minuteStarted) {
        loadKline();
        return;
      }
      const focusBias = data.isFocusing === true || data.focusState === "focus" ? .56 : .46;
      let direction = Math.random() < focusBias ? 1 : -1;
      if (livePrice - basePrice > maxOffset * .62) direction = -1;
      if (basePrice - livePrice > maxOffset * .62) direction = 1;
      if (Math.random() < .22 && Math.abs(livePrice - basePrice) > tickSize * 4) direction = livePrice > basePrice ? -1 : 1;
      const steps = 1 + Math.floor(Math.random() * 7);
      const previousTrade = livePrice;
      let candidate = livePrice + direction * steps * tickSize;
      const lower = Math.max(data.limits.low, basePrice - maxOffset);
      const upper = Math.min(data.limits.high, basePrice + maxOffset);
      livePrice = Math.round(Math.max(lower, Math.min(upper, candidate)) / tickSize) * tickSize;
      if (Math.abs(livePrice - previousTrade) < tickSize * .5) {
        direction *= -1;
        candidate = previousTrade + direction * steps * tickSize;
        livePrice = Math.round(Math.max(lower, Math.min(upper, candidate)) / tickSize) * tickSize;
      }
      direction = livePrice >= previousTrade ? 1 : -1;
      liveHigh = Math.max(liveHigh, livePrice);
      liveLow = Math.min(liveLow, livePrice);
      tickCount += 1;
      applyLiveTrade(data, selected, series, latestPoint, livePrice, direction, tickCount, liveHigh, liveLow);
      schedule();
    };
    schedule();
  }

  function destroyCharts() {
    stopLiveTicks();
    state.liveDailySeries = null;
    state.liveDailyCandle = null;
    state.resizeObservers.forEach((observer) => observer.disconnect());
    state.resizeObservers = [];
    state.charts.forEach((chart) => chart.remove?.());
    state.charts = [];
  }

  function lightweightOptions(host, overrides = {}) {
    const library = window.LightweightCharts;
    const solid = library.ColorType?.Solid ?? 0;
    const base = {
      width: Math.max(300, host.clientWidth),
      height: Math.max(220, host.clientHeight),
      layout: { background: { type: solid, color: "#ffffff" }, textColor: "#758079", fontFamily: '"Source Han Serif SC", "Noto Serif SC", serif', fontSize: 11 },
      grid: { vertLines: { color: "#edf0ef" }, horzLines: { color: "#edf0ef" } },
      rightPriceScale: { borderColor: "#dfe5e2", scaleMargins: { top: .08, bottom: .08 } },
      timeScale: { borderColor: "#dfe5e2", rightOffset: 3, barSpacing: 12, fixLeftEdge: true, lockVisibleTimeRangeOnResize: true, tickMarkFormatter: (time) => chartTimeLabel(time) },
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
    const latestListed = [...data.days].reverse().find((day) => !day.delisted && day.intraday.length);
    const fallback = latestListed || data.days.at(-1) || data.today;
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
    const chart = library.createChart(host, lightweightOptions(host, { timeScale: { borderColor: "#dfe5e2", rightOffset: 4, barSpacing: Math.max(7, Math.min(15, host.clientWidth / days.length)), fixLeftEdge: true, lockVisibleTimeRangeOnResize: true } }));
    const series = chart.addSeries(library.CandlestickSeries, { upColor: "#d66c58", downColor: "#4d8a73", borderVisible: false, wickUpColor: "#d66c58", wickDownColor: "#4d8a73", priceFormat: { type: "price", precision: 3, minMove: data.priceTick } });
    series.setData(days.map((item) => ({ time: item.date, open: item.open, high: item.high, low: item.low, close: item.close })));
    const liveDay = days.find((item) => item.date === data.today.date);
    if (liveDay && !liveDay.delisted) {
      state.liveDailySeries = series;
      state.liveDailyCandle = { time: liveDay.date, open: liveDay.open, high: liveDay.high, low: liveDay.low, close: liveDay.close };
    }
    addLimitLines(series, data);
    // Delisted candles remain frozen after the first breach.  Only the
    // first breached day is a delisting event; later candles may still be
    // today's quote or the historical day being inspected.
    const firstDelistedDate = data.days.find((item) => item.delisted)?.date || "";
    const selected = selectedDay(data);
    const markerDates = new Set([days.at(-1)?.date, firstDelistedDate, selected.date]);
    const markers = days.filter((item) => markerDates.has(item.date)).map((item) => {
      const isFirstDelisted = item.date === firstDelistedDate;
      const isSelected = item.date === selected.date;
      const isToday = item.date === data.today.date;
      return {
        time: item.date,
        position: isFirstDelisted ? "belowBar" : "aboveBar",
        color: isFirstDelisted ? "#758079" : isSelected ? "#8067b3" : "#b47a59",
        shape: isFirstDelisted ? "arrowDown" : isSelected ? "circle" : "square",
        text: isFirstDelisted ? "首次退市" : isSelected && !isToday ? "回看" : isToday ? "今日" : "",
      };
    });
    if (markers.length) library.createSeriesMarkers(series, markers);
    chart.subscribeClick((param) => {
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
    const selected = selectedDay(data);
    const points = selected.intraday.map((item) => ({ ...item, unix: toUnixSeconds(item.time) })).filter((item) => item.unix > 0).sort((left, right) => left.unix - right.unix).filter((item, index, array) => index === 0 || item.unix > array[index - 1].unix);
    const card = host.closest(".kline-intraday-card");
    card?.classList.toggle("is-empty", !points.length);
    setText("#kline-intraday-caption", dayCaption(data, selected));
    setText("#kline-selected-day", dayBadge(data, selected));
    setText("#kline-intraday-empty", selected.delisted ? `${selected.date} 已退市，无盘中记录` : `${selected.date} 暂无盘中记录`);
    if (empty) empty.hidden = Boolean(points.length);
    host.hidden = !points.length;
    if (!points.length) return;
    const library = window.LightweightCharts;
    const chart = library.createChart(host, lightweightOptions(host, { timeScale: { borderColor: "#dfe5e2", timeVisible: true, secondsVisible: false, rightOffset: 3, barSpacing: Math.max(5, Math.min(12, host.clientWidth / points.length)), fixLeftEdge: true, lockVisibleTimeRangeOnResize: true } }));
    const seriesOptions = { color: "#8067b3", lineWidth: 2, lineType: library.LineType?.Simple ?? 0, pointMarkersVisible: false, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: "price", precision: 3, minMove: data.priceTick } };
    const morning = points.filter((item) => shanghaiMinutes(item.time) <= 12 * 60);
    const afternoon = points.filter((item) => shanghaiMinutes(item.time) >= 13 * 60 + 30);
    const asLineData = (items) => items.map((item) => ({ time: item.unix, value: item.value }));
    // Lightweight Charts whitespace points do not consistently break a line
    // across a long intraday pause.  Separate morning and afternoon series so
    // the interior of the 12:00–13:30 lunch interval contains neither a
    // segment nor a point; the 12:00 morning close remains visible.
    const morningSeries = morning.length ? chart.addSeries(library.LineSeries, { ...seriesOptions, lastValueVisible: !afternoon.length }) : null;
    const afternoonSeries = afternoon.length ? chart.addSeries(library.LineSeries, seriesOptions) : null;
    morningSeries?.setData(asLineData(morning));
    afternoonSeries?.setData(asLineData(afternoon));
    const priceSeries = morningSeries || afternoonSeries;
    if (priceSeries) addLimitLines(priceSeries, data);
    const noonClose = morning.find((item) => shanghaiMinutes(item.time) === 12 * 60);
    if (noonClose) {
      const marker = document.createElement("div");
      const label = document.createElement("span");
      marker.className = "kline-noon-marker";
      marker.setAttribute("aria-label", "12:00 午间收盘");
      label.textContent = "12:00 午间收盘";
      marker.append(label);
      host.append(marker);
      const alignNoonMarker = () => {
        const x = chart.timeScale().timeToCoordinate(noonClose.unix);
        marker.hidden = x === null || x < 0 || x > host.clientWidth;
        if (!marker.hidden) marker.style.left = `${Math.round(x)}px`;
      };
      chart.timeScale().subscribeVisibleLogicalRangeChange(alignNoonMarker);
      chart.timeScale().subscribeSizeChange(alignNoonMarker);
      window.requestAnimationFrame?.(() => window.requestAnimationFrame?.(alignNoonMarker));
    }
    chart.timeScale().fitContent();
    const intradayCount = morning.length + afternoon.length;
    const intradayRange = intradayCount > 1 ? { from: -0.5, to: intradayCount - 0.5 } : null;
    if (intradayRange) {
      // Include both 08:00 and the final afternoon point explicitly; this
      // also resets a stale logical range when switching historical dates.
      pinVisibleLogicalRange(chart, intradayRange);
    }
    state.charts.push(chart);
    observeChart(host, chart, intradayRange ? () => pinVisibleLogicalRange(chart, intradayRange) : null);
    const latestPoint = points.at(-1);
    const liveSeries = afternoon.length ? afternoonSeries : morningSeries;
    startLiveTicks(data, selected, liveSeries, latestPoint);
  }

  function renderStatus(data) {
    const dot = $("[data-kline-state-dot]");
    dot?.classList.toggle("is-focus", data.status === "focus");
    dot?.classList.toggle("is-rest", data.status === "rest");
    dot?.classList.toggle("is-delisted", data.status === "delisted");
    setText("#kline-state", data.status === "focus" ? "专注中" : data.status === "delisted" ? "已退市" : data.status === "rest" ? "休息 / 未专注" : "等待数据");
    setText("#kline-session-state", data.status === "focus" ? "LIVE · 专注中" : data.status === "delisted" ? "已退市" : data.status === "rest" ? "休息中" : "等待开盘");
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
    const focusStatus = data.isFocusing === true || data.focusState === "focus" ? "专注中" : data.isFocusing === false || data.focusState === "rest" || data.status === "delisted" ? "休息 / 未专注" : "暂无状态";
    setText("#kline-focus-status", focusStatus);
    setText("#kline-limit-low", point(data.limits.low));
    setText("#kline-limit-high", point(data.limits.high));
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
        showFeedback("#kline-data-feedback", `已载入 ${data.days.length} 个交易日；指数分度 ${data.priceTick.toFixed(3)}。`, "ok");
      } catch (error) {
        showFeedback("#kline-data-feedback", error.message === "load_404" ? "K 线接口尚未启用，请先完成服务端数据计算。" : "历史数据读取失败，请稍后重试。", "error");
        data = normalizePayload({});
      }
    }
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
  }

  function bind() {
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
        if (state.payload) loadKline();
      }, 120);
    });
  }

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
