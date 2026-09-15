from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE = REPO_ROOT / "ALU_Gauntlet" / "core" / "core.py"
HEALTH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "production-health.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _runtime_database_name():
    source = CORE.read_text(encoding="utf-8")
    match = re.search(
        r'get_database\(\s*[\"\']([^\"\']+)[\"\']\s*\)',
        source,
    )
    assert match, "Bot core must define an explicit MongoDB database name."
    return match.group(1)


def test_production_health_uses_the_bot_database_name():
    database_name = _runtime_database_name()
    workflow = HEALTH_WORKFLOW.read_text(encoding="utf-8")

    assert f'client["{database_name}"]' in workflow, (
        "Production health monitoring must query the same MongoDB database "
        f"used by the bot: {database_name!r}."
    )


def test_environment_example_uses_the_bot_database_name():
    database_name = _runtime_database_name()
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")

    mongo_uri_match = re.search(r"^MONGO_URI=.*?/([^/?#]+)(?:\?|$)", env_example, re.MULTILINE)
    assert mongo_uri_match, "The environment example must include a MongoDB URI with a database name."
    assert mongo_uri_match.group(1) == database_name, (
        "The example MONGO_URI database name must match the bot runtime database: "
        f"expected {database_name!r}, found {mongo_uri_match.group(1)!r}."
    )
