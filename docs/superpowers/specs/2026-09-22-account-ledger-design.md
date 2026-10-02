# 共享账号账本（Account Ledger）设计

- 日期：2026-09-22
- 涉及仓库：`G:\Job\social-auto-upload`（SAU，写入方）、`G:\Job\ai-popline`（只读方）
- 状态：待评审

## 1. 背景：为什么要做这件事

账号身份在 ai-pipeline 里有 **6 处代码副本 + 2 处运行态副本**，与 SAU 的真实状态靠人工同步；不一致时不会报错，而是错发或断发布。2026-09-22 实测证据：

| 现象 | 证据 |
|---|---|
| 改标识会静默断发布 | 2026-09-16 快手身份 `破壁人` → `搞AI的罗辑同学`，当天任务 `AUTH_EXPIRED`，需人工同步 9 处副本 |
| 身份名会说谎（身份名 ≠ 平台真实昵称） | 实时探针：`kuaishou_搞AI的罗辑同学` 的页面页头昵称是 **金融破壁人**；`douyin_硅基思维TARS` 的抖音号 68344185416 昵称是 **山下富士** |
| 真实昵称无处可查 | 昵称不存在于 cookies、`db/account_names.json`（空）、bridge `/api/accounts`（`display_name` 全空），只能开浏览器读页面 |
| 身份名会被"偷换" | publish_history 显示 `douyin 山下富士` 发到 2026-08-02，cookie 于 08-25 改名为 `douyin_硅基思维TARS.json`，账号本身未变 |

根因：**SAU 用可变的东西（cookie 文件名）当账号标识**，而配置把这份可变标识抄了 8 份。

## 2. 目标与非目标

**目标**

1. 写入方统一：SAU 改标识/登录后，ai-pipeline 零改配置即跟上（"改一处就生效"）。
2. 读取方统一：ai-pipeline 发布前从账本拿到权威的身份名与状态。
3. 存真实昵称：昵称进账本并持续刷新，身份名与昵称不一致时能被发现。

**非目标**

- 不解决"内容与账号品牌是否匹配"（例如 AI 简报发到金融账号）。账本只负责**暴露**账号事实，不替业务做内容分线决策。
- 不替代 SAU 自身的登录校验（见 §6）。
- 不做多机/远程同步（bridge 已可服务控制台；日后需要再把账本暴露成 HTTP）。
- 不并入发布历史（`logs/publish_history.jsonl` 保持原样）。

## 3. 已定决策

| 决策 | 取值 |
|---|---|
| 存储 | SQLite，`SAU_DIR/db/accounts.db`，WAL 模式。`import sqlite3` 标准库，**零新增依赖** |
| 主键 | `(platform, platform_uid)` —— 平台发的稳定 ID，改名不变 |
| 身份名 | 可变"外号"，只作为 `sau --account` 的取值 |
| 改名历史 | **不保存**。不做 `identity_history`，不做别名解析层 |
| 写入方 | **仅 SAU**。ai-pipeline 只读（`mode=ro`） |
| 配置引用 | 存 **UID**；名字只在人工输入时作为便利写法 |
| 不动 | 遗留库 `db/database.db`；SAU 的 check 与发布行为 |

## 4. 数据模型

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE accounts (
  platform        TEXT NOT NULL,        -- douyin | kuaishou | tencent | bilibili | xiaohongshu
  platform_uid    TEXT NOT NULL,        -- 平台稳定 ID；拿不到时为合成键
  identity        TEXT NOT NULL,        -- 当前身份名 = cookie 文件名 = sau --account 取值
  nickname        TEXT,                 -- 平台侧真实昵称（尽力而为，允许为空）
  public_id       TEXT,                 -- 平台对外号（抖音号等），仅供展示，不参与匹配
  display_name    TEXT,                 -- 界面别名（原 db/account_names.json 语义）
  status          TEXT NOT NULL DEFAULT 'unknown',  -- valid | expired | error | unknown
  status_message  TEXT,
  checked_at      TEXT,                 -- 上次校验时间（ISO）
  uid_source      TEXT NOT NULL DEFAULT 'unknown',  -- cookie | page | synthetic
  first_seen_at   TEXT NOT NULL,
  last_login_at   TEXT,
  PRIMARY KEY (platform, platform_uid)
);

CREATE UNIQUE INDEX accounts_platform_identity ON accounts(platform, identity);
```

**两个命名空间不得混用（重要）**：抖音页面上的"抖音号"（如 `93006552820`）与 cookie 里的内部 uid（如 `7640519636165559355`）**是不同的 ID 体系**。`platform_uid` **只用内部 uid**；"抖音号"存入 `public_id`，仅作展示与人工核对。两者混进同一列会造成"同一账号变成两行"的错误。若内部 uid 拿不到（`douyin_硅基思维TARS` 只有非数字 UUID，不可作稳定键）→ 走合成键，**不拿 `public_id` 顶替**。

**UID 来源与降级**（唯一降级口，显式标注不藏）

各平台离线可读字段（已实测）：抖音 creator uid（cookie 内 `SLARDAR*` localStorage）、快手 `userId`、视频号 `wxuin`、小红书 `USER_INFO_FOR_BIZ.userId`。

离线拿不到时（如 `douyin_硅基思维TARS` 只有 `uid_tt`、bilibili 无字段）→ 开一次页面取（抖音页面显示"抖音号"，是**另一个 ID**，仅作展示，不冒充内部 uid）；两者都拿不到 → 合成键 `unresolved:<identity>` 且 `uid_source='synthetic'`，表示该行**改名不安全**。合成键行被改名时，重写 `platform_uid` 为新的合成值。

**边界规则（必须显式定义，否则解析不确定）**

- 名字解析（`identity` 或 `nickname` → 行）在同一平台内**必须唯一命中**；零命中或多命中一律报错并列出可用账号，要求改用 UID。
- 同一 `identity` 被重新登录成另一个账号（新 uid 撞 `UNIQUE(platform, identity)`）：旧行删除、新行建立，写 WARNING 日志"身份 X 下的账号从 uid A 换成 uid B"。这正是 `douyin_硅基思维TARS` 那类情况。
- `display_name` 并入本表，**`db/account_names.json` 退休**（不留两份别名存储）。退休随写入点 4（别名端点）一起落地，属第二期。

## 5. 数据流

### 5.1 写入点（全部在 SAU）

| # | 触发 | 位置（2026-09-22 现状） | 写入内容 |
|---|---|---|---|
| 1 | 状态校验 | `server/account_dashboard.py:425 AccountStatusManager._worker_loop`（单 worker 串行，天然无写并发） | `status`/`status_message`/`checked_at`/`nickname`/`platform_uid` |
| 2 | 改标识 | `server/account_dashboard.py:158 rename_account_identity` | 更新该 uid 行的 `identity`（uid 不变） |
| 3 | 登录成功 | 各 uploader 的 `*_cookie_gen`、`server/login_sessions.py` | 插入/更新行、`last_login_at`、可读到时写 `nickname` |
| 4 | 删号 / 设别名 | bridge `/api/accounts` 的 delete 与 display-name 端点（`bridge_server.py:1045`/`:1098` 附近） | 删行 / 写 `display_name` |

写入点 1 需要先把昵称与 uid 送出来：扩展 `sau_cli.py:1193` 的 check 分支，让结果 dict 增加 `nickname`（+ `platform_uid` 若页面可读），随 `SAU_CHECK_RESULT:{json}` 输出；`AccountStatusManager` 解析并落库。昵称读取在**该次校验已经打开的页面上**完成（快手 `cp.kuaishou.com/article/publish/video` 页头已实测可读；抖音 `creator-micro/content/upload` 页若取不到，则在 check 结束前额外访问一次 `creator-micro/home`，成本约 2–3s）。

### 5.2 读取点（ai-pipeline 只读）

新增 `account_ledger` 模块：只读打开账本（`file:...?mode=ro`，WAL 下与写入并发安全），提供 `resolve_publish_account(platform, ref)`。

```
ref 是 UID  → 直接命中
ref 是名字  → 按 identity / nickname 查（唯一命中才接受）
产物        → {uid, identity, nickname, status, checked_at, uid_source}
```

**唯一咽喉点**：`tools/sau_client.py:20 _ensure_account_is_known` 升级为该解析函数，三个调用点共用：`call_sau_target:161`、小红书 `:129`、bilibili `:421`。拼 SAU 命令时用**解析出的 `identity`** 替代现在直接塞的 `target.account`。

发布路径**不再依赖 bridge**。控制台下拉框（`deferred_publishing.py:70 _fetch_publish_account_options`）继续走 bridge，但 bridge 读同一份账本，因此两边天然一致；`AccountRecord`（`account_dashboard.py:47`）增加 `platform_uid`/`nickname` 字段用于展示。

## 6. 错误处理与策略

**解析失败分两种，处理相反**（必须分清，否则要么静默错发、要么误拦）：

- **账本不可用**（文件不存在、打开失败、schema 不符）→ **fail-open**：回退用配置里的字面量（即今天的路径）+ 警告。与现状一致，不会因为账本本身出问题而停摆。
- **账本可用但 ref 零命中 / 多命中** → **硬失败** `ConfigError`，列出该平台可用账号（UID + 身份名 + 昵称 + 状态）。账本可用时它就是权威，查不到说明配置里的名字确实已不存在；错误信息中提示"若刚在 SAU 新增账号，请先跑 `sau accounts sync`"。
- 含义：**不允许静默用旧名字发布**——这正是今天两处事故的成因。

**状态字段的角色**：只用于**早失败与告警**，不作为放行依据。

- `expired` → 早失败 `ConfigError`，附重新登录命令。
- `unknown`、`checked_at` 缺失 → 警告放行，交给 SAU 自己的校验。
- `valid` → 放行，**仍然执行 SAU 的校验**，不跳过。
  > 依据：2026-09-21 的 `AUTH_EXPIRED` 是 SAU 校验过程的假阴性。账本不能变成第二处"看起来权威但可能过期"的判据。
- `checked_at` 超过 7 天 → 警告"状态可能过期"（第一期不做定期巡检，见 §8）。

**昵称漂移**：

- `identity != nickname` → 提示（**不拦**）：身份名只是外号，不一致是合法状态；但提示能让"快手其实叫金融破壁人"这类事实浮出水面。
- `nickname` 本次与上次不同 → 由写入方（SAU，写入点 1）在覆盖前比较并写 WARNING 日志。不建历史表、不保留旧值。

## 7. ai-pipeline 侧改造清单

| 位置 | 现状 | 改为 |
|---|---|---|
| `models.py:352-354 / 386-388 / 414-416` | 三个 `*Params` 的账号默认值字面量 | 默认 None，运行时解析 |
| `api/ui_schema.py:116-118 / 188-190 / 260-261` | 表单默认值字面量 | 账本填充，下拉显示"昵称（UID）" |
| `deferred_publishing.py:70` 附近 | 发布就绪默认值 | 同上 |
| `ai_briefing_runner.py:46-51` | 硬编码 3 个 `PublishTarget` | 改从 `publish_policy.json` 读（本来就是策略来源） |
| `config/publish.defaults.yaml` + `src/content_pipeline/config/publish.defaults.yaml` | 两份重复文件、账号字面量 | 换 UID 示例，**并消掉重复**（两份同改是 09-16 事故的放大器） |
| `output/publish_policy.json`、`output/schedules/*.json` | 账号名字面量 | 一次性迁移为 UID（先备份） |
| `tools/sau_client.py:20` | 只做"是否已知"校验 | 升级为解析 + 取 identity |

命令归属：引导与刷新归 SAU（`sau accounts sync`、`sau accounts show`）；ai-pipeline 只加只读的 `ai-pipeline accounts list`。

## 8. 分期

**第一期（端到端可用）**

1. SAU：建账本 + `sau accounts sync` 引导（离线扫 cookies 取 uid，`--probe` 开页面补昵称）+ 写入点 1（check 落库）+ 写入点 2（改标识落库）。
2. ai-pipeline：`account_ledger` 只读模块 + 咽喉点解析 + §7 全部改造 + 运行态迁移。
3. 验收：在 SAU 改一次标识，次日定时任务无改配置即正常发布。

**第二期**

- 写入点 3、4（登录/删号/别名并入，`account_names.json` 随之退休）。
- 定期巡检（定时 check）以解决"状态可能过期"，并顺带刷新昵称。
- 昵称变化的告警出口（现在只有日志）。

**计划切分**：本设计的第一期对应**一份**实施计划（端到端可用）；第二期另立计划，不与第一期混在同一份里。

## 9. 测试策略

**SAU（pytest）**

- 账本读写用临时 db：引导导入（临时 cookies 目录）、check 落库（注入假 runner，断言 nickname/uid 写入）、rename（断言 `identity` 改变而 `platform_uid` 不变）、合成键行改名重写、`UNIQUE(platform, identity)` 冲突规则。
- 旁路保证：写入函数抛异常时，check/rename 的返回值不受影响。

**ai-pipeline（pytest）**

- `resolve_publish_account` 各分支：UID 命中、名字唯一命中、零命中、多命中、`expired`、`unknown`、账本不存在（fail-open）。
- 命令行拼接：`dry_run` 断言 `--account` 用的是**解析后的 identity**。
- 并发读：账本被写时只读打开仍可读（WAL）。
- 需改动的现有测试：`tests/unit/test_account_status.py`、`tests/unit/test_deferred_publish.py`、`tests/unit/test_publish_policy.py`、`tests/test_sau_client.py`、`tests/unit/test_settings_center.py`、`tests/unit/test_web_console.py`、`tests/test_script_video_pipeline.py`、`tests/test_finance_pipeline.py`（这些现在断言账号名字面量）。

**端到端**：对 AI 简报任务跑一次 `dry_run`，断言命令行中的 `--account` 与账本一致。

## 10. 风险与回滚

| 风险 | 处置 |
|---|---|
| SAU 仓库有大量未提交改动，改动可能与其自身演进冲突 | 动手前先确认工作树、必要时开分支；账本相关改动集中在少数文件（`account_dashboard.py`、`sau_cli.py`、`bridge_server.py`、新 `db/` 模块） |
| 写账本把发布链路带挂 | **写入必须旁路**：`try/except` 记日志，绝不影响 check/登录/发布结果（§9 有对应用例） |
| 昵称读取依赖页面结构，平台改版即失效 | `nickname` 允许为 NULL，写入失败只记日志；不参与任何放行判断 |
| 迁移改坏运行态文件 | 迁移前备份到 `output/backups/<date>/`，脚本可反向执行 |
| 想整体回滚 | 账本是新增文件，删除即回滚；ai-pipeline 侧保留 fail-open，账本不存在时行为同今天 |

## 11. 明确不做

- 不建改名历史表、不做别名解析层（已定）。
- 不把发布历史并进账本。
- 不做账本的 HTTP/多机同步。
- 不改变 SAU 的 check 语义与发布流程（只加旁路写入 + 结果字段）。
- 不自动登录/修复任何账号（`douyin_硅基思维TARS` 底下是「山下富士」这件事，账本只负责暴露）。