"""Every served JavaScript source must at least parse.

A single stray quote or missing brace can make the browser drop an entire
script and silently disable page controls. These checks use Node's parser so
syntax errors are caught before deployment.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "ALU_Gauntlet" / "web" / "static"
INLINE_SCRIPT = re.compile(r"<script(?P<attrs>[^>]*)>(?P<code>.*?)</script>", re.S | re.I)
JS_TYPES = {"", "text/javascript", "application/javascript"}


def _node_check(code: str) -> str:
    """Return an empty string when the code parses, otherwise a concise error."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        name = handle.name
    try:
        result = subprocess.run(
            ["node", "--check", name],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        Path(name).unlink(missing_ok=True)
    if result.returncode == 0:
        return ""
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    return next(
        (line for line in lines if line.startswith("SyntaxError")),
        lines[-1] if lines else "unknown error",
    )


def _require_node():
    if shutil.which("node") is None:
        pytest.skip("Node.js is required for the JavaScript syntax check")


def test_static_javascript_files_parse():
    _require_node()
    failures = {
        path.name: error
        for path in sorted(STATIC.glob("*.js"))
        if (error := _node_check(path.read_text(encoding="utf-8")))
    }
    assert not failures, f"JavaScript files with syntax errors: {failures}"


def test_inline_scripts_in_static_pages_parse():
    _require_node()
    failures = {}
    for page in sorted(STATIC.glob("*.html")):
        html = page.read_text(encoding="utf-8")
        for index, match in enumerate(INLINE_SCRIPT.finditer(html)):
            attrs = match.group("attrs")
            if re.search(r"\bsrc\s*=", attrs) or not match.group("code").strip():
                continue
            declared = re.search(r"""\btype\s*=\s*["']?([^"'\s>]+)""", attrs)
            if declared and declared.group(1).lower() not in JS_TYPES:
                continue
            if error := _node_check(match.group("code")):
                failures[f"{page.name} (inline script #{index})"] = error
    assert not failures, f"Inline scripts with syntax errors: {failures}"
