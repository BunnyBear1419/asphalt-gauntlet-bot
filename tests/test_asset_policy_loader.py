from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_asset_policy_loader_has_safe_fallbacks():
    js = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rsl-asset-policy.js").read_text(encoding="utf-8")
    assert "rsl-car-silhouette.svg" in js
    assert "rsl-track-map.svg" in js
    assert "rsl-division-badge.svg" in js
    assert 'addEventListener("error"' in js
    assert "window.RSLAssetPolicy" in js
    assert 'document.readyState==="loading"' in js
    assert "else init();" in js
    assert "dataset.rslFallback" in js
    assert "querySelectorAll(\"img[data-rsl-asset-src]\")" in js

def test_asset_policy_loader_is_activated_site_wide():
    app = (ROOT / "ALU_Gauntlet" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "initRSLAssetPolicy" in app
    assert "/static/rsl-asset-policy.js" in app
    assert 'data-rsl-asset-policy' in app


def test_asset_policy_themes_original_rsl_visuals():
    js = (ROOT / "ALU_Gauntlet" / "web" / "static" / "rsl-asset-policy.js").read_text(encoding="utf-8")
    assert "THEME_COLORS" in js
    assert "var(--rsl-box-accent)" in js
    assert "var(--rsl-box-alt)" in js
    assert "var(--rsl-box-line)" in js
    assert "var(--rsl-box-muted)" in js
    assert "fetch(src" in js
    assert 'data-rsl-themed' in js
