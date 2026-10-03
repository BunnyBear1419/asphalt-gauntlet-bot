from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_all_python_sources_are_readable_and_have_no_undefined_names():
    """Keep the runtime NameError fixes protected by the same F821 rule as CI."""
    sources = [
        path
        for root in (ROOT / "ALU_Gauntlet", ROOT / "tests")
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert sources, "No Python sources were discovered."
    for path in sources:
        path.read_bytes()

    ruff = shutil.which("ruff")
    if not ruff:
        ruff = sys.executable
        command = [ruff, "-m", "ruff"]
    else:
        command = [ruff]
    command.extend(["check", str(ROOT / "ALU_Gauntlet"), str(ROOT / "tests"), "--select", "F821", "--output-format", "concise"])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, (result.stdout + result.stderr).strip()
