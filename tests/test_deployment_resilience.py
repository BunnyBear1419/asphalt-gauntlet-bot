"""Regression checks for the CI workflow and Discloud deployment ownership."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"


def _source():
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_runs_verification():
    source = _source()
    assert "pytest -q" in source
    assert "pip-audit -r requirements.txt" in source
    assert "python -m compileall -q ." in source
    assert "pip check" in source


def test_ci_workflow_does_not_deploy_to_discloud():
    source = _source()
    assert "discloud/deploy-action@" not in source
    assert "DISCLOUD_TOKEN" not in source
    assert "api.discloud.app/v2/app" not in source
    assert "Production deployment is owned by Discloud GitHub Integration." in source


def test_ci_workflow_validates_required_homepage_asset():
    source = _source()
    assert 'HERO_JPG="ALU_Gauntlet/web/static/assets/home-hero-4k.jpg"' in source
    assert "JPEG image data" in source
