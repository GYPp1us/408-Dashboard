(() => {
  "use strict";
  const image = document.getElementById("current-time-art");
  if (!image || !window.DashboardDetails) return;
  const maxBytes = 10 * 1024 * 1024;
  const defaultMotto = "放弃幻想，准备斗争";
  const acceptedTypes = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[char]));
  function applyArtwork(artwork) {
    if (!artwork?.url) return;
    if (image.getAttribute("src") !== artwork.url) image.src = artwork.url;
    image.dataset.custom = String(Boolean(artwork.is_custom));
    const motto = document.getElementById("current-time-motto");
    if (motto) {
      motto.textContent = artwork.motto ?? defaultMotto;
      motto.hidden = !motto.textContent;
    }
  }
  async function request(options = {}) {
    const response = await fetch("/api/dashboard/artwork", { credentials: "same-origin", headers: { Accept: "application/json" }, ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 413) throw new Error("图片超过 10 MiB，请选择较小的文件。");
      if (payload.error === "invalid_motto") throw new Error("标语最多 80 个字，请缩短后再保存。");
      if (response.status === 400) throw new Error("图片无法读取，请选择 PNG、JPG、GIF 或 WebP。");
      if (response.status === 403) throw new Error("请在自己的主页更换表情包。");
      throw new Error("保存失败，请稍后重试。");
    }
    return payload.artwork;
  }
  window.DashboardDetails.register("artwork", async (data) => {
    const artwork = await request({ signal: data.signal });
    applyArtwork(artwork);
    const editable = document.body.dataset.role !== "guest";
    return {
      title: "时间卡片表情包", kicker: "工作台图片与标语",
      html: `<div class="artwork-editor"><div class="artwork-preview-frame"><img class="artwork-preview" data-artwork-preview src="${escape(artwork.url)}" alt="表情包预览"></div>${editable ? `<form class="artwork-upload"><label for="artwork-file">上传自定义表情包</label><input id="artwork-file" name="image" type="file" accept="image/png,image/jpeg,image/gif,image/webp"><p class="artwork-note">PNG、JPG、GIF、WebP · 最大 10 MiB。原图保存，保留动画。</p><label for="artwork-motto">时间卡片标语</label><input id="artwork-motto" name="motto" type="text" maxlength="80" value="${escape(artwork.motto ?? defaultMotto)}" placeholder="${escape(defaultMotto)}"><p class="artwork-note">最多 80 个字，留空后保存可隐藏标语。默认：${escape(defaultMotto)}</p><div class="artwork-actions"><button type="submit" class="ui-button ui-button--primary" data-artwork-save disabled>保存</button><button type="button" class="ui-button ui-button--secondary" data-artwork-reset>恢复默认图片</button></div><p class="artwork-message" role="status"></p></form>` : `<p class="artwork-note">${escape(artwork.motto ?? defaultMotto)}</p><p class="artwork-note">当前主页的表情包与标语。</p>`}</div>`,
      onReady(host) {
        if (!editable) return;
        const form = host.querySelector(".artwork-upload");
        const input = host.querySelector("#artwork-file");
        const mottoInput = host.querySelector("#artwork-motto");
        const preview = host.querySelector("[data-artwork-preview]");
        const save = host.querySelector("[data-artwork-save]");
        const reset = host.querySelector("[data-artwork-reset]");
        const message = host.querySelector(".artwork-message");
        let saved = artwork, selected = null, localUrl = null, busy = false;
        const live = () => !data.signal.aborted && form.isConnected;
        const clearPreview = () => { if (localUrl) URL.revokeObjectURL(localUrl); localUrl = null; };
        const mottoChanged = () => mottoInput.value.trim() !== (saved.motto ?? defaultMotto);
        const updateButtons = () => { input.disabled = busy; mottoInput.disabled = busy; save.disabled = busy || (!selected && !mottoChanged()); reset.disabled = busy || !saved.is_custom; };
        const useSaved = () => { clearPreview(); selected = null; input.value = ""; preview.src = saved.url; updateButtons(); };
        data.signal.addEventListener("abort", clearPreview, { once: true });
        updateButtons();
        mottoInput.addEventListener("input", updateButtons);
        input.addEventListener("change", () => {
          clearPreview();
          selected = input.files?.[0] || null;
          if (!selected) { useSaved(); message.textContent = ""; return; }
          if (selected.size > maxBytes || (selected.type && !acceptedTypes.has(selected.type))) {
            message.textContent = selected.size > maxBytes ? "图片超过 10 MiB，请选择较小的文件。" : "请选择 PNG、JPG、GIF 或 WebP 图片。";
            useSaved(); return;
          }
          localUrl = URL.createObjectURL(selected);
          preview.src = localUrl;
          message.textContent = `正在预览 ${selected.name}，点击保存后应用到主页。`;
          updateButtons();
        });
        async function saveArtwork(options, success) {
          if (busy || !live()) return;
          busy = true; updateButtons();
          message.textContent = "正在保存…";
          try {
            const result = await request({ ...options, signal: data.signal });
            if (!live()) return;
            saved = result; applyArtwork(saved);
            if (options.method === "POST") mottoInput.value = saved.motto ?? defaultMotto;
            useSaved();
            message.textContent = success;
          } catch (error) {
            if (live()) {
              useSaved();
              message.textContent = error.message || "保存失败，请稍后重试。";
            }
          } finally { busy = false; if (live()) updateButtons(); }
        }
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          if (!selected && !mottoChanged()) return;
          const body = new FormData();
          body.append("motto", mottoInput.value);
          if (selected) body.append("image", selected);
          saveArtwork({ method: "POST", body }, "已保存，刷新或换设备后仍会保留。");
        });
        reset.addEventListener("click", () => saveArtwork({ method: "DELETE" }, "已恢复默认表情包。"));
      },
    };
  });
})();
