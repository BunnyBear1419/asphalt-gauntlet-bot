from pathlib import Path
import ast
import re
import subprocess
import textwrap

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
    start = source.index("(function(){")
    end = source.index("</script>", start)
    script = source[start:end]
    node = textwrap.dedent(
        """
        globalThis.localStorage = { getItem: () => null };
        globalThis.document = {
          documentElement: {
            value: "",
            setAttribute(name, value) {
              if (name === "data-theme") this.value = value;
            }
          }
        };
        __SCRIPT__
        if (document.documentElement.value !== "dark") process.exit(1);
        """
    ).replace("__SCRIPT__", script)
    subprocess.run(["node", "--input-type=module"], input=node, text=True, check=True)


def test_orange_palette_final_text_remains_valid():
    source = CORE.read_text(encoding="utf-8")
    assert "--rsl-final-text:#fff0e5" in source


def test_branding_cleanup_imports_object_id_inside_cleanup_block():
    source = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "public.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "save_admin_branding")
    cleanup_if = next(
        node for node in ast.walk(fn)
        if isinstance(node, ast.If) and any(
            isinstance(name, ast.Name) and name.id == "superseded_asset_ids"
            for name in ast.walk(node.test)
        )
    )
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "bson"
        and any(alias.name == "ObjectId" for alias in node.names)
        for node in cleanup_if.body
    )


def test_all_themes_force_shared_form_controls_to_theme_tokens():
    source = (ROOT / "ALU_Gauntlet" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert "html[data-theme] input:not([type=\"checkbox\"]):not([type=\"radio\"])" in source
    assert "html[data-theme] select" in source
    assert "html[data-theme] textarea" in source
    assert "background:var(--rsl-box)!important" in source
    assert "color:var(--rsl-box-text)!important" in source
    assert "border-color:var(--rsl-box-line)!important" in source

def test_light_theme_action_buttons_use_high_contrast_text():
    source = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
    assert 'html[data-theme="light"] .qa-blue' in source
    assert 'html[data-theme="light"] .discord-cta-button{color:#fff!important}' in source


def test_final_theme_control_surface_contract():
    source = (ROOT / "ALU_Gauntlet" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert 'html[data-theme] input:not([type="checkbox"]):not([type="radio"])' in source
    assert 'html[data-theme] select option' in source
    assert 'html[data-theme] select optgroup' in source
    assert 'html[data-theme] input[type="file"]::file-selector-button' in source
    assert 'color-scheme:dark' in source
    assert 'html[data-theme="light"]' in source and 'color-scheme:light' in source
    assert 'var(--rsl-box-accent)' in source
    core = (ROOT / "ALU_Gauntlet" / "web" / "routes" / "core.py").read_text(encoding="utf-8")
    assert 'html[data-theme] .admin-upload-drop' in core
    assert 'html[data-theme] .server-control select' in core
    assert 'html[data-theme] .news-form select' in core
    assert 'html[data-theme] .tournament-create select' in core
