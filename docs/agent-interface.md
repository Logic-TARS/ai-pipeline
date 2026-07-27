# Internal Agent Interface

This document is for internal agents and maintainers that call AI Popline from
Codex, Hermes, or another local automation layer. It describes the current task
submission surfaces, the persisted job contract, and the lower-tool adapter
boundary used by Photo-Process, MoneyPrinterTurbo, and social-auto-upload.

AI Popline is a local automation service. Do not treat these interfaces as a
public internet API or expose them beyond the local trusted environment without
a separate security review.

## Contract Layers

There are two related contracts.

The upper task contract is:

```text
MCP / REST / CLI -> TaskInput -> Orchestrator -> JobSnapshot
```

Agents submit a `TaskInput`, receive or discover a `task_id`, and then read the
latest `JobSnapshot` plus append-only job events. The orchestrator owns routing,
status transitions, artifact persistence, and final success or failure state.

The lower execution contract is:

```text
Orchestrator -> adapter -> Photo-Process / MPT / SAU
```

Adapters isolate external local tools. They normalize command execution,
timeouts, stdout parsing, artifact paths, and validation requirements. Parent
jobs must still verify artifacts before committing them to the job snapshot.

## Upper Interfaces

### MCP

Start the MCP server:

```powershell
python -m content_pipeline.mcp_server
```

Primary agent-facing MCP tools:

| Tool | Purpose | Return shape |
| --- | --- | --- |
| `list_capabilities` | Discover supported workflows, content types, safety defaults, and lower-tool contracts. | `{ "workflows": [...], "status_tools": [...] }` |
| `run_task_async` | Submit and immediately start a generic long-running task. | `{ "task_id": "...", "status": "queued" }` |
| `submit_task` | Create a queued task without starting it. | `{ "task_id": "...", "status": "queued" }` |
| `start_task` | Start a previously queued task by id. | `{ "task_id": "...", "status": "queued" }` or the existing status |
| `get_status` | Read the current persisted `JobSnapshot`. | `JobSnapshot` JSON |
| `get_job_events` | Read recent append-only events for a task. | `{ "task_id": "...", "events": [...] }` |
| `process_ai_art_async` | Submit and start the AI-art Photo-Process folder pipeline. | `{ "task_id": "...", "status": "queued" }` |
| `process_japanese_images` | Submit and start the Japanese local image pipeline. | `{ "task_id": "...", "status": "queued" }` |
| `run_finance_video_async` | Submit and start the dedicated Finance Markdown-to-video pipeline. | `{ "task_id": "...", "status": "queued" }` |

Additional implemented MCP tools exist for compatibility or narrower
maintenance workflows:

| Tool | Notes |
| --- | --- |
| `run_task_sync` | Runs a generic task synchronously and returns the final snapshot or `{ "status": "failed", "error": "..." }`. Prefer async tools for browser, video, or upload work. |
| `get_external_tool_contracts` | Returns adapter contracts such as the current Photo-Process CLI JSON contract. |
| `process_ai_art` | Synchronous variant of the AI-art folder pipeline. |
| `generate_images` | Direct Gemini image generation helper for a content profile. |
| `render_video` | Direct MPT video rendering helper from image paths. |
| `list_profiles` | Lists available profile YAML files. |
| `list_jobs` | Lists recent job summaries from the local job store. |

MCP errors are not fully normalized today. For example, `get_status` and
`get_job_events` raise `ValueError("task not found")` when the task is missing.
Callers should present that as a missing-task error and should not retry blindly.

### REST

Start the local FastAPI app:

```powershell
uvicorn app:app --host 127.0.0.1 --port 8080
```

Implemented endpoints:

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/run` | `TaskInput` JSON body | `{ "task_id": "...", "status": "queued" }` |
| `GET` | `/status/{task_id}` | path parameter | `JobSnapshot` JSON, or HTTP 404 with `task not found` |

The REST service queues work on a local `ThreadPoolExecutor`. It is intended for
trusted local callers on `127.0.0.1`.

### CLI

Run a task file synchronously:

```powershell
python -m content_pipeline.orchestrator --task <task.json>
```

The CLI reads the JSON file as `TaskInput`, submits it, runs it, prints the final
`JobSnapshot` as JSON, and exits with code `0` for `succeeded` or `partial`.
Other final statuses return a non-zero exit code.

## Core Data Structures

These structures are defined in `content_pipeline.models`.

### TaskInput

```json
{
  "description": "Human-readable task description",
  "content_type": "anime | finance | ai_briefing | ai_art | grouped_anime | japanese | unknown | null",
  "topic": "Optional route topic",
  "publish": false,
  "publish_targets": [],
  "params": {}
}
```

Rules:

- `publish` defaults to `false`; upload work requires explicit `true`.
- `content_type` may be omitted and resolved by routing, but task-specific MCP
  tools set it directly.
- `params` is branch-specific and remains the current extension point.

### PublishTarget

```json
{
  "platform": "douyin | kuaishou | bilibili | tencent",
  "account": "account display name or identifier",
  "tid": 21
}
```

Rules:

- `account` is required.
- `tid` is required for `bilibili`.
- Finance supports only Douyin and Kuaishou private publishing in the current
  local contract.

### JobSnapshot

```json
{
  "task_id": "hex id",
  "status": "queued | running | succeeded | failed | blocked | partial",
  "current_step": "route | source_scan | image | video | archive | upload | complete | null",
  "task": {},
  "route": {},
  "artifacts": {},
  "error": null
}
```

The job store persists the snapshot as:

```text
<data_dir>/jobs/<task_id>/status.json
```

It also appends events to:

```text
<data_dir>/jobs/<task_id>/events.jsonl
```

Known event names include `job_created`, `step_started`, `route_resolved`,
`upload_skipped`, and `job_finished`. Treat the event log as audit evidence,
not as the only source of current status.

### ArtifactSet

```json
{
  "images": [],
  "video": null,
  "upload_result": null,
  "validation": {},
  "source_results": [],
  "groups": [],
  "source_document": null,
  "narration_script": null,
  "script_path": null,
  "subtitle": null,
  "mpt_task_dir": null,
  "handoff_path": null,
  "external_status_path": null,
  "manifest_path": null,
  "publish_results": {}
}
```

Important evidence fields:

- `validation.images`: decoded image count and dimensions.
- `validation.video`: duration, dimensions, aspect ratio, codecs, and decoded
  audio/video frame counts.
- `source_results`: per-source AI-art or Japanese image processing result.
- `groups`: per-group grouped-anime artifacts, including video validation and
  per-platform publish results.
- `publish_results`: platform-specific uploader evidence. A target can fail
  while another succeeds, producing a `partial` job.
- `external_status_path` and `manifest_path`: pointers to lower-tool status or
  manifest evidence when a branch records it.

### JobStatus

| Status | Meaning |
| --- | --- |
| `queued` | Task exists and has not started. |
| `running` | Orchestrator is executing the current step. |
| `succeeded` | All required work completed. |
| `failed` | The job failed and should not be treated as complete. |
| `blocked` | The job stopped on a safety or capability boundary, such as unsupported private visibility. |
| `partial` | Local artifacts or some publish targets succeeded while at least one independent target failed. |

### PipelineStep

| Step | Meaning |
| --- | --- |
| `route` | Resolve content type, topic, and route params. |
| `source_scan` | Read and validate local source material. |
| `image` | Generate, edit, or validate images. |
| `video` | Render and validate video. |
| `archive` | Move or record processed source files when the branch supports it. |
| `upload` | Publish through supported upload adapters. |
| `complete` | Terminal successful or partial completion marker. |

## Downstream Interface Standard

The downstream interface is the boundary from the orchestrator to local tool
adapters:

```text
Orchestrator -> adapter -> Photo-Process / MPT / SAU
```

The adapter is the stable boundary. The orchestrator should not depend on
Gemini browser state, MoneyPrinterTurbo internals, uploader UI details, or
tool-specific log formats except through adapter-owned results and evidence.

Required standards:

- Clear boundary: each adapter owns subprocess execution, tool-specific
  arguments, stdout/stderr handling, timeouts, retries when supported, and raw
  tool quirks.
- Stable input: callers pass explicit paths, prompts, params, config-derived
  executables, and publish targets. The adapter contract must not require hidden
  UI state beyond the lower tool's own authenticated local session.
- Machine-readable output: adapters must expose a result shape that callers can
  parse deterministically. For Photo-Process today, this is the final JSON
  object printed to stdout.
- Classifiable errors: failures must carry a human-readable message and the
  most stable available error type or code. Missing config, invalid input,
  timeout, no output, validation failure, and publish failure should be
  distinguishable.
- Artifact revalidation: a lower-tool success return is not enough for job
  success. The parent pipeline must revalidate images, videos, audio, subtitles,
  and publish evidence before updating the job as successful.
- Evidence handoff: generated artifact paths, validation metadata, lower-tool
  status or manifest paths, relevant logs, and publish results should be written
  back into `JobSnapshot.artifacts` so another agent can audit the run.
- Fail closed: when an adapter cannot parse output, cannot find an artifact,
  cannot validate media, or cannot prove private visibility for publishing, the
  parent job must report `failed`, `blocked`, or `partial` instead of treating
  the run as successful.

In short, downstream adapters must provide a clear command boundary,
deterministic machine-readable results, classifiable failure information,
independently verified artifacts, and enough evidence for the orchestrator to
persist in `JobSnapshot`.

## Photo-Process Adapter Contract

The current Photo-Process boundary is a CLI JSON adapter. The orchestrator calls
the adapter through `content_pipeline.tools.photo_process_client`.

Photo-Process now implements the standardized `AdapterResult` envelope. The
legacy `call_photo_process(...) -> Path` helper remains as a compatibility
wrapper around `run_photo_process_adapter(...) -> AdapterResult`.

Command shape:

```powershell
<photo_process_python> <photo_process_dir>\main.py comic --image <image> --prompt <prompt> --json
```

Optional target selectors may be appended before `--json`:

```powershell
--target-gem-name <name>
--target-gem-url <url>
```

The adapter runs with:

- working directory: `settings.photo_process_dir`
- timeout: `900` seconds
- `PYTHONIOENCODING=utf-8`
- `PYTHONUTF8=1`

Lower-tool success JSON:

```json
{
  "success": true,
  "image_path": "absolute generated image path",
  "width": 765,
  "height": 1024,
  "aspect_ratio": 0.747,
  "target_aspect_ratio": "optional parsed target",
  "source_done_path": "optional moved original path"
}
```

Lower-tool failure JSON:

```json
{
  "success": false,
  "error": "human-readable failure reason",
  "error_type": "input_error | no_output | subprocess_error | upstream-specific"
}
```

Owned behavior:

- Gemini browser automation.
- Current-response candidate selection.
- Image decode and aspect-ratio validation inside Photo-Process.

Caller rules:

- Pass staged copies when originals must be preserved.
- Parse only the final JSON object from stdout. The current adapter scans stdout
  from the end and accepts the last JSON object line.
- Treat non-success JSON as adapter failure and include `error_type` in the
  raised message when present.
- Resolve relative `image_path` values against `settings.photo_process_dir`.
- Validate the generated artifact before copying it into the parent job.
- Validate the copied parent-job artifact again before committing it to
  `ArtifactSet`.

The adapter may return an existing matching output file if it already validates.
Agents should therefore use the job snapshot and validation metadata, not command
execution alone, as completion evidence.

Standardized success result:

```json
{
  "ok": true,
  "tool": "Photo-Process",
  "code": "OK",
  "message": null,
  "artifacts": {
    "image_path": "absolute generated image path",
    "processed_path": "absolute copied parent-job artifact path",
    "format": "PNG",
    "width": 765,
    "height": 1024
  },
  "evidence": {
    "command": ["..."],
    "cwd": "Photo-Process working directory",
    "timeout_seconds": 900,
    "validation": {}
  },
  "raw": {
    "photo_process_json": {}
  }
}
```

Standardized failure result:

```json
{
  "ok": false,
  "tool": "Photo-Process",
  "code": "NO_OUTPUT",
  "message": "human-readable failure reason",
  "artifacts": {},
  "evidence": {},
  "raw": {}
}
```

## Other Adapter Boundaries

MoneyPrinterTurbo is called by the orchestrator for video generation branches.
The parent job is responsible for validating the final MP4 before success:
vertical dimensions where required, decodable video frames, usable audio when
voiceover is expected, and subtitles when the branch requires them.

social-auto-upload is called only when `TaskInput.publish` is `true`. Publishing
adapters must fail closed for private visibility. For Finance, supported private
targets are Douyin account `金融破壁人` and Kuaishou account `破壁人`; Finance
must not publish to Bilibili and must not enter the Gemini image flow.

## Recommended Agent Workflow

1. Call `list_capabilities`.
2. Build a `TaskInput` or call the task-specific MCP async tool.
3. Keep `publish=false` unless the user explicitly authorized publishing.
4. Store the returned `task_id`.
5. Poll `get_status(task_id)` until `status` is terminal.
6. Read `get_job_events(task_id)` for audit trail and troubleshooting.
7. Verify artifacts from `artifacts.validation`, `publish_results`, and any
   status or manifest paths before reporting completion.

Terminal statuses are `succeeded`, `failed`, `blocked`, and `partial`.

## Next Standardization Targets

These are implemented for Photo-Process and remain standardization targets for
the other adapters.

### AdapterResult

Adapters should converge on a shared result envelope:

```json
{
  "ok": true,
  "tool": "Photo-Process",
  "code": "OK",
  "message": null,
  "artifacts": {},
  "evidence": {},
  "raw": {}
}
```

Suggested fields:

- `ok`: boolean success flag.
- `tool`: adapter name.
- `code`: stable machine-readable code.
- `message`: human-readable detail.
- `artifacts`: normalized output paths and metadata.
- `evidence`: validation, logs, manifests, or status paths needed by callers.
- `raw`: adapter-specific payload for debugging.

### ErrorCode Taxonomy

Recommended shared codes:

| Code | Meaning |
| --- | --- |
| `OK` | Adapter completed successfully. |
| `CONFIG_ERROR` | Required local path, executable, profile, or setting is missing or invalid. |
| `INPUT_ERROR` | Caller supplied invalid task or source data. |
| `SOURCE_NOT_FOUND` | Requested source file, folder, or daily handoff does not exist. |
| `SOURCE_SCAN_FAILED` | Source exists but does not contain required content. |
| `EXTERNAL_TOOL_FAILED` | Subprocess or browser-backed lower tool failed. |
| `NO_OUTPUT` | Lower tool finished without producing the expected artifact. |
| `VALIDATION_FAILED` | Produced artifact failed decode, aspect, audio, subtitle, or count validation. |
| `PRIVATE_VISIBILITY_UNSUPPORTED` | Upload target cannot prove private visibility. |
| `PUBLISH_FAILED` | Upload attempted but did not produce success evidence. |
| `ALREADY_PUBLISHED` | Deduplication found a prior successful upload for the artifact. |
| `TIMEOUT` | Adapter exceeded its allowed runtime. |

Until this taxonomy is implemented end to end, callers should continue reading
current `status`, `error`, `events`, and branch-specific artifact evidence.
