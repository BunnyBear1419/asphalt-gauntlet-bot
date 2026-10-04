from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rights_policy_exists():
    policy = ROOT / "docs" / "RSL_ASSET_RIGHTS_POLICY.md"
    assert policy.exists()
    text = policy.read_text(encoding="utf-8")
    assert "non-affiliation disclaimer" in text
    assert "documented license/permission" in text


def test_legal_page_contains_rights_safeguards():
    legal = (ROOT / "ALU_Gauntlet" / "web" / "static" / "legal.html").read_text(encoding="utf-8")
    assert "not affiliated with, sponsored by, endorsed by" in legal
    assert "A disclaimer does <em>not</em> create a license" in legal
    assert "No scraping or asset extraction" in legal
    assert "User screenshots and media" in legal


def test_original_visuals_remain_the_default_fallback():
    for name in ("rsl-car-silhouette.svg", "rsl-track-map.svg", "rsl-division-badge.svg"):
        assert (ROOT / "ALU_Gauntlet" / "web" / "static" / "assets" / "rsl" / "visuals" / name).exists()
