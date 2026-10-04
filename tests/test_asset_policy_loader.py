from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_asset_policy_loader_has_safe_fallbacks():
    js = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rsl-asset-policy.js").read_text(encoding="utf-8")
    assert "rsl-car-silhouette.svg" in js
    assert "rsl-track-map.svg" in js
    assert "rsl-division-badge.svg" in js
    assert "addEventListener("error"" in js
    assert "window.RSLAssetPolicy" in js
