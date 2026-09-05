(() => {
  const state = { dashboard: null, dashboardFetchedAt: null, dashboardSignature: null, scoreChart: null, summaryCharts: [], secondTasks: new Map(), secondTimer: null, syncTimer: null, heartbeatTimer: null, heartbeatFailureTimer: null, heartbeatFailureSince: null, heartbeatInFlight: false, syncLost: false, foregroundContinuous: true, focusRecoverySessionId: null, friendTickerTimer: null, syncing: false, wakeLock: null, wakeRetry: null, starting: false, ending: false, pausing: false, locking: false, settling: false, confirmResolver: null, investmentRange: "week", scoreEntry: { subjects: [], selection: { subject: null, hundreds: 0, tens: 0, ones: 0 } } };
  const DAILY_TARGET_SECONDS = 7 * 3600;
  const appFontFamily = '"Source Han Serif SC Medium", "Source Han Serif SC", "思源宋体 SC", "Noto Serif SC", "Noto Serif CJK SC", "Songti SC", "STSong", serif';
  const themePalettes = {
    idle: ["#d66c58", "#b25647", "#dd9073", "#97483e", "#c27758", "#e4a994", "#835144", "#d28a72"],
    focus: ["#8067b3", "#685295", "#9a86c3", "#59447f", "#8b77aa", "#b4a5d1", "#706186", "#9f8db8"],
    settled: ["#6f8f78", "#557763", "#8aa891", "#486653", "#789c81", "#abc0ad", "#5d8068", "#94ae99"],
  };
  const $ = (selector) => document.querySelector(selector);
  const getThemePalette = (active = Boolean(state.dashboard?.focus?.active)) => themePalettes[active ? "focus" : state.dashboard?.daily_settlement ? "settled" : "idle"];
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
  const formatSignedSeconds = (seconds) => `${seconds > 0 ? "+" : seconds < 0 ? "−" : "±"}${formatSeconds(Math.abs(seconds))}`;
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));

  function focusElapsedSeconds(session, now = Date.now()) {
    if (!session?.started_at) return 0;
    const end = session.ended_at ? Date.parse(session.ended_at) : session.paused_at ? Date.parse(session.paused_at) : now;
    return Math.max(0, Math.floor((end - Date.parse(session.started_at)) / 1000) - Number(session.paused_seconds || 0));
  }

  function activeExtraSeconds(active, fetchedAt, now) {
    return active && !active.paused_at ? Math.max(0, Math.floor((now - fetchedAt) / 1000)) : 0;
  }

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

  function requestConfirmation({ title = "请确认操作", message = "此操作无法撤销。", label = "确认", tone = "primary" } = {}) {
    const modal = $("#confirm-action-modal");
    if (!modal) return Promise.resolve(window.confirm(message));
    if (state.confirmResolver) resolveConfirmation(false);
    $("#confirm-action-title").textContent = title;
    $("#confirm-action-message").textContent = message;
    const submit = $("#confirm-action-submit");
    submit.textContent = label;
    submit.classList.remove("ui-button--primary", "ui-button--danger");
    submit.classList.add(tone === "danger" ? "ui-button--danger" : "ui-button--primary");
    modal.showModal();
    return new Promise((resolve) => { state.confirmResolver = resolve; });
  }

  function resolveConfirmation(confirmed) {
    const resolve = state.confirmResolver;
    state.confirmResolver = null;
    $("#confirm-action-modal")?.close();
    resolve?.(confirmed);
  }

  function bindConfirmations() {
    const modal = $("#confirm-action-modal");
    if (modal) {
      $("#confirm-action-cancel")?.addEventListener("click", () => resolveConfirmation(false));
      $("#confirm-action-submit")?.addEventListener("click", () => resolveConfirmation(true));
      modal.addEventListener("cancel", (event) => { event.preventDefault(); resolveConfirmation(false); });
      modal.addEventListener("close", () => { if (state.confirmResolver) resolveConfirmation(false); });
    }
    document.querySelectorAll("form[data-confirm]").forEach((form) => form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const confirmed = await requestConfirmation({ title: form.dataset.confirmTitle, message: form.dataset.confirmMessage, label: form.dataset.confirmLabel, tone: form.dataset.confirmTone });
      if (confirmed) HTMLFormElement.prototype.submit.call(form);
    }));
  }

  function bindButtonMotion() {
    document.addEventListener("pointerdown", (event) => {
      const button = event.target.closest("button, .ui-button");
      if (!button || button.disabled) return;
      button.classList.remove("button-pressed");
      void button.offsetWidth;
      button.classList.add("button-pressed");
      window.setTimeout(() => button.classList.remove("button-pressed"), 260);
    });
  }

  async function copyText(value) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const input = document.createElement("textarea");
    input.value = value;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    document.execCommand("copy");
    input.remove();
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
      const todaySeconds = Number(today.seconds || 0) + activeExtraSeconds(active, todayFetchedAt, now);
      $("#today-study").textContent = `${formatSeconds(todaySeconds)} / 07:00`;
      $("#today-progress").textContent = `完成度 ${Math.min(100, Math.round((todaySeconds / DAILY_TARGET_SECONDS) * 100))}%`;
      $("#focus-today")?.replaceChildren(document.createTextNode(`${formatSeconds(todaySeconds)} / 07:00`));
      $("#guest-today-total")?.replaceChildren(document.createTextNode(formatSeconds(todaySeconds)));
      $("#guest-today-target")?.replaceChildren(document.createTextNode(`7 小时目标 · ${Math.min(100, Math.round((todaySeconds / DAILY_TARGET_SECONDS) * 100))}%`));
    };
    setSecondTask("status", tick);
    $("#current-state").textContent = active ? `${active.paused_at ? "已暂停" : "专注中"} · ${active.subject}` : "准备学习";
    $("#state-dot").classList.toggle("state-dot-active", Boolean(active));
  }

  function renderFriendDiffBoard(friends) {
    const board = $("#friend-diff-board");
    if (!board) return;
    window.clearInterval(state.friendTickerTimer);
    state.friendTickerTimer = null;
    if (!friends?.length) {
      board.hidden = true;
      board.replaceChildren();
      return;
    }
    board.hidden = false;
    const rows = friends.map((friend) => {
      const delta = Number(friend.delta_seconds || 0);
      const relation = delta > 0 ? `领先 ${formatSignedSeconds(delta)}` : delta < 0 ? `落后 ${formatSignedSeconds(Math.abs(delta))}` : "持平 ±00:00:00";
      const tone = delta > 0 ? "ahead" : delta < 0 ? "behind" : "";
      return `<div class="friend-diff-row"><span>好友 · ${escapeHtml(friend.username)}</span><b>${formatSeconds(friend.today_seconds)}</b><em class="${tone}">${relation}</em></div>`;
    }).join("");
    board.innerHTML = `<div class="friend-diff-head"><span>好友 diff</span><small>今日累计 · 与你相比</small></div><div class="friend-diff-window"><div class="friend-diff-track">${rows}</div></div>`;
    const track = board.querySelector(".friend-diff-track");
    let index = 0;
    state.friendTickerTimer = window.setInterval(() => {
      index = (index + 1) % friends.length;
      track.style.transform = `translateY(-${index * 38}px)`;
    }, 4000);
  }

  function renderClock() {
    setSecondTask("clock", (now) => $("#current-time")?.replaceChildren(document.createTextNode(new Date(now).toLocaleTimeString("zh-CN", { hour12: false }))));
  }

  function clockMinutes(value) {
    const [hours, minutes] = String(value || "00:00").split(":").map(Number);
    return hours * 60 + minutes;
  }

  function workWindowProgress(now, windows) {
    const current = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
    const periods = [windows?.morning, windows?.library].filter(Boolean).map((windowValue) => [clockMinutes(windowValue.start) * 60, clockMinutes(windowValue.end) * 60]);
    const total = periods.reduce((sum, [start, end]) => sum + Math.max(0, end - start), 0);
    const elapsed = periods.reduce((sum, [start, end]) => sum + Math.max(0, Math.min(current, end) - start), 0);
    return total ? Math.max(0, Math.min(1, elapsed / total)) : 0;
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
    const segments = (sessions || []).flatMap((session) => (session.segments?.length ? session.segments : [session]).map((segment) => ({ ...segment, subject: session.subject })));
    target.innerHTML = segments.map((segment) => {
      const sessionStart = Math.max(start, dateMinutes(segment.started_at));
      const sessionEnd = Math.min(end, segment.ended_at ? dateMinutes(segment.ended_at) : dateMinutes(Date.now()));
      if (sessionEnd <= sessionStart) return "";
      const left = ((sessionStart - start) / total) * 100;
      const width = ((sessionEnd - sessionStart) / total) * 100;
      const edgeClass = `${sessionStart <= start ? " at-start" : ""}${sessionEnd >= end ? " at-end" : ""}`;
      return `<span class="${edgeClass.trim()}" style="left:${left}%;width:${width}%" title="${escapeHtml(segment.subject)} · ${Math.max(1, Math.round(sessionEnd - sessionStart))} 分钟"></span>`;
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
      const percent = Math.max(0, Math.min(100, (seconds / DAILY_TARGET_SECONDS) * 100));
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
      const extraSeconds = activeExtraSeconds(active, fetchedAt, now);
      const currentSeconds = Number(baseline.current_seconds || 0) + extraSeconds;
      const recordedDayCount = Number(baseline.recorded_day_count || 0);
      const previousRecordedDayCount = Number(baseline.previous_recorded_day_count || 0);
      const dailyAverage = Math.floor(currentSeconds / Math.max(1, recordedDayCount));
      const previousAverage = Number(baseline.previous_daily_average_seconds || 0);
      const trendSeconds = dailyAverage - previousAverage;
      const trend = $("#investment-trend");
      $("#investment-daily-average").textContent = formatSeconds(dailyAverage);
      trend.className = `investment-trend${trendSeconds > 0 ? " up" : trendSeconds < 0 ? " down" : ""}`;
      trend.textContent = trendSeconds > 0 ? `↑ ${formatSeconds(trendSeconds)}` : trendSeconds < 0 ? `↓ ${formatSeconds(Math.abs(trendSeconds))}` : previousRecordedDayCount ? `较前 ${previousRecordedDayCount} 个记录日持平` : "暂无前序记录";
      renderTargetStack("#investment-average-stack", dailyAverage);

      const allTime = state.investmentRange === "all";
      const rangeSeconds = Number(allTime ? baseline.all_time_seconds : baseline.current_seconds || 0) + extraSeconds;
      const rangeSubjects = allTime ? baseline.all_time_subjects : baseline.subjects;
      $("#investment-week-total").textContent = formatSeconds(rangeSeconds);
      $("#investment-range-note").textContent = allTime ? "全部记录累计" : recordedDayCount ? `近 ${recordedDayCount} 个记录日累计` : "暂无记录日";
      renderSubjectStack("#investment-subject-stack", "#investment-subject-legend", subjectsWithActiveTime(rangeSubjects, extraSeconds), rangeSeconds);

      const todaySeconds = Number(baseline.today_seconds || 0) + extraSeconds;
      $("#investment-today-total").textContent = formatSeconds(todaySeconds);
      $("#investment-today-percent").textContent = `${Math.round((todaySeconds / DAILY_TARGET_SECONDS) * 1000) / 10}%`;
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
      return;
    }
    const tick = (now) => {
      const investment = state.dashboard?.focus_investment || {};
      const fetchedAt = state.dashboardFetchedAt || now;
      const extraSeconds = activeExtraSeconds(active, fetchedAt, now);
      const todaySeconds = Number(investment.today_seconds || 0) + extraSeconds;
      const yesterdayTotal = Number(investment.yesterday_seconds || 0);
      const yesterdayBaseline = Math.round(yesterdayTotal * workWindowProgress(new Date(now), state.dashboard?.windows));
      const delta = todaySeconds - yesterdayBaseline;
      view.classList.toggle("ahead", delta > 0);
      view.classList.toggle("behind", delta < 0);
      $("#focus-compare-today").textContent = formatSeconds(todaySeconds);
      $("#focus-compare-trend").textContent = delta > 0 ? `提前 +${formatSeconds(delta)}` : delta < 0 ? `落后 −${formatSeconds(Math.abs(delta))}` : "持平 ±00:00:00";
      const logRatio = Math.min(1, Math.log1p(Math.abs(delta) / 60) / Math.log1p(480));
      const diffWidth = logRatio * 50;
      const diffFill = $("#focus-diff-fill");
      diffFill.style.left = `${delta < 0 ? 50 - diffWidth : 50}%`;
      diffFill.style.width = `${diffWidth}%`;
      $("#focus-diff-track").setAttribute("aria-label", `今日与昨日工作窗折算基线相差 ${delta >= 0 ? "+" : "-"}${formatSeconds(Math.abs(delta))}`);
      renderFocusLeaderboard(state.dashboard?.focus_leaderboard, extraSeconds);
    };
    setSecondTask("focusComparison", tick);
  }

  function renderFocusLeaderboard(leaderboard, activeExtra = 0) {
    const rowsTarget = $("#focus-leaderboard-rows");
    if (!rowsTarget) return;
    const sourceEntries = leaderboard?.entries || [];
    const todayKey = leaderboard?.today?.date || new Date().toLocaleDateString("en-CA");
    const entries = sourceEntries.map((entry) => ({ ...entry, seconds: Number(entry.seconds || 0) }));
    let today = entries.find((entry) => entry.date === todayKey);
    if (today) today.seconds += activeExtra;
    else if (activeExtra || Number(leaderboard?.today?.seconds || 0)) {
      today = { date: todayKey, seconds: Number(leaderboard?.today?.seconds || 0) + activeExtra };
      entries.push(today);
    }
    entries.sort((left, right) => right.seconds - left.seconds || String(right.date).localeCompare(String(left.date)));
    entries.forEach((entry) => {
      const higher = entries.filter((other) => other.seconds > entry.seconds).map((other) => other.seconds);
      entry.rank = higher.length + 1;
      const previous = higher.length ? Math.min(...higher) : null;
      entry.gap_to_previous_seconds = previous === null ? null : previous - entry.seconds;
    });
    const dayCount = entries.length;
    today = entries.find((entry) => entry.date === todayKey);
    const summary = $("#focus-leaderboard-summary");
    const percentile = $("#focus-leaderboard-percentile");
    const dayCountTarget = $("#focus-leaderboard-day-count");
    const chips = $("#focus-leaderboard-chips");
    if (!today || !today.seconds) {
      rowsTarget.innerHTML = '<div class="loading-row">今天产生有效专注后会进入榜单。</div>';
      if (summary) summary.textContent = "今天尚未上榜";
      if (percentile) percentile.textContent = "--";
      if (dayCountTarget) dayCountTarget.textContent = `${dayCount} 个记录日`;
      if (chips) chips.replaceChildren();
      return;
    }
    const percent = Math.round((dayCount - today.rank + 1) / dayCount * 100);
    const gap = Number(today.gap_to_previous_seconds || 0);
    if (summary) summary.textContent = today.rank === 1 ? "今日暂列第 1 名" : `今日第 ${today.rank} 名 · 距上一名 ${formatSeconds(gap)}`;
    if (percentile) percentile.textContent = `${percent}%`;
    if (dayCountTarget) dayCountTarget.textContent = `${dayCount} 个记录日`;
    if (chips) {
      const filled = Math.max(1, Math.ceil(percent / 10));
      chips.innerHTML = Array.from({ length: 10 }, (_value, index) => `<i class="${index < filled ? "is-filled" : ""}"></i>`).join("");
    }
    const visible = entries.slice(0, 4);
    if (!visible.some((entry) => entry.date === today.date)) visible.push(today);
    visible.sort((left, right) => left.rank - right.rank || String(right.date).localeCompare(String(left.date)));
    rowsTarget.innerHTML = visible.map((entry) => {
      const isToday = entry.date === today.date;
      const gapText = entry.rank === 1 ? "榜首" : `差 ${formatSeconds(Number(entry.gap_to_previous_seconds || 0))}`;
      return `<div class="focus-leaderboard-row${isToday ? " is-today" : ""}"><b>#${entry.rank}</b><time>${isToday ? "今天" : escapeHtml(String(entry.date).slice(5).replace("-", "/"))}</time><strong>${formatSeconds(entry.seconds)}</strong><small>${gapText}</small></div>`;
    }).join("");
  }

  function renderGuestSummary(data) {
    const totalTarget = $("#guest-today-total");
    if (!totalTarget) return;
    const today = data.today_focus || { seconds: 0, count: 0 };
    totalTarget.textContent = formatSeconds(today.seconds);
    $("#guest-today-target").textContent = `7 小时目标 · ${Math.min(100, Math.round((today.seconds / DAILY_TARGET_SECONDS) * 100))}%`;
    $("#guest-today-count").textContent = String(today.count || 0);
    $("#guest-today-state").textContent = data.focus?.active ? (data.focus.active.paused_at ? "已暂停" : "专注中") : "空闲";
    const totals = new Map();
    (data.focus?.today || []).forEach((item) => {
      totals.set(item.subject, (totals.get(item.subject) || 0) + Number(item.effective_seconds || 0));
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
    const duration = Number(session.effective_seconds ?? focusElapsedSeconds(session));
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
      const seconds = Number(item.effective_seconds ?? focusElapsedSeconds(item));
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

  function renderModes(modes = []) {
    const target = $("#focus-modes");
    if (!target) return;
    target.innerHTML = modes.map((item) => {
      const label = item.label || `${item.subject} · ${item.name}`;
      return `<div class="mode"><div class="drag-launch" data-focus-item-id="${Number(item.id)}" data-focus-item="${escapeHtml(label)}" data-mode="专注" data-duration="0"><div class="drag-fill"></div><span class="drag-label">${escapeHtml(label)}</span><span class="drag-thumb" role="button" tabindex="0" aria-label="滑动启动 ${escapeHtml(label)}">→</span></div></div>`;
    }).join("");
    initDragLaunchers();
  }

  function renderDailySettlement(data) {
    const banner = $("#daily-settlement-banner");
    const achievement = $("#daily-achievement");
    const modes = $("#focus-modes");
    const settlement = data.daily_settlement;
    if (banner) banner.hidden = !data.can_settle_today;
    if (modes) modes.hidden = Boolean(settlement);
    if (!achievement) return;
    achievement.hidden = !settlement;
    if (!settlement) {
      achievement.replaceChildren();
      return;
    }
    const total = Number(settlement.total_seconds || 0);
    const target = Number(settlement.target_seconds || DAILY_TARGET_SECONDS);
    const completion = Math.min(100, Math.round((total / target) * 100));
    const delta = Number(settlement.delta_seconds || 0);
    const evaluation = completion >= 100 ? "目标达成" : completion >= 80 ? "接近目标" : completion >= 50 ? "稳步推进" : "保留节奏";
    const deltaText = delta > 0 ? `比昨天多 ${formatSeconds(delta)}` : delta < 0 ? `比昨天少 ${formatSeconds(Math.abs(delta))}` : "与昨天持平";
    const subject = settlement.top_subject ? `${escapeHtml(settlement.top_subject)} · ${formatSeconds(settlement.top_subject_seconds || 0)}` : "今天还没有专注记录";
    const rank = data.focus_leaderboard?.today;
    const rankText = rank?.rank ? rank.rank === 1 ? `第 1 名 · ${Number(rank.percentile || 100)}% 分位` : `第 ${rank.rank} 名 · 距上一名 ${formatSeconds(Number(rank.gap_to_previous_seconds || 0))}` : "今天暂无有效专注排名";
    achievement.innerHTML = `<div class="section-heading"><h2>当日成就</h2><span>已结算 · ${escapeHtml(settlement.settlement_date)}</span></div><div class="achievement-total"><span>今日有效专注</span><strong>${formatSeconds(total)}</strong><b>${completion}% · ${evaluation}</b></div><div class="achievement-list"><div><span>昨日差值</span><b class="${delta >= 0 ? "good" : "bad"}">${escapeHtml(deltaText)}</b></div><div><span>历日排名</span><b>${escapeHtml(rankText)}</b></div><div><span>专注次数</span><b>${Number(settlement.session_count || 0)} 次</b></div><div><span>主要投入</span><b>${subject}</b></div></div>`;
  }

  function bindInvestmentRange() {
    document.querySelectorAll("[data-investment-range]").forEach((button) => button.addEventListener("click", () => {
      state.investmentRange = button.dataset.investmentRange === "all" ? "all" : "week";
      document.querySelectorAll("[data-investment-range]").forEach((item) => {
        const selected = item.dataset.investmentRange === state.investmentRange;
        item.classList.toggle("is-active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
      if (state.dashboard) renderFocusInvestment(state.dashboard.focus_investment, state.dashboard.focus.active);
    }));
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
      const session = await api("/api/focus/start", { method: "POST", body: JSON.stringify({ focus_item_id: Number(track.dataset.focusItemId), mode: "专注", planned_minutes: 0, client_token: createClientToken() }) });
      const today = state.dashboard?.focus?.today || [];
      state.dashboard = { ...state.dashboard, focus: { ...(state.dashboard?.focus || {}), active: session.session, today: [...today.filter((item) => item.id !== session.session.id), session.session] } };
      state.dashboardFetchedAt = Date.now();
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

  function updatePauseControl(active) {
    const button = $("#toggle-focus-pause");
    if (!button) return;
    const paused = Boolean(active?.paused_at);
    button.classList.toggle("is-paused", paused);
    button.title = paused ? "继续专注" : "暂停专注";
    button.setAttribute("aria-label", button.title);
    $("#focus-pause-icon").textContent = paused ? "继续" : "暂停";
  }

  async function toggleFocusPause() {
    const active = state.dashboard?.focus?.active;
    if (!active || state.pausing) return;
    state.pausing = true;
    const button = $("#toggle-focus-pause");
    if (button) button.disabled = true;
    try {
      const paused = !active.paused_at;
      await api("/api/focus/pause", { method: "POST", body: JSON.stringify({ session_id: active.id, paused }) });
      await loadDashboard();
      showToast(paused ? "专注已暂停" : "继续专注");
    } catch (error) { showToast(error.message); }
    finally {
      state.pausing = false;
      if (button) button.disabled = false;
    }
  }

  function updateFocusLockControl(active) {
    const status = $("#focus-trust-state");
    const track = $("#lock-focus");
    if (!status || !track) return;
    const trusted = active?.trusted !== false;
    const locked = Boolean(active?.focus_locked);
    status.classList.toggle("untrusted", !trusted && !state.syncLost);
    status.classList.toggle("sync-lost", state.syncLost);
    status.querySelector("b").textContent = state.syncLost ? "失去同步" : trusted ? "受信" : "非受信";
    track.classList.toggle("locked", locked);
    track.querySelector(".drag-label").textContent = locked ? "专注已锁定" : "锁定专注";
    const thumb = track.querySelector(".drag-thumb");
    if (!window.gsap || !thumb) return;
    const x = locked ? Math.max(1, track.clientWidth - thumb.offsetWidth - 4) : 0;
    gsap.set(thumb, { x });
    setDragProgress(track, thumb);
    track.classList.toggle("locked", locked);
  }

  function applyFocusState(active, animate = false) {
    if (animate) animateLayout();
    if (active) {
      state.focusRecoverySessionId = active.id;
      closeFocusSummary();
    } else if (!state.heartbeatFailureSince) {
      state.focusRecoverySessionId = null;
    }
    document.body.classList.toggle("is-focusing", Boolean(active));
    document.body.classList.toggle("is-paused", Boolean(active?.paused_at));
    syncScoreChartTheme(active);
    $("#idle-mode-view").hidden = Boolean(active);
    $("#active-mode-view").hidden = !active;
    $("#focus-investment-view").hidden = Boolean(active);
    $("#focus-comparison-view").hidden = !active;
    $("#home-state-note").textContent = active ? "专注中，保持当前上下文" : "准备开始下一段专注";
    if (!active) {
      removeSecondTask("focus");
      removeSecondTask("focusComparison");
      $("#focus-timer").textContent = "00:00:00";
      updatePauseControl(null);
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
    updatePauseControl(active);
    updateFocusLockControl(active);
    $("#focus-subject").textContent = `${active.subject} · 专注`;
    $("#focus-start").textContent = new Date(active.started_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const tick = (now) => {
      const elapsed = focusElapsedSeconds(active, now);
      $("#focus-timer").textContent = formatSeconds(elapsed);
      $("#focus-window").textContent = "\u00a0";
    };
    setSecondTask("focus", tick);
    initDragEnd();
    initDragLock();
  }

  function dashboardSignature(data) {
    const windowSignature = (value) => [value?.start, value?.end, value?.total_seconds];
    const active = data.focus?.active;
    return JSON.stringify({
      active: active ? [active.id, active.subject, active.started_at, active.status, active.paused_at, active.paused_seconds, active.focus_locked, active.trusted] : null,
      recent: (data.focus?.recent || []).map((item) => [item.id, item.status, item.ended_at]),
      scores: (data.score_history || []).map((item) => [item.id, item.subject, item.exam_date, item.score, item.target]),
      modes: (data.focus_items || data.focus_modes || []).map((item) => [item.id, item.label || item.subject, item.sort_order]),
      messages: (data.focus_messages || []).map((item) => [item.category, item.text]),
      settlement: data.daily_settlement ? [data.daily_settlement.id, data.daily_settlement.settlement_date, data.daily_settlement.total_seconds] : null,
      canSettle: Boolean(data.can_settle_today),
      windows: [windowSignature(data.windows?.morning), windowSignature(data.windows?.library)],
      exam: data.exam?.date,
      day: String(data.now || "").slice(0, 10),
      heatmap: data.heatmap,
      heatmapVisibleHours: data.heatmap_visible_hours,
      friends: (data.friends || []).map((friend) => [friend.id, friend.today_seconds, friend.delta_seconds]),
    });
  }

  function applyDashboard(data) {
    state.dashboard = data;
    state.dashboardFetchedAt = Date.now();
    state.dashboardSignature = dashboardSignature(data);
    document.body.classList.toggle("is-settled", Boolean(data.daily_settlement));
    renderStatus(data); renderClock(); renderWindows(data); renderTicker(data.scores); renderModes(data.focus_items || data.focus_modes); renderHeatmap(data.heatmap, data.heatmap_visible_hours); renderScoreChart(data.score_history); renderFocusInvestment(data.focus_investment, data.focus.active); renderFriendDiffBoard(data.friends); renderGuestSummary(data);
    renderDailySettlement(data);
    $("#today-date")?.replaceChildren(document.createTextNode(new Date().toLocaleDateString("zh-CN", { weekday: "long", year: "numeric", month: "2-digit", day: "2-digit" })));
    applyFocusState(data.focus.active, false);
  }

  async function loadDashboard() {
    applyDashboard(await api("/api/dashboard"));
  }

  async function syncDashboard() {
    if (document.body.dataset.page !== "home" || document.visibilityState !== "visible" || state.syncing) return;
    state.syncing = true;
    try {
      const data = await api("/api/dashboard");
      if (dashboardSignature(data) !== state.dashboardSignature) applyDashboard(data);
      else {
        state.dashboard.focus_investment = data.focus_investment;
        state.dashboard.focus_leaderboard = data.focus_leaderboard;
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
    if (document.body.dataset.page === "home") state.syncTimer = window.setInterval(syncDashboard, 500);
  }

  function setSyncLost(lost) {
    state.syncLost = lost;
    const warning = $("#sync-warning");
    if (warning) warning.hidden = !lost;
    const dot = $("#state-dot");
    dot?.classList.toggle("state-dot-offline", lost);
    if (dot) {
      const label = lost ? "连接异常，正在重连" : "连接正常";
      dot.title = label;
      dot.setAttribute("aria-label", label);
    }
    updateFocusLockControl(state.dashboard?.focus?.active);
  }

  function markHeartbeatFailure() {
    if (state.heartbeatFailureSince) return;
    state.heartbeatFailureSince = Date.now();
    if (state.focusRecoverySessionId == null) state.focusRecoverySessionId = state.dashboard?.focus?.active?.id ?? null;
    window.clearTimeout(state.heartbeatFailureTimer);
    state.heartbeatFailureTimer = window.setTimeout(() => {
      if (state.heartbeatFailureSince) setSyncLost(true);
    }, 10000);
  }

  function markHeartbeatSuccess() {
    state.heartbeatFailureSince = null;
    window.clearTimeout(state.heartbeatFailureTimer);
    setSyncLost(false);
    state.foregroundContinuous = document.visibilityState === "visible";
  }

  async function sendForegroundHeartbeat(allowHidden = false) {
    if ((!allowHidden && document.visibilityState !== "visible") || state.heartbeatInFlight) return;
    state.heartbeatInFlight = true;
    const sessionId = state.focusRecoverySessionId ?? state.dashboard?.focus?.active?.id ?? null;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 2000);
    try {
      const response = await fetch("/api/focus/heartbeat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          allow_recovery: Boolean(sessionId) && document.visibilityState === "visible" && state.foregroundContinuous,
        }),
        keepalive: true,
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`heartbeat_${response.status}`);
      const result = await response.json();
      markHeartbeatSuccess();
      if (result.recovered) {
        await loadDashboard();
        showToast("连接已恢复，继续以受信模式专注");
      } else if (sessionId && result.status === "completed") {
        state.focusRecoverySessionId = null;
        syncDashboard();
      }
    } catch (_error) {
      markHeartbeatFailure();
    } finally {
      window.clearTimeout(timeout);
      state.heartbeatInFlight = false;
    }
  }

  function startForegroundHeartbeat() {
    window.clearInterval(state.heartbeatTimer);
    if (document.body.dataset.page === "account") return;
    sendForegroundHeartbeat();
    state.heartbeatTimer = window.setInterval(sendForegroundHeartbeat, 500);
  }

  async function endFocus() {
    const active = state.dashboard?.focus?.active;
    if (!active) return false;
    try {
      const result = await api("/api/focus/end", { method: "POST", body: JSON.stringify({ session_id: active.id }) });
      state.focusRecoverySessionId = null;
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

  async function commitDailySettlement(track, thumb) {
    if (state.settling || !state.dashboard?.can_settle_today) return;
    state.settling = true;
    track.classList.add("armed");
    try {
      await api("/api/daily-settlement", { method: "POST", body: "{}" });
      await loadDashboard();
      playSettlementFireworks();
      showToast("今日已结算");
    } catch (error) {
      gsap.to(thumb, { x: 0, duration: .62, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
      showToast(error.message);
    } finally {
      state.settling = false;
    }
  }

  function initDragSettlement() {
    const track = $("#settle-today");
    if (!track || !window.gsap || !window.Draggable || track.dataset.bound) return;
    const thumb = track.querySelector(".drag-thumb");
    track.dataset.bound = "1";
    const drag = Draggable.create(thumb, {
      type: "x",
      bounds: track,
      onPress() { if (state.settling) this.endDrag?.(); },
      onDrag() { setDragProgress(track, thumb); },
      onRelease() {
        const { max, ratio } = setDragProgress(track, thumb);
        if (ratio >= .82) {
          track.classList.add("armed");
          gsap.to(thumb, { x: max, duration: .42, ease: "power2.out", onComplete: () => commitDailySettlement(track, thumb) });
        } else {
          gsap.to(thumb, { x: 0, duration: .5, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
        }
      },
    })[0];
    thumb.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      const max = Math.max(1, track.clientWidth - thumb.offsetWidth - 4);
      gsap.to(thumb, { x: max, duration: .42, ease: "power2.out", onUpdate: () => setDragProgress(track, thumb), onComplete: () => commitDailySettlement(track, thumb) });
    });
    drag.update();
  }

  function playSettlementFireworks() {
    const canvas = $("#settlement-fireworks");
    if (!canvas || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const resize = () => {
      canvas.width = Math.floor(window.innerWidth * ratio);
      canvas.height = Math.floor(window.innerHeight * ratio);
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    resize();
    const colors = ["#6f8f78", "#b88b63", "#9a86c3", "#d7a45c"];
    const particles = [];
    const bursts = [
      { x: window.innerWidth * .28, y: window.innerHeight * .28, color: colors[0], at: 120 },
      { x: window.innerWidth * .58, y: window.innerHeight * .2, color: colors[1], at: 280 },
      { x: window.innerWidth * .78, y: window.innerHeight * .38, color: colors[2], at: 430 },
    ];
    let startedAt = performance.now();
    let frame;
    const launch = (burst) => {
      for (let index = 0; index < 28; index += 1) {
        const angle = (Math.PI * 2 * index) / 28 + Math.random() * .08;
        const speed = 1.8 + Math.random() * 2.8;
        particles.push({ x: burst.x, y: burst.y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed, life: 1, color: burst.color, size: 1 + Math.random() * 1.5 });
      }
    };
    const draw = (now) => {
      const elapsed = now - startedAt;
      context.clearRect(0, 0, window.innerWidth, window.innerHeight);
      bursts.filter((burst) => !burst.launched && elapsed >= burst.at).forEach((burst) => { burst.launched = true; launch(burst); });
      particles.forEach((particle) => {
        particle.x += particle.vx;
        particle.y += particle.vy;
        particle.vy += .035;
        particle.vx *= .988;
        particle.vy *= .988;
        particle.life -= .018;
        context.globalAlpha = Math.max(0, particle.life);
        context.fillStyle = particle.color;
        context.fillRect(particle.x, particle.y, particle.size, particle.size);
      });
      context.globalAlpha = 1;
      if (elapsed < 1800) frame = requestAnimationFrame(draw);
      else { context.clearRect(0, 0, window.innerWidth, window.innerHeight); window.removeEventListener("resize", resize); }
    };
    frame = requestAnimationFrame(draw);
    window.setTimeout(() => { if (frame) cancelAnimationFrame(frame); }, 2200);
  }

  function initDragLock() {
    const track = $("#lock-focus");
    if (!track || !window.gsap || !window.Draggable || track.dataset.bound) return;
    const thumb = track.querySelector(".drag-thumb");
    track.dataset.bound = "1";
    const drag = Draggable.create(thumb, {
      type: "x",
      bounds: track,
      onPress() { if (state.locking || state.dashboard?.focus?.active?.focus_locked) this.endDrag?.(); },
      onDrag() { setDragProgress(track, thumb); },
      onRelease() {
        const { max, ratio } = setDragProgress(track, thumb);
        if (ratio >= .82 && !state.dashboard?.focus?.active?.focus_locked) {
          track.classList.add("armed");
          gsap.to(thumb, { x: max, duration: .48, ease: "elastic.out(1, .55)", onComplete: () => commitFocusLock(track, thumb) });
        } else if (!state.dashboard?.focus?.active?.focus_locked) {
          gsap.to(thumb, { x: 0, duration: .58, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
        }
      }
    })[0];
    thumb.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && !state.dashboard?.focus?.active?.focus_locked) {
        event.preventDefault();
        const max = Math.max(1, track.clientWidth - thumb.offsetWidth - 4);
        gsap.to(thumb, { x: max, duration: .48, ease: "elastic.out(1, .55)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => commitFocusLock(track, thumb) });
      }
    });
    drag.update();
  }

  async function commitFocusLock(track, thumb) {
    const active = state.dashboard?.focus?.active;
    if (!active || state.locking || active.focus_locked) return;
    const confirmed = await requestConfirmation({ title: "锁定本段专注", message: "锁定后本段记录将标记为非受信，且不能恢复受信状态。确定继续？", label: "锁定专注", tone: "danger" });
    if (!confirmed) {
      gsap.to(thumb, { x: 0, duration: .62, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
      return;
    }
    state.locking = true;
    try {
      await api("/api/focus/lock", { method: "POST", body: JSON.stringify({ session_id: active.id }) });
      await loadDashboard();
      showToast("本段专注已锁定");
    } catch (error) {
      gsap.to(thumb, { x: 0, duration: .62, ease: "elastic.out(1, .58)", onUpdate: () => setDragProgress(track, thumb), onComplete: () => track.classList.remove("armed") });
      showToast(error.message);
    } finally {
      state.locking = false;
    }
  }

  async function loadSettings() {
    if (!$("#settings-form")) return;
    const [settings, scores] = await Promise.all([api("/api/settings"), api("/api/scores")]);
    Object.entries(settings.settings).forEach(([key, value]) => { const input = document.querySelector(`[name="${key}"]`); if (input) input.value = value; });
    const visibleHours = new Set(String(settings.settings.heatmap_visible_hours || "").split(","));
    document.querySelectorAll("[data-heat-hour]").forEach((input) => { input.checked = visibleHours.has(input.dataset.heatHour); });
    renderSubjectSettings(settings.subjects || []);
    renderFocusItemSettings(settings.focus_items || [], settings.subjects || []);
    renderScores(scores.scores.map((item) => ({ ...item, gap: item.target - item.score, completion: item.score / item.target })), "#settings-scores");
  }

  function renderFriends(friends) {
    const target = $("#friend-list");
    if (!target) return;
    target.innerHTML = friends.length ? friends.map((friend) => `<div class="friend-row"><div><b>@${escapeHtml(friend.username)}</b><small>${escapeHtml(friend.email || "已建立好友关系")}</small></div><button class="ui-button ui-button--danger ui-button--sm" type="button" data-remove-friend="${escapeHtml(friend.username)}">移除</button></div>`).join("") : '<div class="loading-row">暂无好友，先搜索一个用户名。</div>';
    target.querySelectorAll("[data-remove-friend]").forEach((button) => button.addEventListener("click", async () => {
      const confirmed = await requestConfirmation({ title: "移除好友", message: `确定移除好友 @${button.dataset.removeFriend}？双方的好友差值板将不再显示对方。`, label: "移除好友", tone: "danger" });
      if (!confirmed) return;
      try { await api(`/api/friends/${encodeURIComponent(button.dataset.removeFriend)}`, { method: "DELETE" }); await loadFriends(); showToast("好友已移除"); } catch (error) { showToast(error.message); }
    }));
  }

  async function loadFriends() {
    if (!$("#friend-list")) return;
    const data = await api("/api/friends");
    renderFriends(data.friends || []);
  }

  async function searchFriends(event) {
    event.preventDefault();
    const query = $("#friend-search-input")?.value.trim();
    const target = $("#friend-search-results");
    if (!query || !target) return;
    try {
      const data = await api(`/api/friends/search?q=${encodeURIComponent(query)}`);
      target.innerHTML = (data.users || []).map((user) => `<div class="friend-result"><div><b>@${escapeHtml(user.username)}</b><small>${user.is_friend ? "已是好友" : "可添加"}</small></div>${user.is_friend ? "" : `<button class="ui-button ui-button--secondary ui-button--sm" type="button" data-add-friend="${escapeHtml(user.username)}">添加</button>`}</div>`).join("") || '<div class="loading-row">没有匹配的用户名。</div>';
      target.querySelectorAll("[data-add-friend]").forEach((button) => button.addEventListener("click", async () => {
        try { await api("/api/friends", { method: "POST", body: JSON.stringify({ username: button.dataset.addFriend }) }); await loadFriends(); await searchFriends({ preventDefault() {} }); showToast("好友已添加"); } catch (error) { showToast(error.message); }
      }));
    } catch (error) { showToast(error.message); }
  }

  async function loadInvitations() {
    const target = $("#invitation-list");
    if (!target) return;
    const data = await api("/api/invitations");
    target.innerHTML = data.invitations.length ? data.invitations.map((item) => `<div class="invitation-row ${item.used_by ? "is-used" : ""}"><div><code>${escapeHtml(item.code)}</code><small>${item.used_by ? "已使用" : "可注册"}</small></div>${item.used_by ? "" : `<button class="ui-button ui-button--quiet ui-button--sm" type="button" data-copy-invite="${escapeHtml(item.url)}">复制注册链接</button>`}</div>`).join("") : '<div class="loading-row">还没有邀请码。</div>';
    target.querySelectorAll("[data-copy-invite]").forEach((button) => button.addEventListener("click", async () => { await navigator.clipboard?.writeText(button.dataset.copyInvite); showToast("注册链接已复制"); }));
  }

  async function loadAccount() {
    if (!$("#friend-list") && !$("#invitation-list")) return;
    await loadFriends();
    await loadInvitations();
  }

  function bindAccountForms() {
    $("#friend-search-form")?.addEventListener("submit", searchFriends);
    $("#create-invitation")?.addEventListener("click", async () => { try { await api("/api/invitations", { method: "POST", body: "{}" }); await loadInvitations(); showToast("邀请码已生成"); } catch (error) { showToast(error.message); } });
  }

  async function generateMigrationCode() {
    const button = $("#generate-migration-code");
    if (!button) return;
    button.disabled = true;
    try {
      const result = await api("/api/migration/code", { method: "POST", body: "{}" });
      $("#migration-code").textContent = result.code;
      $("#migration-code-expiry").textContent = `有效期至 ${new Date(result.expires_at).toLocaleTimeString("zh-CN")}`;
      $("#migration-code-box").hidden = false;
      try {
        await copyText(result.code);
        showToast("迁移码已生成并复制");
      } catch (_error) {
        showToast("迁移码已生成，请手动复制");
      }
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
  }
  }

  function scoreEntryValue() {
    const selection = state.scoreEntry.selection;
    return Number(selection.hundreds) * 100 + Number(selection.tens) * 10 + Number(selection.ones);
  }

  function selectedScoreSubject() {
    return state.scoreEntry.subjects.find((subject) => Number(subject.id) === Number(state.scoreEntry.selection.subject)) || null;
  }

  function updateScoreEntryPreview() {
    const subject = selectedScoreSubject();
    const score = scoreEntryValue();
    $("#score-selected-subject")?.replaceChildren(document.createTextNode(subject?.name || "--"));
    $("#score-hundreds-value")?.replaceChildren(document.createTextNode(String(state.scoreEntry.selection.hundreds)));
    $("#score-tens-value")?.replaceChildren(document.createTextNode(String(state.scoreEntry.selection.tens)));
    $("#score-ones-value")?.replaceChildren(document.createTextNode(String(state.scoreEntry.selection.ones)));
    $("#score-entry-preview")?.replaceChildren(document.createTextNode(subject ? `${subject.name} · ${String(score).padStart(3, "0")} 分` : "请选择科目"));
    $("#score-entry-target")?.replaceChildren(document.createTextNode(subject ? `目标分 ${Number(subject.target)} · 在设置中维护` : "先在设置中添加科目和目标分"));
    const submit = $("#submit-tape-score");
    if (submit) submit.disabled = !subject;
  }

  function centerScoreStripOption(strip, value, behavior = "auto") {
    const option = [...strip.querySelectorAll("[data-score-option]")].find((item) => item.dataset.value === String(value));
    if (!option) return;
    strip.scrollTo({ left: Math.max(0, option.offsetLeft + option.offsetWidth / 2 - strip.clientWidth / 2), behavior });
  }

  function setScoreStripSelection(strip, option) {
    if (!strip || !option) return;
    const key = strip.dataset.scoreStrip;
    state.scoreEntry.selection[key] = Number(option.dataset.value);
    strip.querySelectorAll("[data-score-option]").forEach((item) => {
      const selected = item === option;
      item.classList.toggle("is-selected", selected);
      item.setAttribute("aria-selected", String(selected));
    });
    updateScoreEntryPreview();
  }

  function selectScoreStripOption(strip, option, behavior = "smooth") {
    setScoreStripSelection(strip, option);
    centerScoreStripOption(strip, option.dataset.value, behavior);
  }

  function syncScoreStripSelection(strip, snapToSelection = false) {
    const options = [...strip.querySelectorAll("[data-score-option]")];
    if (!options.length) return;
    const center = strip.getBoundingClientRect().left + strip.clientWidth / 2;
    const closest = options.reduce((best, option) => {
      const bounds = option.getBoundingClientRect();
      const distance = Math.abs(bounds.left + bounds.width / 2 - center);
      return !best || distance < best.distance ? { option, distance } : best;
    }, null)?.option;
    if (!closest) return;
    setScoreStripSelection(strip, closest);
    if (snapToSelection) centerScoreStripOption(strip, closest.dataset.value, "smooth");
  }

  function bindScoreStrip(strip) {
    if (!strip || strip.dataset.bound) return;
    strip.dataset.bound = "1";
    let dragging = null;
    let frame = null;
    strip.addEventListener("scroll", () => {
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = null; syncScoreStripSelection(strip); });
    }, { passive: true });
    strip.addEventListener("pointerdown", (event) => {
      dragging = { pointerId: event.pointerId, startX: event.clientX, scrollLeft: strip.scrollLeft };
      strip.setPointerCapture?.(event.pointerId);
      strip.classList.add("is-dragging");
    });
    strip.addEventListener("pointermove", (event) => {
      if (!dragging || dragging.pointerId !== event.pointerId) return;
      strip.scrollLeft = dragging.scrollLeft - (event.clientX - dragging.startX);
    });
    const finishDrag = (event) => {
      if (!dragging || dragging.pointerId !== event.pointerId) return;
      strip.releasePointerCapture?.(event.pointerId);
      dragging = null;
      strip.classList.remove("is-dragging");
      syncScoreStripSelection(strip, true);
    };
    strip.addEventListener("pointerup", finishDrag);
    strip.addEventListener("pointercancel", finishDrag);
    strip.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const options = [...strip.querySelectorAll("[data-score-option]")];
      const current = options.findIndex((item) => item.dataset.value === String(state.scoreEntry.selection[strip.dataset.scoreStrip]));
      const next = Math.max(0, Math.min(options.length - 1, current + (event.key === "ArrowRight" ? 1 : -1)));
      if (options[next]) {
        event.preventDefault();
        selectScoreStripOption(strip, options[next]);
      }
    });
  }

  function renderScoreStrip(key, options) {
    const strip = $(`#score-${key}-strip`);
    if (!strip) return;
    const selectedValue = state.scoreEntry.selection[key];
    strip.innerHTML = options.map((option) => `<button class="score-strip-option${String(option.value) === String(selectedValue) ? " is-selected" : ""}" type="button" data-score-option data-value="${escapeHtml(option.value)}" role="option" aria-selected="${String(option.value) === String(selectedValue)}">${escapeHtml(option.label)}</button>`).join("");
    strip.querySelectorAll("[data-score-option]").forEach((option) => option.addEventListener("click", () => selectScoreStripOption(strip, option)));
    bindScoreStrip(strip);
    requestAnimationFrame(() => centerScoreStripOption(strip, selectedValue));
  }

  function renderScoreEntry() {
    const subjects = state.scoreEntry.subjects;
    if (!subjects.some((subject) => Number(subject.id) === Number(state.scoreEntry.selection.subject))) {
      state.scoreEntry.selection.subject = subjects[0]?.id ?? null;
    }
    renderScoreStrip("subject", subjects.map((subject) => ({ value: subject.id, label: subject.name })));
    renderScoreStrip("hundreds", [0, 1].map((value) => ({ value, label: value })));
    renderScoreStrip("tens", Array.from({ length: 10 }, (_value, value) => ({ value, label: value })));
    renderScoreStrip("ones", Array.from({ length: 10 }, (_value, value) => ({ value, label: value })));
    updateScoreEntryPreview();
  }

  async function loadScoreSubjects() {
    const payload = await api("/api/subjects");
    state.scoreEntry.subjects = payload.subjects || [];
    renderScoreEntry();
  }

  async function openQuickScore() {
    const modal = $("#quick-score-modal");
    if (!modal || modal.open) return;
    state.quickScoreReturnFocus = document.activeElement;
    try {
      await loadScoreSubjects();
      modal.showModal();
      requestAnimationFrame(() => {
        modal.classList.add("is-open");
        $("#score-subject-strip")?.focus();
      });
    } catch (error) { showToast(error.message); }
  }

  function closeQuickScore() {
    const modal = $("#quick-score-modal");
    if (!modal?.open || modal.dataset.closing) return;
    modal.dataset.closing = "1";
    modal.classList.remove("is-open");
    window.setTimeout(() => {
      if (modal.open) modal.close();
      delete modal.dataset.closing;
    }, 180);
  }

  async function submitScoreForm(event) {
    event.preventDefault();
    const subject = selectedScoreSubject();
    if (!subject) {
      showToast("请先在设置中添加科目");
      return;
    }
    const button = $("#submit-tape-score");
    if (button) button.disabled = true;
    try {
      await api("/api/scores", { method: "POST", body: JSON.stringify({ subject_id: subject.id, score: scoreEntryValue() }) });
      closeQuickScore();
      if (document.body.dataset.page === "settings") await loadSettings();
      else await loadDashboard();
      showToast("成绩已添加");
    } catch (error) { showToast(error.message); }
    finally { if (button) button.disabled = false; }
  }

  function bindQuickScore() {
    const modal = $("#quick-score-modal");
    if (!modal) return;
    $("#open-quick-score")?.addEventListener("click", openQuickScore);
    $("#close-quick-score")?.addEventListener("click", closeQuickScore);
    $("#quick-score-form")?.addEventListener("submit", submitScoreForm);
    modal.addEventListener("cancel", (event) => { event.preventDefault(); closeQuickScore(); });
    modal.addEventListener("close", () => { modal.classList.remove("is-open"); state.quickScoreReturnFocus?.focus?.(); });
    modal.addEventListener("click", (event) => {
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

  function renderSubjectSettings(subjects) {
    state.scoreEntry.subjects = subjects;
    const target = $("#settings-subjects");
    if (!target) return;
    target.innerHTML = subjects.length ? subjects.map((subject) => `<form class="subject-settings-row" data-subject-id="${Number(subject.id)}"><input name="name" maxlength="24" value="${escapeHtml(subject.name)}" aria-label="科目名称"><input name="target" type="number" min="1" max="199" step="1" value="${Number(subject.target)}" aria-label="目标分"><button class="ui-button ui-button--secondary ui-button--sm" type="submit">保存</button><button class="ui-button ui-button--danger ui-button--sm" type="button" data-delete-subject>删除</button></form>`).join("") : '<div class="loading-row">还没有科目，请先添加一个。</div>';
    target.querySelectorAll(".subject-settings-row").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await api(`/api/subjects/${form.dataset.subjectId}`, { method: "PATCH", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
          await loadSettings();
          showToast("科目已保存");
        } catch (error) { showToast(error.message); }
      });
      form.querySelector("[data-delete-subject]")?.addEventListener("click", async () => {
        const name = new FormData(form).get("name");
        const confirmed = await requestConfirmation({ title: "删除科目", message: `删除“${name}”会同时删除其专注事项；历史记录会保留。`, label: "删除科目", tone: "danger" });
        if (!confirmed) return;
        try {
          await api(`/api/subjects/${form.dataset.subjectId}`, { method: "DELETE" });
          await loadSettings();
          showToast("科目已删除");
        } catch (error) { showToast(error.message); }
      });
    });
  }

  function focusItemSubjectOptions(subjects, selectedId) {
    return subjects.map((subject) => `<option value="${Number(subject.id)}"${Number(subject.id) === Number(selectedId) ? " selected" : ""}>${escapeHtml(subject.name)}</option>`).join("");
  }

  function renderFocusItemSettings(items, subjects) {
    const target = $("#settings-focus-items");
    const createSubject = $("#new-focus-item-subject");
    const createForm = $("#focus-item-create-form");
    if (createSubject) createSubject.innerHTML = focusItemSubjectOptions(subjects, subjects[0]?.id);
    if (createForm) {
      createForm.querySelectorAll("input, select, button").forEach((field) => {
        field.disabled = !subjects.length;
      });
    }
    if (!target) return;
    if (!items.length) {
      target.innerHTML = '<div class="loading-row">还没有专注事项，请先选择科目并添加。</div>';
      return;
    }
    const rankOptions = (selectedRank) => items.map((_item, index) => `<option value="${index + 1}"${index + 1 === selectedRank ? " selected" : ""}>${index + 1}</option>`).join("");
    target.innerHTML = items.map((item, index) => `<form class="focus-item-settings-row" data-focus-item-id="${Number(item.id)}"><select name="subject_id" aria-label="所属科目">${focusItemSubjectOptions(subjects, item.subject_id)}</select><input name="name" maxlength="24" value="${escapeHtml(item.name)}" aria-label="事项名称"><label class="focus-item-rank">顺序<select data-focus-item-rank aria-label="${escapeHtml(item.label)} 的顺序">${rankOptions(index + 1)}</select></label><button class="ui-button ui-button--secondary ui-button--sm" type="submit">保存</button><button class="ui-button ui-button--danger ui-button--sm" type="button" data-delete-focus-item>删除</button></form>`).join("");
    target.querySelectorAll(".focus-item-settings-row").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await api(`/api/focus-items/${form.dataset.focusItemId}`, { method: "PATCH", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
          await loadSettings();
          showToast("专注事项已保存");
        } catch (error) { showToast(error.message); }
      });
      form.querySelector("[data-delete-focus-item]")?.addEventListener("click", async () => {
        const name = new FormData(form).get("name");
        const confirmed = await requestConfirmation({ title: "删除专注事项", message: `删除“${name}”后不能再启动新的专注，历史记录会保留。`, label: "删除事项", tone: "danger" });
        if (!confirmed) return;
        try {
          await api(`/api/focus-items/${form.dataset.focusItemId}`, { method: "DELETE" });
          await loadSettings();
          showToast("专注事项已删除");
        } catch (error) { showToast(error.message); }
      });
      form.querySelector("[data-focus-item-rank]")?.addEventListener("change", async (event) => {
        const currentIndex = items.findIndex((item) => Number(item.id) === Number(form.dataset.focusItemId));
        const destination = Number(event.currentTarget.value) - 1;
        if (currentIndex < 0 || destination === currentIndex) return;
        const ordered = [...items];
        const [moved] = ordered.splice(currentIndex, 1);
        ordered.splice(destination, 0, moved);
        try {
          await api("/api/focus-items/order", { method: "PUT", body: JSON.stringify({ focus_item_ids: ordered.map((item) => Number(item.id)) }) });
          await loadSettings();
          showToast("专注列表顺序已调整");
        } catch (error) {
          await loadSettings();
          showToast(error.message);
        }
      });
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
        const payload = Object.fromEntries(new FormData(event.currentTarget));
        await api("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
        await loadSettings();
        showToast("设置已保存");
      } catch (error) { showToast(error.message); }
    });
    $("#subject-create-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      try {
        await api("/api/subjects", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
        form.reset();
        await loadSettings();
        showToast("科目已添加");
      } catch (error) { showToast(error.message); }
    });
    $("#focus-item-create-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      try {
        await api("/api/focus-items", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
        form.reset();
        await loadSettings();
        showToast("专注事项已添加");
      } catch (error) { showToast(error.message); }
    });
    $("#generate-migration-code")?.addEventListener("click", generateMigrationCode);
    $("#copy-migration-code")?.addEventListener("click", async () => {
      try {
        await copyText($("#migration-code")?.textContent || "");
        showToast("迁移码已复制");
      } catch (_error) {
        showToast("复制失败，请手动选择迁移码");
      }
    });
  }

  function bindSettingsTabs() {
    const tabs = document.querySelectorAll(".settings-tabs [data-settings-tab]");
    const panels = document.querySelectorAll("[data-settings-panel]");
    if (!tabs.length || !panels.length) return;
    const selectTab = (name) => {
      tabs.forEach((tab) => {
        const selected = tab.dataset.settingsTab === name;
        tab.classList.toggle("is-active", selected);
        tab.setAttribute("aria-selected", String(selected));
      });
      panels.forEach((panel) => panel.classList.toggle("is-hidden", panel.dataset.settingsPanel !== name));
      document.body.dataset.settingsTab = name;
      const url = new URL(window.location.href);
      url.pathname = "/settings";
      url.search = `?tab=${encodeURIComponent(name)}`;
      window.history.replaceState({}, "", url);
    };
    tabs.forEach((tab) => tab.addEventListener("click", async () => {
      selectTab(tab.dataset.settingsTab);
      if (tab.dataset.settingsTab === "account") await loadAccount();
      else await loadSettings();
    }));
  }

  document.addEventListener("DOMContentLoaded", async () => {
    startAlignedSecondClock();
    ensureWakeLock();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible") {
        state.foregroundContinuous = false;
        sendForegroundHeartbeat(true);
        return;
      }
      ensureWakeLock();
      sendForegroundHeartbeat();
      runSecondTasks(Date.now());
      syncDashboard();
    });
    window.addEventListener("pagehide", () => sendForegroundHeartbeat(true));
    $("#close-focus-summary")?.addEventListener("click", closeFocusSummary);
    $("#toggle-focus-pause")?.addEventListener("click", toggleFocusPause);
    bindQuickScore();
    bindInvestmentRange();
    initDragSettlement();
    bindSettingsForms();
    bindSettingsTabs();
    bindAccountForms();
    bindConfirmations();
    bindButtonMotion();
    try {
      if (document.body.dataset.page === "settings") {
        await loadSettings();
        await loadAccount();
      } else if (document.body.dataset.page === "account") await loadAccount();
      else if (document.body.dataset.page === "home") await loadDashboard();
    } catch (error) { showToast(error.message); }
    startDashboardSync();
    startForegroundHeartbeat();
  });
})();
