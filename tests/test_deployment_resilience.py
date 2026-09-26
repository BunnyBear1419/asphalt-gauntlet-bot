"""Regression tests for CI/CD deployment safety contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"


def _source():
    return WORKFLOW.read_text(encoding="utf-8")


def test_deploy_workflow_runs_tests_before_deployment():
    source = _source()
    assert "needs: test" in source
    assert "pytest -q" in source
    assert "pip-audit -r requirements.txt" in source
    assert "python -m compileall -q ." in source


def test_discloud_action_is_pinned_to_commit():
    source = _source()
    assert "discloud/deploy-action@fae7024653d941a19daa2b6f56d2ae208e008c54" in source
    assert "discloud/deploy-action@v1" not in source
    assert source.count("app_id: asph") == 2


def test_deployment_has_post_deploy_smoke_test():
    source = _source()
    assert "Post-deployment smoke test" in source
    assert "production_heartbeat" in source
    assert "DEPLOY_STARTED_AT" in source
    assert "Discord API" in source
    assert "MongoClient" in source
    assert "Discloud" in source


def test_discloud_smoke_test_matches_working_production_monitor():
    source = _source()
    assert 'curl -sS -o discloud-status.json -w "%{http_code}"' in source
    assert '"api-token: $DISCLOUD_TOKEN"' in source
    assert 'https://api.discloud.app/v2/app/${DISCLOUD_APP_ID}/status' in source
    assert "urllib.request" not in source
    assert "The prior" in source


def test_failed_smoke_test_rolls_back_previous_revision():
    source = _source()
    assert "Determine rollback revision" in source
    assert "previous_sha" in source
    assert "Roll back to previous known-good revision" in source
    assert "ref: ${{ steps.revision.outputs.previous_sha }}" in source
    assert "Deploy rollback to Discloud" in source
    assert "Verify rollback health" in source
    assert "Mark deployment failed after successful recovery" in source


def test_deployment_is_serialized_to_avoid_discloud_overlap():
    source = _source()
    assert "group: discloud-production-deploy" in source
    assert "cancel-in-progress: false" in source

# CI trigger: run the full GitHub Actions test suite against current main.
