from __future__ import annotations

import json
from pathlib import Path

from content_pipeline.models import TaskInput
from content_pipeline.task_validation import validate_task_params


def _example_jsons(tier: str) -> list[Path]:
    return sorted(Path("examples/tasks", tier).glob("*.json"))


def _current_example_jsons() -> list[Path]:
    return sorted(
        path for tier in ("dry-run", "local", "publish") for path in Path("examples/tasks", tier).glob("*.json")
    )


def _all_example_jsons() -> list[Path]:
    return sorted(Path("examples/tasks").glob("**/*.json"))


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_task_examples_validate_against_task_input_model() -> None:
    examples = _all_example_jsons()

    assert examples
    for path in examples:
        TaskInput.model_validate_json(path.read_text(encoding="utf-8"))


def test_current_task_examples_validate_against_pipeline_param_models() -> None:
    examples = _current_example_jsons()

    assert examples
    for path in examples:
        task = TaskInput.model_validate_json(path.read_text(encoding="utf-8"))
        if task.content_type is not None:
            validate_task_params(task)


def test_task_examples_readme_documents_risk_tiers_and_validation_workflow() -> None:
    readme = Path("examples/tasks/README.md").read_text(encoding="utf-8")

    assert "organized by risk level" in readme
    assert "`dry-run/`: no external publishing" in readme
    assert "must keep `publish: false` and `params.dry_run: true`" in readme
    assert "`local/`: real local generation/editing examples with `publish: false`" in readme
    assert "not permission to upload" in readme
    assert "`publish/`: real private/draft publishing examples" in readme
    assert "may call platform uploaders" in readme
    assert "## Safe validation workflow" in readme
    assert "ai-pipeline validate-task --task examples/tasks/<tier>/<file>.json" in readme
    assert "inspect `status.json`, `events.jsonl`, generated artifacts, and `artifacts.validation`" in readme
    assert "docs/publishing-runbook.md" in readme
    assert "## Production contract" in readme
    assert "`publish/` examples are intentionally dangerous" in readme
    assert "missing visibility proof is not success" in readme


def test_dry_run_examples_never_publish_and_keep_dry_run_enabled() -> None:
    examples = _example_jsons("dry-run")

    assert examples
    for path in examples:
        task = _read_json(path)
        params = task.get("params", {})
        assert task.get("publish") is False, path
        assert isinstance(params, dict), path
        assert params.get("dry_run") is True, path


def test_local_examples_never_publish() -> None:
    examples = _example_jsons("local")

    assert examples
    for path in examples:
        task = _read_json(path)
        assert task.get("publish") is False, path


def test_publish_examples_are_explicitly_marked_dangerous() -> None:
    examples = _example_jsons("publish")

    assert examples
    for path in examples:
        task = _read_json(path)
        assert task.get("publish") is True, path
