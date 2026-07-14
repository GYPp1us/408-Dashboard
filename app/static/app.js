(() => {
  const state = { dashboard: null, timer: null, countdown: null, windowCountdown: null, scoreChart: null, summaryTimer: null, summaryCharts: [], starting: false, ending: false };
  const appFontFamily = '"Source Han Serif SC Medium", "Source Han Serif SC", "思源宋体 SC", "Noto Serif SC", "Noto Serif CJK SC", "Songti SC", "STSong", serif';
  const themePalettes = {
    idle: ["#ef5b3f", "#c74732", "#f1875f", "#a93b2c", "#d76e43", "#f4a184", "#8f4a38", "#e48060"],
    focus: ["#7a5bc7", "#5f42aa", "#987ddd", "#4d358c", "#876cbf", "#b09be7", "#614e87", "#9b84cf"],
  };
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
    const tick = () => {
      const value = Math.max(0, Math.floor((state.examEndsAt - Date.now()) / 1000));
      $("#exam-days").textContent = `${Math.floor(value / 86400)} 天`;
      $("#exam-clock").textContent = formatSeconds(value % 86400);
    };
    tick();
    window.clearInterval(state.countdown);
    state.countdown = window.setInterval(tick, 1000);
    const today = data.today_focus || { seconds: 0, count: 0 };
    $("#today-study").textContent = `${formatSeconds(today.seconds)} / 08:00`;
    $("#today-progress").textContent = `完成度 ${Math.min(100, Math.round((today.seconds / 28800) * 100))}%`;
    const active = data.focus?.active;
    $("#current-state").textContent = active ? `专注中 · ${active.subject}` : "准备学习";
    $("#state-dot").classList.toggle("state-dot-active", Boolean(active));
  }

  function renderClock() {
    const tick = () => { const now = new Date(); $("#current-time")?.replaceChildren(document.createTextNode(now.toLocaleTimeString("zh-CN", { hour12: false }))); };
    tick();
    window.clearInterval(state.clock);
    state.clock = window.setInterval(tick, 1000);
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
    const fetchedAt = Date.now();
    const serverNowAt = Date.parse(data.now);
    const setWindow = (prefix, value, endAt) => {
      const now = Date.now();
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
    window.clearInterval(state.windowCountdown);
    windows.forEach(([prefix, value]) => setWindow(prefix, value, fetchedAt + Number(value.remaining_seconds || 0) * 1000));
    renderHomeWindow(data, new Date(serverNowAt));
    state.windowCountdown = window.setInterval(() => {
      windows.forEach(([prefix, value]) => setWindow(prefix, value, fetchedAt + Number(value.remaining_seconds || 0) * 1000));
      renderHomeWindow(data, new Date(serverNowAt + Date.now() - fetchedAt));
    }, 1000);
  }

  function renderTicker(scores) {
    const track = $("#score-track");
    if (!track) return;
    const rows = scores.length ? scores : [{ subject: "暂无成绩", score: "--", target: "--", gap: 0 }];
    track.innerHTML = [...rows, ...rows.slice(0, 1)].map((item) => `<div class="score-row"><span>${escapeHtml(item.subject)}</span><b>${item.score} / ${item.target}</b><em class="${item.gap > 0 ? "bad" : item.gap < 0 ? "good" : ""}">${item.gap > 0 ? `-${item.gap}` : item.gap < 0 ? `+${Math.abs(item.gap)}` : "--"}</em></div>`).join("");
  }

  function renderHeatmap(heatmap) {
    const hours = $("#heat-hours");
    const grid = $("#heat-grid");
    if (!hours || !grid) return;
    hours.innerHTML = Array.from({ length: 12 }, (_, index) => `<span>${String(index * 2).padStart(2, "0")}</span>`).join("");
    const max = Math.max(120, ...heatmap.flat());
    const renderCell = (minutes, dayIndex, bucket) => {
      const level = minutes === 0 ? 0 : Math.min(4, Math.ceil((minutes / max) * 4));
      const startHour = bucket * 2;
      return `<i class="heat-cell${level ? ` l${level}` : ""}" data-detail="最近第 ${30 - dayIndex} 天 ${String(startHour).padStart(2, "0")}:00-${String(startHour + 2).padStart(2, "0")}:00 · ${minutes} 分钟" title="${minutes} 分钟"></i>`;
    };
    grid.innerHTML = Array.from({ length: 12 }, (_, bucket) => heatmap.map((day, dayIndex) => renderCell(day[bucket] || 0, dayIndex, bucket)).join("")).join("");
    grid.querySelectorAll(".heat-cell").forEach((cell) => cell.addEventListener("click", () => {
      grid.querySelectorAll(".selected").forEach((selected) => selected.classList.remove("selected"));
      cell.classList.add("selected");
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

  function renderRecentFocus(sessions) {
    const target = $("#recent-focus");
    if (!target) return;
    target.innerHTML = sessions.length ? sessions.slice(0, 8).map((item) => `<div class="recent-item"><b>${escapeHtml(item.subject)} · 专注</b><small>${new Date(item.started_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${item.status === "active" ? "进行中" : "已完成"}</small></div>`).join("") : '<div class="loading-row">暂无专注记录。</div>';
  }

  function closeFocusSummary() {
    window.clearInterval(state.summaryTimer);
    state.summaryTimer = null;
    state.summaryCharts.forEach((chart) => chart.destroy());
    state.summaryCharts = [];
    const recent = $("#recent-focus-view");
    const summary = $("#focus-summary");
    if (recent) recent.hidden = false;
    if (summary) summary.hidden = true;
  }

  function showFocusSummary(session, todaySessions) {
    const recent = $("#recent-focus-view");
    const summary = $("#focus-summary");
    if (!recent || !summary || !window.Chart) return;
    closeFocusSummary();
    recent.hidden = true;
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
    const tick = () => {
      const elapsed = Math.floor((Date.now() - restStartedAt) / 1000);
      $("#rest-timer").textContent = formatSeconds(elapsed);
      if (elapsed >= 900) closeFocusSummary();
    };
    tick();
    state.summaryTimer = window.setInterval(tick, 1000);
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
    target.innerHTML = modes.map((mode) => `<div class="mode"><strong>${escapeHtml(mode.subject)}</strong><small>不限时专注</small><div class="drag-launch" data-subject="${escapeHtml(mode.subject)}" data-mode="专注" data-duration="0"><div class="drag-fill"></div><span class="drag-label">滑动启动</span><span class="drag-thumb" role="button" tabindex="0" aria-label="滑动启动 ${escapeHtml(mode.subject)}">→</span></div></div>`).join("");
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
      const session = await api("/api/focus/start", { method: "POST", body: JSON.stringify({ subject: track.dataset.subject, mode: "专注", planned_minutes: 0, client_token: crypto.randomUUID() }) });
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
    const flipState = Flip.getState(".time-card, .activity-panel, .score-panel, .mode-panel");
    requestAnimationFrame(() => Flip.from(flipState, { duration: .42, ease: "power2.inOut", stagger: .015, absolute: false }));
  }

  function applyFocusState(active, animate = false) {
    if (animate) animateLayout();
    if (active) closeFocusSummary();
    document.body.classList.toggle("is-focusing", Boolean(active));
    syncScoreChartTheme(active);
    $("#idle-mode-view").hidden = Boolean(active);
    $("#active-mode-view").hidden = !active;
    $("#home-state-note").textContent = active ? "专注中，保持当前上下文" : "准备开始下一段专注";
    if (!active) {
      window.clearInterval(state.timer);
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
    $("#focus-subject").textContent = `${active.subject} · 专注`;
    $("#focus-start").textContent = new Date(active.started_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const tick = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(active.started_at)) / 1000));
      $("#focus-timer").textContent = formatSeconds(elapsed);
      $("#focus-window").textContent = "持续计时 · 不设上限";
    };
    tick();
    window.clearInterval(state.timer);
    state.timer = window.setInterval(tick, 1000);
    initDragEnd();
  }

  async function loadDashboard() {
    const data = await api("/api/dashboard");
    state.dashboard = data;
    renderStatus(data); renderClock(); renderWindows(data); renderTicker(data.scores); renderModes(data.focus_modes); renderHeatmap(data.heatmap); renderScoreChart(data.score_history); renderRecentFocus(data.focus.recent);
    $("#today-date")?.replaceChildren(document.createTextNode(new Date().toLocaleDateString("zh-CN", { weekday: "long", year: "numeric", month: "2-digit", day: "2-digit" })));
    applyFocusState(data.focus.active, false);
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
    renderScores(scores.scores.map((item) => ({ ...item, gap: item.target - item.score, completion: item.score / item.target })), "#settings-scores");
  }

  function bindSettingsForms() {
    $("#settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/settings", { method: "PATCH", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) }); showToast("设置已保存"); } catch (error) { showToast(error.message); } });
    document.querySelector('[data-form="score"]')?.addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/scores", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) }); event.currentTarget.reset(); await loadSettings(); showToast("成绩已添加"); } catch (error) { showToast(error.message); } });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    $("#close-focus-summary")?.addEventListener("click", closeFocusSummary);
    bindSettingsForms();
    try {
      if (document.body.dataset.page === "settings") await loadSettings();
      else await loadDashboard();
    } catch (error) { showToast(error.message); }
  });
})();
