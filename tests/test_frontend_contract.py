import re
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


def test_javascript_id_selectors_exist_in_html() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    html_ids = re.findall(r'\bid="([^"]+)"', html)
    direct_id_selectors = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', javascript))
    assert len(html_ids) == len(set(html_ids)), "HTML中存在重复id"
    assert direct_id_selectors <= set(html_ids), sorted(direct_id_selectors - set(html_ids))


def test_frontend_uses_versioned_assets_and_no_removed_single_file_state() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    assert "/static/js/app.js?v=" in html
    assert "/static/css/app.css?v=" in html
    assert re.search(r"state\.selectedFile(?!s)", javascript) is None
    assert '$("#material-type")' not in javascript
    assert 'id="sidebar-scrim"' in html
    assert '$("#sidebar-scrim").addEventListener("click"' in javascript
    assert 'event.key === "Escape"' in javascript
    assert "body.nav-open .sidebar-scrim" in css
    assert "场景验证中心" in html
    assert ("评委" + "演示中心") not in html
    assert ("国" + "赛") not in html


def test_care_mode_read_aloud_and_readiness_ui_are_wired() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")

    for identifier in [
        "care-mode-toggle",
        "care-flow-status",
        "read-page-aloud",
        "runtime-status",
        "readiness-panel",
        "readiness-grid",
    ]:
        assert f'id="{identifier}"' in html
    assert "function setCareMode" in javascript
    assert "function speakVisiblePage" in javascript
    assert "function renderReadiness" in javascript
    assert "state.currentView = view;" in javascript
    assert 'navigator.serviceWorker.register("/sw.js"' in javascript
    assert ".care-mode-active" in css
    assert ".readiness-grid" in css


def test_pwa_manifest_and_service_worker_do_not_cache_api() -> None:
    manifest = (STATIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8")
    worker = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    assert '"scope": "/"' in manifest
    assert 'url.pathname.startsWith("/api/")' in worker
    assert "caches.match(\"/\")" in worker


def test_every_view_is_registered_in_router() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    views = set(re.findall(r'data-view="([a-z0-9_-]+)"', html))
    nav_targets = set(re.findall(r'data-nav="([a-z0-9_-]+)"', html))
    page_info_match = re.search(r"const pageInfo = \{(?P<body>.*?)\n\};", javascript, re.DOTALL)
    assert page_info_match, "未找到前端pageInfo路由表"
    registered = set(
        re.findall(r"^\s*([a-z0-9_-]+):\s*\[", page_info_match.group("body"), re.MULTILINE)
    )
    assert views == registered
    assert nav_targets <= views
