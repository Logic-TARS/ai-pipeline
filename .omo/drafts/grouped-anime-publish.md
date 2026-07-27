---
slug: grouped-anime-publish
status: awaiting-approval
intent: clear
pending-action: write .omo/plans/grouped-anime-publish.md
approach: 扩展现有 ai_art 管道，添加按前缀分组逻辑，跳过 AI 改绘步骤，直接组合图片并发布到抖音和B站
---

# Draft: grouped-anime-publish

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->
| id | outcome | status | evidence path |
| --- | --- | --- | --- |
| C1 | 前缀分组逻辑 | active | content_pipeline/grouping.py (新建) |
| C2 | 管道编排扩展 | active | content_pipeline/orchestrator.py:38-46, content_pipeline/ai_art_pipeline.py |
| C3 | 数据模型扩展 | active | content_pipeline/models.py:53-63 |
| C4 | 发布目标配置 | active | content_pipeline/models.py:32-41, task JSON |

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->
| assumption | adopted default | rationale | reversible? |
| --- | --- | --- | --- |
| 前缀检测算法 | 正则：`^(.*?)(\d+)$`，提取数字前的部分作为前缀（保留分隔符） | 用户要求"自动检测"，这是最通用的方案 | Yes |
| 视频样式 | 复用现有 slideshow：5秒/图，0.5秒淡入淡出，BGM，1080x1920 | 用户确认复用现有样式 | Yes |
| 分组排序 | 按前缀的字母顺序，组内按文件名的自然排序 | 符合直觉的排序方式 | Yes |
| 发布目标 | 任务驱动：publish_targets 在任务 JSON 中指定，不硬编码 | 符合现有架构模式 | Yes |
| BGM 配置 | 复用现有 `AI_ART_BGM_DIR` | 用户未指定，复用现有配置 | Yes |
| 归档逻辑 | 不归档源图片（与 ai_art 不同，因为不做处理） | 用户未要求，保持简单 | Yes |
| 最小分组大小 | 无最小限制，单张图片也可成组 | render_slideshow 支持单图 | Yes |

## Findings (cited - path:lines)
- `content_pipeline/ai_art_pipeline.py:24-202`: 现有 AI 艺术管道，包含扫描、分组、视频生成、发布完整流程
- `content_pipeline/tools/slideshow_client.py:23-101`: 幻灯片渲染，支持自定义秒数/图、淡入淡出、BGM
- `content_pipeline/tools/photo_process_client.py:16-35`: `scan_source_images` 扫描逻辑，可复用
- `content_pipeline/models.py:10`: `ContentType = Literal["anime", "finance", "ai_art", "unknown"]` - 需要添加 `"grouped_anime"`
- `content_pipeline/models.py:53-63`: `AiArtParams` 数据模型，需扩展或新建
- `content_pipeline/models.py:32-41`: `PublishTarget` 支持抖音和B站
- `content_pipeline/orchestrator.py:38-46`: 路由到 ai_art 管道的逻辑，需要添加 grouped_anime 分支
- `content_pipeline/router.py:18-20`: 内容类型关键字，需要添加新关键字
- `content_pipeline/router.py:41-51`: `_route_with_rules` 函数，关键字检查顺序很重要

## Decisions (with rationale)
| decision | rationale |
| --- | --- |
| 新建 `grouped_anime_pipeline.py` 而不是修改 `ai_art_pipeline.py` | 避免破坏现有功能，逻辑差异明显（无 AI 改绘） |
| 添加新 content_type `grouped_anime` | 清晰的类型区分，便于路由 |
| 前缀检测放在独立模块 `grouping.py` | 可复用、可测试 |
| 复用 `render_slideshow` 和 `call_sau_target` | 最大化代码复用，减少维护成本 |
| 不使用 profile 系统，直接分发 | 与 ai_art 保持一致，避免创建无用的 profile |
| Router 关键字检查顺序：grouped_anime 在 anime 之前 | 避免关键字冲突导致错误路由 |
| 发布目标由任务 JSON 指定 | 符合现有架构，不硬编码账号 |

## Scope IN
- 指定文件夹，按文件名前缀自动分组图片
- 每组图片生成一个竖屏视频（5秒/图，淡入淡出，BGM）
- 发布到山下富士（抖音）和酸菜鱼（B站）
- 支持 dry_run 模式
- 任务状态持久化和事件日志

## Scope OUT (Must NOT have)
- 不做 AI 改绘（不调用 Photo-Process）
- 不修改现有 ai_art 管道逻辑
- 不支持自定义视频样式（秒数、转场等）
- 不支持其他平台（仅抖音和B站）

## Open questions
无 - 所有关键决策已确认

## Approval gate
status: awaiting-approval
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
