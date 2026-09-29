from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_unified_profile_exposes_season_history_and_records():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    html = (ROOT / "ALU_Gauntlet" / "web" / "static" / "public-profile.html").read_text(encoding="utf-8")
    js = (ROOT / "ALU_Gauntlet" / "web" / "static" / "public-profile.js").read_text(encoding="utf-8")
    assert "season_history" in server
    assert "rsl_records" in server
    assert 'id="season-history"' in html
    assert 'id="rsl-records"' in html
    assert "career.season_history" in js
    assert "career.rsl_records" in js
