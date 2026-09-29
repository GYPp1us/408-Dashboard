(() => {
  "use strict";
  const root = document.documentElement;
  const schemes = new Set(["system", "light", "dark"]);
  const palettes = new Set(["clay", "sage", "ocean"]);
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const portrait = window.matchMedia("(orientation: portrait)");
  const compactBrowser = window.matchMedia("(max-width: 900px)");
  const presets = { balanced: [28, 32, 40], charts: [24, 28, 48], focus: [36, 30, 34] };
  let preferences = {
    theme_mode: root.dataset.themeMode || "system",
    theme_palette: root.dataset.themePalette || "clay",
    quick_focus_count: Number(document.body.dataset.quickFocusCount) || 4,
    viewer_id: document.body.dataset.viewerId || "public",
  };
  let columns = [...presets.balanced];
  let grid = null;
  let drag = null;
  let layoutFrame = null;
  let appearanceSignature = null;
  const storageKey = () => `mutsumiDashboardLayout:v1:${preferences.viewer_id}:${root.classList.contains("native-app") ? "native" : "browser"}`;
  const singleColumn = () => root.classList.contains("native-app") ? portrait.matches : compactBrowser.matches;
  const effectiveTheme = () => preferences.theme_mode === "system" ? systemTheme.matches ? "dark" : "light" : preferences.theme_mode;
  const announceAppearance = () => document.dispatchEvent(new CustomEvent("dashboard:appearance", { detail: { mode: preferences.theme_mode, palette: preferences.theme_palette, effectiveTheme: effectiveTheme() } }));

  function applyPreferences(value = {}) {
    const count = Number(value.quick_focus_count ?? preferences.quick_focus_count);
    preferences = {
      theme_mode: schemes.has(value.theme_mode) ? value.theme_mode : preferences.theme_mode,
      theme_palette: palettes.has(value.theme_palette) ? value.theme_palette : preferences.theme_palette,
      quick_focus_count: Number.isInteger(count) && count >= 2 && count <= 8 ? count : 4,
      viewer_id: value.viewer_id ?? preferences.viewer_id,
    };
    const signature = JSON.stringify([preferences, effectiveTheme()]);
    if (signature === appearanceSignature) return;
    appearanceSignature = signature;
    root.dataset.themeMode = preferences.theme_mode;
    root.dataset.themePalette = preferences.theme_palette;
    root.dataset.theme = effectiveTheme();
    root.style.colorScheme = effectiveTheme();
    document.body.dataset.quickFocusCount = String(preferences.quick_focus_count);
    root.style.setProperty("--dashboard-panel-height", `${Math.max(440, preferences.quick_focus_count * 52 + 124)}px`);
    announceAppearance();
  }

  function loadColumns() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey()) || "null");
      if (Array.isArray(saved) && saved.length === 3 && saved.every((value) => Number.isFinite(value) && value > 0)) {
        const total = saved.reduce((sum, value) => sum + value, 0);
        columns = saved.map((value) => value / total * 100);
      }
    } catch (_error) { /* A disabled storage area still allows resizing. */ }
  }

  function saveColumns() {
    try { localStorage.setItem(storageKey(), JSON.stringify(columns)); } catch (_error) {}
  }

  function allocatedWidths() {
    const available = Math.max(0, grid.clientWidth - 24);
    const minima = [230, 280, 320];
    if (available < minima.reduce((sum, value) => sum + value, 0)) return minima;
    const widths = columns.map((fraction) => available * fraction / 100);
    for (let index = 0; index < 3; index += 1) {
      if (widths[index] >= minima[index]) continue;
      let deficit = minima[index] - widths[index];
      widths[index] = minima[index];
      for (let other = 0; other < 3 && deficit > 0; other += 1) {
        if (other === index) continue;
        const take = Math.min(deficit, Math.max(0, widths[other] - minima[other]));
        widths[other] -= take;
        deficit -= take;
      }
    }
    return widths;
  }

  function renderColumns() {
    if (!grid) return;
    const dividers = [...grid.querySelectorAll("[data-dashboard-divider]")];
    const compact = singleColumn();
    dividers.forEach((divider) => { divider.hidden = compact; divider.tabIndex = compact ? -1 : 0; });
    const tools = document.querySelector(".layout-tools");
    if (tools) tools.hidden = compact;
    if (compact) return;
    const widths = allocatedWidths();
    ["--control-column", "--insight-column", "--activity-column"].forEach((key, index) => grid.style.setProperty(key, `${widths[index]}px`));
    const total = widths.reduce((sum, value) => sum + value, 0);
    dividers.forEach((divider, index) => {
      const before = index === 0 ? 0 : widths[0];
      const pair = widths[index] + widths[index + 1];
      const minima = [230, 280, 320];
      divider.setAttribute("aria-valuenow", String(Math.round((before + widths[index]) / total * 100)));
      divider.setAttribute("aria-valuemin", String(Math.ceil((before + minima[index]) / total * 100)));
      divider.setAttribute("aria-valuemax", String(Math.floor((before + pair - minima[index + 1]) / total * 100)));
      divider.setAttribute("aria-valuetext", `${Math.round(widths[index])} 像素 / ${Math.round(widths[index + 1])} 像素`);
    });
    const selector = document.querySelector("#dashboard-layout-preset");
    if (selector) selector.value = Object.keys(presets).find((name) => columns.every((value, index) => Math.abs(value - presets[name][index]) < .5)) || "custom";
    document.dispatchEvent(new CustomEvent("dashboard:layout"));
  }

  function reflow() {
    if (layoutFrame !== null) return;
    layoutFrame = requestAnimationFrame(() => { layoutFrame = null; renderColumns(); });
  }

  function resizePair(index, delta, originalWidths = allocatedWidths()) {
    const minima = [230, 280, 320];
    const pair = originalWidths[index] + originalWidths[index + 1];
    const left = Math.min(pair - minima[index + 1], Math.max(minima[index], originalWidths[index] + delta));
    const next = [...originalWidths];
    next[index] = left;
    next[index + 1] = pair - left;
    const total = next.reduce((sum, value) => sum + value, 0);
    columns = next.map((value) => value / total * 100);
    renderColumns();
  }

  function resetLayout() {
    columns = [...presets.balanced];
    saveColumns();
    renderColumns();
  }

  function cancelDrag() {
    if (!drag) return;
    columns = drag.originalColumns;
    const divider = drag.divider;
    if (divider.hasPointerCapture?.(drag.pointerId)) divider.releasePointerCapture(drag.pointerId);
    drag = null;
    document.body.classList.remove("is-resizing-dashboard");
    renderColumns();
  }

  function bindLayout() {
    grid = document.querySelector(".dashboard-grid");
    if (!grid) return;
    loadColumns();
    grid.querySelectorAll("[data-dashboard-divider]").forEach((divider) => {
      divider.title = "拖动调整列宽，方向键微调，Home 恢复默认";
      divider.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || singleColumn()) return;
        event.preventDefault();
        cancelDrag();
        drag = { divider, pointerId: event.pointerId, index: Number(divider.dataset.dashboardDivider), startX: event.clientX, widths: allocatedWidths(), originalColumns: [...columns] };
        divider.setPointerCapture(event.pointerId);
        document.body.classList.add("is-resizing-dashboard");
      });
      divider.addEventListener("pointermove", (event) => {
        if (drag?.pointerId === event.pointerId) resizePair(drag.index, event.clientX - drag.startX, drag.widths);
      });
      divider.addEventListener("pointerup", (event) => {
        if (drag?.pointerId !== event.pointerId) return;
        drag = null;
        document.body.classList.remove("is-resizing-dashboard");
        if (divider.hasPointerCapture(event.pointerId)) divider.releasePointerCapture(event.pointerId);
        saveColumns();
      });
      divider.addEventListener("pointercancel", cancelDrag);
      divider.addEventListener("lostpointercapture", cancelDrag);
      divider.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Home") resetLayout();
        else { resizePair(Number(divider.dataset.dashboardDivider), (event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 48 : 16)); saveColumns(); }
      });
      divider.addEventListener("dblclick", resetLayout);
    });
    document.querySelector("#reset-dashboard-layout")?.addEventListener("click", resetLayout);
    document.querySelector("#dashboard-layout-preset")?.addEventListener("change", (event) => {
      if (!presets[event.target.value]) return;
      columns = [...presets[event.target.value]];
      saveColumns();
      renderColumns();
    });
    if (window.ResizeObserver) new ResizeObserver(reflow).observe(grid);
    portrait.addEventListener?.("change", () => { cancelDrag(); reflow(); });
    window.addEventListener("resize", reflow);
    window.addEventListener("blur", cancelDrag);
    renderColumns();
  }

  function bindPreview() {
    document.querySelectorAll("[data-appearance-preview]").forEach((input) => input.addEventListener("change", () => {
      const form = document.querySelector("#settings-form");
      if (!form) return;
      applyPreferences(Object.fromEntries(new FormData(form)));
      const note = document.querySelector("#appearance-preview-note");
      if (note) note.textContent = "正在预览，保存全部设置后应用到账户。";
    }));
  }

  window.DashboardUI = { applyPreferences, resetLayout, reflow, effectiveTheme, get preferences() { return { ...preferences }; } };
  applyPreferences();
  systemTheme.addEventListener?.("change", () => { if (preferences.theme_mode === "system") applyPreferences(); });
  document.addEventListener("DOMContentLoaded", () => { bindLayout(); bindPreview(); });
})();
