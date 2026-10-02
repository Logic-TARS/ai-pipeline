from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path


def _load_main():
    spec = importlib.util.spec_from_file_location("check_wheel", Path("scripts/check_wheel.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


main = _load_main()


def _write_wheel(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _valid_members() -> dict[str, str]:
    return {
        "content_pipeline/config/__init__.py": "",
        "content_pipeline/config/pipeline.defaults.yaml": "enabled: false\n",
        "content_pipeline/api/app.py": "",
        "content_pipeline/cli/main.py": "",
        "content_pipeline/web/static/app.js": "",
        "content_pipeline/web/static/content-studio.js": "",
        "content_pipeline/web/static/index.html": "",
        "content_pipeline/web/static/styles.css": "",
        "ai_pipeline-0.1.0.dist-info/entry_points.txt": (
            "[console_scripts]\nai-pipeline = content_pipeline.cli.main:main\n"
        ),
        "ai_pipeline-0.1.0.dist-info/METADATA": (
            "Metadata-Version: 2.4\n"
            "Name: ai-pipeline\n"
            "Requires-Python: >=3.11\n"
            "Description-Content-Type: text/markdown\n"
            "Classifier: Framework :: FastAPI\n"
            "Classifier: Programming Language :: Python :: 3.11\n"
            "Classifier: Topic :: Multimedia :: Video\n"
            "Keywords: automation,content-pipeline,social-media,video\n"
        ),
    }


def test_check_wheel_accepts_expected_distribution_contents(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    _write_wheel(wheel, _valid_members())

    assert main([str(wheel)]) == 0


def test_check_wheel_rejects_forbidden_members(tmp_path: Path, capsys) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    members = _valid_members()
    members["tests/test_leak.py"] = ""
    _write_wheel(wheel, members)

    assert main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert "forbidden wheel members: tests/test_leak.py" in captured.err


def test_check_wheel_rejects_sensitive_member_names_and_suffixes(tmp_path: Path, capsys) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    members = _valid_members()
    members["content_pipeline/.env.production"] = "WEB_ADMIN_TOKEN=secret"
    members["content_pipeline/private.key"] = "secret"
    _write_wheel(wheel, members)

    assert main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert "content_pipeline/.env.production" in captured.err
    assert "content_pipeline/private.key" in captured.err


def test_check_wheel_rejects_nested_sensitive_member_names(tmp_path: Path, capsys) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    members = _valid_members()
    members["content_pipeline/config/.env"] = "WEB_ADMIN_TOKEN=secret"
    _write_wheel(wheel, members)

    assert main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert "content_pipeline/config/.env" in captured.err


def test_check_wheel_rejects_diagnostic_bundles(tmp_path: Path, capsys) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    members = _valid_members()
    members["diagnostics.zip"] = "diagnostics"
    members["content_pipeline/diagnostics-prod.zip"] = "diagnostics"
    _write_wheel(wheel, members)

    assert main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert "diagnostics.zip" in captured.err
    assert "content_pipeline/diagnostics-prod.zip" in captured.err


def test_check_wheel_rejects_python_cache_artifacts(tmp_path: Path, capsys) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    members = _valid_members()
    members["content_pipeline/__pycache__/models.cpython-311.pyc"] = "bytecode"
    members["content_pipeline/cache.pyo"] = "bytecode"
    _write_wheel(wheel, members)

    assert main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert "content_pipeline/__pycache__/models.cpython-311.pyc" in captured.err
    assert "content_pipeline/cache.pyo" in captured.err


def test_check_wheel_rejects_incomplete_distribution_metadata(tmp_path: Path, capsys) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    members = _valid_members()
    members["ai_pipeline-0.1.0.dist-info/METADATA"] = "Metadata-Version: 2.4\nName: ai-pipeline\n"
    _write_wheel(wheel, members)

    assert main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert "missing required wheel metadata fields:" in captured.err
    assert "Requires-Python: >=3.11" in captured.err


def test_check_wheel_reports_invalid_archive(tmp_path: Path, capsys) -> None:
    wheel = tmp_path / "ai_pipeline-0.1.0-py3-none-any.whl"
    wheel.write_text("not a wheel archive", encoding="utf-8")

    assert main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert "invalid wheel archive:" in captured.err
