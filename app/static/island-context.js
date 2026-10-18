(() => {
  "use strict";
  document.addEventListener("dashboard:updated", event => {
    const data = event.detail, body = document.body.dataset;
    if (body.role === "guest" || !/^[1-9]\d*$/.test(body.viewerId || "") ||
        String(data?.preferences?.viewer_id) !== body.viewerId || !data.island_context) return;
    try { window.MutsumiAndroid?.syncIslandContext?.(JSON.stringify(data.island_context)); }
    catch (error) { console.warn("native_island_context_failed", error); }
  });
})();
