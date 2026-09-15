from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "ALU_Gauntlet" / "core" / "core.py"
HEALTH = ROOT / ".github" / "workflows" / "production-health.yml"
BACKUP = ROOT / ".github" / "workflows" / "mongodb-backup.yml"
BACKUP_VERIFY = ROOT / ".github" / "workflows" / "mongodb-backup-verify.yml"
RESTORE_TEST = ROOT / ".github" / "workflows" / "mongodb-restore-test.yml"
ENV_EXAMPLE = ROOT / ".env.example"

EXPECTED_DB = "asphalt_gauntlet"


def test_bot_uses_the_production_database_name():
    source = CORE.read_text(encoding="utf-8")
    assert f'get_database("{EXPECTED_DB}")' in source


def test_production_health_uses_the_same_database_name():
    source = HEALTH.read_text(encoding="utf-8")
    assert f'client["{EXPECTED_DB}"]' in source


def test_backup_workflows_use_the_same_database_name():
    for path in (BACKUP, BACKUP_VERIFY, RESTORE_TEST):
        source = path.read_text(encoding="utf-8")
        assert EXPECTED_DB in source, f"{path} is not using {EXPECTED_DB!r}"


def test_env_example_documents_the_same_database_name():
    source = ENV_EXAMPLE.read_text(encoding="utf-8")
    match = re.search(r"^MONGO_URI=.*?\.mongodb\.net/([^?\s]+)", source, re.MULTILINE)
    assert match, ".env.example must document a MongoDB database in MONGO_URI"
    assert match.group(1) == EXPECTED_DB
