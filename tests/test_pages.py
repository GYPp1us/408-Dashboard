import pytest


@pytest.fixture()
def authenticated_client(tmp_path):
    from app import create_app

    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "pages.sqlite3"),
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "test-password",
        "COOKIE_SECURE": False,
    })
    client = app.test_client()
    client.post("/login", data={"password": "test-password"})
    return client


def test_dashboard_has_status_bar_and_no_sidebar_or_switch_bar(authenticated_client):
    html = authenticated_client.get("/").get_data(as_text=True)

    assert "<small>今日有效学习</small>" not in html
    assert "<small>近期模拟考</small>" not in html
    assert "score-board" in html
    assert 'id="today-date" class="console-date"' in html
    assert "2 小时级" in html
    assert "focus-modes" in html
    assert "drag-action" in html
    assert "score-chart" in html
    assert "近期专注记录" not in html
    assert 'id="focus-investment-view"' in html
    assert 'id="investment-average-stack"' in html
    assert 'id="investment-subject-stack"' in html
    assert 'id="investment-today-stack"' in html
    assert "lunch-start-label" in html
    assert "library-history" in html
    assert "home-window-label" in html
    assert "home-window-countdown" in html
    assert "上午学习窗口 · 距离午休" not in html
    assert "focus-summary" in html
    assert "session-goal-chart" in html
    assert "today-subject-chart" in html
    assert "summary-today-total" in html
    assert "rest-timer" in html
    assert "长期计划" not in html
    assert "时间窗口、专注状态和长期数据在同一个工作面完成过渡。" not in html
    assert "/static/vendor/chart.umd.js" in html
    assert "/static/vendor/Draggable.min.js" in html
    assert "active-mode-view" in html
    assert 'id="open-quick-score"' in html
    assert 'id="quick-score-modal"' in html
    assert 'id="quick-score-form"' in html
    assert "<h2>快捷专注</h2>" not in html
    assert "选择科目后滑动启动" not in html
    assert "sidebar" not in html
    assert "topnav" not in html


def test_quick_score_shortcut_and_compact_focus_modes_are_in_assets(authenticated_client):
    javascript = authenticated_client.get("/static/app.js").get_data(as_text=True)

    assert 'event.key.toLowerCase() === "n"' in javascript
    assert 'event.preventDefault();' in javascript
    assert 'modal.showModal();' in javascript
    assert "不限时专注" not in javascript
    assert '<span class="drag-label">${escapeHtml(mode.subject)}</span>' in javascript
    assert '<span class="drag-label">滑动启动</span>' not in javascript
    assert "function renderFocusInvestment(investment, active)" in javascript


def test_dashboard_runtime_keeps_awake_syncs_and_uses_one_second_clock(authenticated_client):
    javascript = authenticated_client.get("/static/app.js").get_data(as_text=True)

    assert 'navigator.wakeLock.request("screen")' in javascript
    assert "window.setInterval(syncDashboard, 500)" in javascript
    assert "secondTasks: new Map()" in javascript
    assert 'setSecondTask("clock"' in javascript
    assert 'setSecondTask("status"' in javascript
    assert 'setSecondTask("windows"' in javascript
    assert 'setSecondTask("focus"' in javascript
    assert 'setSecondTask("investment"' in javascript
    assert "setInterval(tick, 1000)" not in javascript


def test_focus_client_token_has_legacy_browser_fallbacks(authenticated_client):
    javascript = authenticated_client.get("/static/app.js").get_data(as_text=True)

    assert "function createClientToken()" in javascript
    assert 'typeof cryptoApi.randomUUID === "function"' in javascript
    assert 'typeof cryptoApi.getRandomValues === "function"' in javascript
    assert "client_token: createClientToken()" in javascript
    assert "client_token: crypto.randomUUID()" not in javascript


def test_guest_dashboard_replaces_controls_with_today_summary(authenticated_client):
    html = authenticated_client.get("/guest").get_data(as_text=True)

    assert 'data-role="guest"' in html
    assert "本日总结" in html
    assert 'id="guest-today-total"' in html
    assert 'id="guest-subject-list"' in html
    assert 'href="/admin"' in html
    assert 'id="focus-modes"' not in html
    assert 'id="end-focus"' not in html
    assert 'id="open-quick-score"' not in html
    assert 'id="quick-score-modal"' not in html
    assert 'href="/settings"' not in html


def test_focus_page_uses_single_dashboard_route(authenticated_client):
    response = authenticated_client.get("/focus")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_settings_is_small_low_frequency_entry(authenticated_client):
    html = authenticated_client.get("/settings").get_data(as_text=True)

    assert "设置" in html
    assert "时间窗口" in html
    assert "长期计划" not in html
    assert "数据中心" not in html
    assert "热度图显示时段" in html
    assert 'name="heatmap_visible_hours"' in html
    assert html.count("data-heat-hour=") == 12
