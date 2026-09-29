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
  let latest = null, dashboardNow = "", fetchedAt = 0, attemptedAt = 0, pending = null, context = null, homeChart = null, drawerDispose = null, refreshDue = false;

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
  function chartOptions(host) {
    const style = getComputedStyle(document.documentElement);
    return { width:Math.max(1, host.clientWidth), height:Math.max(140, host.clientHeight), layout:{ background:{ type:"solid", color:"transparent" }, textColor:style.getPropertyValue("--muted").trim() || "#738078", fontFamily:getComputedStyle(host).fontFamily, fontSize:11 }, grid:{ vertLines:{ visible:false }, horzLines:{ color:style.getPropertyValue("--line").trim() || "#d9e1db" } }, rightPriceScale:{ borderVisible:false }, timeScale:{ borderVisible:false, timeVisible:true, secondsVisible:false, lockVisibleTimeRangeOnResize:true, tickMarkFormatter:(time) => typeof time === "number" ? marketClock(time) : null }, localization:{ locale:"zh-CN", timeFormatter:marketClock }, handleScroll:{ mouseWheel:false, pressedMouseMove:false, horzTouchDrag:false, vertTouchDrag:false }, handleScale:{ axisPressedMouseMove:false, mouseWheel:false, pinch:false } };
  }
  function marketClock(time) {
    if (time && typeof time === "object" && time.year) return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}`;
    if (typeof time !== "number") return String(time);
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
    instance.chart.applyOptions(chartOptions(host));
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
    if (daily) chart.applyOptions({ timeScale:{ timeVisible:false } });
    const observer = new ResizeObserver(() => {
      if (!host.isConnected || !host.clientWidth) return;
      chart.applyOptions({ width:host.clientWidth, height:Math.max(140, host.clientHeight) });
    });
    observer.observe(host);
    return { chart, series, daily, falling:false, hasData:false, dispose:() => { observer.disconnect(); chart.remove(); } };
  }
  function intradayPoints(data) {
    const unique = new Map();
    (data.intraday || []).forEach((item) => {
      const rawTime = item.time ?? item.at ?? item.timestamp;
      const parsed = typeof rawTime === "number" ? rawTime : Date.parse(rawTime) / 1000;
      const value = Number(item.value ?? item.price ?? item.close);
      if (Number.isFinite(parsed) && parsed > 0 && Number.isFinite(value)) unique.set(Math.floor(parsed), value);
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
  function setLine(instance, data, preserve = true) {
    if (!instance) return;
    const range = preserve && instance.hasData ? instance.chart.timeScale().getVisibleLogicalRange() : null;
    const colors = indexColors();
    instance.falling = data.change < 0;
    instance.series.applyOptions({ color:instance.falling ? colors.fall : colors.rise });
    const samples = intradayPoints(data);
    instance.series.setData(samples);
    if (range) instance.chart.timeScale().setVisibleLogicalRange(range);
    else instance.chart.timeScale().fitContent();
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
    $("[data-index-updated]").textContent = `${date && date !== todayDate() ? `回看 ${date} · ` : ""}读取于 ${new Date(fetchedAt).toLocaleTimeString("zh-CN", { hour12:false })}${Number.isNaN(timestamp.getTime()) ? "" : ` · 数据 ${timestamp.toLocaleTimeString("zh-CN", { hour12:false })}`}`;
    $("[data-index-retry]").hidden = true;
    if (!homeChart && visible()) homeChart = createChart($("[data-index-chart]"));
    if (homeChart) setLine(homeChart, data);
    const empty = $("[data-index-empty]");
    empty.hidden = Boolean(homeChart && intradayPoints(data).length);
    empty.textContent = !window.LightweightCharts ? "图表组件未加载，可打开详情查看数值" : data.intraday?.length ? "" : "暂无分时记录 · 开始专注后生成";
  }
  async function refresh(force = false) {
    if (!visible()) { refreshDue = true; return; }
    if (pending) return pending;
    if (!force && !refreshDue && Date.now() - attemptedAt < 15000) return;
    refreshDue = false;
    attemptedAt = Date.now();
    pending = request().then((data) => { latest = data; fetchedAt = Date.now(); render(data); }).catch(() => {
      // Retain the last successful quote, but label it as stale.
      $("[data-index-updated]").textContent = latest ? "行情暂时无法更新 · 显示上次数据" : "指数读取失败";
      $("[data-index-retry]").hidden = false;
    }).finally(() => { pending = null; });
    return pending;
  }

  function detailHtml(data) {
    const day = data.day;
    const metrics = [["开盘", points(day.open ?? 100)], ["最高", points(day.high ?? data.current)], ["最低", points(day.low ?? data.current)], ["收盘 / 当前", points(data.current)], ["振幅", `${(number(day.open) ? (number(day.high) - number(day.low)) / number(day.open) * 100 : 0).toFixed(2)}%`], ["今日专注", duration(data.today_focus_seconds)], ["跌停", points(data.limit_down)], ["涨停", points(data.limit_up)], ["状态", data.is_paused ? "已暂停" : data.is_focusing ? "专注中" : "休息中"]];
    const params = data.parameters || {};
    const parameters = [["低位锚点 A_low", params.a_low_hours, "小时", "对应低位收益区间的专注时长。"], ["目标锚点 A_mid", params.a_mid_hours, "小时", "对应中位收益的目标时长。"], ["高位锚点 A_high", params.a_high_hours, "小时", "对应高位收益区间的专注时长。"], ["低区倍率 K_low", params.k_low_percent_per_hour, "% / 小时", "控制目标时长以下的线性收益变化。"], ["高区倍率 K_high", params.k_high_percent_per_hour, "% / 小时", "控制目标时长以上的线性收益变化。"]];
    const dates = data.candles.map((row) => row.date).filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date));
    return `<div class="index-detail"><div class="index-detail-quote ${data.change < 0 ? "index-fall" : "index-rise"}"><strong>${points(data.current)}</strong><span>${signed(data.change)} (${signed(data.pct, 2)}%)</span></div><p>相对前一日收盘 · ${escape(data.day.date || "暂无交易记录")}<br>读取于 ${escape(new Date().toLocaleTimeString("zh-CN", { hour12:false }))} · 分钟采样来自专注记录</p><dl class="index-detail-grid">${metrics.map(([key, value]) => `<div><dt>${escape(key)}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl><section><h3>历史日线</h3><div class="index-detail-chart" data-index-daily role="img" aria-label="专注指数日线 K 线"></div><p data-index-daily-note>${dates.length ? "红涨绿跌 · 点击日线查看当天分时" : "暂无历史数据"}</p></section><section><div class="index-detail-select"><h3>分时走势</h3><select data-index-day aria-label="选择分时日期" ${dates.length ? "" : "disabled"}>${dates.map((date) => `<option value="${escape(date)}" ${date === data.intraday_date ? "selected" : ""}>${escape(date)}</option>`).join("")}</select></div><div class="index-detail-chart" data-index-intraday role="img" aria-label="所选日期的分钟分时图"></div><p data-index-path-note>${data.intraday?.length ? `${escape(data.intraday_date)} · 1 分钟正式采样` : "暂无分时记录"}</p></section><section><h3>指数参数</h3><dl class="index-params">${parameters.map(([label, value, unit, explanation]) => `<div><dt>${escape(label)} · ${value === undefined ? "—" : escape(value)} ${escape(unit)}</dt><dd>${escape(explanation)}</dd></div>`).join("")}</dl><p>指数是专注行为的量化展示。每日涨跌限制为 ±10%；收盘低于 10 点时，次日从 10 点重新开盘。</p></section><a href="/focus-kline" class="index-detail-link">打开完整行情与参数设置 ↗</a></div>`;
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
      if (window.ChartGestures?.shouldIgnoreClick($("[data-index-daily]"))) return;
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
    if (typeof data.now === "string") dashboardNow = data.now;
    const signature = JSON.stringify([todayDate(), active?.id || null, active?.paused_at || null, data.today_focus?.count, data.daily_settlement?.id]);
    if (context !== null && context !== signature) refreshDue = true;
    context = signature;
    refresh();
  });
  document.addEventListener("dashboard:appearance", () => {
    applyChartTheme(homeChart, $("[data-index-chart]"));
  });
  $("[data-index-retry]").addEventListener("click", () => refresh(true));
  new MutationObserver(() => { if (visible()) { if (latest) render(latest); refresh(); } }).observe(view, { attributes:true, attributeFilter:["hidden", "class", "style"] });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  setInterval(() => { if (visible()) refresh(); }, 15000);
  window.DashboardIndex = { refresh:() => refresh(), resize:() => { if (homeChart && visible()) homeChart.chart.applyOptions({ width:$("[data-index-chart]").clientWidth, height:Math.max(140, $("[data-index-chart]").clientHeight) }); else if (latest && visible()) render(latest); } };
  refresh();
})();
