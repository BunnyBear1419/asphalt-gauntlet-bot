from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ALU_Gauntlet" / "web" / "static"
CORE = ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py"

BROKEN_VAR_ALPHA = re.compile(r"var\(--rsl-[^)]+\)[0-9a-fA-F]{2}(?![0-9a-fA-F])")


def test_no_theme_variable_is_followed_by_raw_hex_alpha():
    files = list(STATIC.glob("*.css")) + list(STATIC.glob("*.html")) + [CORE]
    failures = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        matches = BROKEN_VAR_ALPHA.findall(text)
        if matches:
            failures[str(path.relative_to(ROOT))] = matches
    assert not failures, f"Invalid theme variable alpha syntax: {failures}"


def test_core_theme_first_paint_defaults_to_dark():
    source = CORE.read_text(encoding="utf-8")
    assert 'document.documentElement.setAttribute("data-theme",saved || "dark");' in source


def test_orange_palette_final_text_remains_valid():
    source = CORE.read_text(encoding="utf-8")
    assert "--rsl-final-text:#fff0e5" in source


def test_branding_cleanup_imports_object_id():
    source = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "public.py").read_text(encoding="utf-8")
    assert "from bson import ObjectId" in source


def test_light_theme_action_buttons_use_high_contrast_text():
    source = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
    assert 'html[data-theme="light"] .qa-blue' in source
    assert 'html[data-theme="light"] .discord-cta-button{color:#fff!important}' in source
