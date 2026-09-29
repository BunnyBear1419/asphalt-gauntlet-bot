from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_rsl_command_center_exists_and_is_wired():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    page = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rsl-command-center.html").read_text(encoding="utf-8")
    script = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rsl-command-center.js").read_text(encoding="utf-8")
    player = (ROOT / "ALU_Gauntlet" / "cogs" / "player.py").read_text(encoding="utf-8")
    assert 'self.app.router.add_get("/rsl-center", self.rsl_command_center_page)' in server
    assert 'async def rsl_command_center_page' in server
    for marker in ("Notifications & Next Actions", "Achievements & Milestones", "Career Activity", "RSL Records", "System Health", "Season"):
        assert marker in page
    for marker in ("/api/leaderboard?", "/api/players/", "/api/status", "/api/season?", "/api/admin/diagnostics"):
        assert marker in script
    assert "RSLCommandCenterButton" in player
    assert 'label="RSL Command Center"' in player
