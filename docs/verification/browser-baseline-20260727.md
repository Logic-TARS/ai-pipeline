# 日语视觉化浏览器失败基线（冻结）

**冻结时间：** 2026-07-27  
**用途：** 浏览器自动化改造前的回归比较证据。此文件只保留脱敏后的摘要和原始诊断文件校验值；不复制 Chrome Profile、Cookie、源图或会话内容。

## 受影响的真实任务

| Job | 时间 | 结论 |
| --- | --- | --- |
| `output/jobs/442d35f6a210414a9b7b049d7e0bb2ca/status.json` | 2026-07-27 00:30 | 固定 Gem URL `https://gemini.google.com/gem/7aaa12067979` 被重定向到 `/app`，没有产生可用图片。 |
| `output/jobs/0bb853e7d14b4f459a10e1b05ac63d7d/status.json` | 2026-07-27 00:42–00:53 | 指定 URL 后的按名称恢复路径在 Gem 列表等待超时；没有产生可用图片。 |
| `output/jobs/674dbd7ff9684e069e35d999eae517fa/status.json` | 2026-07-26 17:01 | Chrome `ProcessSingleton` 报错，说明同一 Profile 曾被并发占用。 |

共同的上层终态为：`Photo-Process did not produce any usable Japanese images`。

## 原始诊断文件（Photo-Process）

这些文件仍留在 `G:\Job\Photo-Process\logs\diagnostics\`；以下 SHA-256 用于确认改造前证据未被改变。

| 文件 | SHA-256 | 关键字段 |
| --- | --- | --- |
| `20260727_005018_2568fdfb74fe4015.json` | `d4debf4c7c38c1df5b1af64f5053b8fbafafca6b5fec79faa520313724f3eacb` | `stage=gem_navigation`，最终 URL 为 `/app` |
| `20260727_005041_2568fdfb74fe4015.json` | `c638b44f5330d813253c89032847bde5b681b2a0341e4c4524ac126b1f31fc1a` | `stage=gem_navigation`，目标 Gem 无法进入 |
| `20260727_005250_2568fdfb74fe4015.json` | `52d273de248ca7102416012c5e9f77fcee151b7d2ed285367a8a71e8755dda9b` | `stage=gem_navigation`，最终 URL 为 `/app` |
| `20260727_005313_2568fdfb74fe4015.json` | `cc34fec6470577a2ae1949325391bef6bb28a2b2a0b8a28941b51bc85e907a0b` | `stage=gem_navigation`，目标 Gem 无法进入 |

## 已确认的故障表现

1. 专用浏览器目录为 `C:\Users\Family\.wjz_browser_data`。
2. Gemini 通用页面可加载且有聊天输入框、上传入口；这**不能**证明 Google 已登录或有 Gem 权限。
3. 页面快照含有 `mavatar-sign-in-icon-button` 和默认头像，表明登录检测发生假阳性。
4. 固定 Gem URL 被导向 `/app`；按名称恢复也未能在 20 秒内读取到 Gem 条目。
5. 历史上出现过 Profile 占用，必须作为独立、不可重试的错误处理。

## 改造后的对比要求

后续真实冒烟测试必须记录：认证状态、目标 URL 与最终 URL、目标 Gem 验证结果、错误码、浏览器 Worker 状态，以及经解码校验的输出图像。只有图片已生成并通过验证时，才可替代本基线中的失败结论。
