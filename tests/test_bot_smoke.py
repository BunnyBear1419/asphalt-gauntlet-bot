from pathlib import Path
import py_compile


ROOT = Path(__file__).resolve().parents[1]


def test_main_exists():
    assert (ROOT / "main.py").is_file()


def test_main_compiles():
    py_compile.compile(str(ROOT / "main.py"), doraise=True)


def test_requirements_exists():
    assert (ROOT / "requirements.txt").is_file()
