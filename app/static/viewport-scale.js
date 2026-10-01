(() => {
  "use strict";
  const root = document.documentElement;
  const designWidth = 1440;
  let scale = 1, viewportWidth = 1440, viewportHeight = 720, wide = false;
  let frame = null;

  function update() {
    frame = null;
    // Select the mode before measuring: entering wide mode reserves a scrollbar
    // gutter, which must already be reflected in this same update's ratio.
    const layoutWidth = root.clientWidth || window.innerWidth || designWidth;
    viewportHeight = window.innerHeight || root.clientHeight || 720;
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const screenOrientation = window.screen?.orientation?.type;
    const landscape = coarse && screenOrientation
      ? screenOrientation.startsWith("landscape")
      : layoutWidth > viewportHeight;
    wide = layoutWidth >= 1170 || landscape;
    root.dataset.viewportMode = wide ? "wide" : "portrait";
    // Measure outside the zoomed body; never feed its scaled width back in.
    // Root clientWidth can include Chrome's gutter, whereas its border box does not.
    viewportWidth = root.getBoundingClientRect().width || layoutWidth;
    scale = wide && CSS.supports("zoom", "1") ? viewportWidth / designWidth : 1;
    root.style.setProperty("--ui-scale", String(scale));
    root.style.setProperty("--ui-viewport-width", `${viewportWidth / scale}px`);
    root.style.setProperty("--ui-viewport-height", `${viewportHeight / scale}px`);
    window.dispatchEvent(new CustomEvent("dashboard:viewport"));
  }

  function schedule() {
    if (frame === null) frame = requestAnimationFrame(update);
  }

  window.MutsumiViewport = {
    get scale() { return scale; },
    get wide() { return wide; },
    get viewportWidth() { return viewportWidth; },
    get viewportHeight() { return viewportHeight; },
    get logicalWidth() { return viewportWidth / scale; },
    get logicalHeight() { return viewportHeight / scale; },
    elementScale(element) {
      const width = element?.offsetWidth || element?.clientWidth;
      return width ? element.getBoundingClientRect().width / width || scale : scale;
    },
    update: schedule,
  };
  update();
  document.addEventListener("DOMContentLoaded", update);
  window.addEventListener("resize", schedule);
  window.addEventListener("pageshow", update);
  window.screen?.orientation?.addEventListener("change", schedule);
  window.visualViewport?.addEventListener("resize", schedule);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) update(); });
})();
