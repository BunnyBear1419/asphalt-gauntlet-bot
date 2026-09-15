from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_VERIFY = REPO_ROOT / ".github" / "workflows" / "mongodb-backup-verify.yml"

# Operational MongoDB collections that must survive backup/restore verification.
# Keep this contract synchronized with collections created by the bot.
EXPECTED_OPERATIONAL_COLLECTIONS = {
    "drivers",
    "pending",
    "matches",
    "active_challenges",
    "season_state",
    "season_history",
    "settings",
    "reference_pending",
    "lap_times",
    "lap_time_history",
    "map_records",
    "map_references",
    "system_events",
}


def _required_collections_from_workflow():
    source = BACKUP_VERIFY.read_text(encoding="utf-8")
    match = re.search(
        r"required\s*=\s*\{(?P<body>.*?)\}\s*\n\s*missing\s*=",
        source,
        re.DOTALL,
    )
    assert match, "Backup verification workflow must define its required collection contract."
    return set(re.findall(r'"([A-Za-z0-9_]+)"', match.group("body")))


def test_backup_verification_covers_all_operational_collections():
    required = _required_collections_from_workflow()
    missing_from_verification = EXPECTED_OPERATIONAL_COLLECTIONS - required
    assert not missing_from_verification, (
        "Operational MongoDB collections missing from backup verification: "
        + ", ".join(sorted(missing_from_verification))
    )


def test_backup_verification_does_not_verify_unknown_collections():
    required = _required_collections_from_workflow()
    unknown = required - EXPECTED_OPERATIONAL_COLLECTIONS
    assert not unknown, (
        "Backup verification lists collections that are not in the operational "
        "collection contract: " + ", ".join(sorted(unknown))
    )
