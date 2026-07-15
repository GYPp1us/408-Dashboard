(() => {
  const state = { dashboard: null, dashboardFetchedAt: null, dashboardSignature: null, scoreChart: null, summaryCharts: [], secondTasks: new Map(), secondTimer: null, syncTimer: null, syncing: false, wakeLock: null, wakeRetry: null, starting: false, ending: false, focusMessageIndex: null };
  const appFontFamily = '"Source Han Serif SC Medium", "Source Han Serif SC", "思源宋体 SC", "Noto Serif SC", "Noto Serif CJK SC", "Songti SC", "STSong", serif';
  const themePalettes = {
    idle: ["#d66c58", "#b25647", "#dd9073", "#97483e", "#c27758", "#e4a994", "#835144", "#d28a72"],
    focus: ["#7a5bc7", "#5f42aa", "#987ddd", "#4d358c", "#876cbf", "#b09be7", "#614e87", "#9b84cf"],
  };
  const focusMessages = [
    { category: "时间管理", text: "当前只处理一个问题，剩下的交给计划。" },
    { category: "时间管理", text: "先完成眼前这一步，再决定下一步。" },
    { category: "时间管理", text: "用完整的一小时，换一个真正清晰的知识点。" },
    { category: "时间管理", text: "难题先标记，别让局部拖住整段节奏。" },
    { category: "时间管理", text: "速度不是匆忙，而是减少无意义的切换。" },
    { category: "时间管理", text: "给任务设边界，也给注意力留出余地。" },
    { category: "时间管理", text: "复习进度由完成的闭环决定，不由打开的页面决定。" },
    { category: "时间管理", text: "卡住五分钟，就换一种表述重新理解。" },
    { category: "时间管理", text: "今天的稳定投入，比临时冲刺更可靠。" },
    { category: "时间管理", text: "结束前留两分钟，写下清晰的下一步。" },
    { category: "继续前进", text: "你正在把陌生变成熟悉。" },
    { category: "继续前进", text: "每一次专注，都在降低考场上的不确定性。" },
    { category: "继续前进", text: "不必等状态完美，开始本身会制造状态。" },
    { category: "继续前进", text: "碰到能力边界时，慢一点也算前进。" },
    { category: "继续前进", text: "现在积累的确定性，会在考场上替你说话。" },
    { category: "继续前进", text: "把会做的做稳，把不会的逐步拆开。" },
    { category: "继续前进", text: "今日不求惊艳，只求比昨天更扎实。" },
    { category: "继续前进", text: "题目不会辜负真正理解它的人。" },
    { category: "继续前进", text: "长期主义不是坚持口号，而是完成这一段。" },
    { category: "继续前进", text: "无需一次看见终点，只需要守住当前节奏。" },
    { category: "视线提醒", text: "别盯着面板，回到书页和题目。" },
    { category: "视线提醒", text: "看远处二十秒，让眼睛也完成一次休息。" },
    { category: "视线提醒", text: "肩膀放松，呼吸一次，再继续。" },
    { category: "视线提醒", text: "喝一口水，不要用疲劳冒充努力。" },
    { category: "视线提醒", text: "坐姿归位，屏幕只是计时器，不是任务本身。" },
    { category: "视线提醒", text: "如果正在走神，写下干扰，再回到当前题。" },
    { category: "视线提醒", text: "面板没有新答案，答案在你的草稿纸上。" },
    { category: "视线提醒", text: "眼睛离开屏幕，注意力留在问题上。" },
    { category: "视线提醒", text: "听见自己翻页的声音，比看计时数字更重要。" },
    { category: "视线提醒", text: "不用频繁确认时间，计时会替你记住。" },
  ];
  const $ = (selector) => document.querySelector(selector);
  const getThemePalette = (active = Boolean(state.dashboard?.focus?.active)) => themePalettes[active ? "focus" : "idle"];
  if (window.Chart) {
    Chart.defaults.font.family = appFontFamily;
    Chart.defaults.font.size = 14;
    Chart.defaults.font.weight = 500;
  }
  const formatSeconds = (total) => {
    const value = Math.max(0, Math.floor(total));
    return [Math.floor(value / 3600), Math.floor((value % 3600) / 60), value % 60].map((part) => String(part).padStart(2, "0")).join(":");
  };
  const formatMinutes = (minutes) => formatSeconds(Math.max(0, Math.round(minutes * 60)));
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));

  function createClientToken() {
    const cryptoApi = window.crypto || window.msCrypto;
    if (cryptoApi && typeof cryptoApi.randomUUID === "function") return cryptoApi.randomUUID();
    if (cryptoApi && typeof cryptoApi.getRandomValues === "function") {
      const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
    return `focus-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  }

  function runSecondTasks(now = Date.now()) {
    state.secondTasks.forEach((task) => task(now));
  }

  function setSecondTask(name, task) {
    state.secondTasks.set(name, task);
    task(Date.now());
  }

  function removeSecondTask(name) {
    state.secondTasks.delete(name);
  }

  function startAlignedSecondClock() {
    const tick = () => {
      runSecondTasks(Date.now());
      state.secondTimer = window.setTimeout(tick, Math.max(20, 1000 - (Date.now() % 1000)));
    };
    window.clearTimeout(state.secondTimer);
    state.secondTimer = window.setTimeout(tick, Math.max(20, 1000 - (Date.now() % 1000)));
  }

  function scheduleWakeLockRetry() {
    window.clearTimeout(state.wakeRetry);
    if (document.visibilityState === "visible") state.wakeRetry = window.setTimeout(ensureWakeLock, 2000);
  }

  async function ensureWakeLock() {
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible" || state.wakeLock) return;
    try {
      const lock = await navigator.wakeLock.request("screen");
      state.wakeLock = lock;
      lock.addEventListener("release", () => {
        if (state.wakeLock === lock) state.wakeLock = null;
        scheduleWakeLockRetry();
      });
    } catch (_error) {
      scheduleWakeLockRetry();
    }
  }

  async function api(url, options = {}) {
    const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    if (response.status === 401) {
      window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
      throw new Error("authentication_required");
    }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "请求失败");
    return payload;
  }

  function showToast(message) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2400);
  }

  function renderStatus(data) {
    const remaining = Number(data.exam?.remaining_seconds || 0);
    state.examEndsAt = Date.now() + remaining * 1000;
    const today = data.today_focus || { seconds: 0, count: 0 };
    const active = data.focus?.active;
    const todayFetchedAt = Date.now();
    const tick = (now) => {
      const value = Math.max(0, Math.floor((state.examEndsAt - now) / 1000));
      $("#exam-days").textContent = `${Math.floor(value / 86400)} 天`;
      $("#exam-clock").textContent = formatSeconds(value % 86400);
      const todaySeconds = Number(today.seconds || 0) + (active ? Math.max(0, Math.floor((now - todayFetchedAt) / 1000)) : 0);
      $("#today-study").textContent = `${formatSeconds(todaySeconds)} / 08:00`;
      $("#today-progress").textContent = `完成度 ${Math.min(100, Math.round((todaySeconds / 28800) * 100))}%`;
      $("#focus-today")?.replaceChildren(document.createTextNode(`${formatSeconds(todaySeconds)} / 08:00`));
      $("#guest-today-total")?.replaceChildren(document.createTextNode(formatSeconds(todaySeconds)));
      $("#guest-today-target")?.replaceChildren(document.createTextNode(`8 小时目标 · ${Math.min(100, Math.round((todaySeconds / 28800) * 100))}%`));
    };
    setSecondTask("status", tick);
    $("#current-state").textContent = active ? `专注中 · ${active.subject}` : "准备学习";
    $("#state-dot").classList.toggle("state-dot-active", Boolean(active));
  }

  function renderClock() {
    setSecondTask("clock", (now) => $("#current-time")?.replaceChildren(document.createTextNode(new Date(now).toLocaleTimeString("zh-CN", { hour12: false }))));
  }

  function clockMinutes(value) {
    const [hours, minutes] = String(value || "00:00").split(":").map(Number);
    return hours * 60 + minutes;
  }

  function dateMinutes(value) {
    const date = new Date(value);
    const reference = new Date(state.dashboard?.now || Date.now());
    const dayStart = new Date(reference.getFullYear(), reference.getMonth(), reference.getDate());
    if (date < dayStart) return 0;
    if (date >= new Date(dayStart.getTime() + 86400000)) return 1440;
    return date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60;
  }

  function renderWindowHistory(prefix, value, sessions) {
    const target = $(`#${prefix}-history`);
    if (!target) return;
    const start = clockMinutes(value.start);
    const end = clockMinutes(value.end);
    const total = Math.max(1, end - start);
    target.innerHTML = (sessions || []).map((session) => {
      const sessionStart = Math.max(start, dateMinutes(session.started_at));
      const sessionEnd = Math.min(end, session.ended_at ? dateMinutes(session.ended_at) : dateMinutes(Date.now()));
      if (sessionEnd <= sessionStart) return "";
      const left = ((sessionStart - start) / total) * 100;
      const width = ((sessionEnd - sessionStart) / total) * 100;
      const edgeClass = `${sessionStart <= start ? " at-start" : ""}${sessionEnd >= end ? " at-end" : ""}`;
      return `<span class="${edgeClass.trim()}" style="left:${left}%;width:${width}%" title="${escapeHtml(session.subject)} · ${Math.max(1, Math.round(sessionEnd - sessionStart))} 分钟"></span>`;
    }).join("");
  }

  function renderHomeWindow(data, currentTime) {
    const now = currentTime.getHours() * 3600 + currentTime.getMinutes() * 60 + currentTime.getSeconds();
    const morningStart = clockMinutes(data.windows.morning.start) * 60;
    const lunchStart = clockMinutes(data.windows.morning.end) * 60;
    const libraryStart = clockMinutes(data.windows.library.start) * 60;
    const libraryEnd = clockMinutes(data.windows.library.end) * 60;
    let label;
    let action;
    let remaining;
    if (now < morningStart) {
      label = "休息时间";
      action = "距离上午开始";
      remaining = morningStart - now;
    } else if (now < lunchStart) {
      label = "上午学习窗口";
      action = "距离午休";
      remaining = lunchStart - now;
    } else if (now < libraryStart) {
      label = "午间休息";
      action = "距离下午开始";
      remaining = libraryStart - now;
    } else if (now < libraryEnd) {
      label = "下午学习窗口";
      action = "距离闭馆";
      remaining = libraryEnd - now;
    } else {
      label = "休息时间";
      action = "距离上午开始";
      remaining = 86400 - now + morningStart;
    }
    $("#home-window-label").textContent = label;
    $("#home-window-action").textContent = action;
    $("#home-window-countdown").textContent = formatSeconds(remaining);
  }

  function renderWindows(data) {
    const windows = [
      ["lunch", data.windows.morning],
      ["library", data.windows.library],
    ];
    const timeGrid = $(".time-grid");
    timeGrid?.style.setProperty("--morning-window", `${Math.max(1, Number(data.windows.morning.total_seconds) || 1)}fr`);
    timeGrid?.style.setProperty("--library-window", `${Math.max(1, Number(data.windows.library.total_seconds) || 1)}fr`);
    const fetchedAt = Date.now();
    const serverNowAt = Date.parse(data.now);
    const setWindow = (prefix, value, endAt, now) => {
      const startAt = endAt - Number(value.total_seconds || 0) * 1000;
      const progress = Math.min(1, Math.max(0, (now - startAt) / Math.max(1, endAt - startAt)));
      const remaining = Math.max(0, Math.ceil((endAt - now) / 1000));
      $(`#${prefix}-clock`).textContent = formatSeconds(remaining);
      $(`#${prefix}-remaining`)?.replaceChildren(document.createTextNode(formatSeconds(remaining)));
      $(`#${prefix}-percent`).textContent = `${Math.round(progress * 100)}%`;
      $(`#${prefix}-progress`).style.width = `${Math.round(progress * 100)}%`;
      $(`#${prefix}-start-label`).textContent = value.start;
      $(`#${prefix}-end-label`).textContent = value.end;
      renderWindowHistory(prefix, value, state.dashboard?.focus?.today || []);
    };
    setSecondTask("windows", (now) => {
      windows.forEach(([prefix, value]) => setWindow(prefix, value, fetchedAt + Number(value.remaining_seconds || 0) * 1000, now));
      renderHomeWindow(data, new Date(serverNowAt + now - fetchedAt));
    });
  }

  function renderTicker(scores) {
    const track = $("#score-track");
    if (!track) return;
    const rows = scores.length ? scores : [{ subject: "暂无成绩", score: "--", target: "--", gap: 0 }];
    const billboardRows = Array.from({ length: 4 }, (_, index) => rows[index % rows.length]);
    track.innerHTML = [...billboardRows, billboardRows[0]].map((item) => `<div class="score-row"><span>${escapeHtml(item.subject)}</span><b>${item.score} / ${item.target}</b><em class="${item.gap > 0 ? "bad" : item.gap < 0 ? "good" : ""}">${item.gap > 0 ? `-${item.gap}` : item.gap < 0 ? `+${Math.abs(item.gap)}` : "--"}</em></div>`).join("");
  }

  function renderHeatmap(heatmap, visibleHours) {
    const hours = $("#heat-hours");
    const grid = $("#heat-grid");
    if (!hours || !grid) return;
    const configuredHours = [...new Set((visibleHours || []).map(Number))].filter((hour) => Number.isInteger(hour) && hour >= 0 && hour < 24 && hour % 2 === 0);
    const shownHours = configuredHours.length ? configuredHours : Array.from({ length: 12 }, (_, index) => index * 2);
    const buckets = shownHours.map((hour) => hour / 2);
    const rowTemplate = `repeat(${buckets.length},1fr)`;
    hours.style.gridTemplateRows = rowTemplate;
    grid.style.gridTemplateRows = rowTemplate;
    hours.innerHTML = shownHours.map((hour) => `<span>${String(hour).padStart(2, "0")}</span>`).join("");
    const max = Math.max(120, ...heatmap.flatMap((day) => buckets.map((bucket) => day[bucket] || 0)));
    const renderCell = (minutes, dayIndex, bucket) => {
      const level = minutes === 0 ? 0 : Math.min(4, Math.ceil((minutes / max) * 4));
      const startHour = bucket * 2;
      return `<i class="heat-cell${level ? ` l${level}` : ""}" data-detail="最近第 ${30 - dayIndex} 天 ${String(startHour).padStart(2, "0")}:00-${String(startHour + 2).padStart(2, "0")}:00 · ${minutes} 分钟" title="${minutes} 分钟"></i>`;
    };
    grid.innerHTML = buckets.map((bucket) => heatmap.map((day, dayIndex) => renderCell(day[bucket] || 0, dayIndex, bucket)).join("")).join("");
    grid.querySelectorAll(".heat-cell").forEach((cell) => cell.addEventListener("click", () => {
      $("#heat-detail").textContent = cell.dataset.detail;
    }));
  }

  function renderScores(scores, selector = "#score-table") {
    const target = $(selector);
    if (!target) return;
    target.innerHTML = scores.map((item) => target.tagName === "TBODY"
      ? `<tr><td>${escapeHtml(item.subject)}</td><td>${item.score} / ${item.target}</td><td class="${item.gap > 0 ? "bad" : "good"}">${item.gap > 0 ? `-${item.gap}` : `+${Math.abs(item.gap)}`}</td><td class="${item.completion >= .9 ? "good" : "bad"}">${Math.round(item.completion * 100)}%</td></tr>`
      : `<div><span>${escapeHtml(item.subject)}</span><b>${item.score} / ${item.target} · ${Math.round(item.completion * 100)}%</b></div>`).join("");
  }

  function renderFocusInvestment(investment, active) {
    if (!$("#focus-investment-view")) return;
    const baseline = investment || {};
    const fetchedAt = Date.now();
    const renderTargetStack = (selector, seconds) => {
      const target = $(selector);
      if (!target) return;
      const percent = Math.max(0, Math.min(100, (seconds / 28800) * 100));
      target.innerHTML = `<span class="stack-primary" style="width:${percent}%"></span><span class="stack-rest" style="width:${100 - percent}%"></span>`;
    };
    const subjectsWithActiveTime = (items, extraSeconds) => {
      const subjects = (items || []).map((item) => ({ ...item, seconds: Number(item.seconds || 0) }));
      if (active && extraSeconds) {
        const activeSubject = subjects.find((item) => item.subject === active.subject);
        if (activeSubject) activeSubject.seconds += extraSeconds;
        else subjects.push({ subject: active.subject, seconds: extraSeconds });
      }
      return subjects.sort((left, right) => right.seconds - left.seconds || left.subject.localeCompare(right.subject, "zh-CN"));
    };
    const renderSubjectStack = (stackSelector, legendSelector, subjects, totalSeconds) => {
      const stack = $(stackSelector);
      const legend = $(legendSelector);
      const topSubjects = subjects.slice(0, 3);
      if (!totalSeconds || !topSubjects.length) {
        stack.innerHTML = "";
        legend.innerHTML = "<span>暂无专注数据</span>";
        return;
      }
      const palette = getThemePalette();
      const topSeconds = topSubjects.reduce((sum, item) => sum + item.seconds, 0);
      stack.innerHTML = topSubjects.map((item, index) => `<span style="width:${(item.seconds / totalSeconds) * 100}%;background:${palette[index]}"></span>`).join("") + `<span class="stack-other" style="width:${Math.max(0, ((totalSeconds - topSeconds) / totalSeconds) * 100)}%"></span>`;
      legend.innerHTML = topSubjects.map((item, index) => `<span><i style="background:${palette[index]}"></i>${escapeHtml(item.subject)}<b>${Math.round((item.seconds / totalSeconds) * 1000) / 10}% · ${formatSeconds(item.seconds)}</b></span>`).join("");
    };
    const tick = (now) => {
      const extraSeconds = active ? Math.max(0, Math.floor((now - fetchedAt) / 1000)) : 0;
      const currentSeconds = Number(baseline.current_seconds || 0) + extraSeconds;
      const dailyAverage = Math.floor(currentSeconds / 7);
      const previousAverage = Number(baseline.previous_daily_average_seconds || 0);
      const trendSeconds = dailyAverage - previousAverage;
      const trend = $("#investment-trend");
      $("#investment-daily-average").textContent = formatSeconds(dailyAverage);
      trend.className = `investment-trend${trendSeconds > 0 ? " up" : trendSeconds < 0 ? " down" : ""}`;
      trend.textContent = trendSeconds > 0 ? `↑ ${formatSeconds(trendSeconds)}` : trendSeconds < 0 ? `↓ ${formatSeconds(Math.abs(trendSeconds))}` : "较前 7 天持平";
      renderTargetStack("#investment-average-stack", dailyAverage);

      $("#investment-week-total").textContent = formatSeconds(currentSeconds);
      renderSubjectStack("#investment-subject-stack", "#investment-subject-legend", subjectsWithActiveTime(baseline.subjects, extraSeconds), currentSeconds);

      const todaySeconds = Number(baseline.today_seconds || 0) + extraSeconds;
      $("#investment-today-total").textContent = formatSeconds(todaySeconds);
      $("#investment-today-percent").textContent = `${Math.round((todaySeconds / 28800) * 1000) / 10}%`;
      renderSubjectStack("#investment-today-stack", "#investment-today-legend", subjectsWithActiveTime(baseline.today_subjects, extraSeconds), todaySeconds);
    };
    removeSecondTask("investment");
    if (active) setSecondTask("investment", tick);
    else tick(fetchedAt);
  }

  function renderFocusComparison(active) {
    const view = $("#focus-comparison-view");
    if (!view || !active) {
      removeSecondTask("focusComparison");
      state.focusMessageIndex = null;
      return;
    }
    const tick = (now) => {
      const investment = state.dashboard?.focus_investment || {};
      const fetchedAt = state.dashboardFetchedAt || now;
      const extraSeconds = Math.max(0, Math.floor((now - fetchedAt) / 1000));
      const todaySeconds = Number(investment.today_seconds || 0) + extraSeconds;
      const yesterdaySeconds = Number(investment.yesterday_same_time_seconds || 0);
      const delta = todaySeconds - yesterdaySeconds;
      const maxSeconds = Math.max(1, todaySeconds, yesterdaySeconds);
      view.classList.toggle("ahead", delta > 0);
      view.classList.toggle("behind", delta < 0);
      $("#focus-compare-time").textContent = `截至 ${new Date(now).toLocaleTimeString("zh-CN", { hour12: false })}`;
      $("#focus-compare-today").textContent = formatSeconds(todaySeconds);
      $("#focus-compare-today-label").textContent = formatSeconds(todaySeconds);
      $("#focus-compare-yesterday-label").textContent = formatSeconds(yesterdaySeconds);
      $("#focus-compare-trend").textContent = delta > 0 ? `领先 ${formatSeconds(delta)}` : delta < 0 ? `落后 ${formatSeconds(Math.abs(delta))}` : "与昨日持平";
      $("#focus-compare-today-bar").style.width = `${(todaySeconds / maxSeconds) * 100}%`;
      $("#focus-compare-yesterday-bar").style.width = `${(yesterdaySeconds / maxSeconds) * 100}%`;

      const elapsed = Math.max(0, Math.floor((now - Date.parse(active.started_at)) / 1000));
      const messageIndex = Math.floor(elapsed / 30) % focusMessages.length;
      if (messageIndex !== state.focusMessageIndex) {
        state.focusMessageIndex = messageIndex;
        const message = focusMessages[messageIndex];
        const card = $("#focus-message-card");
        const displayIndex = String(messageIndex + 1).padStart(2, "0");
        card.dataset.index = displayIndex;
        $("#focus-message-category").textContent = message.category;
        $("#focus-message-text").textContent = message.text;
        $("#focus-message-count").textContent = `${displayIndex} / ${focusMessages.length}`;
        card.classList.remove("is-changing");
        void card.offsetWidth;
        card.classList.add("is-changing");
      }
    };
    setSecondTask("focusComparison", tick);
  }

  function renderGuestSummary(data) {
    const totalTarget = $("#guest-today-total");
    if (!totalTarget) return;
    const today = data.today_focus || { seconds: 0, count: 0 };
    totalTarget.textContent = formatSeconds(today.seconds);
    $("#guest-today-target").textContent = `8 小时目标 · ${Math.min(100, Math.round((today.seconds / 28800) * 100))}%`;
    $("#guest-today-count").textContent = String(today.count || 0);
    $("#guest-today-state").textContent = data.focus?.active ? `专注中` : "空闲";
    const totals = new Map();
    (data.focus?.today || []).forEach((item) => {
      const startedAt = Date.parse(item.started_at);
      const endedAt = item.ended_at ? Date.parse(item.ended_at) : Date.now();
      totals.set(item.subject, (totals.get(item.subject) || 0) + Math.max(0, Math.floor((endedAt - startedAt) / 1000)));
    });
    const target = $("#guest-subject-list");
    target.innerHTML = totals.size
      ? [...totals.entries()].sort((left, right) => right[1] - left[1]).map(([subject, seconds]) => `<div><span>${escapeHtml(subject)}</span><b>${formatSeconds(seconds)}</b></div>`).join("")
      : '<div class="loading-row">今日暂无专注记录。</div>';
  }

  function closeFocusSummary() {
    removeSecondTask("summary");
    state.summaryCharts.forEach((chart) => chart.destroy());
    state.summaryCharts = [];
    const overview = $("#focus-investment-view");
    const comparison = $("#focus-comparison-view");
    const summary = $("#focus-summary");
    const active = Boolean(state.dashboard?.focus?.active);
    if (overview) overview.hidden = active;
    if (comparison) comparison.hidden = !active;
    if (summary) summary.hidden = true;
  }

  function showFocusSummary(session, todaySessions) {
    const overview = $("#focus-investment-view");
    const comparison = $("#focus-comparison-view");
    const summary = $("#focus-summary");
    if (!overview || !summary || !window.Chart) return;
    closeFocusSummary();
    overview.hidden = true;
    if (comparison) comparison.hidden = true;
    summary.hidden = false;
    const duration = Math.max(0, Math.floor((Date.parse(session.ended_at) - Date.parse(session.started_at)) / 1000));
    $("#summary-session-time").textContent = formatSeconds(duration);
    const gap = 3600 - duration;
    $("#summary-goal-gap").textContent = gap > 0 ? `距 1 小时还差 ${Math.ceil(gap / 60)} 分钟` : gap < 0 ? `已达标 · 超出 ${Math.floor(Math.abs(gap) / 60)} 分钟` : "已达成 1 小时目标";
    const palette = getThemePalette();
    state.summaryCharts.push(new Chart($("#session-goal-chart"), {
      type: "doughnut",
      data: { datasets: [{ data: [Math.min(duration, 3600), Math.max(0, gap)], backgroundColor: [palette[0], "#e5e7ea"], borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "72%", plugins: { legend: { display: false }, tooltip: { enabled: false } }, animation: { duration: 350 } },
    }));
    const totals = new Map();
    (todaySessions || []).forEach((item) => {
      const seconds = Math.max(0, Math.floor(((item.ended_at ? Date.parse(item.ended_at) : Date.now()) - Date.parse(item.started_at)) / 1000));
      totals.set(item.subject, (totals.get(item.subject) || 0) + seconds);
    });
    if (!totals.size) totals.set(session.subject, duration);
    const subjects = [...totals.keys()];
    const values = [...totals.values()];
    $("#summary-today-total").textContent = formatSeconds(values.reduce((sum, value) => sum + value, 0));
    state.summaryCharts.push(new Chart($("#today-subject-chart"), {
      type: "doughnut",
      data: { labels: subjects, datasets: [{ data: values, backgroundColor: subjects.map((_, index) => palette[index % palette.length]), borderColor: "#fff", borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "58%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => `${context.label} ${formatSeconds(context.raw)}` } } }, animation: { duration: 350 } },
    }));
    const total = Math.max(1, values.reduce((sum, value) => sum + value, 0));
    $("#today-subject-legend").innerHTML = subjects.map((subject, index) => `<span><i style="background:${palette[index % palette.length]}"></i>${escapeHtml(subject)} ${Math.round((values[index] / total) * 100)}%</span>`).join("");
    const restStartedAt = Date.now();
    const tick = (now) => {
      const elapsed = Math.floor((now - restStartedAt) / 1000);
      $("#rest-timer").textContent = formatSeconds(elapsed);
      if (elapsed >= 900) closeFocusSummary();
    };
    setSecondTask("summary", tick);
  }

  function formatScoreDate(value) {
    const date = new Date(`${value}T00:00:00`);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  }

  function renderScoreChart(history) {
    const canvas = $("#score-chart");
    const empty = $("#score-chart-empty");
    const detail = $("#score-chart-detail");
    if (!canvas || !empty || !detail || !window.Chart) return;
    state.scoreChart?.destroy();
    state.scoreChart = null;
    const grouped = new Map();
    (history || []).forEach((item) => {
      const date = String(item.exam_date || "").slice(0, 10);
      if (!date || !item.subject || Number(item.target) <= 0) return;
      if (!grouped.has(date)) grouped.set(date, new Map());
      grouped.get(date).set(item.subject, item);
    });
    const dates = [...grouped.keys()].sort().slice(-10);
    if (!dates.length) {
      canvas.hidden = true;
      empty.hidden = false;
      detail.textContent = "暂无模拟考数据。";
      return;
    }
    canvas.hidden = false;
    empty.hidden = true;
    const subjects = [...new Set(dates.flatMap((date) => [...grouped.get(date).keys()]))];
    const palette = getThemePalette();
    const datasets = subjects.map((subject, index) => ({
      label: subject,
      data: dates.map((date) => {
        const item = grouped.get(date).get(subject);
        return item ? Math.round((Number(item.score) / Number(item.target)) * 1000) / 10 : null;
      }),
      borderColor: palette[index % palette.length],
      backgroundColor: palette[index % palette.length],
      pointBackgroundColor: "#fff",
      pointBorderWidth: 2,
      pointRadius: 3,
      pointHoverRadius: 5,
      borderWidth: 2,
      tension: 0.28,
      spanGaps: false,
    }));
    const maxValue = Math.max(100, ...datasets.flatMap((dataset) => dataset.data.filter((value) => value !== null)));
    const crosshairPlugin = {
      id: "scoreCrosshair",
      afterDraw(chart) {
        const active = chart.tooltip?.getActiveElements?.() || [];
        if (!active.length) return;
        const index = active[0].index;
        const x = chart.scales.x.getPixelForValue(index);
        const context = chart.ctx;
        context.save();
        context.strokeStyle = "rgba(32, 39, 47, .24)";
        context.setLineDash([4, 4]);
        context.beginPath();
        context.moveTo(x, chart.chartArea.top);
        context.lineTo(x, chart.chartArea.bottom);
        context.stroke();
        chart.data.datasets.forEach((dataset, datasetIndex) => {
          if (dataset.data[index] === null) return;
          const point = chart.getDatasetMeta(datasetIndex).data[index];
          if (!point) return;
          context.fillStyle = dataset.borderColor;
          context.beginPath();
          context.arc(point.x, point.y, 5, 0, Math.PI * 2);
          context.fill();
          context.fillStyle = "#fff";
          context.beginPath();
          context.arc(point.x, point.y, 2, 0, Math.PI * 2);
          context.fill();
        });
        context.restore();
      },
    };
    state.scoreChart = new Chart(canvas, {
      type: "line",
      data: { labels: dates.map(formatScoreDate), datasets },
      plugins: [crosshairPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#758079", font: { size: 11 } } },
          y: { beginAtZero: true, suggestedMax: Math.ceil(maxValue / 10) * 10, grid: { color: "#ebefed" }, ticks: { color: "#758079", font: { size: 11 }, callback: (value) => `${value}%` } },
        },
        plugins: {
          legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 7, color: "#5f6b66", font: { size: 11 } } },
          tooltip: {
            enabled: false,
            external: ({ tooltip }) => {
              if (!tooltip || tooltip.opacity === 0 || !tooltip.dataPoints?.length) {
                detail.textContent = "将鼠标移到图表上查看当天各科成绩。";
                return;
              }
              const date = dates[tooltip.dataPoints[0].dataIndex];
              const items = [...grouped.get(date).values()];
              detail.innerHTML = `<strong>${formatScoreDate(date)}</strong>${items.map((item) => `<span>${escapeHtml(item.subject)} ${Math.round((Number(item.score) / Number(item.target)) * 1000) / 10}% · ${item.score} / ${item.target}</span>`).join("")}`;
            },
          },
        },
      },
    });
  }

  function syncScoreChartTheme(active) {
    if (!state.scoreChart) return;
    const palette = getThemePalette(Boolean(active));
    state.scoreChart.data.datasets.forEach((dataset, index) => {
      dataset.borderColor = palette[index % palette.length];
      dataset.backgroundColor = palette[index % palette.length];
    });
    state.scoreChart.update("none");
  }

  function renderModes(modes) {
    const target = $("#focus-modes");
    if (!target) return;
    target.innerHTML = modes.map((mode) => `<div class="mode"><div class="drag-launch" data-subject="${escapeHtml(mode.subject)}" data-mode="专注" data-duration="0"><div class="drag-fill"></div><span class="drag-label">${escapeHtml(mode.subject)}</span><span class="drag-thumb" role="button" tabindex="0" aria-label="滑动启动 ${escapeHtml(mode.subject)}">→</span></div></div>`).join("");
    initDragLaunchers();
  }

  function setDragProgress(track, thumb) {
    const max = Math.max(1, track.clientWidth - thumb.offsetWidth - 4);
    const ratio = Math.max(0, Math.min(1, (Number(gsap.getProperty(thumb, "x")) || 0) / max));
    track.querySelector(".drag-fill").style.width = `${Math.round(ratio * 100)}%`;
    track.querySelector(".drag-label").classList.toggle("on-fill", ratio > .42);
    track.classList.toggle("armed", ratio >= .72);
    return { max, ratio };
  }

  function initDragLaunchers() {
    if (!window.gsap || !window.Draggable) return;
    document.querySelectorAll(".drag-launch").forEach((track) => {
      const thumb = track.querySelector(".drag-thumb");
      if (track.dataset.bound) return;
      track.dataset.bound = "1";
      const drag = Draggable.create(thumb, {
        type: "x",
        bounds: track,
        onPress() { if (state.starting) this.endDrag?.(); },
        onDrag() { setDragProgress(track, thumb); },
        onRelease() {
          const { max, ratio } = setDragProgress(track, thumb);
          if (ratio >= .82) {
            track.classList.add("armed");
            gsap.to(thumb, { x: max, duration: .48, ease: "elastic.out(1, .55)", onComplete: () => commitFocusStart(track, thumb, max) });
          } else {
            gsap.to(thumb, { x: 0, duration: .58, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
          }
        }
      })[0];
      thumb.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          const max = Math.max(1, track.clientWidth - thumb.offsetWidth - 4);
          gsap.to(thumb, { x: max, duration: .48, ease: "elastic.out(1, .55)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => commitFocusStart(track, thumb, max) });
        }
      });
      drag.update();
    });
  }

  async function commitFocusStart(track, thumb, max) {
    if (state.starting) return;
    state.starting = true;
    track.classList.add("armed");
    try {
      const session = await api("/api/focus/start", { method: "POST", body: JSON.stringify({ subject: track.dataset.subject, mode: "专注", planned_minutes: 0, client_token: createClientToken() }) });
      const today = state.dashboard?.focus?.today || [];
      state.dashboard = { ...state.dashboard, focus: { ...(state.dashboard?.focus || {}), active: session.session, today: [...today.filter((item) => item.id !== session.session.id), session.session] } };
      applyFocusState(session.session, true);
      showToast("专注已启动");
    } catch (error) {
      gsap.to(thumb, { x: 0, duration: .62, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb) });
      track.classList.remove("armed");
      showToast(error.message);
    } finally {
      state.starting = false;
    }
  }

  function animateLayout() {
    if (!window.Flip) return;
    const flipState = Flip.getState(".time-card, .activity-panel, .investment-panel, .mode-panel");
    requestAnimationFrame(() => Flip.from(flipState, { duration: .42, ease: "power2.inOut", stagger: .015, absolute: false }));
  }

  function applyFocusState(active, animate = false) {
    if (animate) animateLayout();
    if (active) closeFocusSummary();
    document.body.classList.toggle("is-focusing", Boolean(active));
    syncScoreChartTheme(active);
    $("#idle-mode-view").hidden = Boolean(active);
    $("#active-mode-view").hidden = !active;
    $("#focus-investment-view").hidden = Boolean(active);
    $("#focus-comparison-view").hidden = !active;
    $("#home-state-note").textContent = active ? "专注中，保持当前上下文" : "准备开始下一段专注";
    if (!active) {
      removeSecondTask("focus");
      removeSecondTask("focusComparison");
      state.focusMessageIndex = null;
      $("#focus-timer").textContent = "00:00:00";
      const track = $("#end-focus");
      const thumb = track?.querySelector(".drag-thumb");
      if (track && thumb && window.gsap) {
        gsap.set(thumb, { x: 0 });
        setDragProgress(track, thumb);
        track.classList.remove("armed");
      }
      return;
    }
    renderFocusComparison(active);
    $("#focus-subject").textContent = `${active.subject} · 专注`;
    $("#focus-start").textContent = new Date(active.started_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const tick = (now) => {
      const elapsed = Math.max(0, Math.floor((now - Date.parse(active.started_at)) / 1000));
      $("#focus-timer").textContent = formatSeconds(elapsed);
      $("#focus-window").textContent = "持续计时 · 不设上限";
    };
    setSecondTask("focus", tick);
    initDragEnd();
  }

  function dashboardSignature(data) {
    const windowSignature = (value) => [value?.start, value?.end, value?.total_seconds];
    const active = data.focus?.active;
    return JSON.stringify({
      active: active ? [active.id, active.subject, active.started_at, active.status] : null,
      recent: (data.focus?.recent || []).map((item) => [item.id, item.status, item.ended_at]),
      scores: (data.score_history || []).map((item) => [item.id, item.subject, item.exam_date, item.score, item.target]),
      modes: (data.focus_modes || []).map((item) => [item.id, item.subject]),
      windows: [windowSignature(data.windows?.morning), windowSignature(data.windows?.library)],
      exam: data.exam?.date,
      day: String(data.now || "").slice(0, 10),
      heatmap: data.heatmap,
      heatmapVisibleHours: data.heatmap_visible_hours,
    });
  }

  function applyDashboard(data) {
    state.dashboard = data;
    state.dashboardFetchedAt = Date.now();
    state.dashboardSignature = dashboardSignature(data);
    renderStatus(data); renderClock(); renderWindows(data); renderTicker(data.scores); renderModes(data.focus_modes); renderHeatmap(data.heatmap, data.heatmap_visible_hours); renderScoreChart(data.score_history); renderFocusInvestment(data.focus_investment, data.focus.active); renderGuestSummary(data);
    $("#today-date")?.replaceChildren(document.createTextNode(new Date().toLocaleDateString("zh-CN", { weekday: "long", year: "numeric", month: "2-digit", day: "2-digit" })));
    applyFocusState(data.focus.active, false);
  }

  async function loadDashboard() {
    applyDashboard(await api("/api/dashboard"));
  }

  async function syncDashboard() {
    if (document.body.dataset.page === "settings" || document.visibilityState !== "visible" || state.syncing) return;
    state.syncing = true;
    try {
      const data = await api("/api/dashboard");
      if (dashboardSignature(data) !== state.dashboardSignature) applyDashboard(data);
      else {
        state.dashboard.focus_investment = data.focus_investment;
        state.dashboardFetchedAt = Date.now();
      }
    } catch (error) {
      console.warn("dashboard_sync_failed", error);
    } finally {
      state.syncing = false;
    }
  }

  function startDashboardSync() {
    window.clearInterval(state.syncTimer);
    if (document.body.dataset.page !== "settings") state.syncTimer = window.setInterval(syncDashboard, 500);
  }

  async function endFocus() {
    const active = state.dashboard?.focus?.active;
    if (!active) return false;
    try {
      const result = await api("/api/focus/end", { method: "POST", body: JSON.stringify({ session_id: active.id }) });
      await loadDashboard();
      showFocusSummary(result.session, state.dashboard?.focus?.today || []);
      showToast("本段专注已结束");
      return true;
    } catch (error) { showToast(error.message); }
    return false;
  }

  function initDragEnd() {
    const track = $("#end-focus");
    if (!track || !window.gsap || !window.Draggable || track.dataset.bound) return;
    const thumb = track.querySelector(".drag-thumb");
    track.dataset.bound = "1";
    const drag = Draggable.create(thumb, {
      type: "x",
      bounds: track,
      onDrag() { setDragProgress(track, thumb); },
      onRelease() {
        const { max, ratio } = setDragProgress(track, thumb);
        if (ratio >= .82) {
          track.classList.add("armed");
          gsap.to(thumb, { x: max, duration: .48, ease: "elastic.out(1, .55)", onComplete: () => commitFocusEnd(track, thumb) });
        } else {
          gsap.to(thumb, { x: 0, duration: .58, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
        }
      }
    })[0];
    thumb.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        const max = Math.max(1, track.clientWidth - thumb.offsetWidth - 4);
        gsap.to(thumb, { x: max, duration: .48, ease: "elastic.out(1, .55)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => commitFocusEnd(track, thumb) });
      }
    });
    drag.update();
  }

  async function commitFocusEnd(track, thumb) {
    if (state.ending) return;
    state.ending = true;
    track.classList.add("armed");
    const success = await endFocus();
    if (!success) {
      gsap.to(thumb, { x: 0, duration: .62, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
    }
    state.ending = false;
  }

  async function loadSettings() {
    const [settings, scores] = await Promise.all([api("/api/settings"), api("/api/scores")]);
    Object.entries(settings.settings).forEach(([key, value]) => { const input = document.querySelector(`[name="${key}"]`); if (input) input.value = value; });
    const visibleHours = new Set(String(settings.settings.heatmap_visible_hours || "").split(","));
    document.querySelectorAll("[data-heat-hour]").forEach((input) => { input.checked = visibleHours.has(input.dataset.heatHour); });
    renderScores(scores.scores.map((item) => ({ ...item, gap: item.target - item.score, completion: item.score / item.target })), "#settings-scores");
  }

  function openQuickScore() {
    const modal = $("#quick-score-modal");
    if (!modal || modal.open) return;
    state.quickScoreReturnFocus = document.activeElement;
    const dateInput = $("#quick-score-date");
    if (dateInput && !dateInput.value) {
      const now = new Date();
      dateInput.value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    }
    modal.showModal();
    requestAnimationFrame(() => $("#quick-score-subject")?.focus());
  }

  function closeQuickScore() {
    const modal = $("#quick-score-modal");
    if (modal?.open) modal.close();
  }

  async function submitScoreForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api("/api/scores", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      form.reset();
      if (form.id === "quick-score-form") closeQuickScore();
      if (document.body.dataset.page === "settings") await loadSettings();
      else await loadDashboard();
      showToast("成绩已添加");
    } catch (error) { showToast(error.message); }
  }

  function bindQuickScore() {
    const modal = $("#quick-score-modal");
    if (!modal) return;
    $("#open-quick-score")?.addEventListener("click", openQuickScore);
    $("#close-quick-score")?.addEventListener("click", closeQuickScore);
    $("#quick-score-form")?.addEventListener("submit", submitScoreForm);
    modal?.addEventListener("close", () => state.quickScoreReturnFocus?.focus?.());
    modal?.addEventListener("click", (event) => {
      const bounds = modal.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeQuickScore();
    });
    document.addEventListener("keydown", (event) => {
      if (event.ctrlKey && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "n") {
        event.preventDefault();
        openQuickScore();
      }
    });
  }

  function bindSettingsForms() {
    $("#settings-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const selectedHours = [...document.querySelectorAll("[data-heat-hour]:checked")].map((input) => input.dataset.heatHour);
      if (!selectedHours.length) {
        showToast("热度图至少保留一个时段");
        return;
      }
      $("#heatmap-visible-hours").value = selectedHours.join(",");
      try {
        await api("/api/settings", { method: "PATCH", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
        showToast("设置已保存");
      } catch (error) { showToast(error.message); }
    });
    document.querySelector('[data-form="score"]')?.addEventListener("submit", submitScoreForm);
  }

  document.addEventListener("DOMContentLoaded", async () => {
    startAlignedSecondClock();
    ensureWakeLock();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible") return;
      ensureWakeLock();
      runSecondTasks(Date.now());
      syncDashboard();
    });
    $("#close-focus-summary")?.addEventListener("click", closeFocusSummary);
    bindQuickScore();
    bindSettingsForms();
    try {
      if (document.body.dataset.page === "settings") await loadSettings();
      else await loadDashboard();
    } catch (error) { showToast(error.message); }
    startDashboardSync();
  });
})();
