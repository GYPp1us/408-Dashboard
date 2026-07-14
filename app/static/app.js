(() => {
  const state = { dashboard: null, timer: null, countdown: null, windowCountdown: null, starting: false, ending: false };
  const $ = (selector) => document.querySelector(selector);
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

  function renderWindows(data) {
    const windows = [
      ["lunch", data.windows.morning],
      ["library", data.windows.library],
    ];
    const fetchedAt = Date.now();
    const setWindow = (prefix, value, endAt) => {
      const now = Date.now();
      const startAt = endAt - Number(value.total_seconds || 0) * 1000;
      const progress = Math.min(1, Math.max(0, (now - startAt) / Math.max(1, endAt - startAt)));
      const remaining = Math.max(0, Math.ceil((endAt - now) / 1000));
      $(`#${prefix}-clock`).textContent = formatSeconds(remaining);
      $(`#${prefix}-remaining`)?.replaceChildren(document.createTextNode(formatSeconds(remaining)));
      $(`#${prefix}-percent`).textContent = `${Math.round(progress * 100)}%`;
      $(`#${prefix}-progress`).style.width = `${Math.round(progress * 100)}%`;
    };
    window.clearInterval(state.windowCountdown);
    windows.forEach(([prefix, value]) => setWindow(prefix, value, fetchedAt + Number(value.remaining_seconds || 0) * 1000));
    state.windowCountdown = window.setInterval(() => {
      windows.forEach(([prefix, value]) => setWindow(prefix, value, fetchedAt + Number(value.remaining_seconds || 0) * 1000));
    }, 1000);
  }

  function renderTicker(scores) {
    const track = $("#score-track");
    if (!track) return;
    const rows = scores.length ? scores : [{ subject: "暂无成绩", score: "--", target: "--", gap: 0 }];
    track.innerHTML = [...rows, ...rows.slice(0, 1)].map((item) => `<div class="score-row"><span>${escapeHtml(item.subject)}</span><b>${item.score} / ${item.target}</b><em>${item.gap > 0 ? `-${item.gap}` : item.gap < 0 ? `+${Math.abs(item.gap)}` : "--"}</em></div>`).join("");
  }

  function renderHeatmap(heatmap) {
    const hours = $("#heat-hours");
    const grid = $("#heat-grid");
    if (!hours || !grid) return;
    hours.innerHTML = Array.from({ length: 12 }, (_, index) => `<span>${String(index * 2).padStart(2, "0")}</span>`).join("");
    const max = Math.max(1, ...heatmap.flat());
    grid.innerHTML = heatmap.flatMap((day, dayIndex) => day.map((minutes, bucket) => {
      const level = minutes === 0 ? 0 : Math.min(4, Math.ceil((minutes / max) * 4));
      const startHour = bucket * 2;
      return `<i class="heat-cell${level ? ` l${level}` : ""}" data-detail="最近第 ${30 - dayIndex} 天 ${String(startHour).padStart(2, "0")}:00-${String(startHour + 2).padStart(2, "0")}:00 · ${minutes} 分钟" title="${minutes} 分钟"></i>`;
    })).join("");
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

  function renderPlans(plans, selector = "#plan-list") {
    const target = $(selector);
    if (!target) return;
    target.innerHTML = plans.length ? plans.map((plan) => `<div class="plan-item"><time>${escapeHtml(plan.week_start)}</time><strong>${escapeHtml(plan.subject)} · ${escapeHtml(plan.title)}</strong><span>${Math.round((plan.completed_minutes / plan.target_minutes) * 100)}%</span></div>`).join("") : '<div class="loading-row">暂无长期计划。</div>';
  }

  function renderRecentFocus(sessions) {
    const target = $("#recent-focus");
    if (!target) return;
    target.innerHTML = sessions.length ? sessions.slice(0, 8).map((item) => `<div class="recent-item"><b>${escapeHtml(item.subject)} · 专注</b><small>${new Date(item.started_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${item.status === "active" ? "进行中" : "已完成"}</small></div>`).join("") : '<div class="loading-row">暂无专注记录。</div>';
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
    document.body.classList.toggle("is-focusing", Boolean(active));
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
    renderStatus(data); renderClock(); renderWindows(data); renderTicker(data.scores); renderModes(data.focus_modes); renderHeatmap(data.heatmap); renderScores(data.scores); renderPlans(data.plans); renderRecentFocus(data.focus.recent);
    $("#today-date")?.replaceChildren(document.createTextNode(new Date().toLocaleDateString("zh-CN", { weekday: "long", year: "numeric", month: "2-digit", day: "2-digit" })));
    applyFocusState(data.focus.active, false);
  }

  async function endFocus() {
    const active = state.dashboard?.focus?.active;
    if (!active) return false;
    try {
      await api("/api/focus/end", { method: "POST", body: JSON.stringify({ session_id: active.id }) });
      await loadDashboard();
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
    const [settings, scores, plans] = await Promise.all([api("/api/settings"), api("/api/scores"), api("/api/plans")]);
    Object.entries(settings.settings).forEach(([key, value]) => { const input = document.querySelector(`[name="${key}"]`); if (input) input.value = value; });
    renderScores(scores.scores.map((item) => ({ ...item, gap: item.target - item.score, completion: item.score / item.target })), "#settings-scores");
    renderPlans(plans.plans, "#settings-plans");
  }

  function bindSettingsForms() {
    $("#settings-form")?.addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/settings", { method: "PATCH", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) }); showToast("设置已保存"); } catch (error) { showToast(error.message); } });
    document.querySelector('[data-form="score"]')?.addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/scores", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) }); event.currentTarget.reset(); await loadSettings(); showToast("成绩已添加"); } catch (error) { showToast(error.message); } });
    document.querySelector('[data-form="plan"]')?.addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/plans", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) }); event.currentTarget.reset(); await loadSettings(); showToast("计划已添加"); } catch (error) { showToast(error.message); } });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bindSettingsForms();
    try {
      if (document.body.dataset.page === "settings") await loadSettings();
      else await loadDashboard();
    } catch (error) { showToast(error.message); }
  });
})();
