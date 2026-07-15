from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_colors_follow_focus_state_except_score_deltas():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "body.page-focus,body.is-focusing { --accent:#7a5bc7" in css
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


def test_time_cards_use_window_duration_widths_and_watermark_titles():
    css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "grid-template-columns:360px minmax(0,var(--morning-window)) minmax(0,var(--library-window))" in css
    assert ".time-card h2 { position:absolute" in css
    assert "color:rgba(98,110,104,.24)" in css
    assert 'style.setProperty("--morning-window"' in javascript
    assert 'style.setProperty("--library-window"' in javascript
    assert "data.windows.morning.total_seconds" in javascript
    assert "data.windows.library.total_seconds" in javascript
