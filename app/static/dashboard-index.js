(() => {
  "use strict";
  const view = document.getElementById("activity-index-view");
  if (!view) return;
  const $ = (selector) => view.querySelector(selector);
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const points = (value) => number(value).toFixed(3);
  const signed = (value, digits = 3) => `${value > 0 ? "+" : value < 0 ? "−" : "±"}${Math.abs(value).toFixed(digits)}`;
  const duration = (seconds) => { const s = Math.max(0, Math.floor(number(seconds))); return [Math.floor(s / 3600), Math.floor(s % 3600 / 60), s % 60].map((v) => String(v).padStart(2, "0")).join(":"); };
  const todayDate = () => (dashboardNow || latest?.updated_at || "").slice(0, 10) || null;
  const visible = () => !document.hidden && !view.hidden && view.getClientRects().length > 0;
  let latest = null, live = null, dashboardNow = "", fetchedAt = 0, attemptedAt = 0, pending = null, livePending = null, context = null, homeChart = null, drawerDispose = null, refreshDue = false;
  const DAY_MINUTES = 24 * 60;
  const marketDay = (data) => String(data?.intraday_date || data?.day?.date || data?.today?.date || todayDate() || "").slice(0, 10);
  const dayStart = (date) => Math.floor(Date.parse(`${date}T00:00:00+08:00`) / 1000);
  const minuteTime = (time) => Math.floor(time / 60) * 60;
  const dayScaffold = (date) => {
    const start = dayStart(date);
    return Number.isFinite(start) ? Array.from({ length:DAY_MINUTES + 1 }, (_, minute) => ({ time:start + minute * 60 })) : [];
  };

  function normalize(raw) {
    const data = raw?.data || raw;
    if (!data || typeof data !== "object" || !Array.isArray(data.candles)) throw new Error("指数数据格式错误");
    const day = data.today || data.latest || {};
    const current = number(data.index?.current, number(day.close, 100));
    const previous = number(data.previous_close, number(day.open, 100));
    return { ...data, day, current, change:current - previous, pct:previous ? (current - previous) / previous * 100 : 0 };
  }
  async function request(date = todayDate(), signal) {
    const url = date ? `/api/focus-kline?date=${encodeURIComponent(date)}` : "/api/focus-kline";
    const response = await fetch(url, { credentials:"same-origin", cache:"no-store", signal });
    if (!response.ok) throw new Error(`读取指数失败 (${response.status})`);
    return normalize(await response.json());
  }
  async function requestLive() {
    const response = await fetch("/api/focus-kline/live", { credentials:"same-origin", cache:"no-store" });
    if (!response.ok) throw new Error(`读取实时指数失败 (${response.status})`);
    const body = await response.json();
    return body.data || body;
  }
  function chartOptions(host, date = "") {
    const style = getComputedStyle(document.documentElement);
    return { width:Math.max(1, host.clientWidth), height:Math.max(70, host.clientHeight), layout:{ background:{ type:"solid", color:"transparent" }, textColor:style.getPropertyValue("--muted").trim() || "#738078", fontFamily:getComputedStyle(host).fontFamily, fontSize:11 }, grid:{ vertLines:{ visible:false }, horzLines:{ color:style.getPropertyValue("--line").trim() || "#d9e1db" } }, rightPriceScale:{ borderVisible:false }, timeScale:{ borderVisible:false, minBarSpacing:0.01, timeVisible:true, secondsVisible:false, lockVisibleTimeRangeOnResize:true, tickMarkFormatter:(time) => typeof time === "number" ? dayTick(time, date) : null }, localization:{ locale:"zh-CN", timeFormatter:(time) => marketClock(time, date) }, handleScroll:{ mouseWheel:false, pressedMouseMove:false, horzTouchDrag:false, vertTouchDrag:false }, handleScale:{ axisPressedMouseMove:false, mouseWheel:false, pinch:false } };
  }
  function dayTick(time, date) {
    const hour = (time - dayStart(date)) / 3600;
    return hour <= 2 || hour >= 22 ? "" : marketClock(time, date);
  }
  function marketClock(time, date = "") {
    if (time && typeof time === "object" && time.year) return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}`;
    if (typeof time !== "number") return String(time);
    if (date && time === dayStart(date) + DAY_MINUTES * 60) return "24:00";
    // API timestamps carry the configured timezone offset; keep chart labels
    // in that market timezone even when the browser is in another location.
    const offset = (dashboardNow || latest?.updated_at || "").match(/([+-])(\d{2}):(\d{2})$/);
    const minutes = offset ? (Number(offset[2]) * 60 + Number(offset[3])) * (offset[1] === "-" ? -1 : 1) : 0;
    return new Date((time + minutes * 60) * 1000).toLocaleTimeString("zh-CN", { timeZone:"UTC", hour:"2-digit", minute:"2-digit" });
  }
  function indexColors() {
    const style = getComputedStyle(document.documentElement);
    return { rise:style.getPropertyValue("--index-rise").trim() || "#d66c58", fall:style.getPropertyValue("--index-fall").trim() || "#4d8a73" };
  }
  function applyChartTheme(instance, host) {
    if (!instance) return;
    const colors = indexColors();
    instance.chart.applyOptions(chartOptions(host, instance.scaffoldDate));
    instance.series.applyOptions(instance.daily ? { upColor:colors.rise, downColor:colors.fall, wickUpColor:colors.rise, wickDownColor:colors.fall } : { color:instance.falling ? colors.fall : colors.rise });
    if (instance.daily) instance.chart.applyOptions({ timeScale:{ timeVisible:false } });
  }
  function createChart(host, daily = false) {
    const library = window.LightweightCharts;
    if (!library?.createChart || !library.LineSeries || !library.CandlestickSeries) return null;
    const chart = library.createChart(host, chartOptions(host));
    const colors = indexColors();
    const options = daily ? { upColor:colors.rise, downColor:colors.fall, borderVisible:false, wickUpColor:colors.rise, wickDownColor:colors.fall, priceFormat:{ type:"price", precision:3, minMove:.001 } } : { color:colors.rise, lineWidth:2, crosshairMarkerVisible:true, priceFormat:{ type:"price", precision:3, minMove:.001 } };
    const series = chart.addSeries(daily ? library.CandlestickSeries : library.LineSeries, options);
    const markers = !daily && library.createSeriesMarkers ? library.createSeriesMarkers(series, []) : null;
    if (daily) chart.applyOptions({ timeScale:{ timeVisible:false } });
    // A visible whitespace-only series participates in the library's time scale.
    // `visible:false` is excluded and leaves the plotted morning points stretched.
    const scaffold = daily ? null : chart.addSeries(library.LineSeries, { visible:true, color:"transparent", priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false });
    const observer = new ResizeObserver(() => {
      if (!host.isConnected || !host.clientWidth) return;
      chart.applyOptions({ width:host.clientWidth, height:Math.max(70, host.clientHeight) });
      if (!daily) pinDay(chart);
    });
    observer.observe(host);
    return { chart, host, series, markers, scaffold, scaffoldDate:null, daily, falling:false, hasData:false, lastTime:0, dispose:() => { observer.disconnect(); chart.remove(); } };
  }
  function pinDay(chart) {
    const apply = () => chart.timeScale().setVisibleLogicalRange({ from:-0.5, to:DAY_MINUTES + 0.5 });
    apply();
    requestAnimationFrame(() => requestAnimationFrame(apply));
  }
  function ensureDay(instance, date) {
    if (!instance?.scaffold || !/^\d{4}-\d{2}-\d{2}$/.test(date) || instance.scaffoldDate === date) return;
    instance.scaffold.setData(dayScaffold(date));
    instance.scaffoldDate = date;
    instance.chart.applyOptions({ timeScale:{ tickMarkFormatter:(time) => dayTick(time, date) }, localization:{ timeFormatter:(time) => marketClock(time, date) } });
    pinDay(instance.chart);
    window.DashboardUI?.attachDayAxis(instance.host, instance.chart, dayStart(date));
  }
  function intradayPoints(data) {
    const unique = new Map();
    (data.intraday || []).forEach((item) => {
      const rawTime = item.time ?? item.at ?? item.timestamp;
      const parsed = typeof rawTime === "number" ? rawTime : Date.parse(rawTime) / 1000;
      const value = Number(item.value ?? item.price ?? item.close);
      if (Number.isFinite(parsed) && parsed > 0 && Number.isFinite(value)) unique.set(minuteTime(parsed), value);
    });
    const result = [];
    [...unique].sort((a, b) => a[0] - b[0]).forEach(([time, value]) => {
      const previous = result.at(-1);
      // A whitespace sample keeps the lunch break and other data gaps visible.
      if (previous && time - previous.time > 90) result.push({ time:previous.time + 60 });
      result.push({ time, value });
    });
    return result;
  }
  function setLine(instance, data) {
    if (!instance) return;
    ensureDay(instance, marketDay(data));
    const colors = indexColors();
    instance.falling = data.change < 0;
    instance.series.applyOptions({ color:instance.falling ? colors.fall : colors.rise });
    const samples = intradayPoints(data);
    instance.series.setData(samples);
    instance.markers?.setMarkers((data.intraday || []).filter((item) => item.changed || item.event || item.floor_reset).map((item) => {
      const raw = item.time ?? item.at ?? item.timestamp;
      const parsed = typeof raw === "number" ? raw : Date.parse(raw) / 1000;
      return { time:minuteTime(parsed), position:item.floor_reset ? "belowBar" : "aboveBar", shape:item.floor_reset ? "arrowUp" : "circle", color:item.floor_reset ? "#8067b3" : "#b47a59", text:item.floor_reset ? "复位" : "" };
    }).filter((item) => Number.isFinite(item.time) && item.time > 0).sort((a, b) => a.time - b.time));
    instance.lastTime = samples.at(-1)?.time || 0;
    pinDay(instance.chart);
    instance.hasData = samples.length > 0;
  }
  function render(data) {
    $("[data-index-points]").textContent = points(data.current);
    const change = $("[data-index-change]");
    change.textContent = `${signed(data.change)} (${signed(data.pct, 2)}%)`;
    $(".home-index-quote").classList.toggle("index-rise", data.change >= 0);
    $(".home-index-quote").classList.toggle("index-fall", data.change < 0);
    $("[data-index-focus]").textContent = duration(data.today_focus_seconds);
    $("[data-index-status]").textContent = data.is_paused ? "已暂停" : data.is_focusing ? "专注中" : "休息中";
    const timestamp = new Date(data.updated_at);
    const date = data.intraday_date;
    $("[data-index-updated]").textContent = `${date && date !== todayDate() ? `回看 ${date} · ` : ""}更新 ${Number.isNaN(timestamp.getTime()) ? new Date(fetchedAt).toLocaleTimeString("zh-CN", { hour12:false }) : timestamp.toLocaleTimeString("zh-CN", { hour12:false })}`;
    $("[data-index-retry]").hidden = true;
    if (!homeChart && visible()) homeChart = createChart($("[data-index-chart]"));
    if (homeChart) setLine(homeChart, data);
    const empty = $("[data-index-empty]");
    empty.hidden = Boolean(homeChart && intradayPoints(data).length);
    empty.textContent = !window.LightweightCharts ? "图表组件未加载，可打开详情查看数值" : data.intraday?.length ? "" : "暂无分时记录 · 开始专注后生成";
  }
  function paintNow(instance, timestamp) {
    if (!instance?.scaffoldDate || !Number.isFinite(timestamp)) return;
    if (!instance.nowMarker) {
      const marker = document.createElement("div");
      marker.className = "index-now-marker";
      marker.innerHTML = "<span>现在</span>";
      marker.title = "当前市场时间；横轴固定展示 00:00–24:00";
      instance.host.append(marker);
      instance.nowMarker = marker;
    }
    const minute = minuteTime(Math.floor(timestamp / 1000));
    const left = instance.chart.timeScale().timeToCoordinate(minute);
    const right = instance.chart.timeScale().timeToCoordinate(minute + 60);
    instance.nowMarker.hidden = instance.scaffoldDate !== todayDate() || left === null || right === null || minute < dayStart(instance.scaffoldDate) || minute >= dayStart(instance.scaffoldDate) + DAY_MINUTES * 60;
    if (!instance.nowMarker.hidden) instance.nowMarker.style.left = `${left + (right - left) * ((timestamp / 1000 - minute) / 60)}px`;
  }
  function projectLive(snapshot) {
    const tick = snapshot?.live_tick || {};
    const base = number(tick.value_at, number(snapshot?.index?.current, latest?.current ?? 100));
    const anchor = Date.parse(tick.timestamp || snapshot?.generated_at || "");
    const clock = Date.parse(snapshot?.generated_at || "") + Math.max(0, Date.now() - snapshot.receivedAt);
    const elapsed = Number.isFinite(anchor) && Number.isFinite(clock) ? Math.max(0, Math.min(60, (clock - anchor) / 1000)) : 0;
    const raw = snapshot.market_active ? base + number(tick.per_second) * elapsed : number(snapshot?.index?.current, base);
    return Math.max(number(snapshot.limit_down, -Infinity), Math.min(number(snapshot.limit_up, Infinity), raw));
  }
  function liveSecond() {
    if (!visible() || !latest) return;
    const snapshot = live;
    if (snapshot && marketDay(snapshot) === marketDay(latest)) {
      const value = projectLive(snapshot);
      const previous = number(snapshot.previous_close, number(latest.previous_close, 100));
      latest.current = value;
      latest.change = value - previous;
      latest.pct = previous ? latest.change / previous * 100 : 0;
      $("[data-index-points]").textContent = points(value);
      $("[data-index-change]").textContent = `${signed(latest.change)} (${signed(latest.pct, 2)}%)`;
      $(".home-index-quote").classList.toggle("index-rise", latest.change >= 0);
      $(".home-index-quote").classList.toggle("index-fall", latest.change < 0);
      if (snapshot.market_active && homeChart?.hasData) {
        const tickTime = minuteTime(Math.floor((Date.parse(snapshot.generated_at) + Date.now() - snapshot.receivedAt) / 1000));
        if (tickTime >= homeChart.lastTime && tickTime < dayStart(homeChart.scaffoldDate) + DAY_MINUTES * 60) {
          homeChart.series.update({ time:tickTime, value });
          homeChart.lastTime = tickTime;
        }
      }
      if (Number.isFinite(Number(snapshot.today_focus_seconds))) $("[data-index-focus]").textContent = duration(snapshot.today_focus_seconds);
      $("[data-index-status]").textContent = snapshot.is_paused ? "已暂停" : snapshot.is_focusing ? "专注中" : "休息中";
      paintNow(homeChart, Date.parse(snapshot.generated_at) + Date.now() - snapshot.receivedAt);
    } else paintNow(homeChart, Date.now());
  }
  async function refreshFull(force = false) {
    if (!visible()) { refreshDue = true; return; }
    if (pending) return pending;
    if (!force && !refreshDue && Date.now() - attemptedAt < 15000) return;
    refreshDue = false;
    attemptedAt = Date.now();
    pending = request().then((data) => { latest = data; fetchedAt = Date.now(); render(data); refreshLive(true); }).catch(() => {
      // Retain the last successful quote, but label it as stale.
      $("[data-index-updated]").textContent = latest ? "行情暂时无法更新 · 显示上次数据" : "指数读取失败";
      $("[data-index-retry]").hidden = false;
    }).finally(() => { pending = null; });
    return pending;
  }
  async function refreshLive(force = false) {
    if (!visible() || !latest || livePending) return livePending;
    if (!force && live && Date.now() - live.receivedAt < 12000) return;
    livePending = requestLive().then((snapshot) => {
      snapshot.receivedAt = Date.now();
      live = snapshot;
      if (Array.isArray(snapshot.intraday)) {
        latest.intraday = snapshot.intraday;
        latest.intraday_date = snapshot.intraday_date;
        setLine(homeChart, latest);
      }
      latest.updated_at = snapshot.generated_at || snapshot.updated_at || latest.updated_at;
      $("[data-index-updated]").textContent = `更新 ${new Date(latest.updated_at).toLocaleTimeString("zh-CN", { hour12:false })}`;
      liveSecond();
    }).catch(() => { if (latest) $("[data-index-updated]").textContent = "实时更新暂不可用 · 显示最近数据"; }).finally(() => { livePending = null; });
    return livePending;
  }

  function detailHtml(data) {
    const day = data.day;
    const metrics = [["开盘", points(day.open ?? 100)], ["最高", points(day.high ?? data.current)], ["最低", points(day.low ?? data.current)], ["收盘 / 当前", points(data.current)], ["振幅", `${(number(day.open) ? (number(day.high) - number(day.low)) / number(day.open) * 100 : 0).toFixed(2)}%`], ["今日专注", duration(data.today_focus_seconds)], ["跌停", points(data.limit_down)], ["涨停", points(data.limit_up)], ["状态", data.is_paused ? "已暂停" : data.is_focusing ? "专注中" : "休息中"]];
    const params = data.parameters || {};
    const parameters = [["低位锚点 A_low", params.a_low_hours, "小时", "对应低位收益区间的专注时长。"], ["目标锚点 A_mid", params.a_mid_hours, "小时", "对应中位收益的目标时长。"], ["高位锚点 A_high", params.a_high_hours, "小时", "对应高位收益区间的专注时长。"], ["低区倍率 K_low", params.k_low_percent_per_hour, "% / 小时", "控制目标时长以下的线性收益变化。"], ["高区倍率 K_high", params.k_high_percent_per_hour, "% / 小时", "控制目标时长以上的线性收益变化。"]];
    const dates = data.candles.map((row) => row.date).filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date));
    const quoteMeta = `相对前一日收盘 · ${day.date || "暂无交易记录"} · 数据时间 ${data.updated_at || "未知"} · 分时为分钟正式采样`;
    return `<div class="index-detail"><div class="index-detail-quote ${data.change < 0 ? "index-fall" : "index-rise"}" data-tooltip="${escape(quoteMeta)}" tabindex="0"><strong>${points(data.current)}</strong><span>${signed(data.change)} (${signed(data.pct, 2)}%)</span></div><dl class="index-detail-grid">${metrics.map(([key, value]) => `<div><dt>${escape(key)}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl><section><h3 data-tooltip="红涨绿跌；点击日 K 查看当天分时" tabindex="0">历史日线</h3><div class="index-detail-chart" data-index-daily role="img" aria-label="专注指数日线 K 线"></div><p data-index-daily-note class="sr-only">${dates.length ? "红涨绿跌 · 点击日线查看当天分时" : "暂无历史数据"}</p></section><section><div class="index-detail-select"><h3 data-tooltip="横轴固定展示所选日期 00:00–24:00；圆点标记专注切换，箭头标记收盘重置" tabindex="0">分时走势</h3><select data-index-day aria-label="选择分时日期" ${dates.length ? "" : "disabled"}>${dates.map((date) => `<option value="${escape(date)}" ${date === data.intraday_date ? "selected" : ""}>${escape(date)}</option>`).join("")}</select></div><div class="index-detail-chart" data-index-intraday role="img" aria-label="所选日期全天分时图"></div><p data-index-path-note class="sr-only">${data.intraday?.length ? `${escape(data.intraday_date)} · 1 分钟正式采样` : "暂无分时记录"}</p></section><section><h3 data-tooltip="每日涨跌限制 ±10%；若计算收盘低于 10 点，当日收盘时重置至 10 点" tabindex="0">指数参数</h3><dl class="index-params">${parameters.map(([label, value, unit, explanation]) => `<div><dt data-tooltip="${escape(explanation)}" tabindex="0">${escape(label)} · ${value === undefined ? "—" : escape(value)} ${escape(unit)}</dt></div>`).join("")}</dl></section><a href="/focus-kline" class="index-detail-link">打开完整行情与参数设置 ↗</a></div>`;
  }
  function readyDetail(host, data, signal) {
    drawerDispose?.();
    const detail = host.querySelector(".index-detail");
    if (signal?.aborted || !host.isConnected || !detail) return;
    const daily = createChart(host.querySelector("[data-index-daily]"), true);
    const path = createChart(host.querySelector("[data-index-intraday]"));
    let disposed = false, sequence = 0, dateController = null;
    const select = host.querySelector("[data-index-day]");
    const note = host.querySelector("[data-index-path-note]");
    if (daily) {
      daily.series.setData(data.candles.filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date)).map((row) => ({ time:row.date, open:number(row.open), high:number(row.high), low:number(row.low), close:number(row.close) })));
      daily.chart.timeScale().fitContent();
    } else host.querySelector("[data-index-daily-note]").textContent = "图表组件未加载";
    setLine(path, data, false);
    async function choose(date) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
      dateController?.abort();
      dateController = new AbortController();
      const requestSequence = ++sequence;
      note.textContent = `${date} · 正在读取`;
      try {
        const next = await request(date, dateController.signal);
        if (disposed || sequence !== requestSequence) return;
        setLine(path, next, false);
        note.textContent = next.intraday_date === date && next.intraday?.length ? `${date} · 1 分钟正式采样` : `${date} 暂无分时记录`;
        // The API may fall back to a previous trading day for an empty date.
        if (next.intraday_date !== date && path) { path.series.setData([]); path.hasData = false; }
      } catch (error) { if (error.name !== "AbortError" && !disposed && sequence === requestSequence) note.textContent = `${date} · 读取失败，请重新选择日期重试`; }
    }
    select.addEventListener("change", () => choose(select.value));
    daily?.chart.subscribeClick((event) => {
      if (window.ChartGestures?.shouldIgnoreClick(host.querySelector("[data-index-daily]"))) return;
      const date = typeof event.time === "string" ? event.time : event.time?.year ? `${event.time.year}-${String(event.time.month).padStart(2, "0")}-${String(event.time.day).padStart(2, "0")}` : null;
      if (!date || ![...select.options].some((option) => option.value === date)) return;
      select.value = date;
      choose(date);
    });
    const appearance = () => { applyChartTheme(daily, host.querySelector("[data-index-daily]")); applyChartTheme(path, host.querySelector("[data-index-intraday]")); };
    document.addEventListener("dashboard:appearance", appearance);
    const observer = new MutationObserver(() => { if (!detail.isConnected || !host.contains(detail)) dispose(); });
    observer.observe(host, { childList:true });
    const dispose = () => {
      if (disposed) return;
      disposed = true; sequence += 1;
      dateController?.abort();
      daily?.dispose(); path?.dispose(); observer.disconnect();
      document.removeEventListener("dashboard:appearance", appearance);
      signal?.removeEventListener("abort", dispose);
      if (drawerDispose === dispose) drawerDispose = null;
    };
    drawerDispose = dispose;
    signal?.addEventListener("abort", dispose, { once:true });
  }
  window.DashboardDetails?.register("index", async (descriptor) => {
    const data = await request(todayDate(), descriptor.signal);
    return { title:"专注指数", kicker:"FOCUS INDEX · 行情详情", html:detailHtml(data), onReady:(host) => readyDetail(host, data, descriptor.signal) };
  });
  document.addEventListener("dashboard:detail-closed", () => drawerDispose?.());
  document.addEventListener("dashboard:updated", (event) => {
    const data = event.detail || {}, active = data.focus?.active;
    const priorDay = todayDate();
    if (typeof data.now === "string") dashboardNow = data.now;
    const signature = JSON.stringify([todayDate(), active?.id || null, active?.paused_at || null, data.today_focus?.count, data.daily_settlement?.id]);
    if (priorDay && todayDate() !== priorDay) { live = null; refreshDue = true; refreshFull(true); }
    else if (context !== null && context !== signature) refreshLive(true);
    context = signature;
    if (!latest) refreshFull();
    else refreshLive();
  });
  document.addEventListener("dashboard:appearance", () => {
    applyChartTheme(homeChart, $("[data-index-chart]"));
  });
  $("[data-index-retry]").addEventListener("click", () => refreshFull(true));
  new MutationObserver(() => { if (visible()) { if (latest) { render(latest); liveSecond(); refreshLive(); } else refreshFull(); } }).observe(view, { attributes:true, attributeFilter:["hidden", "class", "style"] });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { if (latest) refreshLive(true); else refreshFull(); } });
  setInterval(liveSecond, 1000);
  setInterval(() => { if (visible()) refreshLive(); }, 15000);
  window.DashboardIndex = { refresh:() => latest ? refreshLive(true) : refreshFull(true), resize:() => { if (homeChart && visible()) { homeChart.chart.applyOptions({ width:$("[data-index-chart]").clientWidth, height:Math.max(70, $("[data-index-chart]").clientHeight) }); pinDay(homeChart.chart); liveSecond(); } else if (latest && visible()) render(latest); } };
  refreshFull();
})();
