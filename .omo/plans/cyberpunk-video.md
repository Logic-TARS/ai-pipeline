# cyberpunk-video - Work Plan

## TL;DR (For humans)

**What you'll get:** 一个关于“赛博朋克”主题的短视频，已自动生成并发布到抖音。

**Why this approach:** 直接调用桑博（Sampo）的 `media_pipeline_run` 工具，这是最成熟的全流程链路（MPT 生成 + SAU 发布）。

**What it will NOT do:** 不手动编辑视频内容；不发布到其他平台（除非后续要求）；不修改桑博的默认账号配置。

**Effort:** Quick
**Risk:** Low - 桑博工具链已验证可用
**Decisions to sanity-check:** 
- 视频脚本和画面风格采用默认“赛博朋克”设定（霓虹、雨天、未来城市）。
- 发布账号使用桑博默认配置的抖音账号。

Your next move: 批准执行。

---

> TL;DR (machine): Quick, Low risk — Trigger Sampo's `media_pipeline_run` via CLI.

## Scope
### Must have
- 使用 `hermes -p sampo -z` 触发视频生成与发布
- 主题为“赛博朋克”
- 发布目标为抖音

### Must NOT have (guardrails, anti-slop, scope boundaries)
- 不修改桑博配置文件
- 不干预生成过程（除非报错）
- 不发布到 B 站或其他平台

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: Manual QA via CLI output analysis
- Evidence: `.omo/evidence/task-1-cyberpunk-video.log`

## Execution strategy
### Parallel execution waves
> Single wave execution.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1. Trigger Sampo pipeline | None | F1-F4 | - |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [ ] 1. Trigger Sampo `media_pipeline_run` for Cyberpunk video to Douyin
  What to do / Must NOT do: Run `hermes -p sampo -z "Use media_pipeline_run to generate a cyberpunk video and publish to Douyin."`. Capture output. Do NOT modify config.
  Parallelization: Wave 1 | Blocked by: 无 | Blocks: F1-F4
  References: `hermes` CLI, Sampo `media_pipeline_run` tool.
  Acceptance criteria: Command returns success status; output indicates video generated and published.
  QA scenarios: 
    - Happy: Output shows "Published to Douyin".
    - Failure: Output shows error (e.g., "Login required", "Generation failed").
    Evidence: `.omo/evidence/task-1-cyberpunk-video.log`
  Commit: N | chore(sampo): trigger cyberpunk video pipeline

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA
- [ ] F4. Scope fidelity

## Commit strategy
- No commits (CLI execution only).

## Success criteria
- [ ] `hermes` command exits with 0.
- [ ] Output confirms video generation.
- [ ] Output confirms Douyin publication.
