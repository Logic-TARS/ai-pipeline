from __future__ import annotations

import json
import threading
from pathlib import Path
from uuid import uuid4

from content_pipeline.content_studio.models import ContentDraft, utc_now

__all__ = ["ContentDraftStore", "DraftConflictError", "DraftCorruptError", "DraftNotFoundError"]


class DraftNotFoundError(FileNotFoundError):
    pass


class DraftConflictError(RuntimeError):
    pass


class DraftCorruptError(RuntimeError):
    pass


class ContentDraftStore:
    def __init__(self, data_dir: Path):
        self.drafts_dir = data_dir / "content-drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(
        self,
        *,
        template_id: str,
        title: str,
        focus_assets: list[str],
        research,
        enabled_source_ids: list[str] | None = None,
    ) -> ContentDraft:
        draft = ContentDraft(
            draft_id=uuid4().hex,
            template_id=template_id,
            title=title,
            focus_assets=focus_assets,
            enabled_source_ids=enabled_source_ids,
            research=research,
        )
        with self._lock:
            self._save_unlocked(draft)
        return draft

    def get(self, draft_id: str) -> ContentDraft:
        with self._lock:
            try:
                path = self._existing_draft_dir(draft_id) / "draft.json"
                return ContentDraft.model_validate_json(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise DraftNotFoundError("content draft not found") from exc
            except ValueError as exc:
                raise DraftCorruptError("content draft is invalid") from exc

    def save(self, draft: ContentDraft, *, expected_revision: int | None = None) -> ContentDraft:
        with self._lock:
            if expected_revision is not None:
                current = self.get(draft.draft_id)
                if current.revision != expected_revision:
                    raise DraftConflictError("content draft changed; reload it before saving")
                draft.revision = current.revision + 1
            draft.updated_at = utc_now()
            self._save_unlocked(draft)
            return draft.model_copy(deep=True)

    def mutate(self, draft_id: str, update, *, expected_revision: int | None = None) -> ContentDraft:
        with self._lock:
            draft = self.get(draft_id)
            if expected_revision is not None and draft.revision != expected_revision:
                raise DraftConflictError("content draft changed; reload it before saving")
            update(draft)
            draft.revision += 1
            draft.updated_at = utc_now()
            self._save_unlocked(draft)
            return draft.model_copy(deep=True)

    def list(self, limit: int = 30) -> list[ContentDraft]:
        with self._lock:
            drafts: list[ContentDraft] = []
            paths = sorted(
                (
                    path
                    for path in self.drafts_dir.glob("*/draft.json")
                    if not path.parent.is_symlink() and path.parent.is_dir()
                ),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for path in paths:
                try:
                    drafts.append(ContentDraft.model_validate_json(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
                if len(drafts) >= limit:
                    break
            return drafts

    def delete(self, draft_id: str) -> None:
        with self._lock:
            path = self._existing_draft_dir(draft_id)
            _rmtree(path)

    def delete_many(self, draft_ids: list[str]) -> dict[str, list[str]]:
        result = {"deleted": [], "not_found": [], "failed": []}
        for draft_id in dict.fromkeys(draft_ids):
            try:
                self.delete(draft_id)
                result["deleted"].append(draft_id)
            except DraftNotFoundError:
                result["not_found"].append(draft_id)
            except OSError:
                result["failed"].append(draft_id)
        return result

    def source_dir(self, draft_id: str) -> Path:
        path = self._existing_draft_dir(draft_id) / "sources"
        if path.is_symlink():
            raise DraftNotFoundError("content draft not found")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_source(self, draft_id: str, source_id: str, payload: dict) -> None:
        if not source_id or len(source_id) > 80 or not source_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid source id")
        path = self.source_dir(draft_id) / f"{source_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _path(self, draft_id: str) -> Path:
        return self._draft_dir(draft_id) / "draft.json"

    def _draft_dir(self, draft_id: str) -> Path:
        if len(draft_id) != 32 or any(character not in "0123456789abcdef" for character in draft_id):
            raise DraftNotFoundError("content draft not found")
        return self.drafts_dir / draft_id

    def _existing_draft_dir(self, draft_id: str) -> Path:
        path = self._draft_dir(draft_id)
        if path.is_symlink() or not path.is_dir():
            raise DraftNotFoundError("content draft not found")
        return path

    def _save_unlocked(self, draft: ContentDraft) -> None:
        path = self._path(draft.draft_id)
        if path.parent.is_symlink():
            raise DraftNotFoundError("content draft not found")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.iterdir(), key=lambda item: item.is_dir(), reverse=True):
        if child.is_dir() and not child.is_symlink():
            _rmtree(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()
