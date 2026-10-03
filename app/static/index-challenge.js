(() => {
  "use strict";
  const endpoint = "/api/focus-kline/challenge";
  let current = null, readPending = null, writePending = null, readDue = false, writeEpoch = 0, warning = "";
  const canEdit = () => document.body.dataset.role === "admin" && /^\d+$/.test(document.body.dataset.viewerId || "") && Number(document.body.dataset.viewerId) > 0;
  const signature = (value) => JSON.stringify([value.revision, value.desired_enabled, value.active_today, value.pending_disable, value.current_limit_percent]);
  const controlHtml = () => '<div class="index-challenge" data-index-challenge><div class="index-challenge-copy"><strong>连胜挑战</strong><span data-index-challenge-status role="status">读取挑战状态</span></div><button type="button" class="ui-button ui-button--secondary ui-button--sm" data-index-challenge-toggle disabled>开启挑战</button><p class="index-challenge-feedback" data-index-challenge-feedback role="alert" hidden></p></div>';
  function render() {
    const readonly = !canEdit();
    const status = !current ? "读取挑战状态" : current.pending_disable ? "本日 ±20%，明日起恢复普通限制" : current.active_today ? "挑战 · ±20%" : "普通 · ±10%";
    const rule = "开启后立即将今日及后续交易日涨跌限制扩大至 ±20%，已发生点位保持不变；关闭后今日仍为 ±20%，下个账户日恢复 ±10%。";
    const explanation = `${rule}${current?.effective_at ? ` 生效时间：${current.effective_at}` : ""}${readonly ? " 访客仅可查看。" : ""}`;
    document.querySelectorAll("[data-index-challenge]").forEach((host) => {
      host.classList.toggle("is-active", Boolean(current?.active_today));
      host.classList.toggle("is-pending-disable", Boolean(current?.pending_disable));
      host.classList.toggle("is-pending", Boolean(writePending));
      host.setAttribute("aria-busy", String(Boolean(writePending)));
      const text = host.querySelector("[data-index-challenge-status]");
      if (text) { text.textContent = status; text.title = explanation; text.setAttribute("data-tooltip", explanation); }
      const button = host.querySelector("[data-index-challenge-toggle]");
      if (button) {
        button.hidden = readonly;
        button.disabled = readonly || !current || Boolean(writePending);
        button.textContent = writePending ? "正在应用…" : current?.pending_disable ? "继续挑战" : current?.desired_enabled ? "关闭挑战" : "开启挑战";
        button.setAttribute("aria-pressed", String(Boolean(current?.desired_enabled)));
      }
      const feedback = host.querySelector("[data-index-challenge-feedback]");
      if (feedback) { feedback.hidden = !warning; feedback.textContent = warning; }
    });
    document.querySelectorAll("[data-index-challenge-badge]").forEach((badge) => {
      badge.hidden = !current?.active_today;
      badge.classList.toggle("is-active", Boolean(current?.active_today));
      badge.classList.toggle("is-pending-disable", Boolean(current?.pending_disable));
      badge.textContent = current?.pending_disable ? "今日 ±20%" : "挑战 · ±20%";
      badge.title = explanation;
      badge.setAttribute("data-tooltip", explanation);
    });
  }
  // Callers must discard the entire quote payload when its policy snapshot is stale.
  function accept(value, source = "payload") {
    if (!value || typeof value !== "object" || !Number.isInteger(value.revision) || value.revision < 0 || !Number.isFinite(Date.parse(value.as_of)) || ["desired_enabled", "active_today", "pending_disable"].some((key) => typeof value[key] !== "boolean") || ![10, 20].includes(value.current_limit_percent)) return false;
    if (current && value.revision < current.revision) return false;
    if (current && value.revision === current.revision && Date.parse(value.as_of) < Date.parse(current.as_of)) return signature(current) === signature(value);
    const changed = current && signature(current) !== signature(value);
    current = { ...value };
    render();
    if (changed) document.dispatchEvent(new CustomEvent("dashboard:challenge-updated", { detail:{ challenge:{ ...current }, source } }));
    return true;
  }
  async function readResponse(response) {
    if (!response.ok) throw new Error(`挑战状态更新失败 (${response.status})`);
    const body = await response.json();
    return body.challenge || body.data?.challenge;
  }
  function requestPolicy(options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    return fetch(endpoint, { credentials:"same-origin", cache:"no-store", ...options, signal:controller.signal })
      .then(readResponse).finally(() => window.clearTimeout(timer));
  }
  function refresh(force = false) {
    if (force) readDue = true;
    if (document.hidden || writePending) { readDue = true; return readPending; }
    if (readPending) return readPending;
    readDue = false;
    const epoch = writeEpoch;
    readPending = requestPolicy().then((value) => { if (epoch === writeEpoch) accept(value, "poll"); })
      .catch(() => { if (!current) { warning = "挑战状态读取失败，请稍后重试。"; render(); } })
      .finally(() => { readPending = null; if (readDue && !writePending && !document.hidden) return refresh(); });
    return readPending;
  }
  function setEnabled(enabled) {
    if (!canEdit() || typeof enabled !== "boolean" || !current) return Promise.resolve(false);
    if (writePending) return writePending;
    warning = "";
    writeEpoch += 1;
    // The pending state appears before network work, while the selected state stays authoritative.
    writePending = Promise.resolve().then(async () => {
      const value = await requestPolicy({ method:"PATCH", headers:{ "Content-Type":"application/json" }, body:JSON.stringify({ enabled }) });
      if (!accept(value, "toggle")) throw new Error("挑战状态已更新，请重试。");
      return true;
    }).catch(() => { warning = "挑战未能更新，已重新读取服务端状态，请重试。"; return false; })
      .finally(() => { writePending = null; render(); refresh(true); });
    render();
    return writePending;
  }
  function mount(root = document) {
    const removers = [];
    root.querySelectorAll("[data-index-challenge-toggle]").forEach((button) => {
      const click = () => { if (current && !button.disabled) setEnabled(!current.desired_enabled); };
      button.addEventListener("click", click);
      removers.push(() => button.removeEventListener("click", click));
    });
    render();
    return () => removers.forEach((remove) => remove());
  }
  window.IndexChallenge = { accept, refresh, setEnabled, mount, controlHtml, canEdit, getState:() => current ? { ...current } : null };
  document.addEventListener("DOMContentLoaded", () => {
    mount(); refresh();
    setInterval(() => refresh(), 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
    window.addEventListener("pageshow", () => refresh(true));
  });
})();
