# Configuration

AI Popline uses two configuration layers:

1. `.env` / environment variables for global tool paths and runtime settings.
2. `config/pipeline.defaults.yaml` for per-pipeline default task parameters.

## Global settings

Common `.env` values:

```env
PIPELINE_DATA_DIR=output
PIPELINE_DEFAULTS_FILE=config/pipeline.defaults.yaml
GEMINI_SKILL_DIR=G:\Job\gemini-skill
PHOTO_PROCESS_DIR=G:\Job\Photo-Process
PHOTO_PROCESS_PYTHON=G:\Job\Photo-Process\.venv311\Scripts\python.exe
MPT_DIR=G:\Job\MoneyPrinterTurbo
MPT_PYTHON=G:\Job\MoneyPrinterTurbo\.venv\Scripts\python.exe
SAU_DIR=G:\Job\social-auto-upload
SAU_EXE=G:\Job\social-auto-upload\.venv\Scripts\sau.exe
SAU_BILIBILI_PRIVATE_ARGS=--is-only-self 1
FINANCE_MD_DIR=G:\Job\Automation-Output\sajin\fund-daily
AI_BRIEFING_DIR=G:\Hermes-Output\每日AI简报
```

Validate global settings with:

```powershell
ai-popline doctor
```

## Per-pipeline defaults

Edit:

```text
config/pipeline.defaults.yaml
```

It is disabled by default:

```yaml
enabled: false
```

Set it to true when you want the file to supply defaults:

```yaml
enabled: true
```

Merge rules:

- `pipelines.<content_type>.params` becomes default task params.
- Explicit values in a task JSON always override YAML defaults.
- Supported placeholders in YAML strings:
  - `{data_dir}`
  - `{task_id}`
  - `{content_type}`
  - `{topic}`

Example Japanese output layout:

```yaml
enabled: true
pipelines:
  japanese:
    params:
      source_dir: "G:\\Job\\Photo-Datasets\\jap"
      output_dir: "{data_dir}\\japanese\\{task_id}"
      target_gem_url: "https://gemini.google.com/gem/f306c82a8105"
      image_prompt: ""
```

Then a minimal task can be:

```json
{
  "description": "日语视觉化图片-only",
  "content_type": "japanese",
  "publish": false,
  "params": {}
}
```

The final output would go under:

```text
output\japanese\<task_id>\
```

## Keep publish explicit

Publishing is not enabled by YAML defaults. A task still needs:

```json
"publish": true
```

Bilibili remains blocked unless `SAU_BILIBILI_PRIVATE_ARGS=--is-only-self 1` is configured.
