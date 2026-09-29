(() => {
  "use strict";
  const providers = new Map();
  const dialog = document.getElementById("detail-drawer");
  const content = document.getElementById("detail-drawer-content");
  if (!dialog || !content) return;
  const title = document.getElementById("detail-drawer-title");
  const kicker = document.getElementById("detail-drawer-kicker");
  const escape = (text) => String(text ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const duration = (seconds) => {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    return [Math.floor(value / 3600), Math.floor(value % 3600 / 60), value % 60].map((part) => String(part).padStart(2, "0")).join(":");
  };
  const dateTime = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "--" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  };
  const metric = (label, value) => `<div class="detail-metric"><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`;
  const itemLabel = (item) => item.label || [item.subject, item.name].filter(Boolean).join(" · ") || "专注事项";
  const records = (sessions = []) => sessions.length ? `<ul class="detail-records">${sessions.map((session) => `<li class="detail-record"><div><strong>${escape(session.label || session.focus_item_label || session.subject || session.name || "专注")}</strong><small>${escape(dateTime(session.started_at))} — ${escape(session.ended_at ? dateTime(session.ended_at) : "进行中")}</small></div><b>${duration(session.effective_seconds ?? session.seconds ?? session.duration_seconds)}</b></li>`).join("")}</ul>` : '<p class="detail-empty">暂无专注记录。</p>';
  let generation = 0;
  let controller = null;
  let current = null;
  let returnFocus = null;
  let closeTimer = null;
  let press = null;
  let suppressed = null;
  let closing = false;
  let detailMounted = false;
  function disposeDetails() {
    if (!detailMounted) return;
    detailMounted = false;
    document.dispatchEvent(new CustomEvent("dashboard:detail-closed", { detail: current }));
  }
  const descriptor = (target) => target instanceof Element ? { kind: target.dataset.detailKind, key: target.dataset.detailKey, date: target.dataset.detailDate, hour: target.dataset.detailHour } : { ...target };
  const blocked = () => document.body.classList.contains("is-paused") || document.body.classList.contains("is-resting") || document.querySelector("#focus-state-overlay:not([hidden])");
  function restoreFocus() {
    let target = returnFocus;
    if (!target?.isConnected && current) target = [...document.querySelectorAll("[data-detail-kind]")].find((element) => {
      const data = descriptor(element);
      return data.kind === current.kind && data.key === current.key && data.date === current.date && data.hour === current.hour;
    });
    if (target instanceof HTMLElement) {
      if (!target.matches("button,a,input,select,textarea,[tabindex]")) target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    }
    returnFocus = null;
  }
  function cancelPress() {
    if (press) { clearTimeout(press.timer); press.target.classList.remove("is-detail-pressing"); }
    press = null;
  }
  function close() {
    cancelPress();
    suppressed = null;
    generation += 1;
    controller?.abort();
    controller = null;
    if (!dialog.open || closing) return;
    closing = true;
    dialog.classList.remove("is-visible");
    clearTimeout(closeTimer);
    const finish = () => { dialog.close(); disposeDetails(); closing = false; restoreFocus(); current = null; };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) finish();
    else closeTimer = window.setTimeout(finish, 250);
  }
  async function open(target) {
    if (!target || blocked()) return;
    const data = descriptor(target);
    if (!data.kind) return;
    cancelPress();
    clearTimeout(closeTimer);
    closing = false;
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    const request = ++generation;
    if (!dialog.open) returnFocus = target instanceof HTMLElement ? target : document.activeElement;
    // Dispose chart/listener resources before replacing the drawer's content.
    // This also covers reopening while the animated close is still pending.
    disposeDetails();
    current = data;
    detailMounted = true;
    title.textContent = "正在读取";
    kicker.textContent = "详情";
    content.innerHTML = '<p class="detail-status" role="status">正在读取详情…</p>';
    if (!dialog.open) dialog.showModal();
    requestAnimationFrame(() => { if (dialog.open && !closing) dialog.classList.add("is-visible"); });
    try {
      const provider = providers.get(data.kind);
      if (!provider) throw new Error("详情暂不可用，请稍后重试。");
      const result = await provider({ ...data, signal });
      if (signal.aborted || request !== generation || !dialog.open || closing) return;
      title.textContent = result.title || "详情";
      kicker.textContent = result.kicker || "详情";
      content.innerHTML = result.html || '<p class="detail-empty">暂无详情。</p>';
      result.onReady?.(content, data);
    } catch (error) {
      if (signal.aborted || request !== generation || !dialog.open || closing) return;
      title.textContent = "详情加载失败";
      content.innerHTML = `<p class="detail-error">${escape(error.message || "网络连接异常，请重试。")}</p><button type="button" class="ui-button ui-button--secondary" data-detail-retry>重新加载</button>`;
    }
  }
  async function fetchJson(url, signal) {
    const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(response.status === 401 ? "请登录后查看详情。" : response.status === 404 ? "该事项已不存在，请刷新主页。" : "无法读取详情，请重试。");
    return payload;
  }
  providers.set("focus", async (data) => {
    const payload = await fetchJson(`/api/focus/items/${encodeURIComponent(data.key)}/summary`, data.signal);
    const bridge = window.DashboardController;
    const items = bridge?.getData()?.focus_items || bridge?.getData()?.focus_modes || [];
    const alternatives = items.filter((item) => String(item.id) !== String(data.key));
    const actions = document.body.dataset.role === "guest" ? "" : `<h3>快捷专注</h3><div class="detail-actions"><button type="button" class="ui-button ui-button--secondary" data-detail-pin>${bridge?.isPinned(data.key) ? "取消固定" : "固定到快捷专注"}</button></div>${alternatives.length ? `<div class="detail-replace"><label for="detail-replacement">将此快捷位置替换为</label><select id="detail-replacement">${alternatives.map((item) => `<option value="${escape(item.id)}">${escape(itemLabel(item))}</option>`).join("")}</select><button type="button" class="ui-button ui-button--secondary" data-detail-replace>替换</button></div>` : ""}<p class="detail-action-message" role="status"></p>`;
    return {
      title: itemLabel(payload.item || {}), kicker: "事项详情",
      html: `<div class="detail-metrics">${metric("今日有效专注", duration(payload.today_seconds))}${metric("累计有效专注", duration(payload.all_time_seconds))}${metric("今日次数", payload.today_count || 0)}</div>${actions}<h3>最近专注记录</h3>${records(payload.recent_sessions)}`,
      onReady(root) {
        const message = root.querySelector(".detail-action-message");
        const action = async (button, callback) => {
          button.disabled = true;
          try { await callback(); } catch (error) { if (message) message.textContent = error.message || "操作失败，请重试。"; }
          finally { button.disabled = false; }
        };
        root.querySelector("[data-detail-pin]")?.addEventListener("click", (event) => action(event.currentTarget, async () => {
          if (!bridge?.togglePin) throw new Error("快捷操作暂不可用。");
          await bridge.togglePin(data.key);
          event.target.textContent = bridge.isPinned(data.key) ? "取消固定" : "固定到快捷专注";
          if (message) message.textContent = "快捷专注已更新。";
        }));
        root.querySelector("[data-detail-replace]")?.addEventListener("click", (event) => action(event.currentTarget, async () => {
          if (!bridge?.replaceQuickItem) throw new Error("快捷操作暂不可用。");
          await bridge.replaceQuickItem(data.key, root.querySelector("#detail-replacement").value);
          if (message) message.textContent = "快捷位置已替换。";
        }));
      },
    };
  });
  providers.set("heat", async (data) => {
    const params = new URLSearchParams({ date: data.date, hour: data.hour });
    const payload = await fetchJson(`/api/focus/interval?${params}`, data.signal);
    const subjects = payload.subjects || [];
    return {
      title: `${data.date} · ${String(data.hour).padStart(2, "0")}:00 — ${String(Number(data.hour) + 2).padStart(2, "0")}:00`, kicker: "时段详情 · 有效专注",
      html: `<div class="detail-metrics">${metric("区间总时长", duration(payload.total_seconds))}${metric("专注记录", (payload.sessions || []).length)}</div><h3>完整科目构成</h3>${subjects.length ? `<ul class="detail-records">${subjects.map((subject) => `<li class="detail-record"><strong>${escape(subject.subject || subject.name || "未分类")}</strong><b>${duration(subject.seconds ?? subject.total_seconds)}</b></li>`).join("")}</ul>` : '<p class="detail-empty">这个时段尚无有效专注。</p>'}<h3>区间记录</h3>${records(payload.sessions)}`,
    };
  });
  document.addEventListener("pointerdown", (event) => {
    cancelPress();
    // A new gesture must not inherit the release-click guard of a long press.
    suppressed = null;
    if (!event.isPrimary || event.button !== 0 || dialog.open || blocked()) return;
    const element = event.target instanceof Element ? event.target : null;
    if (!element || element.closest("a,input,select,textarea,.drag-thumb,[data-detail-open]")) return;
    const target = element.closest("[data-detail-kind]");
    if (!target) return;
    // Heat cells are themselves accessible buttons; nested action buttons keep
    // their ordinary click behavior and must never initiate a long press.
    const button = element.closest("button,[role=button]");
    if (button && button !== target) return;
    const data = descriptor(target);
    press = { target, data, x: event.clientX, y: event.clientY, pointerId: event.pointerId };
    target.classList.add("is-detail-pressing");
    press.timer = setTimeout(() => {
      const held = press;
      if (!held) return;
      suppressed = { pointerId: held.pointerId, expires: Date.now() + 1500 };
      open(held.target.isConnected ? held.target : held.data);
    }, 520);
  }, true);
  document.addEventListener("pointermove", (event) => {
    if (press && (event.pointerId !== press.pointerId || Math.abs(event.clientX - press.x) > 8 || Math.abs(event.clientY - press.y) > 8)) cancelPress();
  }, true);
  document.addEventListener("pointerup", () => { cancelPress(); if (suppressed) suppressed.expires = Date.now() + 700; }, true);
  document.addEventListener("pointercancel", cancelPress, true);
  window.addEventListener("blur", cancelPress);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState !== "visible") cancelPress(); });
  document.addEventListener("click", (event) => {
    if (suppressed && Date.now() < suppressed.expires && (event.target === dialog || !dialog.contains(event.target)) && event.detail !== 0) {
      event.preventDefault(); event.stopImmediatePropagation(); suppressed = null; return;
    }
    const element = event.target instanceof Element ? event.target : null;
    const button = element?.closest("[data-detail-open]");
    if (button) { event.preventDefault(); open(button.dataset.detailKind ? button : button.closest("[data-detail-kind]")); }
    if (element?.closest("[data-detail-close]")) close();
    if (element?.closest("[data-detail-retry]") && current) open(current);
  }, true);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    // WebView may forward a picker cancellation to the underlying HTML dialog
    // after rotation. The picker owns that Back gesture until its return settles.
    try { if (window.MutsumiAndroid?.imagePickerOwnsBack?.()) return; } catch (_error) {}
    close();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close();
  });
  dialog.addEventListener("close", () => {
    // Native close events are queued. A newly opened drawer must not lose its
    // new request or chart when an earlier close event reaches the queue.
    if (dialog.open) return;
    generation += 1;
    controller?.abort();
    dialog.classList.remove("is-visible");
    disposeDetails();
  });
  new MutationObserver(() => { if (blocked()) { cancelPress(); if (dialog.open) close(); } }).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  const overlay = document.getElementById("focus-state-overlay");
  if (overlay) new MutationObserver(() => { if (!overlay.hidden) { cancelPress(); close(); } }).observe(overlay, { attributes: true, attributeFilter: ["hidden"] });
  window.DashboardDetails = { open, close, register(kind, provider) { providers.set(kind, provider); } };
})();
