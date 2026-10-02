from __future__ import annotations

import importlib.util
import tarfile
from pathlib import Path


def _load_main():
    spec = importlib.util.spec_from_file_location("check_sdist", Path("scripts/check_sdist.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


main = _load_main()


def _write_sdist(path: Path, members: dict[str, str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(f"ai_pipeline-0.1.0/{name}")
            info.size = len(payload)
            from io import BytesIO

            archive.addfile(info, BytesIO(payload))


def _valid_members() -> dict[str, str]:
    return {
        "README.md": "# AI Pipeline\n",
        "MANIFEST.in": "include README.md\n",
        "pyproject.toml": '[project]\nname = "ai-pipeline"\n',
        "config/pipeline.defaults.yaml": "enabled: false\n",
        "docs/configuration.md": "# Configuration\n",
        "docs/publishing-runbook.md": "# Publishing Runbook\n",
        "docs/smoke-testing.md": "# Smoke Testing\n",
        "docs/web-access-boundary.md": "# Web Access Boundary\n",
        "examples/tasks/README.md": "# Task examples\n",
        "examples/tasks/dry-run/task.example.json": "{}\n",
        "examples/tasks/local/task.ai-art.example.json": "{}\n",
        "examples/tasks/local/task.japanese.example.json": "{}\n",
        "examples/tasks/publish/task.publish.json": "{}\n",
        "profiles/anime.yaml": "name: anime\n",
        "profiles/finance.yaml": "name: finance\n",
        "src/content_pipeline/api/app.py": "",
        "src/content_pipeline/cli/main.py": "",
        "src/content_pipeline/web/static/app.js": "",
        "src/content_pipeline/web/static/content-studio.js": "",
        "src/content_pipeline/web/static/index.html": "",
        "src/content_pipeline/web/static/styles.css": "",
    }


def test_check_sdist_accepts_expected_distribution_contents(tmp_path: Path) -> None:
    sdist = tmp_path / "ai_pipeline-0.1.0.tar.gz"
    _write_sdist(sdist, _valid_members())

    assert main([str(sdist)]) == 0


def test_check_sdist_rejects_sensitive_members(tmp_path: Path) -> None:
    sdist = tmp_path / "ai_pipeline-0.1.0.tar.gz"
    members = _valid_members()
    members[".env.production"] = "WEB_ADMIN_TOKEN=secret"
    _write_sdist(sdist, members)

    assert main([str(sdist)]) == 1


def test_check_sdist_rejects_generated_directories(tmp_path: Path) -> None:
    sdist = tmp_path / "ai_pipeline-0.1.0.tar.gz"
    members = _valid_members()
    members["output/job/status.json"] = "{}"
    _write_sdist(sdist, members)

    assert main([str(sdist)]) == 1


def test_check_sdist_rejects_diagnostic_bundles(tmp_path: Path, capsys) -> None:
    sdist = tmp_path / "ai_pipeline-0.1.0.tar.gz"
    members = _valid_members()
    members["diagnostics.zip"] = "diagnostics"
    members["docs/diagnostics-prod.zip"] = "diagnostics"
    _write_sdist(sdist, members)

    assert main([str(sdist)]) == 1
    captured = capsys.readouterr()
    assert "diagnostics.zip" in captured.err
    assert "docs/diagnostics-prod.zip" in captured.err


def test_check_sdist_rejects_python_cache_artifacts(tmp_path: Path, capsys) -> None:
    sdist = tmp_path / "ai_pipeline-0.1.0.tar.gz"
    members = _valid_members()
    members["src/content_pipeline/__pycache__/models.cpython-311.pyc"] = "bytecode"
    members["src/content_pipeline/cache.pyo"] = "bytecode"
    _write_sdist(sdist, members)

    assert main([str(sdist)]) == 1
    captured = capsys.readouterr()
    assert "src/content_pipeline/__pycache__/models.cpython-311.pyc" in captured.err
    assert "src/content_pipeline/cache.pyo" in captured.err


def test_check_sdist_requires_production_docs_and_examples(tmp_path: Path, capsys) -> None:
    sdist = tmp_path / "ai_pipeline-0.1.0.tar.gz"
    members = _valid_members()
    del members["docs/publishing-runbook.md"]
    _write_sdist(sdist, members)

    assert main([str(sdist)]) == 1
    captured = capsys.readouterr()
    assert "missing required sdist members: docs/publishing-runbook.md" in captured.err


def test_check_sdist_reports_invalid_archive(tmp_path: Path, capsys) -> None:
    sdist = tmp_path / "ai_pipeline-0.1.0.tar.gz"
    sdist.write_text("not a tar archive", encoding="utf-8")

    assert main([str(sdist)]) == 1
    captured = capsys.readouterr()
    assert "invalid sdist archive:" in captured.err
