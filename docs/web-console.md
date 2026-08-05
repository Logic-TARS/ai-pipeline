# Web Operator Console

AI Popline includes a no-Node, no-CDN operator console packaged with the Python service. It is intended for one operator on loopback or the guarded ZeroTier boundary.

## Start and open

```powershell
ai-popline serve
```

Open `http://127.0.0.1:8080/` for the default loopback configuration. A configured ZeroTier deployment uses its HTTPS origin instead; follow the [ZeroTier Web Access Runbook](zerotier-web-access.md).

When `WEB_AUTH_REQUIRED=true`, enter `WEB_ADMIN_TOKEN` on the login screen. The token is exchanged for a signed, HttpOnly session cookie; the console automatically supplies the separate CSRF token for writes and clears both cookies when you log out.

## Content studio

The default workspace is **内容工作台**. It includes a financial template that collects current research through a fixed read-only ttskill allowlist—gold, bond market, China macro data, and up to five operator-selected stock quotes—and an AI briefing template that imports the latest dated `article.md` and handoff metadata from `AI_BRIEFING_DIR`. Account, holding, profit, order, and trading Skills cannot be invoked from the browser.

Research/import runs in the background and each source retains both its collection time and the source-provided data time. Partial results remain available when one Skill fails. Review the source cards, manually write and save a 350–500 character narration containing the investment-risk disclaimer, then select **保存并生成视频**. This queues a local `script_video` MoneyPrinterTurbo job and switches to the task center; it never enables publishing.

Drafts and sanitized source results are stored under `output/content-drafts/<draft_id>/`. ttskill credentials, cookies, identity data, and arbitrary gateway metadata are not stored or returned by the content API. If the local CLI session expires, run `ttskill login` interactively on the server and refresh the research.

## Dashboard

The **任务中心** shows:

- recent-job counts and active/attention totals;
- storage, profiles, and Web publishing readiness flags without local paths;
- status, pipeline, and text filters;
- automatic 2.5-second refresh while jobs are queued or running, and slower idle refresh;
- the selected job's current step, timestamps, validation evidence, publish results, events, and raw snapshot.

Polling pauses while the browser tab is hidden. Use **Refresh** for an immediate update.

## Create a task

Select **New task**, then choose one of the six pipelines. The form is generated from the authenticated `/ui/bootstrap` contract and presents only that pipeline's common parameters.

1. Enter a description and optional topic.
2. Fill required pipeline fields; safe dry-run defaults are enabled where supported.
3. Keep publishing off for the first run.
4. Optionally add an advanced JSON object; advanced keys override matching form fields.
5. Select **Preflight task** to validate and normalize the task without creating a job or calling an external tool.
6. Review the final JSON and select **Start run**.

Path fields are paths on the AI Popline server workstation. Browsers cannot browse arbitrary server files, and a path from a different client operating system is not uploaded or translated automatically.

## Job details and artifacts

Select a task row to view its step track and append-only event timeline. The details panel shows media validation, grouped results, and per-platform publishing evidence when available.

Only files registered in `JobSnapshot.artifacts` and resolving inside that job's directory appear in the artifact gallery. Images and videos can be previewed; other registered files open through the same authenticated, containment-checked endpoint. External source documents and arbitrary workstation paths are never served.

## Publishing

Web publishing has two independent gates:

1. `WEB_PUBLISH_ENABLED=true` must be configured on the server.
2. The task's publishing switch must be enabled by the operator.

The console labels this action **generate and publish** because the current pipeline runs generation and publishing in one task. It is not a separate approval of an already completed job: first run an equivalent task with publishing off and review its output.

Before submission, the console requires the operator to type `确认发布`. It then submits `PUBLISH:<task_fingerprint>`, where the fingerprint came from server preflight; changing any task field invalidates that confirmation. Recent-login, platform privacy, deduplication, and uploader guards remain enforced by the backend.

## Common errors

- **401 / login screen:** the session expired or the token is invalid; log in again.
- **CSRF failed:** refresh the page and log in again so the session and CSRF cookies match.
- **Peer, Host, Origin, or HTTPS rejected:** review the ZeroTier listener, firewall, allowed hosts/origins, and certificate configuration.
- **Preflight field errors:** correct the named form field or advanced JSON value; preflight does not create a failed job.
- **No artifacts:** the job may still be running, may have failed before output, or may only reference files outside its guarded job directory.
- **Publishing disabled:** keep publishing off, or deliberately configure the server-side Web publishing guard after reviewing the publishing runbook.
