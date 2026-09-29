(() => {
  "use strict";
  const charts = "[data-index-chart], [data-index-daily], [data-index-intraday], .kline-chart-host";
  const inChart = (target) => target instanceof Element && target.closest(charts);
  const gestures = new WeakMap();
  // Some chart versions report a date click when the last pinch finger lifts.
  // Let their touchend handlers clean up, but prevent that click from replacing
  // the chart and resetting the range the user just selected.
  window.ChartGestures = {
    shouldIgnoreClick(host) {
      const gesture = gestures.get(host);
      return Boolean(gesture && (gesture.active || performance.now() < gesture.until));
    },
  };
  // Trackpad pinch arrives as Ctrl-wheel. Cancel browser scaling while the
  // chart still receives the event and handles its own range interactions.
  document.addEventListener("wheel", (event) => {
    if (event.ctrlKey && inChart(event.target)) event.preventDefault();
  }, { capture: true, passive: false });
  // Scope touch ownership to charts, including charts mounted in the drawer.
  for (const type of ["touchstart", "touchmove", "gesturestart", "gesturechange"]) {
    document.addEventListener(type, (event) => {
      const host = inChart(event.target);
      if (host && event.type === "touchstart" && event.touches?.length === 1) gestures.delete(host);
      if (host && (!event.touches || event.touches.length > 1)) {
        gestures.set(host, { active: true, until: 0 });
        event.preventDefault();
      }
    }, { capture: true, passive: false });
  }
  for (const type of ["touchend", "touchcancel", "gestureend"]) {
    document.addEventListener(type, (event) => {
      const host = inChart(event.target);
      const gesture = host && gestures.get(host);
      if (gesture?.active && (!event.touches || event.touches.length === 0)) {
        gesture.active = false;
        gesture.until = performance.now() + 350;
      }
    }, { capture: true, passive: true });
  }
})();
