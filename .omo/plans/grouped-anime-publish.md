# grouped-anime-publish - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** 一个能自动把文件夹里相同前缀的图片分组，每组生成一个竖屏短视频，并发布到抖音（山下富士）和B站（酸菜鱼）的功能。

**Why this approach:** 复用现有的视频生成和上传逻辑，只添加新的分组和管道编排代码，最小化改动风险。

**What it will NOT do:** 不会做AI图片改绘，不会修改现有的动漫或AI艺术管道，不会硬编码发布账号。

**Effort:** Medium (8个任务，3个执行波次)
**Risk:** Low - 复用现有成熟模块，独立的新管道不影响现有功能
**Decisions to sanity-check:** 
- 前缀检测算法：提取文件名末尾数字前的部分作为分组标识
- 视频样式：5秒/图，淡入淡出，自动背景音乐
- 发布目标：在任务JSON中指定，不硬编码

Your next move: 批准计划开始执行，或先运行高精度审查。Full execution detail follows below.

---

> TL;DR (machine): Medium effort, Low risk. 8 todos across 3 waves. Deliverables: prefix grouping module, grouped_anime pipeline, router integration, example task, unit tests. Reuses slideshow rendering and SAU upload. No AI image generation.

## Scope
### Must have
- 按文件名前缀自动分组图片（正则：`^(.*?)(\d+)$`）
- 每组生成一个竖屏视频（5秒/图，淡入淡出，BGM，1080x1920）
- 发布到山下富士（抖音）和酸菜鱼（B站）
- 支持 dry_run 模式
- 任务状态持久化和事件日志
- 单元测试覆盖分组逻辑

### Must NOT have (guardrails, anti-slop, scope boundaries)
- 不做 AI 改绘（不调用 Photo-Process 或 Gemini）
- 不修改现有 ai_art_pipeline.py
- 不使用 profile 系统（直接分发，与 ai_art 保持一致）
- 不支持自定义视频样式（秒数、转场等）
- 不支持除抖音和B站之外的平台
- 不归档源图片（与 ai_art 不同）
- 不硬编码发布账号（由任务 JSON 指定）

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after + pytest
- Evidence: `.omo/evidence/task-<N>-grouped-anime-publish.<ext>`
- Integration test: dry_run with 6 images (3+3 groups) → 2 videos
- Router test: "分组动漫" → grouped_anime, "动漫" → anime
- Grouping test: unit tests for prefix detection edge cases

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

**Wave 1 (Core Infrastructure):** Tasks 1, 2, 3
- Task 1 and 2 can run in parallel (no dependencies)
- Task 3 depends on Task 1 (needs ContentType updated)

**Wave 2 (Pipeline Implementation):** Tasks 4, 5
- Task 4 depends on Tasks 1, 2 (needs models and grouping)
- Task 5 depends on Tasks 3, 4 (needs router and pipeline)

**Wave 3 (Testing and Validation):** Tasks 6, 7, 8
- Task 6 depends on Task 5 (needs orchestrator integration)
- Task 7 depends on Task 2 (needs grouping module)
- Task 8 depends on Tasks 5, 6 (needs full integration)

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | - | 3, 4 | 2 |
| 2 | - | 3, 4, 7 | 1 |
| 3 | 1 | 5 | - |
| 4 | 1, 2 | 5 | - |
| 5 | 3, 4 | 6, 8 | - |
| 6 | 5 | 8 | 7 |
| 7 | 2 | - | 6 |
| 8 | 5, 6 | - | - |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

### Wave 1: Core Infrastructure
- [x] 1. Extend ContentType Literal and add GroupedAnimeParams model
  What to do / Must NOT do: Update `content_pipeline/models.py:10` to add `"grouped_anime"` to ContentType Literal. Add new `GroupedAnimeParams` class with fields: `source_dir: Path`, `title: str`, `description: str = ""`, `tags: list[str] = []`, `archive_dir: Path | None = None`, `failed_dir: Path | None = None`. Must NOT modify existing models.
  Parallelization: Wave 1 | Blocked by: none | Blocks: 2, 3, 4
  References: `content_pipeline/models.py:10` (ContentType), `content_pipeline/models.py:53-63` (AiArtParams reference)
  Acceptance criteria: `python -c "from content_pipeline.models import ContentType, GroupedAnimeParams; from pathlib import Path; p = GroupedAnimeParams(source_dir=Path('.'), title='test'); print('OK')"` exits 0
  QA scenarios: happy: import and instantiate GroupedAnimeParams successfully; failure: missing required field raises ValidationError. Evidence: `.omo/evidence/task-1-grouped-anime-publish.log`
  Commit: Y | feat(models): add grouped_anime content type and params

- [x] 2. Create prefix grouping module
  What to do / Must NOT do: Create `content_pipeline/grouping.py` with function `group_by_prefix(images: list[Path]) -> dict[str, list[Path]]`. Algorithm: regex `^(.*?)(\d+)$` extracts prefix (text before trailing digits). Group images by prefix, sort groups by prefix, sort images within group by natural order. Must NOT modify existing files.
  Parallelization: Wave 1 | Blocked by: none | Blocks: 3
  References: `content_pipeline/tools/photo_process_client.py:112-114` (_natural_key reference)
  Acceptance criteria: `python -c "from content_pipeline.grouping import group_by_prefix; from pathlib import Path; result = group_by_prefix([Path('a_001.jpg'), Path('a_002.jpg'), Path('b_001.jpg')]); assert len(result) == 2; assert len(result['a_']) == 2; print('OK')"` exits 0
  QA scenarios: happy: 6 images with 2 prefixes → 2 groups; failure: images without trailing digits → each becomes own group. Evidence: `.omo/evidence/task-2-grouped-anime-publish.log`
  Commit: Y | feat(grouping): add prefix-based image grouping

- [x] 3. Add router keywords for grouped_anime
  What to do / Must NOT do: In `content_pipeline/router.py:18-20`, add `GROUPED_ANIME_KEYWORDS = ("分组动漫", "grouped anime", "图片组合")`. In `_route_with_rules` function (line 41-51), check `GROUPED_ANIME_KEYWORDS` BEFORE `ANIME_KEYWORDS` to avoid collision. Must NOT modify existing keyword lists.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 5
  References: `content_pipeline/router.py:18-20` (keywords), `content_pipeline/router.py:41-51` (_route_with_rules)
  Acceptance criteria: `python -c "from content_pipeline.router import route_task; from content_pipeline.models import TaskInput; from content_pipeline.settings import Settings; result = route_task(TaskInput(description='分组动漫火影忍者'), Settings()); assert result.content_type == 'grouped_anime'; print('OK')"` exits 0
  QA scenarios: happy: "分组动漫" routes to grouped_anime; failure: "动漫" still routes to anime (not grouped_anime). Evidence: `.omo/evidence/task-3-grouped-anime-publish.log`
  Commit: Y | feat(router): add grouped_anime keywords with correct priority

### Wave 2: Pipeline Implementation
- [x] 4. Create grouped_anime_pipeline module
  What to do / Must NOT do: Create `content_pipeline/grouped_anime_pipeline.py` with function `run_grouped_anime_pipeline(...)`. Flow: (1) scan source images using `scan_source_images`, (2) group by prefix using `group_by_prefix`, (3) for each group: render slideshow using `render_slideshow` with BGM from `choose_bgm`, validate video, (4) if publish=true: call `call_sau_target` for each target. Must NOT call Photo-Process or Gemini. Must follow `ai_art_pipeline.py` structure.
  Parallelization: Wave 2 | Blocked by: 1, 2 | Blocks: 5
  References: `content_pipeline/ai_art_pipeline.py:24-202` (reference), `content_pipeline/tools/slideshow_client.py:23-101` (render_slideshow), `content_pipeline/tools/sau_client.py:15-55` (call_sau_target), `content_pipeline/tools/photo_process_client.py:16-35` (scan_source_images)
  Acceptance criteria: `python -c "from content_pipeline.grouped_anime_pipeline import run_grouped_anime_pipeline; print('OK')"` exits 0
  QA scenarios: happy: folder with 6 images (3+3) → 2 videos generated; failure: empty folder raises ConfigError. Evidence: `.omo/evidence/task-4-grouped-anime-publish.log`
  Commit: Y | feat(pipeline): add grouped_anime pipeline

- [x] 5. Integrate grouped_anime into orchestrator
  What to do / Must NOT do: In `content_pipeline/orchestrator.py:38-46`, add `elif route.content_type == "grouped_anime":` branch that calls `run_grouped_anime_pipeline(...)`. Must NOT modify existing branches. Must import new pipeline function.
  Parallelization: Wave 2 | Blocked by: 3, 4 | Blocks: 6
  References: `content_pipeline/orchestrator.py:38-46` (ai_art dispatch reference)
  Acceptance criteria: `python -m content_pipeline.orchestrator --task test-grouped.json` (with content_type="grouped_anime") runs without import errors
  QA scenarios: happy: task with grouped_anime routes correctly; failure: invalid content_type still raises UnknownContentType. Evidence: `.omo/evidence/task-5-grouped-anime-publish.log`
  Commit: Y | feat(orchestrator): dispatch grouped_anime pipeline

### Wave 3: Testing and Validation
- [x] 6. Create example task JSON
  What to do / Must NOT do: Create `task.grouped-anime.example.json` with: `content_type: "grouped_anime"`, `publish: false`, `publish_targets` for 山下富士 (douyin) and 酸菜鱼 (bilibili with tid), `params.source_dir`, `params.title`, `params.tags`. Must NOT set publish=true by default.
  Parallelization: Wave 3 | Blocked by: 5 | Blocks: none
  References: `task.ai-art.example.json` (reference), `content_pipeline/models.py:32-41` (PublishTarget)
  Acceptance criteria: `python -c "import json; from content_pipeline.models import TaskInput; task = TaskInput.model_validate(json.load(open('task.grouped-anime.example.json'))); assert task.content_type == 'grouped_anime'; assert len(task.publish_targets) == 2; print('OK')"` exits 0
  QA scenarios: happy: valid task JSON parses successfully; failure: missing source_dir raises ValidationError. Evidence: `.omo/evidence/task-6-grouped-anime-publish.log`
  Commit: Y | docs: add grouped_anime example task

- [x] 7. Add unit tests for grouping module
  What to do / Must NOT do: Create `tests/test_grouping.py` with tests for `group_by_prefix`: (1) multiple prefixes, (2) single prefix, (3) no trailing digits, (4) empty list, (5) mixed valid/invalid filenames. Must use pytest. Must NOT modify existing tests.
  Parallelization: Wave 3 | Blocked by: 2 | Blocks: none
  References: `content_pipeline/grouping.py` (to be created), `tests/test_ai_art_pipeline.py` (reference)
  Acceptance criteria: `pytest tests/test_grouping.py -v` exits 0 with all tests passing
  QA scenarios: happy: 6 images with 2 prefixes → 2 groups; failure: empty list → empty dict. Evidence: `.omo/evidence/task-7-grouped-anime-publish.log`
  Commit: Y | test(grouping): add unit tests for prefix grouping

- [x] 8. Run integration test with dry_run
  What to do / Must NOT do: Create a test folder with 6 images (3 with prefix "test_a_", 3 with prefix "test_b_"). Run `python -m content_pipeline.orchestrator --task task.grouped-anime.example.json` with `params.dry_run: true`. Verify: 2 video files generated (or dry-run placeholders), no upload attempted, status.json shows succeeded.
  Parallelization: Wave 3 | Blocked by: 5, 6 | Blocks: none
  References: `content_pipeline/orchestrator.py:109-124` (run_task_file), `task.grouped-anime.example.json`
  Acceptance criteria: Task completes with status "succeeded", output/jobs/<task_id>/groups/ contains 2 subdirectories with video files
  QA scenarios: happy: 2 groups → 2 videos; failure: missing source_dir → task fails with clear error. Evidence: `.omo/evidence/task-8-grouped-anime-publish.log`
  Commit: N | (verification only)

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit: Verify every todo has references + acceptance + QA + commit. Confirm no business-logic assumption without evidence.
- [x] F2. Code quality review: Check for code duplication, proper error handling, type hints, docstrings. Verify no modification to ai_art_pipeline.py.
- [x] F3. Real manual QA: Run integration test with 6 images (3+3 groups), verify 2 videos generated, verify router classification, verify dry_run skips upload.
- [x] F4. Scope fidelity: Confirm no AI image generation, no profile system usage, no hardcoded accounts, no custom video styles.

## Commit strategy
- One commit per todo (except verification-only tasks)
- Commit messages follow conventional commits: `feat(scope): summary` or `test(scope): summary`
- All commits are atomic and reversible
- Final integration test (Task 8) does not commit

## Success criteria
1. `python -m content_pipeline.orchestrator --task task.grouped-anime.example.json` completes successfully with dry_run=true
2. Router correctly classifies "分组动漫" as grouped_anime (not anime)
3. Prefix grouping produces correct groups for test filenames
4. Each group generates a valid 1080x1920 MP4 with audio
5. Publish targets are attempted independently (one failure doesn't block others)
6. All unit tests pass: `pytest tests/test_grouping.py -v`
7. No modification to existing ai_art_pipeline.py
8. No AI image generation calls (Photo-Process or Gemini)
