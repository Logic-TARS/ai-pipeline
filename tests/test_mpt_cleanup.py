import json
import os
import time
from pathlib import Path

from content_pipeline.maintenance.mpt_cleanup import cleanup_mpt_tasks


def _task(root: Path, name: str, *, owned: bool = True) -> Path:
    task = root / "storage" / "tasks" / name
    task.mkdir(parents=True)
    (task / "script.json").write_text(
        json.dumps({"task_id": "ai-pipeline-test" if owned else "someone-else"}),
        encoding="utf-8",
    )
    (task / "final-1.mp4").write_bytes(b"video")
    old = time.time() - 40 * 86400
    for path in (task, task / "script.json", task / "final-1.mp4"):
        os.utime(path, (old, old))
    return task


def test_mpt_cleanup_previews_then_applies_only_unprotected_owned_tasks(tmp_path: Path) -> None:
    owned = _task(tmp_path, "owned")
    protected = _task(tmp_path, "protected")
    unrelated = _task(tmp_path, "unrelated", owned=False)

    preview = cleanup_mpt_tasks(tmp_path, older_than_days=30, protected={protected})
    assert preview.candidates == (owned,)
    assert preview.total_size > 0
    assert owned.is_dir()

    applied = cleanup_mpt_tasks(tmp_path, older_than_days=30, protected={protected}, apply=True)
    assert applied.failures == ()
    assert not owned.exists()
    assert protected.is_dir()
    assert unrelated.is_dir()
