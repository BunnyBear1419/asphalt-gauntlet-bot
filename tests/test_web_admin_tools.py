from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
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
        "Community Links",
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
