from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]

def test_rsl_coach_extension_is_guild_scoped_and_deterministic():
    source = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "rsl_coach.py").read_text(encoding="utf-8")
    page = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rsl-coach.html").read_text(encoding="utf-8")
    init = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "__init__.py").read_text(encoding="utf-8")
    assert "deterministic-rsl-data" in source
    assert '"guild_id": guild' in source
    assert '{"guild_id": guild, "user_id": uid}' in source
    assert "/api/rsl/coach" in source
    assert 'self.app.router.add_get("/rsl-coach"' in source
    assert "Practice Priorities" in page
    assert "No external AI service" in page
    assert "rsl_coach" in init

def test_rsl_coach_helper_prefers_largest_actionable_gap():
    spec = importlib.util.spec_from_file_location("rsl_coach_test_module", ROOT / "ALU_Gauntlet" / "web" / "routes" / "rsl_coach.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.build_coach_recommendations(
        personal_rows=[
            {"track": "Track A", "best_ms": 95000},
            {"track": "Track B", "best_ms": 100000},
        ],
        reference_rows=[
            {"course": "Track A", "time": "1:34.000", "official": True},
            {"course": "Track B", "time": "1:35.000", "official": True},
        ],
        tracks=["Track A", "Track B", "Track C"],
    )
    assert result["recommendations"][0]["track"] == "Track B"
    assert result["recommendations"][0]["gap_ms"] == 5000
    assert result["learn_next"][0]["track"] == "Track C"
