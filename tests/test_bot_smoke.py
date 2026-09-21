from pathlib import Path
import py_compile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ALU_Gauntlet"


def test_main_exists():
    assert (ROOT / "main.py").is_file()


def test_main_compiles():
    py_compile.compile(str(ROOT / "main.py"), doraise=True)


def test_requirements_exists():
    assert (ROOT / "requirements.txt").is_file()


def test_cogs_package_exists():
    assert PACKAGE.is_dir()
    assert (PACKAGE / "__init__.py").is_file()
    assert (PACKAGE / "core" / "core.py").is_file()
    assert (PACKAGE / "cogs" / "__init__.py").is_file()


def test_all_cogs_exist():
    expected = {
        "player.py",
        "defense.py",
        "challenges.py",
        "competition.py",
        "staff.py",
        "season.py",
        "administration.py",
        "help.py",
        "system.py",
        "operations.py",
        "dashboard_setup_bridge.py",
        "tournament.py",
        "asphalt_account.py",
        "notifications.py",
    }
    actual = {p.name for p in (PACKAGE / "cogs").glob("*.py") if p.name != "__init__.py"}
    assert actual == expected
