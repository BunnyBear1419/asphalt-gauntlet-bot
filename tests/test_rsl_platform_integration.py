from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "ALU_Gauntlet" / "web" / "server.py"
STATUS = ROOT / "ALU_Gauntlet" / "web" / "static" / "status.html"
ASSURANCE = ROOT / "ALU_Gauntlet" / "core" / "platform_assurance.py"

def test_assurance_module_covers_new_cross_cutting_controls():
    src = ASSURANCE.read_text(encoding="utf-8")
    for marker in ("redact_document", "privacy_export_metadata", "anti_farm_flags", "anomaly_flags", "readiness_check", "public_status_snapshot", "performance_bucket"):
        assert marker in src

def test_assurance_routes_are_registered_without_duplicate_support_systems():
    src = SERVER.read_text(encoding="utf-8")
    for marker in (
        'add_get("/status", self.platform_status_page)',
        'add_get("/api/status/public", self.public_status)',
        'add_get("/api/privacy/export", self.privacy_export)',
        'add_post("/api/privacy/request", self.privacy_request)',
        'add_get("/api/evidence/timeline", self.evidence_timeline)',
        'add_get("/api/transparency", self.transparency_snapshot)',
        'add_get("/api/notifications/inbox", self.notification_inbox)',
        'add_get("/api/admin/security/events", self.admin_security_events)',
        'add_get("/api/admin/readiness", self.admin_readiness)',
        'add_get("/api/admin/performance", self.admin_performance)',
    ):
        assert marker in src

def test_privacy_requests_keep_support_in_discord():
    src = SERVER.read_text(encoding="utf-8")
    assert "official RSL Discord ticket workflow" in src or "official Discord ticket workflow" in src
    assert "https://discord.gg/q46RQxu2fm" in src

def test_public_status_page_exists_and_uses_public_status_api():
    page = STATUS.read_text(encoding="utf-8")
    assert "RSL SYSTEM STATUS" in page
    assert "/api/status/public" in page

def test_existing_canonical_systems_are_reused():
    src = SERVER.read_text(encoding="utf-8")
    assert 'add_get("/api/admin/diagnostics", self.admin_diagnostics)' in src
    assert 'add_get("/api/player/economy/history", self.player_economy_history)' in src
    assert 'add_get("/api/notifications", self.notification_preferences)' in src
