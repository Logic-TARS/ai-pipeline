# mcp-server - Draft (resume point)

status: awaiting-approval
pending action: write .omo/plans/mcp-server.md
approach: 使用官方 mcp Python SDK 创建 stdio MCP Server，暴露 10 个工具覆盖 AI Popline 全部能力

## Decisions
- 使用 mcp>=1.12.0 SDK（官方 Python SDK）
- stdio 传输协议（Agent 标准接入方式）
- 10 个 MCP tools: submit_task, get_status, run_task_sync, generate_images, render_video, upload_video, process_ai_art, list_profiles, list_jobs, upload_video
- 纯新增模块，不修改现有代码
- tests-after 策略，复用 tmp_path fixture

## Approval gate
- 计划已完成，等待用户审阅批准
