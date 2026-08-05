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
TTSKILL_COMMAND=ttskill
TTSKILL_TIMEOUT_SECONDS=120
```

`TTSKILL_COMMAND` and `TTSKILL_TIMEOUT_SECONDS` configure the content studio's read-only financial research adapter. The browser cannot override its fixed Skill allowlist or action parameters; authenticate the local CLI separately with `ttskill login`.

Validate global settings with:

```powershell
ai-popline doctor
```

## Web and ZeroTier settings

The packaged operator console is served at `/` by `ai-popline serve`. The safe default is loopback-only, without Web/API publishing:

```env
WEB_BIND_HOST=127.0.0.1
WEB_PORT=8080
WEB_ALLOWED_NETWORKS=
WEB_ALLOWED_HOSTS=127.0.0.1,localhost,::1
WEB_ALLOWED_ORIGINS=http://127.0.0.1:8080,http://localhost:8080
WEB_AUTH_REQUIRED=false
WEB_PUBLISH_ENABLED=false
WEB_ALLOW_ZEROTIER_HTTP=false
```

Remote access requires the exact ZeroTier interface IP and all of the following:

- `WEB_ALLOWED_NETWORKS`: comma-separated ZeroTier CIDRs whose direct peers may connect.
- `WEB_ALLOWED_HOSTS`: comma-separated HTTP Host names/IPs; include the exact bind IP.
- `WEB_ALLOWED_ORIGINS`: comma-separated browser origins including scheme and port.
- `WEB_AUTH_REQUIRED=true`.
- independent `WEB_ADMIN_TOKEN`, `WEB_API_TOKEN`, and `WEB_SESSION_SECRET` values of at least 32 characters.
- both `WEB_TLS_CERTFILE` and `WEB_TLS_KEYFILE`, unless the explicit restricted-mode `WEB_ALLOW_ZEROTIER_HTTP=true` exception is accepted.

`WEB_SESSION_TTL_SECONDS` controls session lifetime, and `WEB_PUBLISH_REAUTH_SECONDS` controls how recently a session must have logged in before a publish request. `WEB_PUBLISH_ENABLED` defaults to false and is an additional API-level guard; it does not override pipeline privacy checks.

`ai-popline serve` rejects wildcard listeners, remote addresses outside the configured CIDRs, missing authentication, partial TLS configuration, and bind addresses that are not assigned to a local interface. See the [ZeroTier Web Access Runbook](zerotier-web-access.md) before enabling remote access.

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
