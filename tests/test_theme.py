from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_colors_follow_focus_state_except_score_deltas():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "body.page-focus,body.is-focusing { --accent:#7a5bc7" in css
    assert ":root { --ink:#20272f" in css and "--accent:#d66c58" in css
    assert "idle: [\"#d66c58\", \"#b25647\", \"#dd9073\"" in javascript
    assert "#ef5b3f" not in css
    assert "#ef5b3f" not in javascript
    assert ".progress i" in css and "background:#a8afb5" in css
    assert ".progress-history span" in css and "background:var(--accent)" in css
    assert ".heat-cell.l1{background:var(--heat-l1)}" in css
    assert "--score-positive:#09685f" in css
    assert "--score-negative:#b83c2c" in css
    assert 'focus: ["#7a5bc7"' in javascript
    assert "#148b7d" not in css
    assert "#148b7d" not in javascript


def test_heatmap_scale_and_current_time_art_are_fixed():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    image = ROOT / "app" / "static" / "current-time-art.jpg"

    assert image.is_file()
    assert "minmax(0,40.5%)" in css
    assert ".heatmap" in css and "width:100%" in css
    assert ".heat-grid" in css and "gap:3.5px; width:100%" in css
    assert ".heat-hours" in css and "gap:3.5px" in css
    assert ".heat-cell { min-width:0; aspect-ratio:1" in css
    assert "user-select:none" in css
    assert ".heat-cell.selected" not in css
    assert 'classList.add("selected")' not in javascript
    assert 'background:url("current-time-art.jpg") right center/auto 100% no-repeat' in css
    assert "right:8px" in css
    assert "opacity:.8" in css


def test_status_bar_uses_stacked_date_and_tall_score_billboard():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".status-title { display:grid" in css
    assert ".status-title i { grid-row:1 / 3" in css
    assert ".score-window { flex:1; height:38px" in css
    assert ".score-row" in css and "height:38px" in css
    assert "translateY(-152px)" in css


def test_time_cards_use_window_duration_widths_and_compact_titles():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    template = (ROOT / "app" / "templates" / "dashboard.html").read_text(encoding="utf-8")

    assert "grid-template-columns:468px minmax(280px,var(--morning-window)) minmax(0,var(--library-window))" in css
    assert ".time-card h2 { color:var(--muted); font-size:13px" in css
    assert ".time-card > strong { display:block; margin-top:5px" in css
    assert ".progress-meta { display:flex; justify-content:space-between; margin-top:10px" in css
    assert ".progress { position:relative; height:8px; margin-top:5px" in css
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
    assert ".focus-compare-row.today i { background:var(--accent)" in css
    assert ".focus-comparison-view.ahead .focus-compare-row.today i" not in css
    assert ".focus-comparison-view.behind .focus-compare-row.today i" not in css
    assert ".focus-message-card" in css and "height:96px; min-height:0" in css
    assert ".focus-message-card::after { content:attr(data-index)" in css
    assert "@keyframes message-card-in" in css
