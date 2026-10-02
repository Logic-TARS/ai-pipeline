# Task examples

The examples are organized by risk level so operators can pick a task without accidentally moving from local validation to publication.

- `dry-run/`: no external publishing and suitable for local command smoke tests. These examples must keep `publish: false` and `params.dry_run: true` where the pipeline supports dry runs.
- `local/`: real local generation/editing examples with `publish: false`. They may reference real workstation paths and optional `publish_targets`, but those targets are documentation for a later reviewed publish step, not permission to upload.
- `publish/`: real private/draft publishing examples. These examples must keep explicit `publish: true`, must be reviewed before use, and may call platform uploaders when run with valid credentials.
- `archive/`: date-specific historical examples kept for regression/reference use. Do not treat these as current production tasks without reviewing the date, paths, accounts, and publish flag.

The root-level `task.*.json` files are kept as compatibility shortcuts; prefer the risk-tiered directories for new automation and documentation.

## Safe validation workflow

Before running a checked-in example in production:

1. Run `ai-pipeline validate-task --task examples/tasks/<tier>/<file>.json` and review the normalized task.
2. For `dry-run/` and `local/`, confirm `publish` is `false`; for `publish/`, confirm every `publish_targets` entry is intentional.
3. For examples with real paths, replace or verify every workstation-specific directory before running.
4. Run the task with publishing disabled first and inspect `status.json`, `events.jsonl`, generated artifacts, and `artifacts.validation`.
5. Only use files under `publish/` after following `docs/publishing-runbook.md` and confirming the private/draft visibility guarantees for the target platform.

## Production contract

- A safe smoke example is always available at `dry-run/task.example.json` for `ai-pipeline validate-task` and `ai-pipeline run` checks that must not publish.
- `local/` examples must not publish, even when they include `publish_targets` for operator convenience.
- `publish/` examples are intentionally dangerous: they are the only checked-in tier expected to contain `publish: true`.
- Publishing-capable examples must rely on AI Pipeline's fail-closed privacy and draft guards; missing visibility proof is not success.
- When adding a new example, place it in the correct risk tier and update tests if the tier contract changes.
