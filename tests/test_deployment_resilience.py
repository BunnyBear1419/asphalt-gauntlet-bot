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
    assert "PREDEPLOY_RELEASE_SHA: ${{ steps.predeploy.outputs.release_sha }}" in source
    assert "PREVIOUS_SHA: ${{ steps.revision.outputs.previous_sha }}" in source
    assert "Validated rollback revision" in source
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
    assert "Check production web RSL health endpoint" in source
    assert 'https://asph.discloud.app/rsl-healthz' in source
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
    assert 'https://asph.discloud.app/rsl-healthz' in source
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
    assert "(steps.restart.outcome == 'failure' || steps.smoke.outcome == 'failure' || steps.deploy_gate.outcome == 'failure') && steps.rollback_deploy.outcome == 'failure'" in source


def test_rollback_retry_conditions_preserve_failure_precedence():
    source = _source()
    assert "if: (steps.restart.outcome == 'failure' || steps.smoke.outcome == 'failure' || steps.deploy_gate.outcome == 'failure') && steps.rollback_deploy.outcome == 'failure'" in source


def test_recovery_success_requires_rollback_restart_and_verification():
    source = _source()
    assert "id: rollback_restart" in source
    assert "continue-on-error: true" in source
    assert "id: rollback_verify" in source
    assert "steps.rollback_restart.outcome == 'success'" in source
    assert "Fail recovery if rollback restart or verification failed" in source
    assert "Rollback upload completed, but rollback restart or health verification failed" in source


def test_deployment_start_time_is_not_dead_state():
    source = _source()
    assert "Record deployment start time" not in source
    assert "DEPLOY_STARTED_AT" not in source
    assert "steps.deployment.outputs.started_at" not in source


def test_restart_paths_retry_transient_discloud_failures():
    source = _source()
    assert "Discloud restart attempt $attempt/3 HTTP status" in source
    assert "Restart request did not succeed; retrying in 20 seconds." in source
    assert "Discloud restart failed after 3 attempts." in source
    assert "Rollback Discloud restart attempt $attempt/3 HTTP status" in source
    assert "Rollback restart request did not succeed; retrying in 20 seconds." in source
    assert "Rollback Discloud restart failed after 3 attempts." in source


def test_rollback_revision_must_be_a_distinct_committed_predecessor():
    source = _source()
    assert 'current="$(git rev-parse HEAD)"' in source
    assert 'if [ "$previous" = "$current" ]' in source
    assert 'Rollback revision resolves to the release being deployed.' in source
    assert 'git merge-base --is-ancestor "$previous" "$current"' in source
    assert "Rollback revision is a committed predecessor of the release." in source


def test_discloud_ignore_excludes_ci_and_test_artifacts():
    ignore = (ROOT / ".discloudignore").read_text(encoding="utf-8")
    for entry in [".git", ".github", "tests", "__pycache__", ".pytest_cache", "*.pyc", "*.pyo", ".coverage"]:
        assert entry in ignore


def test_rollback_recovery_verifies_web_surface():
    source = _source()
    assert "Rollback web surface verification passed." in source
    assert "rollback-web-login.html" in source
    assert "rollback-web-css.css" in source
    assert "rollback-web-home.html" in source
    assert "Rollback PNG artwork" in source
    assert "rollback-web-home-stale.html" in source
    assert "invalid-production-rollback-session" in source


def test_predeploy_heartbeat_capture_survives_transient_mongo_failures():
    source = _source()
    assert "A transient Mongo outage on the runner must not block a deployment." in source
    assert "heartbeat_at=0" in source
    assert "Pre-deployment heartbeat baseline: $heartbeat_at" in source
    assert "PREVIOUS_HEARTBEAT_AT:" in source


def test_post_deploy_heartbeat_python_block_is_valid():
    source = _source()
    start = source.index('HEARTBEAT_OK=$(MONGO_URI=')
    block_start = source.index("python - <<'PY'", start) + len("python - <<'PY'")
    block_end = source.index("\n          PY", block_start)
    import textwrap
    script = textwrap.dedent(source[block_start:block_end]).strip("\n")
    compile(script, "deploy-heartbeat", "exec")

def test_all_embedded_deploy_python_blocks_are_valid():
    """Catch indentation/syntax regressions in any Python heredoc in deploy.yml."""
    import re
    import textwrap

    source = _source()
    blocks = re.findall(
        r"^[ \t]*python - <<'PY'\s*\n(?P<body>.*?)^[ \t]*PY[ \t]*$",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert blocks, "Expected at least one embedded Python heredoc in deploy.yml"
    for index, body in enumerate(blocks, 1):
        script = textwrap.dedent(body).strip("\n")
        compile(script, f"deploy-heredoc-{index}", "exec")


def test_failed_discloud_deploy_attempts_enter_recovery_path():
    source = _source()
    assert "id: deploy_gate" in source
    assert "All Discloud deployment attempts failed; entering the recovery path." in source
    assert "steps.deploy_gate.outcome == 'failure'" in source
    assert "Clean failed-release workspace before rollback upload" in source
    assert "Deploy rollback to Discloud" in source
    assert "Restart Discloud app after rollback upload" in source
    assert "Verify rollback health" in source


def test_deployment_marks_and_verifies_exact_runtime_revision():
    source = _source()
    assert 'printf "%s\\n" "$GITHUB_SHA" > rsl-release-sha.txt' in source
    assert 'ROLLBACK_SHA="${{ steps.predeploy.outputs.release_sha || steps.revision.outputs.previous_sha }}"' in source
    assert 'printf "%s\\n" "$ROLLBACK_SHA" > .rsl-release-sha' in source
    assert 'EXPECTED_ROLLBACK_SHA: ${{ steps.predeploy.outputs.release_sha || steps.revision.outputs.previous_sha }}' in source
    assert 'Pre-deployment production release' in source
    assert 'Rollback revision mismatch: expected' in source
    assert 'Rollback heartbeat revision mismatch: expected' in source


def test_runtime_release_identity_is_exposed_by_health_and_heartbeat():
    server = (ROOT / "ALU_Gauntlet" / "web" / "server.py").read_text(encoding="utf-8")
    core = (ROOT / "ALU_Gauntlet" / "core" / "core.py").read_text(encoding="utf-8")
    release = (ROOT / "ALU_Gauntlet" / "release.py").read_text(encoding="utf-8")
    assert "current_release_revision" in server
    assert '"release_sha": current_release_revision()' in server
    assert "current_release_revision" in core
    assert '"release_sha": current_release_revision()' in core
    assert "Path(__file__).resolve().parents[1] / \".rsl-release-sha\"" in release