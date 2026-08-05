from __future__ import annotations

import json
import threading
from pathlib import Path
from uuid import uuid4

from content_pipeline.content_studio.models import ContentDraft, utc_now


class DraftNotFoundError(FileNotFoundError):
    pass


class DraftConflictError(RuntimeError):
    pass


class ContentDraftStore:
    def __init__(self, data_dir: Path):
        self.drafts_dir = data_dir / "content-drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(self, *, template_id: str, title: str, focus_assets: list[str], research) -> ContentDraft:
        draft = ContentDraft(
            draft_id=uuid4().hex,
            template_id=template_id,
            title=title,
            focus_assets=focus_assets,
            research=research,
        )
        with self._lock:
            self._save_unlocked(draft)
        return draft

    def get(self, draft_id: str) -> ContentDraft:
        path = self._path(draft_id)
        with self._lock:
            try:
                return ContentDraft.model_validate_json(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise DraftNotFoundError("content draft not found") from exc

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

    def mutate(self, draft_id: str, update) -> ContentDraft:
        with self._lock:
            draft = self.get(draft_id)
            update(draft)
            draft.revision += 1
            draft.updated_at = utc_now()
            self._save_unlocked(draft)
            return draft.model_copy(deep=True)

    def list(self, limit: int = 30) -> list[ContentDraft]:
        with self._lock:
            drafts: list[ContentDraft] = []
            paths = sorted(
                self.drafts_dir.glob("*/draft.json"),
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

    def source_dir(self, draft_id: str) -> Path:
        path = self._draft_dir(draft_id) / "sources"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_source(self, draft_id: str, source_id: str, payload: dict) -> None:
        if not source_id.replace("-", "").replace("_", "").isalnum():
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

    def _save_unlocked(self, draft: ContentDraft) -> None:
        path = self._path(draft.draft_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
