from __future__ import annotations

from pathlib import Path

import yaml


def test_quality_workflow_runs_project_quality_gate() -> None:
    workflow_path = Path(".github/workflows/quality.yml")
    assert workflow_path.is_file()

    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert workflow["name"] == "Quality Gate"
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is True

    triggers = workflow["on"]
    assert "pull_request" in triggers
    assert "push" in triggers
    assert triggers["push"]["branches"] == ["master"]
    assert "workflow_dispatch" in triggers

    job = workflow["jobs"]["check"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] <= 15

    steps = job["steps"]
    uses = [step.get("uses") for step in steps]
    assert "actions/checkout@v4" in uses
    assert "astral-sh/setup-uv@v5" in uses
    assert "actions/setup-python@v5" in uses
    assert "actions/setup-node@v4" in uses
    node_step = next(step for step in steps if step.get("uses") == "actions/setup-node@v4")
    assert node_step["with"] == {"node-version": "24"}

    runs = [step.get("run") for step in steps]
    assert "uv sync --extra test --extra dev" in runs
    assert "bash scripts/check.sh" in runs

    assert "actions/upload-artifact@v4" in uses
    artifact_step = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
    assert artifact_step["with"] == {
        "name": "ai-pipeline-dist",
        "path": "dist/check/*",
        "if-no-files-found": "error",
        "retention-days": 14,
    }

    docker_job = workflow["jobs"]["docker-build"]
    assert docker_job["runs-on"] == "ubuntu-latest"
    assert docker_job["timeout-minutes"] <= 20
    assert docker_job["needs"] == "check"
    docker_steps = docker_job["steps"]
    docker_uses = [step.get("uses") for step in docker_steps]
    assert "actions/checkout@v4" in docker_uses
    assert "docker/setup-buildx-action@v3" in docker_uses
    assert "docker/build-push-action@v6" in docker_uses
    build_step = next(step for step in docker_steps if step.get("uses") == "docker/build-push-action@v6")
    assert build_step["with"] == {
        "context": ".",
        "file": "Dockerfile",
        "push": False,
        "load": False,
        "tags": "ai-pipeline:ci",
        "cache-from": "type=gha",
        "cache-to": "type=gha,mode=max",
    }
