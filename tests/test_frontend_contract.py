import re
from pathlib import Path

from app.version import APP_VERSION

STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


def _sources() -> tuple[str, str, str]:
    return (
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8"),
        (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8"),
    )


def test_javascript_id_selectors_exist_in_html() -> None:
    html, javascript, _ = _sources()
    html_ids = re.findall(r'\bid="([^"]+)"', html)
    direct_id_selectors = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', javascript))
    assert len(html_ids) == len(set(html_ids)), "HTML中存在重复id"
    assert direct_id_selectors <= set(html_ids), sorted(direct_id_selectors - set(html_ids))


def test_new_information_architecture_separates_resident_and_professional_work() -> None:
    html, javascript, css = _sources()
    pages = set(re.findall(r'data-page="([a-z0-9_-]+)"', html))
    assert pages == {"home", "screening", "documents", "evidence", "trust", "professional"}
    assert 'id="page-professional"' in html
    assert "面向工作人员和项目验收，不与居民服务混用" in html
    assert "function navigate" in javascript
    assert "[data-page=\"${route}\"]" in javascript
    assert ".professional-page" in css
    assert "sidebar" not in html.lower()


def test_structured_first_ai_has_confirmable_supplement_closed_loop() -> None:
    html, javascript, css = _sources()
    for identifier in [
        "assistive-narrative", "parse-assistive", "assistive-extraction",
        "narrative", "analyze-supplement", "supplement-result", "wizard-steps",
        "profile-review", "screening-consent", "screen-submit",
    ]:
        assert f'id="{identifier}"' in html
    assert "填写有困难？使用辅助录入" in html
    assert "还有需要特别说明的情况" in html
    assert "AI不会直接改表，也不会直接判断资格" in html
    assert "async function parseAssistiveNarrative" in javascript
    assert "async function analyzeSupplement" in javascript
    assert "/api/v1/profile/analyze-supplement" in javascript
    assert "data-continue-assistive" in javascript
    assert "data-candidate-action" in javascript
    assert "pendingSupplementCandidates" in javascript
    assert "function updateReview" in javascript
    assert "result.next_question.plain_language || result.next_question.label" in javascript
    assert "result.next_question.question" not in javascript
    assert ".ai-result" in css
    assert ".supplement-workbench" in css
    assert ".supplement-candidate" in css
    assert 'id="residence_proof"' in html
    assert 'id="resolution-panel"' in html
    assert "data-fix-field" in javascript


def test_results_are_semantically_layered_and_never_force_first_item() -> None:
    html, javascript, _ = _sources()
    for identifier in [
        "outcome-banner", "matched-results", "related-results", "review-results", "unmatched-results",
        "next-action-card", "calculation-summary", "audit-trail-content",
    ]:
        assert f'id="{identifier}"' in html
    assert 'item.status === "likely"' in javascript
    assert '["incomplete", "manual_review"].includes(item.status)' in javascript
    assert 'item.status === "unlikely"' in javascript
    assert 'code: "no_current_match"' in javascript
    assert "系统没有强行推荐任何事项" in javascript
    assert "report.results[0]" not in javascript
    assert 'class="action-number" aria-hidden="true"' in javascript


def test_resident_language_avoids_internal_profile_and_plan_jargon() -> None:
    html, _, _ = _sources()
    resident_html = html.split('id="page-professional"', 1)[0]
    assert "生成画像" not in resident_html
    assert "主路径" not in resident_html
    assert "分层备选" not in resident_html
    assert "联动事项" not in resident_html
    assert "我家可以了解" not in resident_html
    assert "一句清楚的结论" in resident_html


def test_document_upload_has_visible_feedback_and_real_package_api() -> None:
    html, javascript, css = _sources()
    for identifier in [
        "upload-selection", "selected-file-title", "selected-file-list",
        "selected-file-count", "clear-selected-files", "document-result",
    ]:
        assert f'id="{identifier}"' in html
    assert "function selectFiles" in javascript
    assert "/api/v1/documents/package-precheck" in javascript
    assert ".upload-selection" in css
    assert ".drop-zone.dragging" in css


def test_policy_evidence_discloses_temporal_and_retrieval_context() -> None:
    html, javascript, _ = _sources()
    assert 'id="evidence-as-of"' in html
    assert 'id="evidence-results"' in html
    assert "/api/v1/policy/answer" in javascript
    assert "excluded_evidence" in javascript
    assert "政策逐字原文" in javascript
    assert "查看政府原文" in javascript
    assert "引用白名单、数值来源、越权表达、逐字核验均通过" in javascript


def test_safety_gate_controls_render_and_print() -> None:
    html, javascript, css = _sources()
    assert 'id="print-safety-block"' in html
    assert re.search(r'id="print-report" disabled', html)
    assert "function safetyGateAllowsReport" in javascript
    assert "function renderSafetyBlock" in javascript
    assert 'error.code === "SAFETY_GATE_BLOCKED"' in javascript
    assert 'document.body.dataset.printAuthorized = "true"' in javascript
    assert 'body:not([data-print-authorized="true"])>*' in css


def test_mobile_navigation_accessibility_and_pwa_are_wired() -> None:
    html, javascript, css = _sources()
    assert 'id="mobile-menu"' in html
    assert 'id="nav-scrim"' in html
    assert 'event.key === "Escape"' in javascript
    assert 'navigator.serviceWorker.register("/sw.js"' in javascript
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css
    assert "skip-link" in html


def test_pwa_manifest_and_service_worker_use_current_version_without_api_cache() -> None:
    manifest = (STATIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8")
    worker = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    assert '"start_url": "/#home"' in manifest
    assert '"scope": "/"' in manifest
    assert f"huimin-shell-v{APP_VERSION}" in worker
    assert 'url.pathname.startsWith("/api/")' in worker
    assert 'caches.match("/")' in worker


def test_professional_tools_keep_unknown_and_ai_policy_compiler_visible() -> None:
    html, javascript, _ = _sources()
    for identifier in ["worker-form", "worker-output", "compiler-text", "compiler-use-llm", "compiler-output", "admin-token"]:
        assert f'id="{identifier}"' in html
    for identifier in ["worker-hukou", "worker-member", "worker-assets", "worker-urgent"]:
        select = re.search(rf'<select id="{identifier}">(?P<options>.*?)</select>', html, re.DOTALL)
        assert select
        assert select.group("options").lstrip().startswith('<option value="">')
    assert "async function compilePolicy" in javascript
    assert "/api/v1/admin/policy/compile" in javascript
    assert "/api/v1/admin/policy/impact" in javascript
    compiler = re.search(r'<select id="compiler-benefit">(?P<options>.*?)</select>', html, re.DOTALL)
    assert compiler
    assert compiler.group("options").lstrip().startswith('<option value="">')
    assert "候选规则与影响分析已生成，仍禁止自动发布" in javascript


def test_direct_form_is_primary_and_ai_filling_is_optional() -> None:
    html, _, _ = _sources()
    assert 'class="primary-action" type="button" data-route="screening" data-screen-start="manual"' in html
    assert "填写有困难？使用辅助录入" in html
    assert "如果还有表格说不清的经历" in html
