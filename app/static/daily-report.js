(() => {
  "use strict";
  const dialog = document.getElementById("daily-report-modal");
  const content = document.getElementById("daily-report-content");
  if (!dialog || !content) return;
  const closeButton = document.getElementById("close-daily-report");
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[char]));
  const known = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
  const seconds = (value) => {
    if (!known(value)) return "—";
    const total = Math.max(0, Math.floor(Number(value)));
    return [Math.floor(total / 3600), Math.floor(total % 3600 / 60), total % 60].map((part) => String(part).padStart(2, "0")).join(":");
  };
  const percent = (value, digits = 1) => known(value) ? `${Number(value).toFixed(digits).replace(/\.0$/, "")}%` : "—";
  const signedDuration = (value) => !known(value) ? "—" : `${Number(value) > 0 ? "+" : Number(value) < 0 ? "−" : "±"}${seconds(Math.abs(Number(value)))}`;
  const point = (value) => known(value) ? Number(value).toLocaleString("zh-CN", { minimumFractionDigits:3, maximumFractionDigits:3 }) : "—";
  const dateLabel = (date) => /^\d{4}-\d{2}-\d{2}$/.test(String(date)) ? String(date).replace(/-/g, " · ") : "当日";
  const validReport = (report) => Boolean(report && report.version === 1 && /^\d{4}-\d{2}-\d{2}$/.test(String(report.date)) && known(report.total_seconds) && Number(report.total_seconds) >= 0 && ["settled", "legacy_summary"].includes(report.snapshot_kind));
  const timeLabel = (value, timezone) => {
    if (!value || !Number.isFinite(Date.parse(value))) return "—";
    try { return new Intl.DateTimeFormat("zh-CN", { timeZone:timezone || "Asia/Shanghai", hour:"2-digit", minute:"2-digit", hour12:false }).format(new Date(value)); }
    catch (_error) { return "—"; }
  };
  const metric = (label, value, note = "", extra = "") => `<div class="daily-report-metric ${extra}"><span>${escape(label)}</span><strong>${escape(value)}</strong>${note ? `<small>${escape(note)}</small>` : ""}</div>`;
  const historyKey = "mutsumiDailyReport";
  let settlement = null, currentDate = null, returnFocus = null, request = 0, controller = null, historyToken = null, closing = false;

  function updateGeometry() {
    const viewport = window.MutsumiViewport;
    dialog.classList.toggle("is-compact", Boolean(viewport?.wide) && (viewport.logicalHeight || 720) < 720);
  }

  function show(trigger) {
    updateGeometry();
    closing = false;
    if (!dialog.open) {
      returnFocus = trigger instanceof HTMLElement ? trigger : document.activeElement;
      dialog.showModal();
      historyToken = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      try { window.history.pushState({ ...(window.history.state || {}), [historyKey]:historyToken }, ""); }
      catch (_error) { historyToken = null; }
    }
    requestAnimationFrame(() => { if (dialog.open && !closing) dialog.classList.add("is-visible"); });
    closeButton?.focus({ preventScroll:true });
  }

  function restoreFocus() {
    const fallback = document.querySelector("[data-open-daily-report]:not([hidden])") || document.querySelector("#dashboard-controls");
    const target = returnFocus?.isConnected && !returnFocus.closest?.("[hidden]") ? returnFocus : fallback;
    if (target instanceof HTMLElement) {
      if (!target.matches("button,a,input,select,textarea,[tabindex]")) target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll:true });
    }
    returnFocus = null;
  }

  function close(fromHistory = false) {
    if (!dialog.open || closing) return;
    closing = true;
    request += 1;
    controller?.abort();
    controller = null;
    dialog.classList.remove("is-visible");
    dialog.close();
    restoreFocus();
    if (!fromHistory && historyToken && window.history.state?.[historyKey] === historyToken) window.history.back();
    historyToken = null;
    closing = false;
  }

  function status(title, message, error = false) {
    content.setAttribute("aria-busy", String(!error));
    content.classList.remove("is-ready");
    content.innerHTML = `<div class="daily-report-status" role="${error ? "alert" : "status"}"><span class="daily-report-eyebrow">408 FOCUS CONSOLE · ${escape(dateLabel(currentDate))}</span>${error ? '<span class="daily-report-status-mark" aria-hidden="true">!</span>' : '<span class="daily-report-loading-mark" aria-hidden="true"></span>'}<h2 id="daily-report-title">${escape(title)}</h2><p id="daily-report-caption">${escape(message)}</p>${error ? '<button type="button" class="ui-button ui-button--secondary" data-daily-report-retry>重新读取纪念卡</button>' : '<span class="daily-report-status-note">结束本段专注 · 固定当日快照</span>'}</div>`;
  }

  function reportHtml(report) {
    const legacy = report.snapshot_kind === "legacy_summary";
    const subjects = (Array.isArray(report.subject_totals) ? report.subject_totals : []).filter((item) => known(item.seconds) && Number(item.seconds) > 0);
    const completeSubjects = report.subject_breakdown_complete === true;
    const index = report.index, challenge = report.challenge;
    const total = Number(report.total_seconds);
    const completion = known(report.completion_percent) ? Number(report.completion_percent) : known(report.completion) ? Number(report.completion) * 100 : null;
    const target = known(report.target_seconds) ? Number(report.target_seconds) : null;
    const rank = known(report.rank) && Number(report.rank) > 0 ? `#${Number(report.rank)}` : "—";
    const rankNote = rank === "—" ? "无已存排名" : `${known(report.day_count) ? `${Number(report.day_count)} 个记录日` : "历日排名"}${known(report.percentile) ? ` · ${percent(report.percentile)} 分位` : ""}`;
    const delta = Number(report.delta_seconds);
    const deltaNote = !known(report.delta_seconds) ? "无已存比较" : delta > 0 ? "比昨日多投入" : delta < 0 ? "比昨日少投入" : "与昨日持平";
    const subjectRows = subjects.map((item, position) => {
      const ratio = known(item.percent) ? Number(item.percent) : total > 0 ? Number(item.seconds) / total * 100 : 0;
      const width = Math.max(0, Math.min(100, ratio));
      return `<li class="daily-report-subject" style="--subject-order:${position % 6}"><div><span><i aria-hidden="true"></i>${escape(item.subject || "未分类")}</span><b>${escape(seconds(item.seconds))}${completeSubjects ? `<small>${escape(percent(ratio))}</small>` : ""}</b></div>${completeSubjects ? `<div class="daily-report-subject-track" aria-hidden="true"><span style="width:${width}%"></span></div>` : ""}</li>`;
    }).join("");
    const indexChange = index && known(index.return_percent) ? Number(index.return_percent) : null;
    const indexTone = indexChange > 0 ? "is-rise" : indexChange < 0 ? "is-fall" : "";
    const change = known(indexChange) ? `${indexChange > 0 ? "+" : indexChange < 0 ? "−" : "±"}${percent(Math.abs(indexChange), 2)}` : "—";
    const indexHtml = index ? `<div class="daily-report-index-value ${indexTone}"><strong>${escape(point(index.current))}</strong><b>${escape(change)}</b></div><div class="daily-report-index-baseline"><span>开盘 <b>${escape(point(index.open))}</b></span><span>前收 <b>${escape(point(index.previous_close))}</b></span></div><p class="daily-report-note">${escape(index.note || "结算时的指数快照")}${index.is_market_closed ? " · 已收市" : ""}${index.as_of ? ` · ${escape(timeLabel(index.as_of, report.timezone))}` : ""}</p>` : '<p class="daily-report-empty">这份记录没有保存指数快照</p>';
    const challengeHtml = challenge ? `<div class="daily-report-challenge"><span class="daily-report-challenge-mark" aria-hidden="true">${challenge.active_today ? "✦" : "○"}</span><div><strong>${challenge.active_today ? "连胜挑战" : "普通节奏"}</strong><span>当日涨跌限制 ±${Number(challenge.current_limit_percent) === 20 ? "20" : "10"}%${challenge.pending_disable ? " · 次日恢复 ±10%" : ""}</span></div></div>` : '<p class="daily-report-empty">未保存当日挑战状态</p>';
    const achievements = (Array.isArray(report.achievements) ? report.achievements : []).filter((item) => item?.label).map((item) => `<span class="daily-report-achievement" title="${escape(item.detail || item.label)}">${escape(item.label)}</span>`).join("");
    const trustCounts = known(report.trusted_seconds) ? `受信 ${seconds(report.trusted_seconds)}${known(report.untrusted_seconds) ? ` · 非受信 ${seconds(report.untrusted_seconds)}` : ""}` : "";
    const trustNote = trustCounts || report.trust_note || "本记录未保存受信明细";
    return `<header class="daily-report-header"><div><span class="daily-report-eyebrow">408 FOCUS CONSOLE</span><h2 id="daily-report-title">今日投入，留作纪念</h2></div><div class="daily-report-date"><time datetime="${escape(report.date)}">${escape(dateLabel(report.date))}</time><span>${escape(report.username ? `@${report.username}` : "我的专注记录")}</span></div></header>
      <section class="daily-report-hero" aria-label="本日总专注"><div class="daily-report-total"><span>今日有效专注</span><strong>${escape(seconds(total))}</strong><p id="daily-report-caption" title="${escape(report.trust_note || trustNote)}" data-tooltip="${escape(report.trust_note || trustNote)}">${escape(trustNote)}</p></div><div class="daily-report-goal"><div class="daily-report-goal-heading"><span>每日目标</span><strong>${escape(seconds(target))}</strong></div><div class="daily-report-goal-track" role="meter" aria-label="每日专注目标完成度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.max(0, Math.min(100, completion || 0))}" aria-valuetext="${escape(percent(completion))}"><span style="width:${Math.max(0, Math.min(100, completion || 0))}%"></span></div><div class="daily-report-goal-footer"><b>${escape(percent(completion))}</b><span>${target !== null ? total >= target ? "目标达成" : `距目标 ${escape(seconds(target - total))}` : "无已存目标"}</span></div></div></section>
      <div class="daily-report-metrics">${metric("较昨日增量", signedDuration(report.delta_seconds), deltaNote, delta > 0 ? "is-positive" : "")}${metric("历日排名", rank, rankNote)}${metric("最长一段", seconds(report.longest_session_seconds), `${Number(report.session_count || 0)} 段专注`)}</div>
      <div class="daily-report-columns"><section class="daily-report-subjects"><h3>${completeSubjects ? "时间去向" : "已存主要事项"}</h3>${subjects.length ? `<ul>${subjectRows}</ul>` : '<p class="daily-report-empty">这一天没有已存科目记录</p>'}${!completeSubjects && subjects.length ? '<p class="daily-report-note">早期记录仅保存主要事项，未保存完整科目比例。</p>' : ""}</section><aside class="daily-report-snapshot"><section><h3>专注指数 · 结算快照</h3>${indexHtml}</section><section class="daily-report-policy">${challengeHtml}</section></aside></div>
      <footer class="daily-report-footer"><div class="daily-report-achievements">${achievements}</div><p class="daily-report-closing">${escape(report.closing_note || "这一天的投入已经留在记录里。")}</p><div class="daily-report-proof"><span>${legacy ? "早期已结算记录" : "当日已结算 · 固定快照"}${report.first_start && report.last_end ? ` · ${escape(timeLabel(report.first_start, report.timezone))} — ${escape(timeLabel(report.last_end, report.timezone))}` : ""}</span><span>${escape(report.timezone || "账户时区")}</span></div></footer>`;
  }

  function render(report) {
    if (!validReport(report)) throw new Error("服务端报告尚未确认，请重新读取。");
    currentDate = report.date;
    content.setAttribute("aria-busy", "false");
    content.innerHTML = reportHtml(report);
    content.classList.add("is-ready");
    content.scrollTop = 0;
  }

  function acceptSettlement(value) { settlement = value || null; }

  function pending(date, trigger) {
    request += 1;
    controller?.abort();
    currentDate = date;
    status("正在为今天收官", "正在确认结算并整理你的当日投入，请稍候。");
    show(trigger);
  }

  function open(report, trigger) {
    request += 1;
    controller?.abort();
    render(report);
    show(trigger);
  }

  function complete(report, trigger) {
    if (!validReport(report)) return fail("服务端报告尚未确认，请重新读取。");
    if (dialog.open) open(report, trigger);
  }

  function fail(message) {
    if (!dialog.open) return;
    status("结算尚未确认", message || "请重新读取服务端状态后再试。", true);
  }

  async function read(trigger) {
    const report = settlement?.report;
    const date = currentDate || settlement?.settlement_date || String(window.DashboardController?.getData()?.now || "").slice(0, 10);
    if (validReport(report) && report.date === date) return open(report, trigger);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal, generation = ++request;
    currentDate = date;
    status("正在读取纪念卡", "正在读取服务端保存的当日快照。");
    show(trigger);
    try {
      const response = await fetch(`/api/daily-settlement/report?date=${encodeURIComponent(date)}`, { credentials:"same-origin", cache:"no-store", headers:{ Accept:"application/json" }, signal });
      const payload = await response.json();
      if (!response.ok) throw new Error(response.status === 404 ? "这一天尚未结算，请关闭纪念卡后滑动收官。" : "纪念卡读取失败，请稍后重试。");
      if (signal.aborted || generation !== request || !dialog.open) return;
      render(payload.report || payload.settlement?.report);
    } catch (error) {
      if (signal.aborted || generation !== request || !dialog.open) return;
      fail(error.message);
    }
  }

  closeButton?.addEventListener("click", () => close());
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close();
  });
  window.addEventListener("popstate", () => { if (dialog.open && window.history.state?.[historyKey] !== historyToken) close(true); });
  window.addEventListener("dashboard:viewport", updateGeometry);
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest?.("[data-open-daily-report]");
    if (trigger) { currentDate = settlement?.settlement_date || null; read(trigger); }
    else if (event.target.closest?.("[data-daily-report-retry]")) read(event.target);
  });
  window.DailyReport = { acceptSettlement, pending, open, complete, fail, close };
})();
