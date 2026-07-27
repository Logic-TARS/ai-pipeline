# AI Popline Content Pipeline

This project orchestrates three local tools into a deterministic content pipeline:

1. Route a task to a content profile.
2. Generate ordered images.
3. Build a video with MoneyPrinterTurbo.
4. Upload with social-auto-upload, only when private Bilibili visibility is explicitly configured.

It also supports an `ai_art` branch that reads a local image folder, edits each image through Photo-Process, groups successful outputs into vertical gallery videos, adds background music, and optionally publishes privately to Douyin and/or Bilibili.

The `japanese` branch is image-only: it reads a local image folder, edits each image through Photo-Process, and saves processed images to a local output folder. It does not generate video or upload anywhere.

Real tasks stop after producing and validating the local video unless `publish: true` is explicitly present in the task. This safe default prevents an accidental upload.

## Run the Daily AI Briefing Pipeline

The first-class `ai_briefing` pipeline reads today's handoff, Markdown, and text from `G:\Hermes-Output\每日AI简报\YYYYMMDD`. It deterministically compresses the briefing to 350–500 Chinese characters, derives a complete in-video subject capped at 16 characters, calls MoneyPrinterTurbo with Pexels material, a 9:16 aspect ratio, `zh-CN-YunxiNeural`, and subtitles, then validates the video, audio, and spoken subtitles. It never falls back to an older date.

```powershell
python -m content_pipeline.orchestrator --task task.ai-briefing.example.json
```

Real output remains compatible with the handoff directory as `video\briefing.mp4`, `video\briefing.srt`, `video_status.json`, and `handoff_index.jsonl`. MPT tasks use the deterministic id `ai-briefing-YYYYMMDD` and are reused only when the narration and source hashes match.

The scheduled publish task is installed with `scripts\register_daily_ai_briefing_task.ps1`. It runs daily at 09:30 in the logged-in user's session and privately publishes to Douyin account `金融破壁人` and Kuaishou account `破壁人`. Platform titles use a complete lead phrase capped at 20 characters instead of mechanically truncating the full article title. Publishing remains fail-closed and file-hash deduplication cannot be bypassed by the compatibility runner.

## Run the Daily Finance Pipeline

Finance tasks use the newest Markdown for today, or yesterday when today's file is absent, from `G:\Job\Automation-Output\sajin\fund-daily`. The pipeline reads only the `## Response` section, accepts structured headings or the compact module-summary table emitted by the local archive, and builds a 350–500 character narration for a roughly 90-second video. A path-only handoff or an undersized script fails during source scanning before MoneyPrinterTurbo or either uploader can run. Valid input calls MoneyPrinterTurbo directly with Pexels material, a 9:16 aspect ratio, Chinese voiceover, and subtitles. Finance tasks do not call Gemini.

```powershell
python -m content_pipeline.orchestrator --task task.finance.example.json
```

With `publish: false`, the validated video remains local. With explicit `publish: true`, the default targets are Douyin account `金融破壁人` and Kuaishou account `破壁人`. Both uploaders must prove `仅自己可见` and successful publication; otherwise that target fails while the other target continues. Finance tasks do not publish to Bilibili.

## Run a Dry Run

```powershell
python -m content_pipeline.orchestrator --task task.example.json
```

## Run Real Generation Without Uploading

```powershell
python -m content_pipeline.orchestrator --task task.real.example.json
```

The real run uses the configured Gemini Skill and MoneyPrinterTurbo installations. Gemini requires Chrome/Edge with an existing Google login and normally takes 60–120 seconds per image. The generated images must decode successfully, and the final video must be a decodable vertical MP4 with a valid audio track. Validation metadata is returned under `artifacts.validation`.

## Run the AI Art Folder Pipeline

Edit `task.ai-art.example.json` so `params.source_dir` points to a folder containing images, then run:

```powershell
python -m content_pipeline.orchestrator --task task.ai-art.example.json
```

Images are scanned from the top level in natural filename order, or restricted to the exact filenames in optional `source_files`. Photo-Process receives the shared `image_prompt`; successful originals move to `archive_dir` (default `source_dir/已处理`) and failures move to optional `failed_dir`. Successful edited images are regrouped four per video, with a final smaller group when needed. Each image displays for five seconds with a subtle zoom and fade, using a deterministic MP3 from `AI_ART_BGM_DIR`.

Set `publish: true` only after reviewing the generated videos. Each target in `publish_targets` is attempted independently; a failed target does not stop the others and produces a `partial` job result. Douyin must prove “仅自己可见” before success. Bilibili remains blocked unless verified private arguments are configured.

## Run the Japanese Local Image Pipeline

Edit `task.japanese.example.json` so `params.source_dir` points to a folder containing images, then run:

```powershell
python -m content_pipeline.orchestrator --task task.japanese.example.json
```

Images are scanned from the top level in natural filename order, or restricted to filenames in optional `source_files`. Photo-Process receives `image_prompt`; successful outputs are saved as stable numbered image files in `params.output_dir`, defaulting to `source_dir/日语改图`. Original source images are preserved. This pipeline stops after local image validation and ignores publishing.

## Run the Grouped Anime MPT Pipeline

Use `task.grouped-anime.example.json` for the persistent grouped-anime workflow:

```powershell
python -m content_pipeline.orchestrator --task task.grouped-anime.example.json
```

The workflow copies source images into the job workspace, groups them by filename prefix, deterministically selects music from MoneyPrinterTurbo's `resource/songs`, and trims or loops it to `image count × seconds_per_image`. Each prefix group invokes MoneyPrinterTurbo exactly once with local images, the prepared music as custom audio, 9:16 output, subtitles disabled, TTS skipped, additional BGM disabled, and MPT cross-posting disabled. The video is pure imagery: `params.title` is optional and no title, description, subtitle, or other text is rendered into the frame. The final MP4 and its MPT task directory are retained as job artifacts and validated before any publishing step.

The example keeps `publish: false`. After reviewing the output, explicitly change it to `true` to publish independently to the configured Douyin and Bilibili accounts. Publishing remains private and fail-closed: Douyin must report “仅自己可见”, and Bilibili requires `SAU_BILIBILI_PRIVATE_ARGS=--is-only-self 1`. A failed target does not discard successful videos or other successful targets.

## Start the API

```powershell
uvicorn app:app --host 127.0.0.1 --port 8080
```

Then call:

```text
POST /run
GET /status/{task_id}
```

## Agent MCP Interface

The MCP server is the preferred interface for Codex/Hermes-style agents:

```powershell
python -m content_pipeline.mcp_server
```

Use `list_capabilities` first to discover supported workflows and lower-tool contracts. For long browser, video, or publishing work, use `run_task_async` or a task-specific async tool, then poll `get_status` and inspect `get_job_events`.

Task-specific MCP tools include:

- `process_ai_art_async`: Photo-Process folder editing, gallery video creation, optional private publishing.
- `process_japanese_images`: Photo-Process-backed local image editing; no video or upload.
- `run_finance_video_async`: dedicated Finance Markdown-to-video workflow; Finance never enters the Gemini image flow.

Lower tools should be connected through stable adapters. `Photo-Process` is exposed as a CLI JSON adapter through `main.py comic --image <path> --prompt <text> --json`; it owns Gemini browser automation, current-response candidate selection, and image validation. The parent pipeline should pass staged copies when originals must be preserved and should commit only validated artifacts.

## Private Upload Guard

Real Bilibili upload is blocked unless `SAU_BILIBILI_PRIVATE_ARGS` is set after verifying the actual `biliup upload --help` supports a private/visibility argument. Dry runs never call SAU.

Uploading also requires the task itself to contain `"publish": true`. Without that explicit opt-in, `upload_result` reports `publish_not_requested`.
