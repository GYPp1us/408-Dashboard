(() => {
  const state = { dashboard: null, focus: null, timer: null, countdown: null };

  const $ = (selector) => document.querySelector(selector);
  const formatSeconds = (total) => {
    const value = Math.max(0, Math.floor(total));
    const hours = String(Math.floor(value / 3600)).padStart(2, "0");
    const minutes = String(Math.floor((value % 3600) / 60)).padStart(2, "0");
    const seconds = String(value % 60).padStart(2, "0");
    return `${hours}:${minutes}:${seconds}`;
  };
  const formatMinutes = (minutes) => formatSeconds(Math.max(0, Math.round(minutes * 60)));
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));

  async function api(url, options = {}) {
    const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    if (response.status === 401) { window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname); throw new Error("authentication_required"); }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "请求失败");
    return payload;
  }

  function showToast(message) {
    const toast = $("#toast"); if (!toast) return;
    toast.textContent = message; toast.classList.add("show");
    window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2400);
  }

  function renderStatus(data) {
    const countdown = data.exam?.remaining_seconds || 0;
    const days = Math.floor(countdown / 86400);
    $("#exam-days").textContent = `${days} 天`;
    $("#exam-clock").textContent = formatSeconds(countdown % 86400);
    window.clearInterval(state.countdown);
    state.countdown = window.setInterval(() => {
      const next = Math.max(0, (Number($("#exam-days").dataset.seconds || countdown) - Math.floor((Date.now() - renderStatus.startedAt) / 1000)));
      $("#exam-days").textContent = `${Math.floor(next / 86400)} 天`;
      $("#exam-clock").textContent = formatSeconds(next % 86400);
    }, 1000);
    $("#exam-days").dataset.seconds = countdown;
    renderStudyStatus(data.focus?.recent || []);
    const active = data.focus?.active;
    $("#current-state").textContent = active ? `专注中 · ${active.subject}` : "准备学习";
    $("#state-dot").classList.toggle("state-dot-active", Boolean(active));
  }
  renderStatus.startedAt = Date.now();

  function renderStudyStatus(sessions) {
    const today = new Date().toISOString().slice(0, 10);
    const minutes = sessions.filter((item) => item.started_at?.slice(0, 10) === today).reduce((sum, item) => {
      const start = Date.parse(item.started_at); const end = item.ended_at ? Date.parse(item.ended_at) : Date.now();
      return sum + Math.max(0, Math.round((end - start) / 60000));
    }, 0);
    $("#today-study").textContent = `${formatMinutes(minutes)} / 08:00`;
    $("#today-progress").textContent = `完成度 ${Math.min(100, Math.round((minutes / 480) * 100))}%`;
  }

  function renderClock() {
    const tick = () => { const now = new Date(); $("#current-time")?.replaceChildren(document.createTextNode(now.toLocaleTimeString("zh-CN", { hour12: false }))); };
    tick(); window.setInterval(tick, 1000);
  }

  function renderWindows(data) {
    const setWindow = (prefix, value) => {
      $(`#${prefix}-clock`).textContent = formatSeconds(value.remaining_seconds);
      $(`#${prefix}-remaining`)?.replaceChildren(document.createTextNode(formatSeconds(value.remaining_seconds)));
      $(`#${prefix}-percent`).textContent = `${Math.round(value.progress * 100)}%`;
      $(`#${prefix}-progress`).style.width = `${Math.round(value.progress * 100)}%`;
    };
    setWindow("lunch", data.windows.morning); setWindow("library", data.windows.library);
  }

  function renderTicker(scores) {
    const track = $("#score-track");
    track.innerHTML = [...scores, ...scores.slice(0, 1)].map((item) => `<div class="score-row"><span>${escapeHtml(item.subject)}</span><b>${item.score} / ${item.target}</b><em>${item.gap > 0 ? `-${item.gap}` : `+${Math.abs(item.gap)}`}</em></div>`).join("");
  }

  function renderHeatmap(heatmap) {
    const hours = $("#heat-hours"); const grid = $("#heat-grid"); if (!hours || !grid) return;
    hours.innerHTML = Array.from({ length: 24 }, (_, hour) => `<span>${hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}</span>`).join("");
    const max = Math.max(1, ...heatmap.flat());
    grid.innerHTML = heatmap.flatMap((day, dayIndex) => day.map((minutes, hour) => {
      const level = minutes === 0 ? 0 : Math.min(4, Math.ceil((minutes / max) * 4));
      return `<i class="heat-cell${level ? ` l${level}` : ""}" data-detail="最近第 ${30 - dayIndex} 天 ${String(hour).padStart(2, "0")}:00 · ${minutes} 分钟" title="${minutes} 分钟"></i>`;
    })).join("");
    grid.querySelectorAll(".heat-cell").forEach((cell) => cell.addEventListener("click", () => { grid.querySelectorAll(".selected").forEach((selected) => selected.classList.remove("selected")); cell.classList.add("selected"); $("#heat-detail").textContent = cell.dataset.detail; }));
  }

  function renderScores(scores, selector = "#score-table") {
    const target = $(selector); if (!target) return;
    const rows = scores.map((item) => target.tagName === "TBODY" ? `<tr><td>${escapeHtml(item.subject)}</td><td>${item.score} / ${item.target}</td><td class="${item.gap > 0 ? "bad" : "good"}">${item.gap > 0 ? `-${item.gap}` : `+${Math.abs(item.gap)}`}</td><td class="${item.completion >= .9 ? "good" : "bad"}">${Math.round(item.completion * 100)}%</td></tr>` : `<div><span>${escapeHtml(item.subject)}</span><b>${item.score} / ${item.target} · ${Math.round(item.completion * 100)}%</b></div>`);
    target.innerHTML = rows.join("");
  }

  function renderPlans(plans, selector = "#plan-list") {
    const target = $(selector); if (!target) return;
    target.innerHTML = plans.map((plan) => `<div class="plan-item"><time>${escapeHtml(plan.week_start)}</time><strong>${escapeHtml(plan.subject)} · ${escapeHtml(plan.title)}</strong><span>${Math.round((plan.completed_minutes / plan.target_minutes) * 100)}%</span></div>`).join("");
  }

  function renderRecentFocus(sessions, selector = "#recent-focus") {
    const target = $(selector); if (!target) return;
    target.innerHTML = sessions.slice(0, 5).map((item) => `<div class="recent-item"><b>${escapeHtml(item.subject)} · ${escapeHtml(item.mode)}</b><small>${new Date(item.started_at).toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit" })} · ${item.status === "active" ? "进行中" : "已完成"}</small></div>`).join("") || '<div class="loading-row">今天还没有专注记录。</div>';
  }

  function renderModes(modes) {
    const target = $("#focus-modes"); if (!target) return;
    target.innerHTML = modes.map((mode, index) => `<div class="mode"><strong>${escapeHtml(mode.name)}</strong><small>${escapeHtml(mode.subject)} · ${mode.duration_minutes || "自由"} ${mode.duration_minutes ? "分钟" : "计时"}</small><button class="slide-start${index ? " secondary" : ""}" data-mode-id="${mode.id}" data-subject="${escapeHtml(mode.subject)}" data-mode="${escapeHtml(mode.name)}" data-duration="${mode.duration_minutes || 25}">滑动启动 <b>→</b></button></div>`).join("");
    target.querySelectorAll("[data-mode-id]").forEach((button) => button.addEventListener("click", async () => { try { await api("/api/focus/start", { method: "POST", body: JSON.stringify({ subject: button.dataset.subject, mode: button.dataset.mode, planned_minutes: Number(button.dataset.duration) }) }); window.location.href = "/focus"; } catch (error) { showToast(error.message); } }));
  }

  async function loadDashboard() {
    const data = await api("/api/dashboard"); state.dashboard = data; renderStatus(data); renderClock(); renderWindows(data); renderTicker(data.scores); renderModes(data.focus_modes || []); renderHeatmap(data.heatmap); renderScores(data.scores); renderPlans(data.plans); renderRecentFocus(data.focus.recent); $("#today-date")?.replaceChildren(document.createTextNode(new Date().toLocaleDateString("zh-CN", { weekday: "long", year: "numeric", month: "2-digit", day: "2-digit" })));
  }

  function renderFocus(data) {
    const active = data.active; const table = $("#focus-table");
    if (!active) { $("#focus-subject").textContent = "当前没有进行中的专注"; table.innerHTML = '<tr><td colspan="5">从首页选择一个专注模式开始。</td></tr>'; return; }
    $("#focus-subject").textContent = `${active.subject} · ${active.mode}`; $("#end-focus").dataset.sessionId = active.id; $("#focus-planned").textContent = `${active.planned_minutes} 分钟`; $("#focus-start").textContent = new Date(active.started_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const tick = () => { const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(active.started_at)) / 1000)); const planned = active.planned_minutes * 60; $("#focus-timer").textContent = formatSeconds(elapsed); $("#focus-progress").style.width = `${Math.min(100, Math.round((elapsed / planned) * 100))}%`; $("#focus-ring").textContent = `${Math.min(100, Math.round((elapsed / planned) * 100))}%`; $("#focus-window").textContent = `预计结束 ${new Date(Date.parse(active.started_at) + planned * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} · 剩余 ${formatSeconds(planned - elapsed)}`; };
    tick(); window.clearInterval(state.timer); state.timer = window.setInterval(tick, 1000);
    table.innerHTML = data.recent.map((item) => `<tr><td>${new Date(item.started_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</td><td>${escapeHtml(item.subject)}</td><td>${escapeHtml(item.mode)}</td><td>${item.planned_minutes} 分钟</td><td class="${item.status === "active" ? "good" : "bad"}">${item.status === "active" ? "进行中" : "已完成"}</td></tr>`).join("");
  }

  async function loadFocus() { const [dashboard, focus] = await Promise.all([api("/api/dashboard"), api("/api/focus")]); state.dashboard = dashboard; renderStatus(dashboard); renderTicker(dashboard.scores); renderFocus(focus); renderScores(dashboard.scores, "#focus-score-summary"); renderPlans(dashboard.plans, "#focus-plan-summary"); renderHeatmap(dashboard.heatmap); }

  async function loadSettings() {
    const [settings, scores, plans] = await Promise.all([api("/api/settings"), api("/api/scores"), api("/api/plans")]);
    Object.entries(settings.settings).forEach(([key, value]) => { const input = document.querySelector(`[name="${key}"]`); if (input) input.value = value; });
    renderScores(scores.scores.map((item) => ({ ...item, gap: item.target - item.score, completion: item.score / item.target })), "#settings-scores"); renderPlans(plans.plans, "#settings-plans");
  }

  function bindForms() {
    $("#end-focus")?.addEventListener("click", async (event) => { try { await api("/api/focus/end", { method: "POST", body: JSON.stringify({ session_id: Number(event.currentTarget.dataset.sessionId) }) }); window.location.href = "/"; } catch (error) { showToast(error.message); } });
    $("#settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget)); try { await api("/api/settings", { method: "PATCH", body: JSON.stringify(body) }); showToast("设置已保存"); } catch (error) { showToast(error.message); } });
    document.querySelector('[data-form="score"]')?.addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/scores", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) }); event.currentTarget.reset(); await loadSettings(); showToast("成绩已添加"); } catch (error) { showToast(error.message); } });
    document.querySelector('[data-form="plan"]')?.addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/plans", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) }); event.currentTarget.reset(); await loadSettings(); showToast("计划已添加"); } catch (error) { showToast(error.message); } });
  }

  document.addEventListener("DOMContentLoaded", async () => { bindForms(); try { const page = document.body.dataset.page; if (page === "home") await loadDashboard(); if (page === "focus") await loadFocus(); if (page === "settings") await loadSettings(); } catch (error) { showToast(error.message); } });
})();
