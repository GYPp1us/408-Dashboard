from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_colors_follow_focus_state_except_score_deltas():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "body.page-focus,body.is-focusing { --accent:#8067b3" in css
    assert ":root { --ink:#20272f" in css and "--accent:#d66c58" in css
    assert "idle: [\"#d66c58\", \"#b25647\", \"#dd9073\"" in javascript
    assert "#ef5b3f" not in css
    assert "#ef5b3f" not in javascript
    assert ".progress i" in css and "background:#a8afb5" in css
    assert "--window-accent:#c98072" in css
    assert "--window-accent:#8879a6" in css
    assert ".progress-history span" in css and "background:var(--window-accent)" in css
    assert ".heat-cell.l1{background:var(--heat-l1)}" in css
    assert "--score-positive:#09685f" in css
    assert "--score-negative:#b83c2c" in css
    assert 'focus: ["#8067b3"' in javascript
    assert "#148b7d" not in css
    assert "#148b7d" not in javascript


def test_heatmap_scale_and_current_time_art_are_fixed():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    image = ROOT / "app" / "static" / "current-time-art.jpg"

    assert image.is_file()
    assert "grid-template-columns:minmax(300px,1.5fr) minmax(330px,3fr) minmax(440px,2fr)" in css
    assert "body { min-width:1280px" in css
    assert ".active-mode-view { position:relative; width:100%" in css
    assert "--dashboard-panel-height:352px" in css
    assert ".focus-modes { display:grid; height:auto; grid-template-columns:1fr; grid-auto-rows:auto; align-content:start; gap:8px" in css
    assert ".focus-launch-actions { display:grid; height:32px" in css
    assert ".mode .drag-launch { height:100%" not in css
    assert ".heatmap" in css and "width:100%" in css
    assert ".heat-grid" in css and "gap:3.5px; width:100%" in css
    assert "cursor:grab; touch-action:pan-y" in css
    assert ".heat-hours" in css and "gap:3.5px" in css
    assert ".heat-cell { min-width:0; aspect-ratio:1" in css
    assert "user-select:none" in css
    assert ".heat-cell.selected" not in css
    assert 'classList.add("selected")' not in javascript
    assert "const gapRatio = .27" in javascript
    assert "cell * gapRatio" in javascript
    assert "dayCount + (dayCount - 1) * gapRatio" in javascript
    assert ".heat-cell.fade-25 { opacity:.25; }" in css
    assert ".heat-cell.fade-50 { opacity:.5; }" in css
    assert ".heat-cell.fade-75 { opacity:.75; }" in css
    assert ".activity-switch { position:relative; z-index:2" in css
    assert 'background:url("current-time-art.jpg") right center/auto 100% no-repeat' in css
    assert "right:8px" in css
    assert "opacity:.8" in css


def test_status_bar_uses_stacked_date_and_tall_score_billboard():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".status-bar { display:grid; grid-template-columns:minmax(220px,1fr) max-content minmax(250px,320px) max-content max-content" in css
    assert ".status-title { display:grid" in css
    assert ".status-title { display:grid; grid-template-columns:9px minmax(0,1fr); grid-template-rows:auto auto; align-items:center; gap:2px 8px; min-width:0; text-align:left" in css
    assert ".status-title i { grid-row:1 / 3" in css
    assert ".exam-countdown { display:flex; align-items:baseline; gap:7px" in css
    assert ".score-window { flex:1; height:38px" in css
    assert ".score-row { display:flex; align-items:center; gap:10px" in css
    assert ".today-study { display:flex; flex-direction:column; align-items:flex-start" in css
    assert ".current-state { display:flex; align-items:center; gap:6px" in css
    assert "translateY(-152px)" in css


def test_time_cards_use_window_duration_widths_and_compact_titles():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    template = (ROOT / "app" / "templates" / "dashboard.html").read_text(encoding="utf-8")

    assert "grid-template-columns:468px minmax(280px,var(--morning-window)) minmax(0,var(--library-window))" in css
    assert ".time-card h2 { color:var(--muted); font-size:13px" in css
    assert ".time-card > strong { display:block; margin-top:5px" in css
    assert ".current-time-card > strong { margin-top:5px" in css
    assert ".current-time-card .current-window { margin:0" in css
    assert ".progress-meta { display:flex; justify-content:space-between; margin-top:10px" in css
    assert ".progress { position:relative; height:14px; margin-top:5px; overflow:hidden; border-radius:4px" in css
    assert ".mode .drag-launch { margin-top:0" in css
    assert ".drag-launch .drag-label { font-size:13px" in css
    assert "<h2>当前时间</h2>" not in template
    assert 'style.setProperty("--morning-window"' in javascript
    assert 'style.setProperty("--library-window"' in javascript
    assert "data.windows.morning.total_seconds" in javascript
    assert "data.windows.library.total_seconds" in javascript


def test_focus_investment_uses_stacked_linear_charts_and_state_colors():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".investment-charts { display:grid" in css
    assert "grid-template-rows:auto auto auto" in css
    assert ".investment-chart { display:flex; flex-direction:column; padding:10px 0 11px" in css
    assert "min-height:470px" not in css
    assert ".linear-stack { display:flex; height:14px" in css
    assert ".linear-stack .stack-primary { background:var(--accent)" in css
    assert ".investment-trend.up { background:#e7f3ef; color:var(--score-positive)" in css
    assert ".investment-trend.down { background:#faebe8; color:var(--score-negative)" in css
    assert ".focus-comparison-view.ahead .focus-compare-trend" in css
    assert ".focus-comparison-view.behind .focus-compare-trend" in css
    assert "--diff-positive" not in css and "--diff-negative" not in css
    assert ".focus-comparison-view.ahead .focus-compare-trend { background:#e7f3ef; color:var(--score-positive)" in css
    assert ".focus-comparison-view.behind .focus-compare-trend { background:#faebe8; color:var(--score-negative)" in css
    assert ".focus-diff-track" not in css
    assert ".focus-diff-scale" not in css
    assert ".score-row em.good { color:var(--score-positive)" in css
    assert ".score-row em.bad { color:var(--score-negative)" in css
    assert ".focus-compare-trend { width:100%; padding:0 10px" in css
    assert ".focus-leaderboard { display:grid; grid-template-columns:minmax(0,4fr) minmax(108px,1fr)" in css
    assert ".score-paper-bands { position:relative; display:grid; gap:5px; padding:5px 8px; border:1px solid var(--line)" in css
    assert ".score-strip { display:flex; min-height:44px" in css
    assert ".score-strip-option { display:grid; width:64px; min-width:64px; height:44px" in css
    assert ".focus-leaderboard-quantile { display:flex; min-width:0; min-height:0; flex-direction:column; overflow:hidden" in css
    assert ".focus-leaderboard-profile" in css
    assert "height:min(100%,calc(100% - 38px)); max-height:calc(100% - 38px)" in css
    assert ".focus-leaderboard-metric strong { overflow:hidden; color:var(--ink); font-size:16px" in css
    assert ".focus-profile-row { position:relative; display:flex; min-height:0; align-items:center; padding:0 8px; --profile-row-height:10px" in css
    assert ".focus-leaderboard-profile { display:grid" in css
    assert ".focus-profile-marker { position:absolute" in css and "width:calc(var(--profile-row-height) / 3)" in css
    assert ".focus-profile-current-marker { position:absolute" in css
    assert "clip-path:polygon(0 0,100% 50%,0 100%)" in css
    assert "border:1px solid #fff" in css
    assert ".focus-profile-row.is-current i { background:var(--accent-deep)" in css
    assert ".focus-profile-row.is-profitable i { background:var(--accent)" in css
    assert ".focus-profile-row.is-muted" in css
    assert ".focus-profile-row.is-current i" in css
    assert "@media (max-width:560px)" not in css
    assert "html.native-app .activity-panel,html.native-app .investment-panel,html.native-app .mode-panel" in css


def test_settings_page_uses_modern_two_column_editor_layout():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".settings-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert ".settings-content-grid { display:grid; grid-template-columns:.72fr 1.28fr" in css
    assert ".settings-editor textarea" in css and "min-height:190px" in css


def test_pause_and_trust_controls_use_text_and_status_box_styles():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".focus-pause-button" in css and "width:52px" in css
    assert ".focus-trust-state" in css and "background:#e7f3ef; color:var(--score-positive)" in css
    assert ".focus-trust-state.untrusted { background:#faebe8; color:var(--score-negative)" in css


def test_focus_comparison_labels_share_the_same_header_row():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".focus-compare-value { display:grid; grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert ".focus-compare-value > span { grid-column:1; grid-row:1" in css
    assert ".focus-compare-time { grid-column:2; grid-row:1" in css
    assert ".focus-compare-value > strong,.focus-compare-trend { display:flex; grid-row:2; align-items:center; height:38px" in css
    assert ".focus-compare-trend { width:100%; padding:0 10px" in css
