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
