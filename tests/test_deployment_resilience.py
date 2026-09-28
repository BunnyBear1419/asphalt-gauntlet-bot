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
    assert source.count("app_id: asph") == 5
    assert "secrets.DISCLOUD_APP_ID" not in source


def test_deployment_has_post_deploy_smoke_test():
    source = _source()
    assert "Post-deployment smoke test" in source
    assert "production_heartbeat" in source
    assert "DEPLOY_STARTED_AT" in source
    assert "Discord API" in source
    assert "MongoClient" in source
    assert "Discloud" in source
    assert "seq 1 12" in source
    assert "waiting 10 seconds" in source
    assert "seq 1 6" in source


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
    assert "Restart Discloud app after rollback upload" in source
    assert "Install deployment check dependencies" in source
    assert "cache: 'pip'" in source
    assert "https://api.discloud.app/v2/app/${DISCLOUD_APP_ID}/restart" in source
    assert "Verify rollback health" in source
    assert "Mark deployment failed after successful recovery" in source


def test_deployment_is_serialized_to_avoid_discloud_overlap():
    source = _source()
    assert "group: discloud-production-deploy" in source
    assert "cancel-in-progress: false" in source

def test_deployment_cleans_ci_artifacts_before_upload():
    source = _source()
    assert "Clean CI-generated files before Discloud upload" in source
    assert "find . -type d -name __pycache__ -prune -exec rm -rf {} +" in source
    assert "rm -rf .pytest_cache" in source
    assert "discord-preflight.json" in source


# CI trigger: run the full GitHub Actions test suite against current main.


def test_rollback_upload_failure_blocks_recovery_success():
    source = _source()
    assert "Fail recovery if rollback upload failed" in source
    assert "steps.rollback_deploy.outcome == 'failure'" in source
    assert "steps.rollback_retry.outcome == 'failure'" in source
    assert "Refusing to restart or mark production recovered" in source


def test_rollback_cleans_failed_release_workspace_before_upload():
    source = _source()
    assert "Clean failed-release workspace before rollback upload" in source
    assert "git clean -fdx" in source
    assert "known-good Git revision" in source


def test_production_health_checks_web_health_endpoint():
    source = (ROOT / ".github" / "workflows" / "production-health.yml").read_text(encoding="utf-8")
    assert "Check production web health endpoint" in source
    assert 'https://asph.discloud.app/healthz' in source
    assert 'web-health.json' in source
    assert 'data.get("ok")' in source

def test_post_deploy_smoke_requires_fresh_production_heartbeat():
    source = _source()
    assert 'PREVIOUS_HEARTBEAT_AT: ${{ steps.predeploy.outputs.heartbeat_at }}' in source
    assert 'Production heartbeat gate: $HEARTBEAT_OK' in source
    assert 'timestamp <= previous' in source
    assert 'age > 120' in source
    assert 'production_heartbeat' in source


def test_rollback_recovery_requires_web_health_endpoint():
    source = _source()
    assert 'rollback-web-health.json' in source
    assert 'https://asph.discloud.app/healthz' in source
    assert 'Rollback web health HTTP status' in source
    assert 'rollback_web_ok' in source
    assert '[ "$rollback_web_ok" = "true" ]' in source

def test_rollback_recovery_requires_fresh_heartbeat():
    source = _source()
    assert "Capture pre-rollback heartbeat" in source
    assert "PREVIOUS_ROLLBACK_HEARTBEAT_AT" in source
    assert "timestamp <= previous" in source
    assert "time.time() - timestamp > 120" in source
    assert "fresh post-rollback heartbeat" in source

def test_smoke_heartbeat_probe_retries_transient_mongo_failures():
    source = _source()
    assert ') || HEARTBEAT_OK=false' in source
    assert 'Production heartbeat gate: $HEARTBEAT_OK' in source
    assert 'seq 1 12' in source


def test_rollback_recovery_survives_transient_mongo_failures():
    source = _source()
    assert 'heartbeat_at=0' in source
    assert 'rollback_heartbeat_ok=false' in source
    assert 'Rollback heartbeat probe failed or is not fresh yet; retrying.' in source
    assert '[ "$rollback_heartbeat_ok" = "true" ]' in source


def test_restart_failure_enters_rollback_path():
    source = _source()
    assert "id: restart" in source
    assert "continue-on-error: true" in source
    assert "if: steps.restart.outcome == 'success'" in source
    assert "if: steps.restart.outcome == 'failure' || steps.smoke.outcome == 'failure'" in source
    assert "Both rollback uploads failed" in source
    assert "(steps.restart.outcome == 'failure' || steps.smoke.outcome == 'failure') && steps.rollback_deploy.outcome == 'failure'" in source
