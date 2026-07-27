# AI Popline Architecture

## Overview

AI Popline is a local AI content production pipeline that orchestrates three external tools — Gemini, Photo-Process, MoneyPrinterTurbo (MPT), and social-auto-upload (SAU) — to generate and publish short-form video content across 6 content pipelines.

```
TaskInput (JSON/MCP/REST)
  → Orchestrator.submit() → JobStore
  → route_task() → RouteResult
  → pipeline dispatch → adapter calls
  → JobSnapshot (persisted to output/jobs/<id>/)
```

## Six Content Pipelines

| Pipeline | Content Type | Flow | External Tools |
|---|---|---|---|
| **Anime** | `anime` | Gemini image gen → MPT video → Bilibili upload | Gemini, MPT, SAU |
| **Finance** | `finance` | Markdown parsing → narrated MPT video → Douyin/Kuaishou publish | MPT, SAU |
| **AI Briefing** | `ai_briefing` | Daily handoff → script building → narrated MPT → Douyin/Kuaishou/Tencent publish | MPT, SAU |
| **AI Art** | `ai_art` | Photo-Process folder editing → slideshow groups → optional private publish | Photo-Process, ffmpeg, SAU |
| **Grouped Anime** | `grouped_anime` | Source images grouped by prefix → per-group MPT video → optional publish | MPT, SAU |
| **Japanese** | `japanese` | Photo-Process Gem editing → local image output only | Photo-Process |

## Pipeline Steps

Every pipeline progresses through a subset of these steps:

```
ROUTE → SOURCE_SCAN → IMAGE → VIDEO → ARCHIVE → UPLOAD → COMPLETE
```

- **Japanese** stops after IMAGE (no video or upload)
- **Finance** and **AI Briefing** skip IMAGE (no image generation)
- **Anime** (legacy) uses IMAGE → VIDEO → UPLOAD

## External Tool Dependencies

| Tool | Path | Adapter | Purpose |
|---|---|---|---|
| Gemini Skill | `GEMINI_SKILL_DIR` | `adapters/gemini_mcp.py` | MCP-based image generation |
| Photo-Process | `PHOTO_PROCESS_DIR` | `adapters/photo_process.py` | Browser-automated image editing |
| MoneyPrinterTurbo | `MPT_DIR` | `adapters/mpt.py`, `adapters/mpt_narrated.py` | Video generation |
| social-auto-upload | `SAU_DIR` | `adapters/sau.py` | Multi-platform publishing |
| ffmpeg | (system) | `adapters/slideshow.py`, `adapters/audio.py` | Slideshow rendering, music prep |

## Entry Points

| Interface | Command | Description |
|---|---|---|
| CLI | `python -m content_pipeline.orchestrator --task <file>` | Run a task JSON synchronously |
| MCP | `python -m content_pipeline.mcp_server` | MCP stdio server (18 tools) |
| REST | `uvicorn app:app --host 127.0.0.1 --port 8080` | FastAPI with POST /run and GET /status/:id |
| Doctor | `ai-popline doctor` | Environment and tool diagnostics |
| Capabilities | `ai-popline capabilities` | List available pipelines |

## Adapter Pattern

All external tool calls return a uniform `AdapterResult`:

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

Adapters isolate subprocess execution, timeouts, stdout parsing, and tool-specific quirks. The orchestrator never depends on Gemini browser state, MPT internals, or uploader UI details directly.

## Job Persistence

Jobs are stored at `<data_dir>/jobs/<task_id>/`:

- `status.json` — full `JobSnapshot` (task, route, artifacts, validation, error)
- `events.jsonl` — append-only audit log (job_created, step_started, job_finished, etc.)
- `images/` — generated/staged images
- `video/` — generated MP4 files
- Pipeline-specific directories (groups/, processed/, photo_process_sources/)

## Publishing Safety

All publishing defaults to OFF. `TaskInput.publish` must be explicitly `true`. Each platform has private-visibility enforcement:

- **Douyin**: must prove "仅自己可见"
- **Kuaishou**: must prove private visibility
- **Bilibili**: requires `SAU_BILIBILI_PRIVATE_ARGS=--is-only-self 1`
- **Tencent**: saves as draft only

Fail-closed: any uncertainty → BLOCKED status.

## Directory Structure

```
src/content_pipeline/
  api/          # FastAPI app factory
  cli/          # CLI entry points (doctor, capabilities, orchestrator runner)
  core/         # settings, models, errors, router
  pipelines/    # 6 pipeline implementations + registry
  adapters/     # external tool clients (gemini, mpt, photo_process, sau, ffmpeg)
  storage/      # job store persistence
  validation/   # media validation, grouping
```
