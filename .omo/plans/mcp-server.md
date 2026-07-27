# mcp-server - Work Plan

## TL;DR (For humans)

**What you'll get:** 一个 MCP Server，让任何支持 MCP 的 AI Agent（包括 OpenCode）能直接调用 AI Popline 的全部能力——提交内容生产任务、查询状态、单独调用生图/合成视频/上传等子步骤，以及管理 AI Art 图片处理流水线。

**Why this approach:** 使用官方 `mcp` Python SDK 的 `MCPServer`（原 FastMCP），通过 stdio 传输协议运行。复用现有的 `Orchestrator`、`JobStore`、各 tool client 模块，零破坏性改动。新增独立 `mcp_server.py` 模块 + `pyproject.toml` 依赖。

**What it will NOT do:** 不修改现有 Orchestrator/FastAPI/CLI 接口；不改变现有数据目录结构；不实现 SSE/HTTP 传输（仅 stdio）；不替代现有 profile YAML 配置。

**Effort:** Short
**Risk:** Low - 纯新增模块，复用现有经过测试的内部 API
**Decisions I made for you:** 
- 使用官方 `mcp` SDK（非第三方封装），stdio 传输（Agent 标准接入方式）
- 工具命名采用 `snake_case`，与 MCP 生态一致
- 同步工具（`run_task_sync`）和异步工具（`submit_task` + `get_status`）并存
- 不暴露 `dry_run` 作为工具参数默认值，安全优先
- 测试策略：tests-after，复用现有 `tmp_path` fixture 模式

Your next move: 审阅后批准执行，或提出修改意见。

---

> TL;DR (machine): Short effort, Low risk — 1 new file + 1 dependency update + 1 test file, exposing 8 MCP tools over stdio.

## Scope
### Must have
- 新增 `content_pipeline/mcp_server.py`：基于 `mcp.server.FastMCP` 的 stdio MCP Server
- 暴露 8 个 MCP Tool，覆盖：任务提交/查询/同步执行、子步骤调用、AI Art 处理、Profile 查询、Job 列表
- 更新 `pyproject.toml`：添加 `mcp>=1.12.0` 依赖
- 新增 `tests/test_mcp_server.py`：覆盖核心工具的 happy path + 错误处理
- 支持通过 `python -m content_pipeline.mcp_server` 启动

### Must NOT have (guardrails, anti-slop, scope boundaries)
- 不修改 `orchestrator.py`、`app.py`、现有 tool client 的内部签名
- 不实现 SSE/HTTP/streamable-http 传输（仅 stdio，Agent 标准接入方式）
- 不改变 `Settings`、`JobStore`、`TaskInput` 等现有模型
- 不实现资源（resources）或提示（prompts），仅暴露工具（tools）
- 不在 MCP 层实现额外的权限/认证（依赖本地 stdio 进程隔离）
- 不添加 CLI 子命令或 FastAPI 路由变更

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after + pytest，复用现有 `tmp_path` fixture 和 `Settings(data_dir=...)` 模式
- 证据路径: `.omo/evidence/task-<N>-mcp-server.<ext>`
- 每个 MCP tool 至少 1 个 happy path 测试 + 1 个错误路径测试
- 通过 `pytest tests/test_mcp_server.py` 全绿作为最终验证

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

- **Wave 1**: 依赖更新 + MCP Server 骨架（todo 1-2）
- **Wave 2**: 核心任务工具（todo 3-5）
- **Wave 3**: 子步骤工具 + AI Art 工具（todo 6-8）
- **Wave 4**: 查询工具 + CLI 入口 + 测试（todo 9-11）

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1. pyproject.toml 依赖 | 无 | 2 | - |
| 2. MCP Server 骨架 | 1 | 3-10 | - |
| 3. submit_task | 2 | - | 4, 5 |
| 4. get_status | 2 | - | 3, 5 |
| 5. run_task_sync | 2 | - | 3, 4 |
| 6. generate_images | 2 | - | 7, 8 |
| 7. render_video | 2 | - | 6, 8 |
| 8. process_ai_art | 2 | - | 6, 7 |
| 9. list_profiles + list_jobs | 2 | - | 10, 11 |
| 10. CLI 入口 __main__ | 2 | - | 9, 11 |
| 11. 测试文件 | 2-10 | F1-F4 | 9, 10 |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

- [x] 1. pyproject.toml: 添加 `mcp>=1.12.0` 依赖
  What to do / Must NOT do: 在 `dependencies` 列表中添加 `"mcp>=1.12.0"`，不改动其他依赖项，不添加 optional-dependencies。
  Parallelization: Wave 1 | Blocked by: 无 | Blocks: 2
  References: `pyproject.toml:6-14` — 现有 dependencies 列表
  Acceptance criteria: `pyproject.toml` 包含 `"mcp>=1.12.0"`，`uv pip install -e .` 成功安装 mcp 包
  QA scenarios: 运行 `python -c "from mcp.server import MCPServer; print('OK')"` 无 ImportError。Evidence: `.omo/evidence/task-1-mcp-server.txt`
  Commit: Y | chore(deps): add mcp>=1.12.0 dependency

- [x] 2. content_pipeline/mcp_server.py: MCP Server 骨架 + Settings/Orchestrator 初始化
  What to do / Must NOT do: 创建新文件，导入 `FastMCP`，创建 `mcp = FastMCP("ai-popline")` 实例，初始化 `Settings()` 和 `Orchestrator()` 作为模块级共享实例。添加 `if __name__ == "__main__"` 块调用 `mcp.run(transport="stdio")`。不添加任何 tool 装饰器（留给后续 todo）。使用 `logging` 模块配置 stderr 日志，避免污染 stdout 流。
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3-11
  References: 
    - `content_pipeline/settings.py:12-44` — Settings dataclass
    - `content_pipeline/orchestrator.py:21-24` — Orchestrator 构造函数
    - MCP SDK: `from mcp.server import FastMCP` + `mcp.run(transport="stdio")`
  Acceptance criteria: `python -m content_pipeline.mcp_server` 启动后等待 stdin，无 crash；`python -c "from content_pipeline.mcp_server import mcp; print(mcp.name)"` 输出 `ai-popline`
  QA scenarios: 模块可导入，FastMCP 实例 name 为 "ai-popline"，__main__ 入口存在。Evidence: `.omo/evidence/task-2-mcp-server.txt`
  Commit: Y | feat(mcp): add MCP server skeleton with stdio transport

- [x] 3. submit_task 工具: 异步提交任务，返回 task_id
  What to do / Must NOT do: 添加 `@mcp.tool()` 装饰的函数 `submit_task(description, content_type, topic, publish, params)`，参数与 `TaskInput` 对应（content_type/topic/publish 可选，params 可选 dict）。内部构造 `TaskInput` 调用 `orchestrator.submit()` 返回 `{"task_id": str, "status": "queued"}`。不执行 `orchestrator.run()`（那是异步的）。
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 无
  References: 
    - `content_pipeline/models.py:44-50` — TaskInput schema
    - `content_pipeline/orchestrator.py:26-27` — submit 方法
    - `app.py:15-19` — 现有 POST /run 的等价逻辑
  Acceptance criteria: 调用 `submit_task(description="动漫短片", content_type="anime", topic="测试")` 返回包含 32 位 hex task_id 的 dict
  QA scenarios: 
    - happy: 提交 anime 任务返回 task_id
    - happy: 提交时不指定 content_type（触发路由）返回 task_id
    - failure: description 为空字符串时返回 MCP error
    Evidence: `.omo/evidence/task-3-mcp-server.txt`
  Commit: Y | feat(mcp): add submit_task tool

- [x] 4. get_status 工具: 查询任务状态和产物
  What to do / Must NOT do: 添加 `@mcp.tool()` 装饰的函数 `get_status(task_id: str)`，调用 `orchestrator.store.get(task_id)` 返回完整 `JobSnapshot` 的 JSON 序列化 dict。FileNotFoundError 时返回 MCP error 而非抛异常。
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 无
  References: 
    - `content_pipeline/orchestrator.py` 未直接暴露 get_status，但 `app.py:22-27` 有等价逻辑
    - `content_pipeline/job_store.py:44-46` — get 方法
    - `content_pipeline/models.py:138-145` — JobSnapshot schema
  Acceptance criteria: 对已知 task_id 返回包含 status/current_step/artifacts 的 dict；对未知 task_id 返回错误
  QA scenarios: 
    - happy: 查询已提交任务返回完整状态
    - failure: 查询不存在的 task_id 返回 "task not found" 错误
    Evidence: `.omo/evidence/task-4-mcp-server.txt`
  Commit: Y | feat(mcp): add get_status tool

- [x] 5. run_task_sync 工具: 同步执行任务并返回完整结果
  What to do / Must NOT do: 添加 `@mcp.tool()` 装饰的函数 `run_task_sync(description, content_type, topic, publish, params)`，内部调用 `orchestrator.submit()` + `orchestrator.run()` + `orchestrator.store.get()` 返回最终结果。与 submit_task 参数相同。注意：此调用是阻塞的，生图+视频可能需要 60-180 秒。
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 无
  References: 
    - `content_pipeline/orchestrator.py:120-126` — run_task_file 的等价逻辑
    - `content_pipeline/orchestrator.py:29-117` — run 方法完整流程
  Acceptance criteria: 调用 `run_task_sync(description="动漫短片", content_type="anime", topic="测试", params={"dry_run": True})` 返回 status="succeeded" 的完整结果
  QA scenarios: 
    - happy: dry_run 模式同步执行返回 succeeded + 4 张图片 + 视频路径
    - failure: unknown content_type 返回 failed 状态
    Evidence: `.omo/evidence/task-5-mcp-server.txt`
  Commit: Y | feat(mcp): add run_task_sync tool

- [x] 6. generate_images 工具: 单独调用 Gemini 生图
  What to do / Must NOT do: 添加 `@mcp.tool()` 装饰的函数 `generate_images(prompt, count, content_type, output_dir)`。根据 content_type 加载对应 profile（anime/finance），调用 `call_gemini_skill()` 返回图片路径列表。output_dir 可选，默认使用 Settings.data_dir 下的临时目录。
  Parallelization: Wave 3 | Blocked by: 2 | Blocks: 无
  References: 
    - `content_pipeline/tools/gemini_client.py:17-55` — call_gemini_skill
    - `content_pipeline/profiles.py:44-52` — load_profile
    - `content_pipeline/profiles/anime.yaml` — image_gen 配置
  Acceptance criteria: 调用 `generate_images(prompt="赛博朋克城市", count=2, content_type="anime", params={"dry_run": True})` 返回 2 个图片路径
  QA scenarios: 
    - happy: dry_run 模式返回指定数量的占位图片
    - failure: 无效 content_type 返回错误
    Evidence: `.omo/evidence/task-6-mcp-server.txt`
  Commit: Y | feat(mcp): add generate_images tool

- [x] 7. render_video 工具: 单独调用 MoneyPrinterTurbo 合成视频
  What to do / Must NOT do: 添加 `@mcp.tool()` 装饰的函数 `render_video(images, content_type, topic, params)`。images 为图片路径列表，根据 content_type 加载 video_gen profile，调用 `call_mpt()` 返回视频路径。
  Parallelization: Wave 3 | Blocked by: 2 | Blocks: 无
  References: 
    - `content_pipeline/tools/mpt_client.py:15-68` — call_mpt
    - `content_pipeline/profiles/anime.yaml` — video_gen 配置
  Acceptance criteria: 调用 `render_video(images=[...], content_type="anime", topic="测试", params={"dry_run": True})` 返回视频路径
  QA scenarios: 
    - happy: dry_run 模式返回占位 MP4 路径
    - failure: 空图片列表返回错误
    Evidence: `.omo/evidence/task-7-mcp-server.txt`
  Commit: Y | feat(mcp): add render_video tool

- [x] 8. process_ai_art 工具: AI Art 图片处理流水线
  What to do / Must NOT do: 添加 `@mcp.tool()` 装饰的函数 `process_ai_art(source_dir, image_prompt, title, source_files, archive_dir, failed_dir, group_size)`。参数对应 `AiArtParams`。内部调用 `run_ai_art_pipeline()` 或复用其子逻辑（scan → photo_process → group → slideshow）。为简化，此工具执行完整 AI Art 流水线而非单步。
  Parallelization: Wave 3 | Blocked by: 2 | Blocks: 无
  References: 
    - `content_pipeline/ai_art_pipeline.py:24-163` — run_ai_art_pipeline
    - `content_pipeline/models.py:53-62` — AiArtParams
  Acceptance criteria: 调用 `process_ai_art(source_dir="...", image_prompt="风格化", title="测试", params={"dry_run": True})` 返回处理结果
  QA scenarios: 
    - happy: 有图片的 source_dir + dry_run 返回成功
    - failure: 空目录返回 "no supported images" 错误
    Evidence: `.omo/evidence/task-8-mcp-server.txt`
  Commit: Y | feat(mcp): add process_ai_art tool

- [x] 9. list_profiles + list_jobs 工具: 查询可用 Profile 和历史 Job
  What to do / Must NOT do: 添加两个工具。`list_profiles()` 扫描 profiles_dir 下所有 .yaml 文件，返回 profile 名称列表和简要信息。`list_jobs(limit)` 扫描 jobs_dir 下所有任务，按创建时间倒序返回最多 limit 个任务的摘要（task_id, status, description, created_at）。
  Parallelization: Wave 4 | Blocked by: 2 | Blocks: 无
  References: 
    - `content_pipeline/profiles.py:44-52` — load_profile + profiles_dir
    - `content_pipeline/job_store.py:16-86` — jobs_dir 结构
    - `profiles/anime.yaml`, `profiles/finance.yaml` — 现有 profile 文件
  Acceptance criteria: `list_profiles()` 返回 `["anime", "finance"]`；`list_jobs(limit=5)` 返回最近 5 个任务摘要
  QA scenarios: 
    - happy: 无任务时 list_jobs 返回空列表
    - happy: list_profiles 返回所有 yaml profile 名称
    Evidence: `.omo/evidence/task-9-mcp-server.txt`
  Commit: Y | feat(mcp): add list_profiles and list_jobs tools

- [x] 10. __main__.py: CLI 入口支持 `python -m content_pipeline.mcp_server`
  What to do / Must NOT do: 在 `content_pipeline/mcp_server.py` 中添加 `if __name__ == "__main__"` 块，调用 `mcp.run(transport="stdio")`。不需要单独的 `__main__.py` 文件。确保 stderr 日志不影响 stdio 流（使用 logging 模块，配置 handler 输出到 stderr）。
  Parallelization: Wave 4 | Blocked by: 2 | Blocks: 无
  References: 
    - MCP SDK stdio transport: `mcp.run(transport="stdio")` 阻塞监听 stdin
    - `content_pipeline/orchestrator.py:129-139` — 现有 main() 模式参考
  Acceptance criteria: `python -m content_pipeline.mcp_server` 启动后进程保持运行，等待 stdin JSON-RPC 请求
  QA scenarios: 
    - happy: 进程启动无 crash
    - 验证: 发送 `{"jsonrpc":"2.0","method":"tools/list","id":1}` 返回工具列表
    Evidence: `.omo/evidence/task-10-mcp-server.txt`
  Commit: Y | feat(mcp): add __main__ entry point for stdio transport

- [x] 11. tests/test_mcp_server.py: MCP 工具测试覆盖
  What to do / Must NOT do: 创建测试文件，覆盖所有 8 个工具的 happy path + 关键错误路径。使用 `tmp_path` fixture 创建隔离的 Settings，与 `test_orchestrator.py` 模式一致。不测试真实外部工具调用（全部使用 dry_run）。
  Parallelization: Wave 4 | Blocked by: 2-10 | Blocks: F1-F4
  References: 
    - `tests/test_orchestrator.py` — 现有测试模式
    - `tests/test_sau_client.py` — 错误路径测试模式
    - 所有工具的实现代码（todo 3-9）
  Acceptance criteria: `pytest tests/test_mcp_server.py -v` 全绿，至少 15 个测试用例
  QA scenarios: 
    - 每个工具至少 1 个 happy path + 1 个 failure path
    - 使用 dry_run 避免真实外部调用
    - 验证 MCP tool 签名与 inputSchema 正确
    Evidence: `.omo/evidence/task-11-mcp-server.txt`
  Commit: Y | test(mcp): add MCP server test suite

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit: 验证所有 11 个 todo 已实现，8 个 MCP tool 全部注册，无 Must NOT have 违规
- [x] F2. Code quality review: 类型注解完整、无裸 except、错误消息清晰、无硬编码路径
- [x] F3. Real manual QA: 启动 `python -m content_pipeline.mcp_server`，通过 stdin 发送 tools/list 确认 8 个工具注册，提交 dry_run 任务验证端到端
- [x] F4. Scope fidelity: 无修改 orchestrator.py/app.py/现有 tool client，仅新增 mcp_server.py + pyproject.toml + tests

## Commit strategy
- 每个 todo 独立 commit（共 11 commits），遵循 conventional commits
- 最终验证通过后不额外 squash（保留审计轨迹）
- 所有 commit message 以 `feat(mcp):` / `chore(deps):` / `test(mcp):` 为前缀

## Success criteria
- [ ] `python -m content_pipeline.mcp_server` 启动无 crash
- [ ] MCP tools/list 返回 8 个工具，每个有 name + description + inputSchema
- [ ] `pytest tests/test_mcp_server.py -v` 全绿（≥15 tests）
- [ ] `pytest tests/` 全绿（现有测试不被破坏）
- [ ] 端到端: 通过 stdin 提交 dry_run anime 任务 → get_status 返回 succeeded → artifacts 包含 4 张图片和视频路径
