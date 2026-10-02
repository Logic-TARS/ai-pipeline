# 项目约定

## 定时任务术语

- 用户说“定时任务”“项目定时任务”或“两个定时任务”时，默认指 AI Pipeline 项目内置调度（Web 后台管理、由 `AI Pipeline Backend` 执行，配置位于 `output/schedules/`）。
- 只有用户明确说“Windows 计划任务”时，才查询 Windows Task Scheduler。
- 不要因为项目中存在 `register_*_task.ps1`，就把未加限定的“定时任务”理解为 Windows 计划任务。
- 如果用户要求检查“所有定时任务”，应分别检查并明确区分“项目内置调度”和“Windows 计划任务”。
