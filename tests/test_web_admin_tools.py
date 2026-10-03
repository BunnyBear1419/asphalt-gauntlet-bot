from pathlib import Path
from web_source import web_source

ROOT = Path(__file__).resolve().parents[1]
SERVER = web_source()
ADMIN = (ROOT / "ALU_Gauntlet" / "web" / "static" / "admin.html").read_text(encoding="utf-8")


def test_admin_tools_are_exposed_from_profile():
    assert 'href="/admin"' in SERVER
    assert 'id="rsl-admin-tools-link"' in SERVER
    assert '"admin": admin' in SERVER


def test_guild_scoped_white_label_configuration_exists():
    assert 'DEFAULT_WEB_BRANDING' in SERVER
    assert 'settings.get("web_branding")' in SERVER
    assert '"/api/admin/branding"' in SERVER
    assert 'guild_id' in SERVER
    assert 'rsl_guild_id' in SERVER


def test_persistent_brand_asset_upload_exists():
    assert 'web_brand_assets' in SERVER
    assert '"/api/admin/upload-asset"' in SERVER
    assert '"/assets/tenant/{guild_id}/{asset_id}"' in SERVER


def test_admin_control_center_contains_requested_tools():
    for text in (
        "Website Branding",
        "Images &amp; Media",
        "Links",
        "Site Settings",
        "Members &amp; Roles",
        "Gauntlet Management",
        "Tournament Management",
        "Club Management",
        "Diagnostics",
        "Audit Log",
        "Force Discord Sync",
        "Download Configuration Backup",
    ):
        assert text in ADMIN


def test_admin_page_has_guild_selector_and_branding_sections():
    assert 'id="guild-select"' in ADMIN
    assert 'id="section-branding"' in ADMIN
    assert 'id="section-media"' in ADMIN
    assert 'id="section-links"' in ADMIN
    assert 'id="section-system"' in ADMIN


def test_admin_image_upload_supports_click_and_drag_drop():
    assert 'id="asset-drop"' in ADMIN
    assert 'dragover' in ADMIN
    assert 'dataTransfer.files' in ADMIN
    assert '8*1024*1024' in ADMIN


def test_admin_document_closes_inline_script_and_has_navigation_recovery():
    page=(ROOT/"ALU_Gauntlet"/"web"/"static"/"admin.html").read_text(encoding="utf-8")
    assert page.rstrip().endswith("</script>\n</body>\n</html>")
    assert "function activate(name)" in page
    assert "data-rsl-nav-recovery" in page
    assert 'activate(hash)' in page


def test_brand_asset_replacement_purges_only_previous_references():
    source = (ROOT / "ALU_Gauntlet/web/routes/public.py").read_text(encoding="utf-8")
    assert "previous_asset_ids = _tenant_asset_ids(json.dumps(previous_branding))" in source
    assert "superseded_asset_ids = previous_asset_ids - new_asset_ids" in source
    assert 'await bucket.delete(ObjectId(str(gridfs_id)))' in source


def test_gridfs_asset_serving_streams_in_bounded_chunks():
    for path in (
        ROOT / "ALU_Gauntlet/web/routes/admin.py",
        ROOT / "ALU_Gauntlet/web/routes/public.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert 'await stream.read(64 * 1024)' in source


def test_csp_diagnostics_is_admin_only_and_aggregated():
    source = (ROOT / "ALU_Gauntlet/web/routes/admin.py").read_text(encoding="utf-8")
    core = (ROOT / "ALU_Gauntlet/web/routes/core.py").read_text(encoding="utf-8")
    assert 'async def admin_csp_diagnostics' in source
    assert '_, guild_id, _guild = await self.require_admin(request)' in source
    assert 'csp_reports.find(' in source
    assert '"report": 1' in source
    assert 'script-sample' not in source.split('async def admin_csp_diagnostics', 1)[1].split('async def admin_diagnostics', 1)[0]
    assert '"/api/admin/csp-diagnostics", self.admin_csp_diagnostics' in core
    assert '"remote"' not in source.split('async def admin_csp_diagnostics', 1)[1].split('async def admin_diagnostics', 1)[0]


def test_csp_report_collector_supports_legacy_and_reporting_api_payloads():
    core = (ROOT / "ALU_Gauntlet/web/routes/core.py").read_text(encoding="utf-8")
    collector = core.split("async def csp_report", 1)[1].split("def _apply_security_headers", 1)[0]
    assert 'payload if isinstance(payload, list) else [payload]' in collector
    assert 'entry.get("csp-report")' in collector
    assert 'entry.get("body")' in collector
    assert 'await self.bot.db.csp_reports.insert_many' in collector
    assert 'datetime.now(timezone.utc)' in collector


def test_csp_report_headers_advertise_both_reporting_formats():
    core = (ROOT / "ALU_Gauntlet/web/routes/core.py").read_text(encoding="utf-8")
    assert 'Content-Security-Policy"' in core
    assert 'Content-Security-Policy-Report-Only' not in core
    assert 'report-uri /api/csp-report' in core
    assert 'report-to rsl-csp' in core
    assert 'Reporting-Endpoints' in core
    assert 'rsl-csp="/api/csp-report"' in core


def test_guild_ownership_audit_is_read_only_and_registered():
    source = (ROOT / "ALU_Gauntlet/web/routes/admin.py").read_text(encoding="utf-8")
    core = (ROOT / "ALU_Gauntlet/web/routes/core.py").read_text(encoding="utf-8")
    page = (ROOT / "ALU_Gauntlet/web/static/admin.html").read_text(encoding="utf-8")
    assert "async def admin_guild_ownership_audit" in source
    audit = source.split("async def admin_guild_ownership_audit", 1)[1].split("async def admin_diagnostics", 1)[0]
    assert "count_documents" in audit
    assert "update_one" not in audit
    assert "delete_one" not in audit
    assert "insert_one" not in audit
    assert '"/api/admin/guild-ownership-audit", self.admin_guild_ownership_audit' in core
    assert 'id="run-guild-ownership-audit"' in page
    assert '"/api/admin/guild-ownership-audit"+q()' in page


def test_guild_ownership_audit_renders_details_without_overwriting_results():
    page = (ROOT / "ALU_Gauntlet/web/static/admin.html").read_text(encoding="utf-8")
    assert 'id="guild-ownership-audit-status"' in page
    assert 'setStatus("guild-ownership-audit-status"' in page
    assert 'id="diagnostic-results" class="admin-log"' in page
    assert 'setStatus("diagnostic-results","Scanning guild-scoped collections' not in page
