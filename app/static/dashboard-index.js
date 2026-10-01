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
  let dashboardClock = null, liveRefreshDue = false, liveRequestVersion = 0, fullRequestVersion = 0;
  const Market = window.IndexMarket;
  const acceptPolicy = (data) => !data.challenge || !window.IndexChallenge || window.IndexChallenge.accept(data.challenge);
  const marketDay = (data) => String(data?.intraday_date || data?.day?.date || data?.today?.date || todayDate() || "").slice(0, 10);
  const marketFor = (data) => {
    const date = marketDay(data);
    const candle = data.candles?.find((item) => item.date === date);
    return Market?.market(date, candle?.trading_sessions || data.day?.trading_sessions || data.today?.trading_sessions || data.trading_sessions, data.updated_at);
  };
  const serverNow = () => dashboardClock ? dashboardClock.epoch + Math.max(0, Date.now() - dashboardClock.receivedAt) : Date.now();
  const updateClock = (value, data = latest) => {
    const timestamp = Market.parse(value);
    return Number.isFinite(timestamp) ? Market.clockSeconds(timestamp, marketFor(data)?.offset || Market.offsetOf(dashboardNow || value)) : "—";
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
  function chartOptions(host, market = null) {
    const style = getComputedStyle(document.documentElement);
    return { width:Math.max(1, host.clientWidth), height:Math.max(70, host.clientHeight), layout:{ background:{ type:"solid", color:"transparent" }, textColor:style.getPropertyValue("--muted").trim() || "#738078", fontFamily:getComputedStyle(host).fontFamily, fontSize:11 }, grid:{ vertLines:{ visible:false }, horzLines:{ color:style.getPropertyValue("--line").trim() || "#d9e1db" } }, rightPriceScale:{ borderVisible:false }, timeScale:{ borderVisible:false, minBarSpacing:0.01, timeVisible:true, secondsVisible:false, lockVisibleTimeRangeOnResize:true, ...(market ? { tickMarkFormatter:(time) => typeof time === "number" ? Market.clock(time, market.offset) : null } : {}) }, localization:{ locale:"zh-CN", ...(market ? { timeFormatter:(time) => typeof time === "number" ? Market.clock(time, market.offset) : "" } : {}) }, handleScroll:{ mouseWheel:false, pressedMouseMove:false, horzTouchDrag:false, vertTouchDrag:false }, handleScale:{ axisPressedMouseMove:false, mouseWheel:false, pinch:false } };
  }
  function indexColors() {
    const style = getComputedStyle(document.documentElement);
    return { rise:style.getPropertyValue("--index-rise").trim() || "#d66c58", fall:style.getPropertyValue("--index-fall").trim() || "#4d8a73" };
  }
  function applyChartTheme(instance, host) {
    if (!instance) return;
    const colors = indexColors();
    instance.chart.applyOptions(chartOptions(host, instance.market));
    (instance.lines || [instance.series]).forEach((line) => line.applyOptions(instance.daily ? { upColor:colors.rise, downColor:colors.fall, wickUpColor:colors.rise, wickDownColor:colors.fall } : { color:instance.falling ? colors.fall : colors.rise }));
    if (instance.daily) instance.chart.applyOptions({ timeScale:{ timeVisible:false } });
  }
  function createChart(host, daily = false) {
    const library = window.LightweightCharts;
    if (!library?.createChart || !library.LineSeries || !library.CandlestickSeries) return null;
    const chart = daily ? library.createChart(host, chartOptions(host)) : Market.createChart(host, chartOptions(host));
    const colors = indexColors();
    const options = daily ? { upColor:colors.rise, downColor:colors.fall, borderVisible:false, wickUpColor:colors.rise, wickDownColor:colors.fall, priceFormat:{ type:"price", precision:3, minMove:.001 } } : { color:colors.rise, lineWidth:2, crosshairMarkerVisible:true, priceFormat:{ type:"price", precision:3, minMove:.001 } };
    const series = chart.addSeries(daily ? library.CandlestickSeries : library.LineSeries, options);
    const markers = daily ? null : Market.createSeriesMarkers(series, []);
    if (daily) chart.applyOptions({ timeScale:{ timeVisible:false } });
    const observer = new ResizeObserver(() => {
      if (!host.isConnected || !host.clientWidth) return;
      chart.applyOptions({ width:host.clientWidth, height:Math.max(70, host.clientHeight) });
      if (!daily) Market.pin(chart, result.market);
    });
    observer.observe(host);
    const result = { chart, host, series, lines:[series], markerGroups:[markers], markers, market:null, daily, showEvents:host !== $("[data-index-chart]"), falling:false, hasData:false, dispose:() => { observer.disconnect(); chart.remove(); } };
    return result;
  }
  function ensureMarket(instance, market) {
    if (!instance || instance.daily || !market) return;
    const key = JSON.stringify([market.date, market.windows]);
    if (instance.marketKey === key) return;
    instance.marketKey = key;
    instance.market = market;
    instance.timeline = Market.timeline(market);
    instance.chart.setMarket(market);
    instance.chart.applyOptions(chartOptions(instance.host, market));
    Market.pin(instance.chart, market);
  }
  function setLine(instance, data) {
    if (!instance) return;
    const market = marketFor(data);
    ensureMarket(instance, market);
    const colors = indexColors();
    instance.falling = data.change < 0;
    if (!market) return;
    instance.timeline.reconcile(data.intraday, (item) => item.time ?? item.at ?? item.timestamp, (item) => item.value ?? item.price ?? item.close);
    const samples = instance.timeline;
    const activeIndex = samples.groups.findLastIndex((group) => group.length);
    while (instance.lines.length < samples.groups.length) {
      const line = instance.chart.addSeries(window.LightweightCharts.LineSeries, { color:instance.falling ? colors.fall : colors.rise, lineWidth:2, priceFormat:{ type:"price", precision:3, minMove:.001 }, lastValueVisible:true });
      instance.lines.push(line);
      instance.markerGroups.push(Market.createSeriesMarkers(line, []));
    }
    instance.lines.forEach((line, index) => {
      const group = samples.groups[index] || [];
      line.applyOptions({ color:instance.falling ? colors.fall : colors.rise, lastValueVisible:index === activeIndex });
      line.setData(group);
      instance.markerGroups[index]?.setMarkers(instance.showEvents ? (samples.events[index] || []).map((event) => ({ time:event.time, value:event.value, position:event.floorReset ? "belowBar" : "aboveBar", shape:event.floorReset ? "arrowUp" : "circle", color:event.floorReset ? "#8067b3" : "#b47a59", text:event.floorReset ? "复位" : "" })) : []);
    });
    instance.series = instance.lines[Math.max(0, activeIndex)];
    Market.pin(instance.chart, market);
    instance.hasData = samples.groups.some((group) => group.length);
  }
  function render(data) {
    updateQuote(data.current, data.previous_close);
    $("[data-index-focus]").textContent = duration(data.today_focus_seconds);
    $("[data-index-status]").textContent = data.is_paused ? "已暂停" : data.is_focusing ? "专注中" : "休息中";
    const date = data.intraday_date;
    $("[data-index-updated]").textContent = `${date && date !== todayDate() ? `回看 ${date} · ` : ""}更新 ${updateClock(data.updated_at, data)}`;
    $("[data-index-retry]").hidden = true;
    if (!homeChart && visible()) homeChart = createChart($("[data-index-chart]"));
    if (homeChart) setLine(homeChart, data);
    const empty = $("[data-index-empty]");
    empty.hidden = Boolean(homeChart?.hasData);
    empty.textContent = !window.LightweightCharts ? "图表组件未加载，可打开详情查看数值" : data.intraday?.length ? "" : "暂无分时记录 · 开始专注后生成";
  }
  function updateQuote(value, previous) {
    const target = $("[data-index-points]");
    const next = points(value);
    const before = Number(target.textContent);
    if (target.textContent.trim() && Number.isFinite(before) && target.textContent !== next) {
      target.classList.remove("is-tick-up", "is-tick-down");
      void target.offsetWidth;
      target.classList.add(value > before ? "is-tick-up" : "is-tick-down");
    }
    target.textContent = next;
    const change = value - number(previous, 100);
    const pct = previous ? change / previous * 100 : 0;
    $("[data-index-change]").textContent = `${signed(change)} (${signed(pct, 2)}%)`;
    $(".home-index-quote").classList.toggle("index-rise", change >= 0);
    $(".home-index-quote").classList.toggle("index-fall", change < 0);
  }
  function paintNow(instance, timestamp) {
    if (!instance?.market || !Number.isFinite(timestamp)) return;
    if (!instance.nowMarker) {
      const marker = document.createElement("div");
      marker.className = "index-now-marker";
      marker.innerHTML = "<span>现在</span>";
      marker.title = `当前市场时间；横轴 ${Market.clock(instance.market.open, instance.market.offset)}–${Market.clock(instance.market.close, instance.market.offset)}`;
      instance.host.append(marker);
      instance.nowMarker = marker;
    }
    const now = timestamp / 1000;
    const x = Market.coordinate(instance.chart, now);
    instance.nowMarker.hidden = instance.market.date !== todayDate() || x === null || now < instance.market.open || now > instance.market.close;
    if (!instance.nowMarker.hidden) instance.nowMarker.style.left = `${x}px`;
  }
  function appendLive(instance, projection) {
    if (!instance?.timeline || !projection?.active) return;
    const group = instance.timeline.append(projection.time, projection.value);
    if (group < 0) return;
    instance.hasData = true;
    if (instance === homeChart) $("[data-index-empty]").hidden = true;
    instance.lines.forEach((line, index) => line.applyOptions({ lastValueVisible:index === group }));
    instance.lines[group].setData(instance.timeline.groups[group]);
  }
  function liveSecond() {
    if (!visible() || !latest) return;
    const snapshot = live;
    if (snapshot && snapshot.requestVersion === liveRequestVersion && marketDay(snapshot) === marketDay(latest)) {
      const projection = Market.project(snapshot, homeChart?.market || marketFor(latest));
      if (!projection) return;
      const value = projection.value;
      const previous = number(snapshot.previous_close, number(latest.previous_close, 100));
      latest.current = value;
      latest.change = value - previous;
      latest.pct = previous ? latest.change / previous * 100 : 0;
      updateQuote(value, previous);
      appendLive(homeChart, projection);
      if (Number.isFinite(Number(snapshot.today_focus_seconds))) $("[data-index-focus]").textContent = duration(snapshot.today_focus_seconds);
      $("[data-index-status]").textContent = snapshot.is_paused ? "已暂停" : snapshot.is_focusing ? "专注中" : "休息中";
      paintNow(homeChart, projection.now * 1000);
      if (projection.stale) $("[data-index-updated]").textContent = "实时更新暂不可用 · 显示最近数据";
    } else paintNow(homeChart, snapshot ? (Market.project(snapshot, homeChart?.market)?.now ?? serverNow() / 1000) * 1000 : serverNow());
  }
  async function refreshFull(force = false) {
    if (force) { refreshDue = true; fullRequestVersion += 1; }
    if (!visible()) { refreshDue = true; return; }
    if (pending) return pending;
    if (!force && !refreshDue && Date.now() - attemptedAt < 15000) return;
    const requestedDate = todayDate(), requestVersion = fullRequestVersion;
    refreshDue = false;
    attemptedAt = Date.now();
    pending = request(requestedDate).then((data) => {
      const responseDay = data.today?.date || data.day?.date;
      if (requestVersion !== fullRequestVersion || (requestedDate && requestedDate !== todayDate()) || (!requestedDate && todayDate() && responseDay && responseDay !== todayDate())) {
        refreshDue = true;
        return;
      }
      if (!acceptPolicy(data) || requestVersion !== fullRequestVersion) return;
      latest = data; fetchedAt = Date.now(); render(data); refreshLive(true);
    }).catch(() => {
      // Retain the last successful quote, but label it as stale.
      $("[data-index-updated]").textContent = latest ? "行情暂时无法更新 · 显示上次数据" : "指数读取失败";
      $("[data-index-retry]").hidden = false;
    }).finally(() => {
      pending = null;
      if (refreshDue && visible()) return refreshFull();
    });
    return pending;
  }
  async function refreshLive(force = false) {
    if (force) {
      liveRefreshDue = true;
      liveRequestVersion += 1;
      document.dispatchEvent(new CustomEvent("dashboard:index-invalidated"));
    }
    // Keep a forced state refresh queued while hidden or while an older
    // response is in flight. Its response must not restart the old direction.
    if (!visible() || !latest || livePending) return livePending;
    if (!liveRefreshDue && live && Date.now() - live.receivedAt < 15000) return;
    const requestVersion = liveRequestVersion;
    liveRefreshDue = false;
    livePending = requestLive().then((snapshot) => {
      if (requestVersion !== liveRequestVersion) return;
      if (!acceptPolicy(snapshot) || requestVersion !== liveRequestVersion) return;
      if (latest.day?.date && snapshot.intraday_date !== latest.day.date) {
        refreshDue = true;
        refreshFull();
        return;
      }
      snapshot.receivedAt = Date.now();
      snapshot.requestVersion = requestVersion;
      live = snapshot;
      latest.challenge = snapshot.challenge || latest.challenge;
      latest.limit_down = snapshot.limit_down ?? latest.limit_down;
      latest.limit_up = snapshot.limit_up ?? latest.limit_up;
      latest.today_focus_seconds = snapshot.today_focus_seconds ?? latest.today_focus_seconds;
      latest.is_focusing = snapshot.is_focusing; latest.is_paused = snapshot.is_paused;
      if (Array.isArray(snapshot.intraday)) {
        latest.intraday = snapshot.intraday;
        latest.intraday_date = snapshot.intraday_date;
        const candle = latest.candles.find((item) => item.date === snapshot.intraday_date);
        if (candle) latest.day = candle;
        if (!homeChart && visible()) homeChart = createChart($("[data-index-chart]"));
        setLine(homeChart, latest);
        $("[data-index-empty]").hidden = Boolean(homeChart?.hasData);
      }
      latest.updated_at = snapshot.generated_at || snapshot.updated_at || latest.updated_at;
      $("[data-index-updated]").textContent = `更新 ${updateClock(latest.updated_at)}`;
      liveSecond();
      document.dispatchEvent(new CustomEvent("dashboard:index-live", { detail:snapshot }));
    }).catch(() => { if (latest) $("[data-index-updated]").textContent = "实时更新暂不可用 · 显示最近数据"; }).finally(() => {
      livePending = null;
      if (liveRefreshDue && visible() && latest) return refreshLive();
    });
    return livePending;
  }

  function detailHtml(data) {
    const day = data.day;
    const metrics = [["开盘", points(day.open ?? 100)], ["最高", points(day.high ?? data.current)], ["最低", points(day.low ?? data.current)], ["收盘 / 当前", points(data.current), "current"], ["振幅", `${(number(day.open) ? (number(day.high) - number(day.low)) / number(day.open) * 100 : 0).toFixed(2)}%`], ["今日专注", duration(data.today_focus_seconds), "focus"], ["跌停", points(data.limit_down), "low"], ["涨停", points(data.limit_up), "high"], ["状态", data.is_paused ? "已暂停" : data.is_focusing ? "专注中" : "休息中", "status"]];
    const params = data.parameters || {};
    const parameters = [["低位锚点 A_low", params.a_low_hours, "小时", "对应低位收益区间的专注时长。"], ["目标锚点 A_mid", params.a_mid_hours, "小时", "对应中位收益的目标时长。"], ["高位锚点 A_high", params.a_high_hours, "小时", "对应高位收益区间的专注时长。"], ["低区倍率 K_low", params.k_low_percent_per_hour, "% / 小时", "控制目标时长以下的线性收益变化。"], ["高区倍率 K_high", params.k_high_percent_per_hour, "% / 小时", "控制目标时长以上的线性收益变化。"]];
    const dates = data.candles.map((row) => row.date).filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date));
    const quoteMeta = `相对前一日收盘 · ${day.date || "暂无交易记录"} · 数据时间 ${data.updated_at || "未知"} · 盘中逐秒更新，历史保留正式采样和状态事件`;
    return `<div class="index-detail"><div class="index-detail-quote ${data.change < 0 ? "index-fall" : "index-rise"}" data-tooltip="${escape(quoteMeta)}" tabindex="0"><strong>${points(data.current)}</strong><span>${signed(data.change)} (${signed(data.pct, 2)}%)</span></div><dl class="index-detail-grid">${metrics.map(([key, value, metric]) => `<div><dt>${escape(key)}</dt><dd ${metric ? `data-index-detail-metric="${metric}"` : ""}>${escape(value)}</dd></div>`).join("")}</dl><section><h3 data-tooltip="红涨绿跌；点击日 K 查看当天分时" tabindex="0">历史日线</h3><div class="index-detail-chart" data-index-daily role="img" aria-label="专注指数日线 K 线"></div><p data-index-daily-note class="sr-only">${dates.length ? "红涨绿跌 · 点击日线查看当天分时" : "暂无历史数据"}</p></section><section><div class="index-detail-select"><h3 data-tooltip="横轴固定展示所选日期开盘至收盘；圆点标记专注切换，箭头标记收盘重置" tabindex="0">分时走势</h3><select data-index-day aria-label="选择分时日期" ${dates.length ? "" : "disabled"}>${dates.map((date) => `<option value="${escape(date)}" ${date === data.intraday_date ? "selected" : ""}>${escape(date)}</option>`).join("")}</select></div><div class="index-detail-chart" data-index-intraday role="img" aria-label="所选日期交易时段分时图"></div><p data-index-path-note class="sr-only">${data.intraday?.length ? `${escape(data.intraday_date)} · 1 分钟正式采样` : "暂无分时记录"}</p></section><section><h3 data-tooltip="普通限制 ±10%，挑战限制 ±20%；各日按当时生效的政策计算；低于 10 点时收盘重置至 10 点" tabindex="0">指数参数</h3>${window.IndexChallenge?.controlHtml() || ""}<dl class="index-params">${parameters.map(([label, value, unit, explanation]) => `<div><dt data-tooltip="${escape(explanation)}" tabindex="0">${escape(label)} · ${value === undefined ? "—" : escape(value)} ${escape(unit)}</dt></div>`).join("")}</dl></section><a href="/focus-kline" class="index-detail-link">打开完整行情与参数设置 ↗</a></div>`;
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
    const unmountChallenge = window.IndexChallenge?.mount(host);
    const paintDetailQuote = (value, previous) => {
      const quote = host.querySelector(".index-detail-quote"), target = quote?.querySelector("strong"), delta = quote?.querySelector("span");
      const change = value - previous;
      if (target) {
        const before = number(target.textContent, value), next = points(value);
        if (target.textContent !== next) {
          target.classList.remove("is-tick-up", "is-tick-down"); void target.offsetWidth;
          target.classList.add(value > before ? "is-tick-up" : "is-tick-down"); target.textContent = next;
        }
      }
      if (delta) delta.textContent = `${signed(change)} (${signed(previous ? change / previous * 100 : 0, 2)}%)`;
      quote?.classList.toggle("index-rise", change >= 0); quote?.classList.toggle("index-fall", change < 0);
      const currentMetric = host.querySelector('[data-index-detail-metric="current"]');
      if (currentMetric) currentMetric.textContent = points(value);
    };
    const summary = (next) => {
      const values = { current:points(next.index?.current ?? next.current), focus:duration(next.today_focus_seconds), low:points(next.limit_down), high:points(next.limit_up), status:next.is_paused ? "已暂停" : next.is_focusing ? "专注中" : "休息中" };
      Object.entries(values).forEach(([key, value]) => { const target = host.querySelector(`[data-index-detail-metric="${key}"]`); if (target) target.textContent = value; });
      paintDetailQuote(number(next.index?.current ?? next.current), number(next.previous_close, 100));
    };
    if (daily) {
      daily.series.setData(data.candles.filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date)).map((row) => ({ time:row.date, open:number(row.open), high:number(row.high), low:number(row.low), close:number(row.close) })));
      daily.chart.timeScale().fitContent();
    } else host.querySelector("[data-index-daily-note]").textContent = "图表组件未加载";
    setLine(path, data);
    let selectedData = data, detailSnapshot = live, detailPending = null, detailTimer = null, detailPollTimer = null, detailRefreshDue = false;
    const detailSecond = () => {
      if (disposed || !path?.market || select.value !== todayDate()) return;
      const snapshot = detailSnapshot;
      if (!snapshot || snapshot.requestVersion !== liveRequestVersion || marketDay(snapshot) !== select.value) { paintNow(path, serverNow()); return; }
      const projection = Market.project(snapshot, path.market);
      if (!projection) return;
      appendLive(path, projection);
      paintNow(path, projection.now * 1000);
      const previous = number(snapshot.previous_close, selectedData.previous_close);
      paintDetailQuote(projection.value, previous);
    };
    const detailPoll = () => {
      if (disposed || document.hidden || select.value !== todayDate()) return;
      if (detailPending) { detailRefreshDue = true; return; }
      const requestSequence = sequence;
      const requestVersion = liveRequestVersion;
      detailRefreshDue = false;
      detailPending = requestLive().then((snapshot) => {
        if (disposed || requestSequence !== sequence || requestVersion !== liveRequestVersion || marketDay(snapshot) !== select.value) return;
        if (!acceptPolicy(snapshot) || disposed || requestSequence !== sequence || requestVersion !== liveRequestVersion) return;
        snapshot.receivedAt = Date.now(); snapshot.requestVersion = requestVersion;
        acceptDetail(snapshot);
      }).catch(() => { if (!disposed) note.textContent = "实时更新暂不可用 · 显示最近数据"; }).finally(() => {
        detailPending = null;
        if (detailRefreshDue && !disposed) detailPoll();
      });
    };
    const acceptDetail = (snapshot) => {
      if (disposed || snapshot.requestVersion !== liveRequestVersion || !acceptPolicy(snapshot)) return;
      summary(snapshot);
      if (select.value !== todayDate() || marketDay(snapshot) !== select.value) return;
      if (detailSnapshot && Market.parse(snapshot.generated_at) < Market.parse(detailSnapshot.generated_at)) return;
      detailSnapshot = snapshot;
      selectedData = { ...selectedData, intraday:snapshot.intraday || selectedData.intraday, intraday_date:snapshot.intraday_date, updated_at:snapshot.generated_at, change:number(snapshot.index?.current, 100) - number(snapshot.previous_close, 100) };
      setLine(path, selectedData); detailSecond();
    };
    const detailFresh = (event) => acceptDetail(event.detail);
    const detailInvalidated = () => { detailSnapshot = null; detailRefreshDue = true; detailPoll(); };
    document.addEventListener("dashboard:index-live", detailFresh);
    document.addEventListener("dashboard:index-invalidated", detailInvalidated);
    const challengeChanged = () => { if (!disposed) { detailSnapshot = null; choose(select.value); } };
    document.addEventListener("dashboard:challenge-updated", challengeChanged);
    detailTimer = setInterval(detailSecond, 1000);
    detailPollTimer = setInterval(detailPoll, 15000);
    detailPoll(); detailSecond();
    async function choose(date) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
      dateController?.abort();
      dateController = new AbortController();
      const requestSequence = ++sequence;
      note.textContent = `${date} · 正在读取`;
      try {
        const next = await request(date, dateController.signal);
        if (disposed || sequence !== requestSequence) return;
        if (!acceptPolicy(next) || disposed || sequence !== requestSequence) return;
        selectedData = next;
        summary(next);
        setLine(path, next);
        note.textContent = next.intraday_date === date && next.intraday?.length ? `${date} · 1 分钟正式采样` : `${date} 暂无分时记录`;
        // The API may fall back to a previous trading day for an empty date.
        if (next.intraday_date !== date && path) { path.lines.forEach((line) => line.setData([])); path.hasData = false; }
        if (date === todayDate()) detailPoll();
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
      clearInterval(detailTimer); clearInterval(detailPollTimer);
      dateController?.abort();
      daily?.dispose(); path?.dispose(); observer.disconnect();
      unmountChallenge?.();
      document.removeEventListener("dashboard:appearance", appearance);
      document.removeEventListener("dashboard:index-live", detailFresh);
      document.removeEventListener("dashboard:index-invalidated", detailInvalidated);
      document.removeEventListener("dashboard:challenge-updated", challengeChanged);
      signal?.removeEventListener("abort", dispose);
      if (drawerDispose === dispose) drawerDispose = null;
    };
    drawerDispose = dispose;
    signal?.addEventListener("abort", dispose, { once:true });
  }
  window.DashboardDetails?.register("index", async (descriptor) => {
    let data = await request(todayDate(), descriptor.signal);
    if (!acceptPolicy(data)) { data = await request(todayDate(), descriptor.signal); if (!acceptPolicy(data)) throw new Error("挑战状态更新中，请重新打开详情"); }
    return { title:"专注指数", kicker:"FOCUS INDEX · 行情详情", html:detailHtml(data), onReady:(host) => readyDetail(host, data, descriptor.signal) };
  });
  document.addEventListener("dashboard:detail-closed", () => drawerDispose?.());
  document.addEventListener("dashboard:challenge-updated", () => { live = null; refreshFull(true); refreshLive(true); });
  document.addEventListener("dashboard:updated", (event) => {
    const data = event.detail || {}, active = data.focus?.active;
    const priorDay = todayDate();
    if (typeof data.now === "string") {
      dashboardNow = data.now;
      const epoch = Date.parse(data.now);
      if (Number.isFinite(epoch)) dashboardClock = { epoch, receivedAt:Date.now() };
    }
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
  new MutationObserver(() => { if (visible()) { if (refreshDue || !latest) refreshFull(); else { render(latest); liveSecond(); refreshLive(); } } }).observe(view, { attributes:true, attributeFilter:["hidden", "class", "style"] });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { if (refreshDue || !latest) refreshFull(); else refreshLive(true); } });
  setInterval(liveSecond, 1000);
  setInterval(() => { if (visible()) refreshLive(); }, 15000);
  window.DashboardIndex = { refresh:() => latest ? refreshLive(true) : refreshFull(true), resize:() => { if (homeChart && visible()) { homeChart.chart.applyOptions({ width:$("[data-index-chart]").clientWidth, height:Math.max(70, $("[data-index-chart]").clientHeight) }); Market.pin(homeChart.chart, homeChart.market); liveSecond(); } else if (latest && visible()) render(latest); } };
  refreshFull();
})();
