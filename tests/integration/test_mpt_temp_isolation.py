from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from content_pipeline.profiles import VideoGenProfile
from content_pipeline.settings import Settings
from content_pipeline.tools.mpt_client import call_mpt

FAKE_MPT_CLI = """\
import argparse
import json
import os
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--task-id", required=True)
args, _ = parser.parse_known_args()

mpt_dir = Path.cwd()
temp_dir = Path(tempfile.gettempdir()).resolve()
environment_temp_dirs = [Path(os.environ[name]).resolve() for name in ("TEMP", "TMP", "TMPDIR")]
if any(path != temp_dir for path in environment_temp_dirs):
    raise RuntimeError(f"inconsistent temporary directories: {temp_dir}, {environment_temp_dirs}")

rendezvous_dir = mpt_dir / "rendezvous"
rendezvous_dir.mkdir(exist_ok=True)
reports_dir = mpt_dir / "temp-reports"
reports_dir.mkdir(exist_ok=True)
scratch = temp_dir / "final-1TEMP_MPY_wvf_snd.mp4"
with scratch.open("xb") as handle:
    handle.write(args.task_id.encode("utf-8"))
    handle.flush()
    (rendezvous_dir / f"{args.task_id}.ready").write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 10
    while len(list(rendezvous_dir.glob("*.ready"))) < 2:
        if time.monotonic() >= deadline:
            raise TimeoutError("concurrent fake MPT process did not become ready")
        time.sleep(0.02)
    time.sleep(0.2)
    (reports_dir / f"{args.task_id}.json").write_text(
        json.dumps({"temp_dir": str(temp_dir), "scratch": str(scratch)}),
        encoding="utf-8",
    )

video = mpt_dir / "storage" / "tasks" / args.task_id / "final-1.mp4"
video.parent.mkdir(parents=True, exist_ok=True)
video.write_bytes(f"video-{args.task_id}".encode("utf-8"))
print(json.dumps({"result": {"videos": [str(video)]}}))
"""


def test_concurrent_mpt_calls_use_isolated_temporary_directories(tmp_path: Path, monkeypatch) -> None:
    mpt_dir = tmp_path / "mpt"
    mpt_dir.mkdir()
    (mpt_dir / "cli.py").write_text(FAKE_MPT_CLI, encoding="utf-8")
    image = tmp_path / "source.png"
    image.write_bytes(b"image")
    parent_environment = {
        "TEMP": str(tmp_path / "parent-temp"),
        "TMP": str(tmp_path / "parent-tmp"),
        "TMPDIR": str(tmp_path / "parent-tmpdir"),
    }
    for name, value in parent_environment.items():
        monkeypatch.setenv(name, value)

    start = threading.Barrier(2)
    settings = Settings(mpt_dir=mpt_dir, mpt_python=Path(sys.executable))

    def invoke(task_id: str) -> Path:
        start.wait(timeout=5)
        return call_mpt(
            task_id=task_id,
            profile=VideoGenProfile(),
            topic="topic",
            params={"script": "placeholder"},
            images=[image],
            output_dir=tmp_path / f"output-{task_id}",
            settings=settings,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outputs = list(executor.map(invoke, ("one", "two")))

    reports = [json.loads(path.read_text(encoding="utf-8")) for path in (mpt_dir / "temp-reports").glob("*.json")]
    temporary_directories = [Path(report["temp_dir"]) for report in reports]
    scratch_files = [Path(report["scratch"]) for report in reports]

    assert len(reports) == 2
    assert len(set(temporary_directories)) == 2
    assert {path.name for path in scratch_files} == {"final-1TEMP_MPY_wvf_snd.mp4"}
    assert all(not path.exists() for path in temporary_directories)
    assert all(not path.exists() for path in scratch_files)
    assert {name: os.environ.get(name) for name in parent_environment} == parent_environment
    assert [output.name for output in outputs] == ["final-1.mp4", "final-1.mp4"]
    assert all(output.is_file() and output.read_bytes() for output in outputs)
    assert outputs[0].read_bytes() != outputs[1].read_bytes()
