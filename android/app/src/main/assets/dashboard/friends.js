(() => {
  if (window.DashboardFriends) return;

  function rank(entries) {
    entries.sort((a, b) => b.seconds - a.seconds
      || String(b.date).localeCompare(String(a.date))
      || Number(Boolean(a.friendKey)) - Number(Boolean(b.friendKey)));
    let previous = null, total = null, position = 0;
    return entries.map((entry, index) => {
      if (entry.seconds !== total) {
        previous = total;
        total = entry.seconds;
        position = index + 1;
      }
      return { ...entry, rank: position, gap_to_previous_seconds: previous === null ? null : previous - total };
    });
  }

  function visibleRows(entries, todayKey) {
    const featured = entries.flatMap((entry, index) => entry.friendKey || entry.date === todayKey ? [index] : []);
    if (!featured.length) return [];
    if (featured.every((index) => index < 5)) return entries.slice(0, 5);
    const fixed = featured.some((index) => index < 4) ? 4 : 3;
    const indices = [...entries.slice(0, fixed).keys(), ...featured.filter((index) => index >= fixed)];
    return indices.flatMap((index, slot) => slot > 0 && index > indices[slot - 1] + 1
      ? [{ isGap: true }, entries[index]] : [entries[index]]);
  }

  function leaderboard(leaderboard, todayKey, extraSeconds, friend) {
    const baseline = (leaderboard?.entries || []).map((entry) => ({ ...entry, seconds: Number(entry.seconds || 0) }));
    const existing = baseline.find((entry) => entry.date === todayKey);
    if (existing) existing.seconds += extraSeconds;
    else if (extraSeconds || leaderboard?.today?.seconds) {
      baseline.push({ date: todayKey, seconds: Number(leaderboard?.today?.seconds || 0) + extraSeconds });
    }
    const history = rank(baseline);
    const comparison = Number(friend?.seconds) > 0
      ? rank([...history, { date: todayKey, friendKey: friend.key, name: friend.name, seconds: Number(friend.seconds) }])
      : history;
    return {
      history,
      ownToday: history.find((entry) => entry.date === todayKey),
      today: comparison.find((entry) => !entry.friendKey && entry.date === todayKey),
      rows: visibleRows(comparison, todayKey),
    };
  }

  function bindAccount({ api, showToast, requestConfirmation, escapeHtml, formatSeconds }) {
    const byId = (id) => document.getElementById(id);
    const list = byId("friend-list");
    const panel = byId("blockcolc-friends-connect");
    const form = byId("blockcolc-link-form");
    const token = byId("blockcolc-friend-token");
    const edit = byId("blockcolc-edit-link");
    const disconnect = byId("blockcolc-disconnect");
    const integrationsUrl = "/api/integrations/blockcolc-friends";
    const errorMessages = {
      blockcolc_invalid_token: "请填入方块钟生成的读取好友令牌。",
      blockcolc_expired: "令牌已失效或过期，请重新生成。",
      blockcolc_scope: "这个令牌缺少「读取好友」权限。",
      blockcolc_rate_limited: "方块钟请求较多，请稍后重试。",
      blockcolc_unavailable: "暂时无法连接方块钟，请稍后重试。",
      friend_not_found: "此好友暂不可用，请刷新列表后重试。",
    };
    let sequence = 0, busy = false, editing = false, listSignature = "", pollPending = false;
    let linkStatus = "disconnected", selected = null;

    function renderLink(link) {
      if (!panel) return;
      const status = link?.status || "disconnected";
      linkStatus = status;
      const messages = {
        disconnected: "尚未连接",
        connected: "已连接",
        expired: "令牌已失效",
        scope: "缺少读取好友权限",
        unavailable: "同步暂时中断",
      };
      const stamp = link?.synced_at
        ? new Date(link.synced_at * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "";
      const caption = [link?.name, messages[status]].filter(Boolean).join(" · ");
      const statusText = byId("blockcolc-sync-status");
      if (statusText.textContent !== caption) statusText.textContent = caption;
      byId("blockcolc-sync-time").textContent = status === "connected" && stamp ? ` · 已同步 ${stamp}` : "";
      form.hidden = !editing && (status === "connected" || status === "unavailable");
      edit.hidden = !form.hidden;
      disconnect.hidden = status === "disconnected";
      panel.hidden = false;
    }

    function friendRow(friend, status) {
      const external = friend.source === "blockcolc";
      const key = escapeHtml(friend.key || `local:${friend.id}`);
      const name = escapeHtml(friend.username);
      const isSelected = (friend.key || `local:${friend.id}`) === selected;
      const details = external
        ? ["方块钟", friend.focusing === true ? "正在专注" : "", friend.today_seconds != null
          ? `今日 ${formatSeconds(friend.today_seconds)}` : status === "unavailable" ? "暂无最新时长" : "未分享每日时长"].filter(Boolean).join(" · ")
        : friend.email || "站内好友";
      return `<div class="friend-row"><div class="friend-identity"><b>${external ? name : `@${name}`}</b><small>${escapeHtml(details)}</small></div><div class="friend-row-actions"><button class="ui-button ui-button--sm ${isSelected ? "ui-button--secondary" : "ui-button--quiet"}" type="button" data-rank-friend="${key}" aria-pressed="${isSelected}">${isSelected ? "榜单显示中" : "在榜单显示"}</button>${external ? "" : `<button class="ui-button ui-button--danger ui-button--sm" type="button" data-remove-friend="${name}">移除</button>`}</div></div>`;
    }

    function render(data) {
      selected = data.selected_friend;
      renderLink(data.blockcolc);
      const friends = data.friends || [];
      const content = friends.length
        ? friends.map((friend) => friendRow(friend, linkStatus)).join("")
        : '<div class="loading-row">暂无好友，可搜索站内用户或连接方块钟。</div>';
      if (content !== listSignature) {
        listSignature = content;
        list.innerHTML = content;
      }
    }

    async function load() {
      const read = ++sequence;
      const data = await api("/api/friends");
      if (read === sequence) render(data);
    }

    async function mutate(action, message) {
      if (busy) return;
      busy = true;
      sequence++;
      list.setAttribute("aria-busy", "true");
      panel?.setAttribute("aria-busy", "true");
      try {
        await action();
        await load();
        showToast(message);
      } catch (error) {
        showToast(errorMessages[error.message] || error.message);
      } finally {
        busy = false;
        list.removeAttribute("aria-busy");
        panel?.removeAttribute("aria-busy");
      }
    }

    list.addEventListener("click", async (event) => {
      const rankButton = event.target.closest("[data-rank-friend]");
      const remove = event.target.closest("[data-remove-friend]");
      if (rankButton) {
        const key = rankButton.dataset.rankFriend === selected ? null : rankButton.dataset.rankFriend;
        await mutate(() => api("/api/friends/leaderboard-selection", { method: "PUT", body: JSON.stringify({ key }) }),
          key === null ? "已清除榜单好友" : "已在今日榜单显示该好友");
      } else if (remove && await requestConfirmation({
        title: "移除好友", message: `移除好友 @${remove.dataset.removeFriend} 后，双方列表都会更新。`, label: "移除好友", tone: "danger",
      })) {
        await mutate(() => api(`/api/friends/${encodeURIComponent(remove.dataset.removeFriend)}`, { method: "DELETE" }), "好友已移除");
      }
    });

    edit?.addEventListener("click", () => {
      editing = true;
      edit.hidden = true;
      form.hidden = false;
      token.focus();
    });
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      const secret = token.value.trim();
      void mutate(async () => {
        await api(integrationsUrl, { method: "PUT", body: JSON.stringify({ token: secret }) });
        editing = false;
        token.value = "";
      }, "已连接方块钟账户");
    });
    disconnect?.addEventListener("click", () => {
      void mutate(async () => {
        await api(integrationsUrl, { method: "DELETE" });
        editing = false;
        token.value = "";
      }, "已断开方块钟连接");
    });

    async function refreshVisible() {
      if (busy || pollPending || document.visibilityState !== "visible" || list.offsetParent === null) return;
      pollPending = true;
      try { await load(); } catch { /* Keep the current UI until the next refresh. */ }
      finally { pollPending = false; }
    }
    document.addEventListener("visibilitychange", refreshVisible);
    window.setInterval(refreshVisible, 5000);
    return { load };
  }

  window.DashboardFriends = { leaderboard, bindAccount };
})();
