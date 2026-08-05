# AI Popline Content Pipeline

AI Popline is a local-first content automation service for turning structured tasks, daily Markdown handoffs, and image folders into validated short-form media. It coordinates Gemini, Photo-Process, MoneyPrinterTurbo (MPT), FFmpeg, and social-auto-upload (SAU) across six pipelines, while keeping publishing disabled unless a task explicitly opts in.

> **Safety first:** generation and validation can run without publishing. A task must contain `"publish": true` before any uploader is called, and supported publishing paths fail closed when private visibility cannot be proved.

📖 **[Full documentation](docs/README.md)** — [architecture](docs/architecture.md), [configuration](docs/configuration.md), [agent interfaces](docs/agent-interface.md), [testing](docs/smoke-testing.md), and [publishing](docs/publishing-runbook.md)

## Contents

- [Pipelines](#pipelines)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Task format](#task-format)
- [Running pipelines](#running-pipelines)
- [CLI reference](#cli-reference)
- [Web operator console](#web-operator-console)
- [REST API](#rest-api)
- [MCP agent interface](#mcp-agent-interface)
- [Jobs, status, and artifacts](#jobs-status-and-artifacts)
- [Publishing safety](#publishing-safety)
- [Development and testing](#development-and-testing)
- [Docker](#docker)
- [Troubleshooting](#troubleshooting)

## Pipelines

| Pipeline | `content_type` | Input and flow | Local output | Optional publishing |
| --- | --- | --- | --- | --- |
| Anime | `anime` | Task script/topic → Gemini images → MPT video | Images and validated vertical MP4 | Bilibili |
| Finance | `finance` | Daily Finance Markdown → 350–500-character narration → narrated MPT video | MP4, subtitles, script, and validation evidence | Douyin, Kuaishou |
| AI Briefing | `ai_briefing` | Daily handoff/Markdown/text → compressed narration → narrated MPT video | MP4, subtitles, handoff status, and validation evidence | Douyin, Kuaishou, Tencent draft |
| AI Art | `ai_art` | Image folder → Photo-Process editing → grouped FFmpeg gallery videos | Processed images and one or more validated MP4 files | Douyin, Bilibili |
| Grouped Anime | `grouped_anime` | Images grouped by filename prefix → one visual-only MPT video per group | Group videos, prepared music, and MPT artifacts | Douyin, Bilibili |
| Japanese | `japanese` | Image folder → Photo-Process `日语视觉化` Gem | Validated processed images | None; publishing is ignored |

Run `ai-popline capabilities` to read the pipeline metadata exposed by the installed version.

## Requirements

### Core

- Python **3.11 or newer**
- [`uv`](https://docs.astral.sh/uv/)
- A writable local output directory
- Windows PowerShell is used in the examples; the Python CLI also works from other shells

### Pipeline-specific local tools

Only configure the tools needed by the pipelines you run:

| Tool | Used for |
| --- | --- |
| Gemini Skill or `GEMINI_IMAGE_COMMAND` | Anime image generation |
| Photo-Process | AI Art and Japanese image editing through Gemini |
| MoneyPrinterTurbo | Anime, Finance, AI Briefing, and Grouped Anime video generation |
| FFmpeg | Gallery rendering, audio preparation, and media validation |
| social-auto-upload | Optional publishing |

Real browser-backed and publishing runs require valid authenticated local sessions in the corresponding tools. AI Popline is a single-operator service: keep it on loopback today; the only supported remote boundary is authenticated access over an explicitly configured ZeroTier network, while browser workers and lower-tool ports remain loopback-only. See the [Web Access Boundary](docs/web-access-boundary.md).

## Quick start

```powershell
# Install the package and runtime dependencies
uv sync

# Create local configuration
copy .env.example .env
# Edit .env and replace the example paths with paths on this machine

# Inspect configured tools and paths
ai-popline doctor

# Discover available workflows
ai-popline capabilities

# Validate and run a safe dry-run task
ai-popline validate-task --task examples/tasks/dry-run/task.example.json
ai-popline run --task examples/tasks/dry-run/task.example.json
```

On Bash or Git Bash, use `cp .env.example .env` instead of `copy`.

`doctor` checks all known external tools, so it may return a non-zero exit code when an unused pipeline dependency is not installed. The Anime dry-run example does not publish.

## Configuration

AI Popline has two configuration layers:

1. `.env` or process environment variables for global paths and runtime settings.
2. [`config/pipeline.defaults.yaml`](config/pipeline.defaults.yaml) for optional per-pipeline task defaults.

Important environment variables include:

| Variable | Purpose |
| --- | --- |
| `PIPELINE_DATA_DIR` | Job and artifact root; defaults to `output` |
| `PIPELINE_DEFAULTS_FILE` | Per-pipeline defaults file |
| `GEMINI_SKILL_DIR` | Gemini Skill installation |
| `GEMINI_IMAGE_COMMAND` | Optional command template used instead of the default Gemini integration |
| `PHOTO_PROCESS_DIR` | Photo-Process installation |
| `PHOTO_PROCESS_PYTHON` | Python executable for Photo-Process |
| `PHOTO_PROCESS_WORKER_URL` | Optional localhost persistent Photo-Process browser worker |
| `MPT_DIR` / `MPT_PYTHON` | MoneyPrinterTurbo installation and Python executable |
| `AI_ART_BGM_DIR` | Music directory used by image-based video pipelines |
| `SAU_DIR` / `SAU_EXE` | social-auto-upload installation and executable |
| `SAU_BILIBILI_PRIVATE_ARGS` | Verified Bilibili only-self arguments, normally `--is-only-self 1` |
| `FINANCE_MD_DIR` | Default Finance Markdown archive |
| `AI_BRIEFING_DIR` | Default daily AI briefing handoff root |
| `ROUTER_LLM_BASE_URL`, `ROUTER_LLM_API_KEY`, `ROUTER_LLM_MODEL` | Optional router LLM; deterministic keyword routing is used when absent |

The defaults file is intentionally disabled:

```yaml
enabled: false
```

After reviewing its paths, set `enabled: true` to merge `pipelines.<content_type>.params` into tasks. Explicit values in task JSON always win. Publishing cannot be enabled through these parameter defaults; the task itself must set `publish` to `true`.

See [Configuration](docs/configuration.md) for merge rules and supported path placeholders.

## Task format

A minimal safe task looks like this:

```json
{
  "description": "Create a four-scene Friday anime short",
  "content_type": "anime",
  "topic": "Friday after work",
  "publish": false,
  "params": {
    "script": "Scene 1... Scene 2... Scene 3... Scene 4...",
    "dry_run": true
  }
}
```

| Field | Required | Description |
| --- | --- | --- |
| `description` | Yes | Human-readable task description |
| `content_type` | Recommended | `anime`, `finance`, `ai_briefing`, `ai_art`, `grouped_anime`, or `japanese`; if omitted, the router attempts to resolve it |
| `topic` | No | Routing or content topic |
| `publish` | No | Defaults to `false`; must be explicitly `true` to call uploaders |
| `publish_targets` | No | List of platform/account targets; Bilibili targets also require `tid` |
| `params` | No | Pipeline-specific settings such as source folders, scripts, dates, titles, and dry-run flags |

A publish target has this shape:

```json
{
  "platform": "bilibili",
  "account": "account-name",
  "tid": 27
}
```

Canonical examples are organized by risk level:

- [`examples/tasks/dry-run/`](examples/tasks/dry-run/) — safe command smoke tests
- [`examples/tasks/local/`](examples/tasks/local/) — local generation/editing with `publish: false`
- [`examples/tasks/publish/`](examples/tasks/publish/) — real private/draft publishing examples; review before use
- [`examples/tasks/archive/`](examples/tasks/archive/) — date-specific regression/reference tasks

See [`examples/tasks/README.md`](examples/tasks/README.md) for the example layout.

## Running pipelines

### Safe Anime dry run

```powershell
ai-popline run --task examples/tasks/dry-run/task.example.json
```

For real Gemini and MPT generation without upload, configure both tools and run:

```powershell
ai-popline run --task examples/tasks/local/task.real.example.json
```

Generated images must decode successfully. The final video must be a decodable vertical MP4 with valid audio; validation metadata is persisted under `artifacts.validation`.

### Daily AI Briefing

```powershell
ai-popline run --task examples/tasks/local/task.ai-briefing.example.json
```

The default source is `AI_BRIEFING_DIR\YYYYMMDD`. The pipeline uses only the requested/current date and never silently falls back to an older briefing. It builds a 350–500 Chinese-character narration, produces a 9:16 MPT video with Chinese voiceover and subtitles, and validates video, audio, and spoken-subtitle evidence.

The checked-in local example has `dry_run: true`; remove that flag or set it to `false` for real generation. Compatible handoff outputs include `video\briefing.mp4`, `video\briefing.srt`, `video_status.json`, and `handoff_index.jsonl`.

To register the daily 09:30 Windows task used by this project:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_daily_ai_briefing_task.ps1
```

Review the script and publish task before registering it: the scheduled workflow can privately publish to its configured accounts.

### Daily Finance

```powershell
ai-popline run --task examples/tasks/local/task.finance.example.json
```

Finance scans `FINANCE_MD_DIR` unless `params.source_dir` overrides it. It chooses today's Markdown, or yesterday's when today's file is absent, reads the `## Response` content, builds a 350–500 Chinese-character narration, and invokes MPT directly with Pexels material, Chinese voiceover, subtitles, and a 9:16 aspect ratio. Finance does not call Gemini or publish to Bilibili.

The checked-in local example has `dry_run: true`. A missing, path-only, malformed, or undersized source fails during source scanning before MPT or an uploader can run.

### AI Art folder processing

Edit `params.source_dir` and the archive/output settings in the example, then run:

```powershell
ai-popline run --task examples/tasks/local/task.ai-art.example.json
```

Top-level images are processed in natural filename order, or restricted by `source_files`. Photo-Process applies the shared `image_prompt`; validated results are grouped into gallery videos, with deterministic background music from `AI_ART_BGM_DIR`. Successful originals move to `archive_dir` and failures can move to `failed_dir`.

### Japanese local image processing

```powershell
ai-popline run --task examples/tasks/local/task.japanese.example.json
```

The pipeline sends top-level source images to the configured Photo-Process Gem and stores stable numbered outputs in `params.output_dir` (default: `source_dir/日语改图`). Source images are preserved. This workflow ends after image validation and never generates video or publishes.

### Grouped Anime videos

```powershell
ai-popline run --task examples/tasks/local/task.grouped-anime.example.json
```

Source images are grouped by filename prefix. Each group gets one visual-only MPT invocation, with deterministic music trimmed or looped to `image count × seconds_per_image`. No title, description, subtitles, or other text is rendered into the frame. Group videos and MPT task directories remain available for review before publishing.

## CLI reference

The package installs the `ai-popline` command:

| Command | Purpose |
| --- | --- |
| `ai-popline doctor` | Check Python, configuration, external tools, output directory, and profiles |
| `ai-popline doctor --bundle diagnostics.zip` | Write a diagnostic bundle |
| `ai-popline capabilities` | List registered pipelines and their contracts |
| `ai-popline validate-task --task <file.json>` | Parse and normalize a task without running it |
| `ai-popline run --task <file.json>` | Run a task synchronously and print the final job snapshot |
| `ai-popline serve` | Start the REST API using the guarded Web listener configuration |
| `ai-popline mcp` | Start the MCP stdio server |
| `ai-popline jobs list [--status STATUS] [--content-type TYPE] [--limit N]` | List recent jobs |
| `ai-popline jobs show <task_id>` | Print a persisted job snapshot |
| `ai-popline jobs events <task_id> [--limit N]` | Print recent audit events |
| `ai-popline jobs cleanup --older-than-days N` | Delete old persisted jobs |

`run` exits with code `0` for `succeeded` or `partial`; other terminal states return a non-zero code.

## Web operator console

Start the guarded service and open the main interface:

```powershell
ai-popline serve
# Open http://127.0.0.1:8080/
```

The no-Node console is packaged with the Python application. It provides a dedicated content studio plus seven pipeline-aware task forms, safe preflight validation, recent-job filters, live status polling, event timelines, validation evidence, and previews for registered artifacts contained in each job directory.

The content studio provides two 90-second templates: financial research from an explicit read-only ttskill allowlist (gold, bond, China macro, and optional stock data), and the latest dated AI briefing article from `AI_BRIEFING_DIR`. It stores sanitized source material with an operator-edited 350–500 character script, then queues the reviewed script through the local `script_video` MoneyPrinterTurbo pipeline. It never exposes arbitrary Skill invocation, account/trading Skills, or automatic publishing.

When `WEB_AUTH_REQUIRED=true`, the page first requests `WEB_ADMIN_TOKEN` and then uses a signed session plus CSRF protection. Publishing remains off unless `WEB_PUBLISH_ENABLED=true`; an enabled publish task is clearly labeled **generate and publish**, requires a typed warning confirmation, and is bound to the server-returned task fingerprint.

Directory fields refer to paths on the AI Popline server, not the browser device. The console never exposes an arbitrary filesystem browser, lower-tool ports, configuration secrets, or paths through readiness diagnostics.

## REST API

Start the API with its safe loopback defaults:

```powershell
ai-popline serve
```

A direct Uvicorn command is supported only for loopback development; disable proxy-header trust explicitly:

```powershell
uvicorn app:app --host 127.0.0.1 --port 8080 --no-proxy-headers --no-server-header
```

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Minimal unauthenticated process health |
| `GET` | `/ready` | Authenticated, redacted readiness flags |
| `POST` | `/auth/login` | Exchange the admin token for a browser session and CSRF token |
| `POST` | `/auth/logout` | Clear an authenticated browser session |
| `GET` | `/capabilities` | Registered pipeline metadata |
| `GET` | `/ui/bootstrap` | Authenticated, non-sensitive Web form and status contract |
| `GET/POST/PATCH` | `/content/...` | Authenticated content templates, read-only research, drafts, refresh, and script-video handoff |
| `POST` | `/validate-task` | Validate and normalize a task without creating a job |
| `POST` | `/run` | Queue a `TaskInput`; publishing requires additional enablement and confirmation |
| `GET` | `/status/{task_id}` | Read the current job snapshot |
| `GET` | `/jobs` | List jobs; supports `status`, `content_type`, and `limit` query parameters |
| `GET` | `/jobs/{task_id}/events` | Read recent append-only events; supports `limit` |
| `GET` | `/jobs/{task_id}/artifacts` | List guarded, registered files contained in the job directory |

The service uses a local thread pool for background jobs. Non-loopback startup is fail-closed and supports only an exact configured ZeroTier interface IP with peer-network restrictions, application authentication, Host/Origin checks, and TLS or an explicit restricted HTTP exception. Follow the [ZeroTier Web Access Runbook](docs/zerotier-web-access.md); never expose lower-tool or browser-helper ports.

`/health` is the only unauthenticated operational endpoint and returns minimal liveness data. When `WEB_AUTH_REQUIRED=true`, use a login session plus CSRF token for browser writes or `Authorization: Bearer <WEB_API_TOKEN>` for REST automation; Web/API publishing also requires `WEB_PUBLISH_ENABLED=true` and task-bound confirmation.

## MCP agent interface

Start the preferred interface for Codex/Hermes-style agents:

```powershell
ai-popline mcp
```

Agents should call `list_capabilities`, submit long work with `run_task_async` or a pipeline-specific async tool, poll `get_status`, and inspect `get_job_events` before reporting completion. Pipeline-specific tools include:

- `process_ai_art_async`
- `process_japanese_images`
- `run_finance_video_async`

See [Agent Interface](docs/agent-interface.md) for all MCP tools, data contracts, adapter evidence, and error handling.

## Jobs, status, and artifacts

By default, jobs are persisted under:

```text
output/jobs/<task_id>/
├── status.json       # Current JobSnapshot
├── events.jsonl      # Append-only audit events
├── images/           # Generated or staged images, when applicable
├── video/            # Generated videos, when applicable
└── ...               # Pipeline-specific processed/group/artifact directories
```

A job moves through a subset of `route`, `source_scan`, `image`, `video`, `archive`, `upload`, and `complete`.

| Status | Meaning |
| --- | --- |
| `queued` | Persisted but not started |
| `running` | A pipeline step is executing |
| `succeeded` | All required work completed |
| `failed` | Required work failed |
| `blocked` | A safety or capability guard prevented completion |
| `partial` | Local artifacts or some independent publish targets succeeded while another target failed |

Treat `status.json`, `events.jsonl`, `artifacts.validation`, and `artifacts.publish_results` as completion evidence. A lower tool returning success is not sufficient unless AI Popline also validates the resulting artifacts.

## Publishing safety

Publishing is always opt-in:

```json
{
  "publish": true,
  "publish_targets": [
    {"platform": "douyin", "account": "account-name"}
  ]
}
```

Before setting `publish: true`, run the same task locally with publishing disabled and review every generated artifact.

| Platform | Guard |
| --- | --- |
| Douyin | The uploader must prove `仅自己可见` |
| Kuaishou | The uploader must prove private visibility |
| Bilibili | Requires a `tid` and verified `SAU_BILIBILI_PRIVATE_ARGS=--is-only-self 1` |
| Tencent | Saved as a draft for manual review; not auto-published |

Publishing targets are attempted independently where supported. One failed target can produce a `partial` job without discarding valid local artifacts or successful targets. Missing or ambiguous privacy evidence results in `blocked`, `failed`, or `partial` rather than silent success. File-hash deduplication also prevents accidental repeat uploads.

Read the **[Publishing Runbook](docs/publishing-runbook.md)** before using anything under [`examples/tasks/publish/`](examples/tasks/publish/).

## Development and testing

Install test tooling:

```powershell
uv sync --extra test
```

Run the repository quality gate:

```powershell
.\scripts\check.ps1
```

On Bash or Git Bash:

```bash
bash scripts/check.sh
```

The quality gate checks formatting, Ruff lint, and tests that do not call external tools or publish. Individual commands are:

```powershell
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run pytest -m "not publish and not external" --tb=short
```

External and publishing tests are intentionally separate:

```powershell
# Requires configured real tools
$env:RUN_EXTERNAL_TESTS = "1"
uv run pytest -m external

# DANGER: tests selected here may really publish
$env:RUN_PUBLISH_TESTS = "1"
uv run pytest -m publish
```

See [Smoke Testing](docs/smoke-testing.md) and [`tests/README.md`](tests/README.md) before running real integrations.

## Docker

The REST service can be built with the included Docker files:

```powershell
docker compose up --build
```

Create `.env` first and configure independent `WEB_ADMIN_TOKEN`, `WEB_API_TOKEN`, and `WEB_SESSION_SECRET` values. Docker Compose requires authentication, publishes `${API_PORT:-8080}` on host loopback only, and mounts job output at `./output:/data`; the container deployment is not the supported ZeroTier listener path.

The production pipelines still need their external tools, executables, media resources, browser sessions, and credentials to be accessible inside the container. Windows `.exe` paths from the example `.env` are not executable in a Linux container; use Linux-compatible installations and container paths, or run AI Popline directly on the configured Windows workstation.

## Troubleshooting

1. Run `ai-popline doctor` and resolve relevant path or executable failures.
2. Validate the task with `ai-popline validate-task --task <file>`.
3. Inspect `ai-popline jobs show <task_id>` and `ai-popline jobs events <task_id>`.
4. Check `artifacts.validation`, `artifacts.publish_results`, and referenced lower-tool logs/manifests.
5. For browser-backed failures, follow [Browser Automation Strategy](docs/browser-automation-strategy.md).
6. For `PRIVATE_VISIBILITY_UNSUPPORTED`, `PUBLISH_FAILED`, or `ALREADY_PUBLISHED`, follow the [Publishing Runbook](docs/publishing-runbook.md).

Common safety behavior is intentional: missing source material, invalid media, unavailable authenticated sessions, unsupported private visibility, and unparseable lower-tool output all fail closed rather than being treated as success.
