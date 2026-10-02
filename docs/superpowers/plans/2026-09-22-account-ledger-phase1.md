# 共享账号账本 · 第一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 SAU 成为账号数据的唯一写入方，ai-pipeline 发布时只读账本并解析出当前身份名，从而消灭 6 处账号名副本、让"改标识"不再需要手工同步。

**Architecture:** SAU 侧新增 SQLite 账本 `db/accounts.db`，以平台内部 UID 为主键、身份名（cookie 文件名）为可变外号，在「引导同步」「改标识」「状态校验」三个时机写入。ai-pipeline 侧新增只读模块 `account_ledger`，在唯一咽喉点 `tools/sau_client.py` 把配置里的账号引用（UID 或名字）解析成当前身份名，再用它拼 `sau <platform> upload-video --account <identity>`。

**Tech Stack:** Python 3.12 标准库 `sqlite3`（零新增依赖）、pytest、argparse。SAU 用 `patchright` 驱动浏览器（仅既有代码，本期新增单测不依赖它）。

**Spec:** `docs/superpowers/specs/2026-09-22-account-ledger-design.md`

## Global Constraints

- **账本路径**：`SAU_DIR/db/accounts.db`，SQLite WAL。写入方**只有 SAU**；ai-pipeline 一律 `file:...?mode=ro` 只读。
- **主键**：`(platform, platform_uid)`。`platform_uid` **只用平台内部 uid**；抖音号等对外号存入 `public_id`，**不参与任何匹配**。
- **不建改名历史表**，不做别名解析层。
- **写入必须旁路**：账本读写失败只记日志（`logging.getLogger(__name__).warning`），绝不影响 check / 登录 / 发布 / 改标识的返回值。
- **SAU 新增单测不得 import `patchright`、不得 import `uploader.*` 顶层模块**（conda python 无 patchright）。需要页面时用鸭子类型假 page 对象测纯函数。SAU 跑测试用：`python -m pytest tests/<file> -v`（cwd = SAU 根）。
  - **不要往 `G:\Job\social-auto-upload\.venv` 装任何东西**（该 venv 无 pip、无 pytest）。
- ai-pipeline 跑测试用：`uv run --extra test pytest tests/<file> -v`；新增测试**不得**带 `publish` / `external` 标记。
- **提交纪律**（两个仓库都脏）：`git add` 只加本任务明确列出的文件，**禁止 `git add -A` / `git add .`**。SAU 仓库有大量未提交改动，误加即事故。提交前先开分支（两仓库当前都在默认分支上）。commit message 结尾加：`Co-Authored-By: Claude Code <noreply@anthropic.com>`。不执行 push。

## 文件结构

**SAU（`G:\Job\social-auto-upload`）**

| 文件 | 责任 |
|---|---|
| `utils/account_ledger.py`（新） | 账本 schema + CRUD + cookie 离线取 UID + 解析。**只依赖标准库与 `conf`** |
| `utils/account_page.py`（新） | 页面文本 → 昵称/对外号 的纯解析 + 鸭子类型读页函数。**不 import patchright** |
| `utils/account_sync.py`（新） | `accounts sync` 的编排：扫 cookies 目录 → 写账本（可选 `--probe`） |
| `sau_cli.py`（改） | 注册 `accounts sync` / `accounts show`；check 分支带出 nickname/public_id |
| `server/account_dashboard.py`（改） | 改标识落库；`_worker_loop` 校验结果落库 |
| `tests/test_account_ledger.py`（新） | 账本单测 |
| `tests/test_account_page.py`（新） | 页面解析单测 |
| `tests/test_account_sync.py`（新） | 引导同步单测 |
| `tests/test_account_check_ledger.py`（新） | 校验落库 / 改标识落库单测 |

**ai-pipeline（`G:\Job\ai-popline`）**

| 文件 | 责任 |
|---|---|
| `src/content_pipeline/account_ledger.py`（新） | 只读账本 + `resolve_publish_account` |
| `src/content_pipeline/tools/sau_client.py`（改） | 唯一咽喉点：解析 ref → identity，拼 CLI |
| `src/content_pipeline/models.py`（改） | `*Params` 账号字段默认空；`PublishTarget.account` 允许空 |
| `src/content_pipeline/api/ui_schema.py`（改） | 表单默认值去字面量 |
| `src/content_pipeline/deferred_publishing.py`（改） | `:405-407` 默认值去字面量 |
| `src/content_pipeline/ai_briefing_runner.py`（改） | `:46-51` 硬编码 targets 改读策略 |
| `config/publish.defaults.yaml` + `src/content_pipeline/config/publish.defaults.yaml`（改） | 去字面量；消除重复文件 |
| `src/content_pipeline/cli/main.py`（改） | 注册 `accounts list` |
| `tests/unit/test_account_ledger.py`（新） | 解析规则单测 |
| `scripts/migrate_accounts_to_uid.py`（新） | 运行态文件迁移（先备份） |

---

### Task 1: SAU 账本模块

**Files:**
- Create: `G:\Job\social-auto-upload\utils\account_ledger.py`
- Test: `G:\Job\social-auto-upload\tests\test_account_ledger.py`

**Interfaces:**
- Consumes: `conf.BASE_DIR`（已存在）
- Produces:
  - `LEDGER_RELATIVE_PATH: Path`、`UNRESOLVED_PREFIX = "unresolved:"`
  - `ledger_path() -> Path`（环境变量 `SAU_ACCOUNT_LEDGER` 可覆盖，测试用）
  - `synthetic_uid(identity: str) -> str`
  - `connect(path: Path | None = None) -> sqlite3.Connection`
  - `LedgerRow`（frozen dataclass，字段见 schema；属性 `rename_safe: bool`）
  - `upsert_account(conn, *, platform, platform_uid, identity, uid_source, nickname=None, public_id=None, display_name=None, now=None) -> None`
  - `record_check(conn, *, platform, identity, status, status_message=None, checked_at=None, nickname=None, public_id=None, platform_uid=None, uid_source=None) -> None`
  - `rename_identity(conn, *, platform, old_identity, new_identity, now=None) -> bool`
  - `find_by_identity(conn, platform, identity) -> LedgerRow | None`
  - `list_accounts(conn, platform: str | None = None) -> list[LedgerRow]`
  - `resolve(conn, platform, ref) -> tuple[LedgerRow | None, str]`，判定取值 `"hit" | "none" | "ambiguous"`

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\social-auto-upload\tests\test_account_ledger.py
import sqlite3

import pytest

from utils import account_ledger as ledger


@pytest.fixture()
def conn(tmp_path):
    connection = ledger.connect(tmp_path / "accounts.db")
    yield connection
    connection.close()


def test_upsert_then_resolve_by_uid_and_identity(conn):
    ledger.upsert_account(
        conn, platform="douyin", platform_uid="7640519636165559355",
        identity="金融破壁人", nickname="金融破壁人", uid_source="cookie",
    )
    row, verdict = ledger.resolve(conn, "douyin", "7640519636165559355")
    assert verdict == "hit" and row.identity == "金融破壁人"
    row, verdict = ledger.resolve(conn, "douyin", "金融破壁人")
    assert verdict == "hit" and row.platform_uid == "7640519636165559355"
    assert row.rename_safe is True


def test_identity_moved_to_another_uid_drops_old_row(conn):
    ledger.upsert_account(conn, platform="douyin", platform_uid="111",
                          identity="硅基思维TARS", uid_source="cookie")
    ledger.upsert_account(conn, platform="douyin", platform_uid="222",
                          identity="硅基思维TARS", uid_source="cookie")
    rows = ledger.list_accounts(conn, "douyin")
    assert [r.platform_uid for r in rows] == ["222"]


def test_rename_identity_keeps_uid(conn):
    ledger.upsert_account(conn, platform="kuaishou", platform_uid="5362435333",
                          identity="破壁人", uid_source="cookie")
    assert ledger.rename_identity(conn, platform="kuaishou",
                                  old_identity="破壁人", new_identity="搞AI的罗辑同学") is True
    row, verdict = ledger.resolve(conn, "kuaishou", "5362435333")
    assert verdict == "hit"
    assert (row.identity, row.platform_uid) == ("搞AI的罗辑同学", "5362435333")


def test_rename_rewrites_synthetic_key(conn):
    synthetic = ledger.synthetic_uid("bilibili_旧名")
    ledger.upsert_account(conn, platform="bilibili", platform_uid=synthetic,
                          identity="旧名", uid_source="synthetic")
    ledger.rename_identity(conn, platform="bilibili", old_identity="旧名", new_identity="新名")
    rows = ledger.list_accounts(conn, "bilibili")
    assert rows[0].identity == "新名"
    assert rows[0].platform_uid == ledger.synthetic_uid("新名")
    assert rows[0].rename_safe is False


def test_record_check_warns_when_nickname_changes(conn, caplog):
    ledger.upsert_account(conn, platform="kuaishou", platform_uid="5362435333",
                          identity="搞AI的罗辑同学", nickname="金融破壁人", uid_source="cookie")
    with caplog.at_level("WARNING"):
        ledger.record_check(conn, platform="kuaishou", identity="搞AI的罗辑同学",
                            status="valid", status_message="登录状态有效",
                            nickname="改过的昵称")
    assert "昵称" in caplog.text
    row, _ = ledger.resolve(conn, "kuaishou", "5362435333")
    assert row.nickname == "改过的昵称"
    assert row.status == "valid"


def test_resolve_reports_ambiguous_nickname(conn):
    ledger.upsert_account(conn, platform="douyin", platform_uid="111",
                          identity="甲", nickname="同一个昵称", uid_source="cookie")
    ledger.upsert_account(conn, platform="douyin", platform_uid="222",
                          identity="乙", nickname="同一个昵称", uid_source="cookie")
    row, verdict = ledger.resolve(conn, "douyin", "同一个昵称")
    assert row is None and verdict == "ambiguous"


def test_resolve_missing_returns_none(conn):
    row, verdict = ledger.resolve(conn, "tencent", "不存在的号")
    assert row is None and verdict == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.account_ledger'`

- [ ] **Step 3: Write the implementation**

```python
# G:\Job\social-auto-upload\utils\account_ledger.py
"""SAU 账号账本：以平台内部 UID 为主键的单一账号数据源。

只有 SAU 写这份账本；ai-pipeline 只读（`file:...?mode=ro`）。
身份名（identity，即 cookie 文件名）是可变的外号，platform_uid 才是账号本身。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from conf import BASE_DIR

__all__ = [
    "LEDGER_RELATIVE_PATH", "UNRESOLVED_PREFIX", "LedgerRow",
    "ledger_path", "synthetic_uid", "connect", "upsert_account", "record_check",
    "rename_identity", "find_by_identity", "list_accounts", "resolve",
]

_logger = logging.getLogger(__name__)

LEDGER_RELATIVE_PATH = Path("db") / "accounts.db"
UNRESOLVED_PREFIX = "unresolved:"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  platform        TEXT NOT NULL,
  platform_uid    TEXT NOT NULL,
  identity        TEXT NOT NULL,
  nickname        TEXT,
  public_id       TEXT,
  display_name    TEXT,
  status          TEXT NOT NULL DEFAULT 'unknown',
  status_message  TEXT,
  checked_at      TEXT,
  uid_source      TEXT NOT NULL DEFAULT 'unknown',
  first_seen_at   TEXT NOT NULL,
  last_login_at   TEXT,
  PRIMARY KEY (platform, platform_uid)
);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_platform_identity
  ON accounts (platform, identity);
"""

_COLUMNS = ("platform", "platform_uid", "identity", "nickname", "public_id",
            "display_name", "status", "status_message", "checked_at",
            "uid_source", "first_seen_at", "last_login_at")


@dataclass(frozen=True)
class LedgerRow:
    platform: str
    platform_uid: str
    identity: str
    nickname: str | None
    public_id: str | None
    display_name: str | None
    status: str
    status_message: str | None
    checked_at: str | None
    uid_source: str
    first_seen_at: str
    last_login_at: str | None

    @property
    def rename_safe(self) -> bool:
        """合成键行没有稳定 UID，改标识时只能跟着改写键，标记为不安全。"""
        return not self.platform_uid.startswith(UNRESOLVED_PREFIX)


def ledger_path() -> Path:
    override = os.environ.get("SAU_ACCOUNT_LEDGER", "").strip()
    return Path(override) if override else BASE_DIR / LEDGER_RELATIVE_PATH


def synthetic_uid(identity: str) -> str:
    return f"{UNRESOLVED_PREFIX}{identity}"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path else ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _row(record: sqlite3.Row | None) -> LedgerRow | None:
    if record is None:
        return None
    return LedgerRow(**{column: record[column] for column in _COLUMNS})


def find_by_identity(conn: sqlite3.Connection, platform: str, identity: str) -> LedgerRow | None:
    cursor = conn.execute(
        "SELECT * FROM accounts WHERE platform=? AND identity=?", (platform, identity))
    return _row(cursor.fetchone())


def list_accounts(conn: sqlite3.Connection, platform: str | None = None) -> list[LedgerRow]:
    if platform:
        cursor = conn.execute(
            "SELECT * FROM accounts WHERE platform=? ORDER BY identity", (platform,))
    else:
        cursor = conn.execute("SELECT * FROM accounts ORDER BY platform, identity")
    return [_row(record) for record in cursor.fetchall()]


def upsert_account(
    conn: sqlite3.Connection,
    *,
    platform: str,
    platform_uid: str,
    identity: str,
    uid_source: str,
    nickname: str | None = None,
    public_id: str | None = None,
    display_name: str | None = None,
    now: str | None = None,
) -> None:
    """写入/更新一行。同一身份被换到另一个 uid 时，旧行删除并记 WARNING。"""
    timestamp = now or _now()
    existing = find_by_identity(conn, platform, identity)
    if existing is not None and existing.platform_uid != platform_uid:
        _logger.warning(
            "身份 %s:%s 下的账号从 uid %s 换成 %s，删除旧记录",
            platform, identity, existing.platform_uid, platform_uid,
        )
        conn.execute("DELETE FROM accounts WHERE platform=? AND platform_uid=?",
                     (platform, existing.platform_uid))
    conn.execute(
        """
        INSERT INTO accounts (platform, platform_uid, identity, nickname, public_id,
                              display_name, uid_source, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_uid) DO UPDATE SET
          identity=excluded.identity,
          nickname=COALESCE(excluded.nickname, accounts.nickname),
          public_id=COALESCE(excluded.public_id, accounts.public_id),
          display_name=COALESCE(excluded.display_name, accounts.display_name),
          uid_source=excluded.uid_source
        """,
        (platform, platform_uid, identity, nickname, public_id, display_name,
         uid_source, timestamp),
    )
    conn.commit()


def record_check(
    conn: sqlite3.Connection,
    *,
    platform: str,
    identity: str,
    status: str,
    status_message: str | None = None,
    checked_at: str | None = None,
    nickname: str | None = None,
    public_id: str | None = None,
    platform_uid: str | None = None,
    uid_source: str | None = None,
) -> None:
    """校验结果落库（写入点 1）。账本里没有的身份先建行。"""
    row = find_by_identity(conn, platform, identity)
    if row is None or (platform_uid and platform_uid != row.platform_uid):
        upsert_account(
            conn, platform=platform,
            platform_uid=platform_uid or (row.platform_uid if row else synthetic_uid(identity)),
            identity=identity,
            uid_source=uid_source or ("cookie" if platform_uid else "synthetic"),
            nickname=nickname, public_id=public_id,
        )
        row = find_by_identity(conn, platform, identity)
    if nickname and row is not None and row.nickname and nickname != row.nickname:
        _logger.warning("账号 %s:%s 的昵称从「%s」变为「%s」",
                        platform, identity, row.nickname, nickname)
    conn.execute(
        """
        UPDATE accounts SET
          status=?, status_message=?, checked_at=?,
          nickname=COALESCE(?, nickname),
          public_id=COALESCE(?, public_id),
          uid_source=COALESCE(?, uid_source)
        WHERE platform=? AND identity=?
        """,
        (status, status_message, checked_at or _now(), nickname, public_id,
         uid_source, platform, identity),
    )
    conn.commit()


def rename_identity(
    conn: sqlite3.Connection, *, platform: str, old_identity: str, new_identity: str,
    now: str | None = None,
) -> bool:
    """改标识后同步账本：uid 不变，只改身份名。返回是否有行被更新。"""
    row = find_by_identity(conn, platform, old_identity)
    if row is None:
        return False
    # 合成键的规范形式是 synthetic_uid(identity)（unresolved:<identity>，不含平台前缀）；
    # 这里用前缀判断而非等值比较 —— 与 LedgerRow.rename_safe 同一谓词（2026-09-22 执行期裁决）。
    if row.platform_uid.startswith(UNRESOLVED_PREFIX):
        conn.execute(
            "UPDATE accounts SET platform_uid=?, identity=? WHERE platform=? AND platform_uid=?",
            (synthetic_uid(new_identity), new_identity, platform, row.platform_uid),
        )
    else:
        conn.execute("UPDATE accounts SET identity=? WHERE platform=? AND identity=?",
                     (new_identity, platform, old_identity))
    conn.commit()
    return True


def resolve(
    conn: sqlite3.Connection, platform: str, ref: str
) -> tuple[LedgerRow | None, str]:
    """按 uid → identity → nickname 的顺序解析。返回 (行, hit|none|ambiguous)。"""
    reference = str(ref or "").strip()
    if not reference:
        return None, "none"
    cursor = conn.execute(
        "SELECT * FROM accounts WHERE platform=? AND platform_uid=?", (platform, reference))
    row = _row(cursor.fetchone())
    if row is not None:
        return row, "hit"
    row = find_by_identity(conn, platform, reference)
    if row is not None:
        return row, "hit"
    cursor = conn.execute(
        "SELECT * FROM accounts WHERE platform=? AND nickname=?", (platform, reference))
    matches = [_row(record) for record in cursor.fetchall()]
    if len(matches) == 1:
        return matches[0], "hit"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "none"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_ledger.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
cd "G:\Job\social-auto-upload"
git checkout -b feat/account-ledger        # 若已在特性分支则跳过
git add utils/account_ledger.py tests/test_account_ledger.py
git commit -m "feat(ledger): add UID-keyed account ledger store

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: cookie 离线提取平台 UID

**Files:**
- Modify: `G:\Job\social-auto-upload\utils\account_ledger.py`（追加函数）
- Test: `G:\Job\social-auto-upload\tests\test_account_ledger.py`（追加用例）

**Interfaces:**
- Produces: `extract_platform_uid(platform: str, cookie_path: Path) -> tuple[str | None, str]`，返回 `(uid, source)`，`source ∈ {"cookie", "unknown"}`。任何解析异常都返回 `(None, "unknown")`。

**平台字段映射（2026-09-22 实测）**

| 平台 | 来源 | 取值 |
|---|---|---|
| douyin | localStorage `SLARDARdouyin_creator_longvideo`（裸 JSON）优先，其次 `SLARDARdouyin_creator`（base64+URL 编码 的 JSON） | `userId`，**必须全数字**；非数字视为未知 |
| kuaishou | `cookies[].name == "userId"` | 数字 |
| tencent | `cookies[].name == "wxuin"` | 数字 |
| xiaohongshu | localStorage `USER_INFO_FOR_BIZ`（JSON） | `userId`（十六进制，长度 ≥ 16） |
| bilibili / 其他 | —— | 未知 |

- [ ] **Step 1: Write the failing test**

```python
# 追加到 G:\Job\social-auto-upload\tests\test_account_ledger.py
import base64
import json
from urllib.parse import quote

from utils import account_ledger as ledger


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_extract_douyin_uid_from_plain_longvideo(tmp_path):
    path = _write(tmp_path, "douyin_甲.json", {
        "cookies": [],
        "origins": [{"localStorage": [
            {"name": "SLARDARdouyin_creator_longvideo",
             "value": '{"userId":"7640519636165559355","deviceId":"x"}'},
        ]}],
    })
    assert ledger.extract_platform_uid("douyin", path) == ("7640519636165559355", "cookie")


def test_extract_douyin_uid_from_base64_urlencoded(tmp_path):
    inner = '{"userId":"7640519636165559355","deviceId":"x"}'
    encoded = base64.b64encode(quote(inner).encode()).decode()
    path = _write(tmp_path, "douyin_乙.json", {
        "cookies": [],
        "origins": [{"localStorage": [{"name": "SLARDARdouyin_creator", "value": encoded}]}],
    })
    assert ledger.extract_platform_uid("douyin", path) == ("7640519636165559355", "cookie")


def test_extract_douyin_rejects_non_numeric_uid(tmp_path):
    path = _write(tmp_path, "douyin_丙.json", {
        "cookies": [],
        "origins": [{"localStorage": [
            {"name": "SLARDARdouyin_creator",
             "value": base64.b64encode(quote('{"userId":"88443fb7-d2c5-452d-8627-ca925e354c5e"}').encode()).decode()},
        ]}],
    })
    assert ledger.extract_platform_uid("douyin", path) == (None, "unknown")


def test_extract_kuaishou_and_tencent_and_xiaohongshu_uids(tmp_path):
    ks = _write(tmp_path, "kuaishou_甲.json", {
        "cookies": [{"name": "userId", "value": "5362435333"}], "origins": []})
    assert ledger.extract_platform_uid("kuaishou", ks) == ("5362435333", "cookie")
    tx = _write(tmp_path, "tencent_甲.json", {
        "cookies": [{"name": "wxuin", "value": "1104697687"}], "origins": []})
    assert ledger.extract_platform_uid("tencent", tx) == ("1104697687", "cookie")
    xhs = _write(tmp_path, "xiaohongshu_甲.json", {
        "cookies": [],
        "origins": [{"localStorage": [
            {"name": "USER_INFO_FOR_BIZ",
             "value": '{"userId":"676ee26e0000000018014240","userName":"山下富士"}'},
        ]}],
    })
    assert ledger.extract_platform_uid("xiaohongshu", xhs) == ("676ee26e0000000018014240", "cookie")


def test_extract_returns_unknown_for_broken_file(tmp_path):
    broken = tmp_path / "bilibili_甲.json"
    broken.write_text("{ 不是 json", encoding="utf-8")
    assert ledger.extract_platform_uid("bilibili", broken) == (None, "unknown")
    assert ledger.extract_platform_uid("douyin", tmp_path / "missing.json") == (None, "unknown")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_ledger.py -k extract -v`
Expected: FAIL with `AttributeError: module 'utils.account_ledger' has no attribute 'extract_platform_uid'`

- [ ] **Step 3: Write the implementation**

```python
# 追加到 G:\Job\social-auto-upload\utils\account_ledger.py
import base64
import json
import re
from urllib.parse import unquote

_NUMERIC_RE = re.compile(r"^\d{5,}$")
_HEX_UID_RE = re.compile(r"^[0-9a-fA-F]{16,}$")

_COOKIE_UID_NAMES = {"kuaishou": "userId", "tencent": "wxuin"}


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _local_storage(payload: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for origin in payload.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        for item in origin.get("localStorage") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                values[item["name"]] = str(item.get("value") or "")
    return values


def _decode_loose_json(text: str) -> dict | None:
    """值可能是裸 JSON，也可能是 base64(URL 编码 JSON)。"""
    candidates = [text]
    try:
        candidates.append(base64.b64decode(text + "==", validate=False).decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001 - 旁路：任何解码失败都退化为未知
        pass
    for candidate in candidates:
        for variant in (candidate, unquote(candidate)):
            try:
                payload = json.loads(variant)
            except ValueError:
                continue
            if isinstance(payload, dict):
                return payload
    return None


def _douyin_uid(payload: dict) -> str | None:
    storage = _local_storage(payload)
    for key in ("SLARDARdouyin_creator_longvideo", "SLARDARdouyin_creator"):
        raw = storage.get(key)
        if not raw:
            continue
        decoded = _decode_loose_json(raw)
        if decoded is None:
            continue
        candidate = str(decoded.get("userId") or "").strip()
        if _NUMERIC_RE.match(candidate):
            return candidate
    return None


def _xiaohongshu_uid(payload: dict) -> str | None:
    raw = _local_storage(payload).get("USER_INFO_FOR_BIZ")
    if not raw:
        return None
    decoded = _decode_loose_json(raw)
    if decoded is None:
        return None
    candidate = str(decoded.get("userId") or "").strip()
    return candidate if _HEX_UID_RE.match(candidate) else None


def _cookie_uid(payload: dict, platform: str) -> str | None:
    wanted = _COOKIE_UID_NAMES.get(platform)
    if not wanted:
        return None
    for cookie in payload.get("cookies") or []:
        if isinstance(cookie, dict) and cookie.get("name") == wanted:
            candidate = str(cookie.get("value") or "").strip()
            if candidate:
                return candidate
    return None


def extract_platform_uid(platform: str, cookie_path: Path) -> tuple[str | None, str]:
    """从 cookie / storage_state 文件离线取平台内部 uid。不启动浏览器。"""
    payload = _read_json(cookie_path)
    if payload is None:
        return None, "unknown"
    try:
        if platform == "douyin":
            uid = _douyin_uid(payload)
        elif platform == "xiaohongshu":
            uid = _xiaohongshu_uid(payload)
        else:
            uid = _cookie_uid(payload, platform)
    except Exception as exc:  # noqa: BLE001 - 旁路：解析失败只记日志
        _logger.warning("从 %s 提取 %s uid 失败: %s", cookie_path, platform, exc)
        return None, "unknown"
    return (uid, "cookie") if uid else (None, "unknown")
```

并把 `extract_platform_uid` 加入 `__all__`。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_ledger.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: 用真实 cookies 目录做一次只读抽查（不写账本）**

```bash
cd "G:\Job\social-auto-upload"
python -c "
from pathlib import Path
from utils import account_ledger as ledger
for name in ['douyin_金融破壁人','douyin_硅基思维TARS','kuaishou_搞AI的罗辑同学','tencent_每日金融摘要','xiaohongshu_山下富士','bilibili_硅基思维TARS']:
    print(name, ledger.extract_platform_uid(name.split('_')[0], Path('cookies')/(name+'.json')))
"
```
Expected（与 2026-09-22 实测一致）：
```
douyin_金融破壁人 ('7640519636165559355', 'cookie')
douyin_硅基思维TARS (None, 'unknown')      <- 只有非数字 UUID，按设计判未知
kuaishou_搞AI的罗辑同学 ('5362435333', 'cookie')
tencent_每日金融摘要 ('1104697687', 'cookie')
xiaohongshu_山下富士 ('676ee26e0000000018014240', 'cookie')
bilibili_硅基思维TARS (None, 'unknown')
```

- [ ] **Step 6: Commit**

```bash
git add utils/account_ledger.py tests/test_account_ledger.py
git commit -m "feat(ledger): extract platform uid from cookie files offline

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: `sau accounts sync` 与 `accounts show`

**Files:**
- Create: `G:\Job\social-auto-upload\utils\account_sync.py`
- Modify: `G:\Job\social-auto-upload\sau_cli.py`（注册子命令 + dispatch 分支）
- Test: `G:\Job\social-auto-upload\tests\test_account_sync.py`

**Interfaces:**
- Consumes: `server.account_dashboard.discover_accounts(cookies_dir) -> list[AccountRecord]`（已存在，纯标准库）；`AccountRecord.platform/.account/.cookie_path`；Task 1/2 的账本函数。
- Produces:
  - `sync_accounts(cookies_dir: Path, conn: sqlite3.Connection | None = None) -> dict[str, int]`，返回 `{"scanned": n, "with_uid": n, "synthetic": n}`
  - `format_accounts_table(rows: list[LedgerRow]) -> str`
  - CLI：`sau accounts sync [--cookies-dir PATH]`、`sau accounts show [--platform P] [--json]`

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\social-auto-upload\tests\test_account_sync.py
import json

import pytest

from utils import account_ledger as ledger
from utils import account_sync


@pytest.fixture()
def cookies_dir(tmp_path):
    root = tmp_path / "cookies"
    root.mkdir()
    (root / "kuaishou_搞AI的罗辑同学.json").write_text(
        json.dumps({"cookies": [{"name": "userId", "value": "5362435333"}], "origins": []}),
        encoding="utf-8")
    (root / "bilibili_硅基思维TARS.json").write_text(
        json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    (root / "not-an-account.png").write_text("x", encoding="utf-8")
    return root


def test_sync_writes_uid_rows_and_synthetic_fallback(cookies_dir, tmp_path):
    conn = ledger.connect(tmp_path / "accounts.db")
    stats = account_sync.sync_accounts(cookies_dir, conn=conn)
    assert stats == {"scanned": 2, "with_uid": 1, "synthetic": 1}
    rows = {row.identity: row for row in ledger.list_accounts(conn)}
    assert rows["搞AI的罗辑同学"].platform_uid == "5362435333"
    assert rows["搞AI的罗辑同学"].uid_source == "cookie"
    assert rows["硅基思维TARS"].platform_uid == ledger.synthetic_uid("硅基思维TARS")
    assert rows["硅基思维TARS"].rename_safe is False
    conn.close()


def test_sync_is_idempotent_and_keeps_nickname(cookies_dir, tmp_path):
    conn = ledger.connect(tmp_path / "accounts.db")
    account_sync.sync_accounts(cookies_dir, conn=conn)
    ledger.record_check(conn, platform="kuaishou", identity="搞AI的罗辑同学",
                        status="valid", nickname="金融破壁人")
    account_sync.sync_accounts(cookies_dir, conn=conn)
    row, _ = ledger.resolve(conn, "kuaishou", "5362435333")
    assert row.nickname == "金融破壁人"
    assert row.status == "valid"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.account_sync'`

- [ ] **Step 3: Write the implementation**

```python
# G:\Job\social-auto-upload\utils\account_sync.py
"""accounts sync 的编排：扫 cookies 目录 → 写账本。

不启动浏览器；昵称与对外号由 `--probe`（Task 12）或状态校验补齐。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from server.account_dashboard import discover_accounts

from utils import account_ledger as ledger

__all__ = ["sync_accounts", "format_accounts_table"]

_COLUMN_LABELS = ("平台", "身份名", "昵称", "对外号", "UID", "UID来源", "状态", "校验时间", "改名安全")


def sync_accounts(cookies_dir: Path, conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """把 cookies 目录里的账号并进账本。已存在的行只补字段，不覆盖状态/昵称。"""
    own_conn = conn is None
    connection = conn or ledger.connect()
    stats = {"scanned": 0, "with_uid": 0, "synthetic": 0}
    try:
        for record in discover_accounts(Path(cookies_dir)):
            stats["scanned"] += 1
            uid, source = ledger.extract_platform_uid(record.platform, record.cookie_path)
            if uid:
                stats["with_uid"] += 1
                platform_uid = uid
            else:
                stats["synthetic"] += 1
                platform_uid = ledger.synthetic_uid(record.account)
                source = "synthetic"
            ledger.upsert_account(
                connection, platform=record.platform, platform_uid=platform_uid,
                identity=record.account, uid_source=source,
            )
    finally:
        if own_conn:
            connection.close()
    return stats


def format_accounts_table(rows: list[ledger.LedgerRow]) -> str:
    header = _COLUMN_LABELS
    body = [
        (row.platform, row.identity, row.nickname or "-", row.public_id or "-",
         row.platform_uid, row.uid_source, row.status, row.checked_at or "-",
         "是" if row.rename_safe else "否")
        for row in rows
    ]
    widths = [max(len(str(line[index])) for line in (header, *body))
              for index in range(len(header))]
    lines = ["  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(header))]
    lines.append("  ".join("-" * width for width in widths))
    for line in body:
        lines.append("  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(line)))
    return "\n".join(lines)
```

在 `sau_cli.py` 里注册（放在 `parser.add_subparsers(dest="platform", required=True)` 之后、与 `douyin_parser = ...` 同级）：

```python
    accounts_parser = platform_parsers.add_parser("accounts", help="Account ledger operations")
    accounts_actions = accounts_parser.add_subparsers(dest="action", required=True)

    accounts_sync_parser = accounts_actions.add_parser("sync", help="Sync account ledger from the cookies directory")
    accounts_sync_parser.add_argument("--cookies-dir", help="Override the cookies directory path")

    accounts_show_parser = accounts_actions.add_parser("show", help="Print the account ledger")
    # 注意：不能直接用 --platform —— 顶层 subparsers 已占用 dest="platform"，
    # 同 dest 会被 show 子命令的默认值 None 覆盖，导致 dispatch 走错分支（2026-09-22 执行期裁决）。
    accounts_show_parser.add_argument("--platform", dest="filter_platform",
                                      help="Only show one platform")
    accounts_show_parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
```

在 `dispatch()` 最前面加分支（`args.platform == "accounts"`）：

```python
async def dispatch(args: argparse.Namespace) -> int:
    if args.platform == "accounts":
        from utils import account_sync as _account_sync
        from utils import account_ledger as _ledger

        if args.action == "sync":
            cookies_dir = Path(args.cookies_dir) if args.cookies_dir else BASE_DIR / "cookies"
            stats = _account_sync.sync_accounts(cookies_dir)
            print("ACCOUNTS_SYNC:" + json.dumps(stats, ensure_ascii=False))
            return 0

        connection = _ledger.connect()
        try:
            rows = _ledger.list_accounts(connection, getattr(args, "filter_platform", None))
        finally:
            connection.close()
        if args.json:
            print(json.dumps([row.__dict__ for row in rows], ensure_ascii=False, indent=2))
        else:
            print(_account_sync.format_accounts_table(rows))
        return 0

    if args.platform == "douyin":
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_sync.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 冒烟：对真实 cookies 目录跑一次（会创建 `db/accounts.db`，这是本任务预期产物）**

```bash
cd "G:\Job\social-auto-upload"
./.venv/Scripts/python.exe -m sau_cli accounts sync
./.venv/Scripts/python.exe -m sau_cli accounts show
```
Expected: 打印 `ACCOUNTS_SYNC:{"scanned": 7, ...}`；表格里 5 行有 cookie uid、2 行为合成键（`douyin_硅基思维TARS`、`bilibili_硅基思维TARS`）。

- [ ] **Step 6: Commit**

```bash
git add utils/account_sync.py sau_cli.py tests/test_account_sync.py
git commit -m "feat(ledger): add accounts sync and show commands

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 改标识落库（写入点 2）

**Files:**
- Modify: `G:\Job\social-auto-upload\server\account_dashboard.py:158-193`（`rename_account_identity`）
- Test: `G:\Job\social-auto-upload\tests\test_account_check_ledger.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `ledger.rename_identity` / `ledger.connect` / `ledger.upsert_account`
- Produces: `_sync_ledger_rename(platform, old_identity, new_identity) -> None`（模块内私有助手，旁路）

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\social-auto-upload\tests\test_account_check_ledger.py
import json
from pathlib import Path

import pytest

from server.account_dashboard import rename_account_identity
from utils import account_ledger as ledger


@pytest.fixture()
def ledger_env(tmp_path, monkeypatch):
    target = tmp_path / "accounts.db"
    monkeypatch.setenv("SAU_ACCOUNT_LEDGER", str(target))
    monkeypatch.chdir(tmp_path)
    return target


def _make_account(cookies_dir: Path, platform: str, account: str) -> None:
    cookies_dir.mkdir(parents=True, exist_ok=True)
    (cookies_dir / f"{platform}_{account}.json").write_text(
        json.dumps({"cookies": [{"name": "userId", "value": "5362435333"}], "origins": []}),
        encoding="utf-8")


def test_rename_updates_ledger_identity_but_keeps_uid(tmp_path, ledger_env):
    cookies_dir = tmp_path / "cookies"
    _make_account(cookies_dir, "kuaishou", "破壁人")
    conn = ledger.connect()
    ledger.upsert_account(conn, platform="kuaishou", platform_uid="5362435333",
                          identity="破壁人", uid_source="cookie")
    conn.close()

    rename_account_identity(cookies_dir, "kuaishou", "破壁人", "搞AI的罗辑同学")

    conn = ledger.connect()
    row, verdict = ledger.resolve(conn, "kuaishou", "5362435333")
    conn.close()
    assert verdict == "hit"
    assert row.identity == "搞AI的罗辑同学"


def test_rename_survives_ledger_failure(tmp_path, ledger_env, monkeypatch):
    """旁路：账本写失败不能影响改名本身。"""
    cookies_dir = tmp_path / "cookies"
    _make_account(cookies_dir, "kuaishou", "甲")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("ledger is gone")

    monkeypatch.setattr(ledger, "connect", boom)
    record = rename_account_identity(cookies_dir, "kuaishou", "甲", "乙")
    assert record.account == "乙"
    assert (cookies_dir / "kuaishou_乙.json").is_file()
```

在该文件顶部补 `import sqlite3`。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_check_ledger.py -v`
Expected: FAIL —— 第一条断言 `row.identity == "破壁人"`（账本没被更新）

- [ ] **Step 3: Write the implementation**

在 `rename_account_identity` 的 `return build_account_record(...)` 之前插入：

```python
    _sync_ledger_rename(platform, account, new_account)
    return build_account_record(cookies_dir, platform, new_account)
```

并在该函数下方加助手（旁路实现）：

```python
def _sync_ledger_rename(platform: str, old_identity: str, new_identity: str) -> None:
    """改标识后同步账本。账本不可用只记日志，绝不影响改名结果。

    import 必须放在函数内：`server/bridge_server.py` 把项目根插入 sys.path 的
    时机在它导入本模块**之后**（`bridge_server.py:80-86`），所以顶层
    `from utils import ...` 会让 `python server/bridge_server.py` 启动即
    ModuleNotFoundError。函数内导入时根目录早已就位（2026-09-22 执行期裁决）。
    """
    try:
        from utils import account_ledger as _account_ledger
        connection = _account_ledger.connect()
        try:
            _account_ledger.rename_identity(
                connection, platform=platform,
                old_identity=old_identity, new_identity=new_identity,
            )
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001 - 旁路
        logging.getLogger(__name__).warning("同步账本失败（改名已成功）: %s", exc)
```

若无 `logging` 导入，在 import 区加 `import logging` 与模块级 `_logger = logging.getLogger(__name__)`，助手用 `_logger.warning(...)`。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_check_ledger.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 回归既有测试**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_dashboard.py tests/test_account_names.py -q`
Expected: PASS（原有 12 passed 不变）

- [ ] **Step 6: Commit**

```bash
git add server/account_dashboard.py tests/test_account_check_ledger.py
git commit -m "feat(ledger): follow identity renames into the account ledger

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: ai-pipeline 只读账本 + 解析

**Files:**
- Create: `G:\Job\ai-popline\src\content_pipeline\account_ledger.py`
- Test: `G:\Job\ai-popline\tests\unit\test_account_ledger.py`

**Interfaces:**
- Consumes: `Settings.sau_dir`（已存在）
- Produces:
  - `LedgerAccount`（frozen dataclass：`platform, platform_uid, identity, nickname, public_id, status, checked_at, uid_source`）
  - `load_accounts(settings) -> dict[str, list[LedgerAccount]] | None`（`None` = 账本不可用）
  - `resolve_publish_account(settings, platform, ref) -> LedgerAccount | None`（`None` = 账本不可用 → 调用方 fail-open）；查不到/歧义抛 `ConfigError`
  - `describe_platform_accounts(accounts: dict, platform: str) -> str`

**解析规则（与 SAU 侧 `resolve` 一致）**：`ref` 为空 → 该平台只有一个账号时用它，多个则报错；非空 → 依次按 `platform_uid`、`identity`、`nickname` 匹配，昵称多命中报歧义。

**状态策略**：额外产出 `ensure_account_publishable(account, *, now=None, max_age_days=7) -> list[str]`——`expired` 抛 `ConfigError`（附重新登录命令）；`identity != nickname`、缺 `checked_at`、`checked_at` 超过 7 天 → 返回告警文案（**不阻断**）。`valid` 不作为放行依据，SAU 自己的校验照旧执行。

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\ai-popline\tests\unit\test_account_ledger.py
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from content_pipeline.account_ledger import (
    ensure_account_publishable,
    load_accounts,
    resolve_publish_account,
)
from content_pipeline.core.errors import ConfigError
from content_pipeline.settings import Settings

SCHEMA = """
CREATE TABLE accounts (
  platform TEXT NOT NULL, platform_uid TEXT NOT NULL, identity TEXT NOT NULL,
  nickname TEXT, public_id TEXT, display_name TEXT,
  status TEXT NOT NULL DEFAULT 'unknown', status_message TEXT, checked_at TEXT,
  uid_source TEXT NOT NULL DEFAULT 'unknown', first_seen_at TEXT NOT NULL,
  last_login_at TEXT, PRIMARY KEY (platform, platform_uid)
);
"""


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    sau_dir = tmp_path / "sau"
    (sau_dir / "db").mkdir(parents=True)
    conn = sqlite3.connect(sau_dir / "db" / "accounts.db")
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO accounts (platform, platform_uid, identity, nickname, status,"
        " checked_at, uid_source, first_seen_at) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("douyin", "7640519636165559355", "金融破壁人", "金融破壁人", "valid",
             "2026-09-22T20:30:46+08:00", "cookie", "2026-09-22T00:00:00+08:00"),
            ("douyin", "unresolved:硅基思维TARS", "硅基思维TARS", "山下富士", "valid",
             "2026-09-22T22:02:00+08:00", "synthetic", "2026-09-22T00:00:00+08:00"),
            ("kuaishou", "5362435333", "搞AI的罗辑同学", "金融破壁人", "valid",
             "2026-09-22T22:03:07+08:00", "cookie", "2026-09-22T00:00:00+08:00"),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("SAU_DIR", str(sau_dir))
    return Settings()


def _write_row(sau_dir: Path, **overrides) -> None:
    """按本文件的库结构写一行，用于构造 expired 等场景。"""
    row = {
        "platform": "kuaishou", "platform_uid": "5362435333",
        "identity": "搞AI的罗辑同学", "nickname": "金融破壁人", "status": "valid",
        "checked_at": "2026-09-22T22:03:07+08:00", "uid_source": "cookie",
        "first_seen_at": "2026-09-22T00:00:00+08:00",
    }
    row.update(overrides)
    connection = sqlite3.connect(sau_dir / "db" / "accounts.db")
    connection.execute(
        "INSERT OR REPLACE INTO accounts (platform, platform_uid, identity, nickname,"
        " status, checked_at, uid_source, first_seen_at) VALUES (?,?,?,?,?,?,?,?)",
        (row["platform"], row["platform_uid"], row["identity"], row["nickname"],
         row["status"], row["checked_at"], row["uid_source"], row["first_seen_at"]),
    )
    connection.commit()
    connection.close()


def _settings_with_status(tmp_path, monkeypatch, **overrides) -> Settings:
    sau_dir = tmp_path / "sau_status"
    (sau_dir / "db").mkdir(parents=True)
    connection = sqlite3.connect(sau_dir / "db" / "accounts.db")
    connection.executescript(SCHEMA)
    connection.commit()
    connection.close()
    _write_row(sau_dir, **overrides)
    monkeypatch.setenv("SAU_DIR", str(sau_dir))
    return Settings()


def test_load_accounts_groups_by_platform(settings):
    accounts = load_accounts(settings)
    assert accounts is not None
    assert [row.identity for row in accounts["kuaishou"]] == ["搞AI的罗辑同学"]


def test_load_accounts_returns_none_when_ledger_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SAU_DIR", str(tmp_path / "nope"))
    assert load_accounts(Settings()) is None


def test_resolve_by_uid_identity_and_nickname(settings):
    by_uid = resolve_publish_account(settings, "douyin", "7640519636165559355")
    assert by_uid.identity == "金融破壁人"
    by_identity = resolve_publish_account(settings, "douyin", "金融破壁人")
    assert by_identity.platform_uid == "7640519636165559355"
    by_nickname = resolve_publish_account(settings, "douyin", "山下富士")
    assert by_nickname.identity == "硅基思维TARS"


def test_resolve_empty_ref_uses_the_only_account(settings):
    assert resolve_publish_account(settings, "kuaishou", "").identity == "搞AI的罗辑同学"


def test_resolve_empty_ref_is_ambiguous_with_two_accounts(settings):
    with pytest.raises(ConfigError) as excinfo:
        resolve_publish_account(settings, "douyin", "")
    assert "硅基思维TARS" in str(excinfo.value)


def test_resolve_unknown_ref_lists_available_accounts(settings):
    with pytest.raises(ConfigError) as excinfo:
        resolve_publish_account(settings, "kuaishou", "破壁人")
    message = str(excinfo.value)
    assert "搞AI的罗辑同学" in message and "sau accounts sync" in message


def test_resolve_returns_none_when_ledger_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("SAU_DIR", str(tmp_path / "nope"))
    assert resolve_publish_account(Settings(), "douyin", "金融破壁人") is None


def test_identity_nickname_drift_warns_but_does_not_block(settings):
    account = resolve_publish_account(settings, "kuaishou", "5362435333")
    # 2026-09-22T22:03:07+08:00 == 14:03 UTC，取当天晚些时候，避开"过期"告警
    warnings = ensure_account_publishable(
        account, now=datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc))
    assert any("昵称是「金融破壁人」" in warning for warning in warnings)


def test_expired_account_fails_early(tmp_path, monkeypatch):
    settings = _settings_with_status(tmp_path, monkeypatch, status="expired")
    account = resolve_publish_account(settings, "kuaishou", "5362435333")
    with pytest.raises(ConfigError) as excinfo:
        ensure_account_publishable(account)
    assert "sau kuaishou login" in str(excinfo.value)


def test_stale_check_warns(settings):
    account = resolve_publish_account(settings, "douyin", "金融破壁人")
    far_future = datetime(2027, 1, 1, tzinfo=timezone.utc)
    warnings = ensure_account_publishable(account, now=far_future)
    assert any("状态可能过期" in warning for warning in warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_account_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'content_pipeline.account_ledger'`

- [ ] **Step 3: Write the implementation**

```python
# G:\Job\ai-popline\src\content_pipeline\account_ledger.py
"""只读 SAU 账号账本（SQLite），把配置里的账号引用解析成当前身份名。

SAU 是唯一写入方。账本不可用时返回 None，调用方按 fail-open 处理
（沿用配置里的字面量），因此账本本身出问题不会阻断发布。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_pipeline.core.errors import ConfigError
from content_pipeline.settings import Settings

__all__ = [
    "LEDGER_RELATIVE_PATH", "LedgerAccount", "ensure_account_publishable",
    "load_accounts", "resolve_publish_account", "describe_platform_accounts",
]

LEDGER_RELATIVE_PATH = Path("db") / "accounts.db"


@dataclass(frozen=True)
class LedgerAccount:
    platform: str
    platform_uid: str
    identity: str
    nickname: str | None
    public_id: str | None
    status: str
    checked_at: str | None
    uid_source: str


def _ledger_file(settings: Settings) -> Path:
    return Path(settings.sau_dir) / LEDGER_RELATIVE_PATH


def load_accounts(settings: Settings) -> dict[str, list[LedgerAccount]] | None:
    """读取账本。``None`` 表示账本不可用（不存在 / 打不开 / schema 不符）。"""
    path = _ledger_file(settings)
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        connection.row_factory = sqlite3.Row
        records = connection.execute(
            "SELECT platform, platform_uid, identity, nickname, public_id, status,"
            " checked_at, uid_source FROM accounts"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    grouped: dict[str, list[LedgerAccount]] = {}
    for record in records:
        account = LedgerAccount(
            platform=record["platform"], platform_uid=record["platform_uid"],
            identity=record["identity"], nickname=record["nickname"],
            public_id=record["public_id"], status=record["status"],
            checked_at=record["checked_at"], uid_source=record["uid_source"],
        )
        grouped.setdefault(account.platform, []).append(account)
    return grouped


def describe_platform_accounts(accounts: dict[str, list[LedgerAccount]], platform: str) -> str:
    rows = accounts.get(platform) or []
    if not rows:
        return f"SAU 账号账本里没有 {platform} 平台的任何账号"
    parts = [
        f"{row.nickname or '（无昵称）'}(uid {row.platform_uid}, 身份名 {row.identity}, {row.status})"
        for row in rows
    ]
    return "、".join(parts)


def resolve_publish_account(
    settings: Settings, platform: str, ref: str
) -> LedgerAccount | None:
    """把账号引用解析成账本里的账号。

    返回 ``None`` 表示账本不可用（调用方 fail-open）；账本可用但引用
    查不到或命中多个时抛 ``ConfigError``，绝不静默沿用旧名字。
    """
    accounts = load_accounts(settings)
    if accounts is None:
        return None
    rows = accounts.get(platform) or []
    reference = str(ref or "").strip()
    if not reference:
        if len(rows) == 1:
            return rows[0]
        if not rows:
            raise ConfigError(
                f"{platform} 平台在 SAU 账号账本里没有任何账号。"
                "若刚在 SAU 新增/改过账号，请先运行 `sau accounts sync` 刷新账本。"
            )
        raise ConfigError(
            f"{platform} 平台没有指定账号，而账本里有多个可选账号："
            f"{describe_platform_accounts(accounts, platform)}。"
            "请在发布策略或任务参数里指定账号（UID 或昵称均可）。"
        )
    for row in rows:
        if row.platform_uid == reference:
            return row
    for row in rows:
        if row.identity == reference:
            return row
    by_nickname = [row for row in rows if row.nickname and row.nickname == reference]
    if len(by_nickname) == 1:
        return by_nickname[0]
    if len(by_nickname) > 1:
        raise ConfigError(
            f"{platform} 平台有多个账号昵称都是「{reference}」，无法区分："
            f"{describe_platform_accounts(accounts, platform)}。请改用 UID 指定。"
        )
    raise ConfigError(
        f"SAU 账号账本里没有 {platform} 账号「{reference}」：账号可能已在 SAU 改过标识或换号。"
        f"当前可用账号：{describe_platform_accounts(accounts, platform)}。"
        "若刚在 SAU 新增/改过账号，请先运行 `sau accounts sync` 刷新账本。"
    )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def ensure_account_publishable(
    account: LedgerAccount, *, now: datetime | None = None, max_age_days: int = 7
) -> list[str]:
    """发布前的状态策略：``expired`` 早失败；其余只返回告警，不阻断。

    ``valid`` 不作为放行依据——SAU 自己的登录校验照旧执行，账本只用来
    提前失败与提示。
    """
    if account.status == "expired":
        raise ConfigError(
            f"SAU 账号「{account.identity}」（昵称 {account.nickname or '未知'}）登录状态已失效。"
            f"请先重新登录：sau {account.platform} login --account \"{account.identity}\""
        )
    warnings: list[str] = []
    if account.nickname and account.nickname != account.identity:
        warnings.append(
            f"账号 {account.platform}:{account.identity} 的平台昵称是「{account.nickname}」，"
            "与身份名不一致（常见于改过标识）——请确认发布目标账号是否正确。"
        )
    checked = _parse_iso(account.checked_at)
    if checked is None:
        warnings.append(
            f"账号 {account.platform}:{account.identity} 没有校验记录，登录状态可能过期。"
        )
    elif (now or datetime.now(timezone.utc)) - checked > timedelta(days=max_age_days):
        warnings.append(
            f"账号 {account.platform}:{account.identity} 上次校验是 {account.checked_at}，"
            "登录状态可能过期。"
        )
    return warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_account_ledger.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
cd "G:\Job\ai-popline"
git checkout -b feat/account-ledger        # 若已在特性分支则跳过
git add src/content_pipeline/account_ledger.py tests/unit/test_account_ledger.py
git commit -m "feat(ledger): read SAU account ledger and resolve publish accounts

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 咽喉点接入（解析 → 用 identity 拼命令）

**Files:**
- Modify: `G:\Job\ai-popline\src\content_pipeline\tools\sau_client.py:20-39`（`_ensure_account_is_known`）、`:129`、`:161`、`:421`
- Test: `G:\Job\ai-popline\tests\test_sau_client.py`（追加用例）

**Interfaces:**
- Consumes: Task 5 的 `resolve_publish_account` / `LedgerAccount`
- Produces: `_resolve_account_identity(platform: str, ref: str, settings: Settings) -> str` —— 返回要传给 `sau --account` 的身份名；账本不可用时返回 `ref` 原值（fail-open）。

**行为变更（要写进 docstring）**：解析在 `dry_run` 下**也执行**，这样 `--dry-run` 打印出的命令行能直接核对解析结果；`_enforce_publish_policy` 的 dry_run 行为不变。因此 dry_run 也可能因"名字已不存在"报错——这是探测陈旧配置的手段，属预期。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 G:\Job\ai-popline\tests\test_sau_client.py
import sqlite3

import pytest

from content_pipeline.core.errors import ConfigError
from content_pipeline.settings import Settings
from content_pipeline.tools.sau_client import _resolve_account_identity

SCHEMA = """
CREATE TABLE accounts (
  platform TEXT NOT NULL, platform_uid TEXT NOT NULL, identity TEXT NOT NULL,
  nickname TEXT, public_id TEXT, display_name TEXT,
  status TEXT NOT NULL DEFAULT 'unknown', status_message TEXT, checked_at TEXT,
  uid_source TEXT NOT NULL DEFAULT 'unknown', first_seen_at TEXT NOT NULL,
  last_login_at TEXT, PRIMARY KEY (platform, platform_uid)
);
"""


@pytest.fixture()
def ledger_settings(tmp_path, monkeypatch):
    sau_dir = tmp_path / "sau"
    (sau_dir / "db").mkdir(parents=True)
    conn = sqlite3.connect(sau_dir / "db" / "accounts.db")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO accounts (platform, platform_uid, identity, nickname, status,"
        " uid_source, first_seen_at) VALUES ('kuaishou','5362435333','搞AI的罗辑同学',"
        "'金融破壁人','valid','cookie','2026-09-22T00:00:00+08:00')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("SAU_DIR", str(sau_dir))
    return Settings()


def test_stale_name_resolves_to_current_identity(ledger_settings):
    """旧名字（改标识前的）→ 解析出当前身份名。"""
    assert _resolve_account_identity("kuaishou", "破壁人", ledger_settings) == "破壁人" or True


def test_uid_resolves_to_current_identity(ledger_settings):
    assert _resolve_account_identity("kuaishou", "5362435333", ledger_settings) == "搞AI的罗辑同学"


def test_nickname_resolves_to_current_identity(ledger_settings):
    assert _resolve_account_identity("kuaishou", "金融破壁人", ledger_settings) == "搞AI的罗辑同学"


def test_unresolvable_name_raises(ledger_settings):
    with pytest.raises(ConfigError):
        _resolve_account_identity("kuaishou", "不存在的号", ledger_settings)


def test_missing_ledger_falls_back_to_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("SAU_DIR", str(tmp_path / "nope"))
    assert _resolve_account_identity("kuaishou", "搞AI的罗辑同学", Settings()) == "搞AI的罗辑同学"
```

**注意**：`test_stale_name_resolves_to_current_identity` 里 `"破壁人"` 在账本中**不存在**（改标识后账本里只有新名），按设计它必须**报错**，不是解析成功。把它改成断言报错：

```python
def test_stale_name_is_rejected_loudly(ledger_settings):
    """旧名字不再兜底解析——响亮失败，避免静默发到错账号。"""
    with pytest.raises(ConfigError):
        _resolve_account_identity("kuaishou", "破壁人", ledger_settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/test_sau_client.py -k _resolve_account_identity -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_account_identity'`

- [ ] **Step 3: Write the implementation**

在 `tools/sau_client.py` 中：删掉 `_ensure_account_is_known`（含 `from content_pipeline.account_status import fetch_account_identities` 导入，若别处未用到），替换为：

```python
def _resolve_account_identity(platform: str, ref: str, settings: Settings) -> str:
    """把账号引用解析成 SAU 的当前身份名（cookie 文件名）。

    SAU 用身份名当账号标识，改标识后名字会变；账本以平台 UID 锚定账号，
    所以这里把旧引用换成当前身份名。账本不可用时返回原值（fail-open）；
    账本可用但引用查不到时抛 ConfigError —— 绝不静默沿用旧名字。
    解析成功后按状态策略告警，``expired`` 直接早失败。
    """
    resolved = resolve_publish_account(settings, platform, ref)
    if resolved is None:
        return str(ref or "")
    for warning in ensure_account_publishable(resolved):
        _logger.warning("%s", warning)
    return resolved.identity
```

并加导入：`from content_pipeline.account_ledger import ensure_account_publishable, resolve_publish_account`；`_logger = logging.getLogger(__name__)` 若模块内还没有就加上 `import logging`。

追加两条用例到 Task 6 的测试文件：

```python
def test_expired_account_blocks_before_upload(tmp_path, monkeypatch):
    """账本里 expired 的账号必须早失败。"""
    sau_dir = tmp_path / "sau_expired"
    (sau_dir / "db").mkdir(parents=True)
    conn = sqlite3.connect(sau_dir / "db" / "accounts.db")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO accounts (platform, platform_uid, identity, nickname, status,"
        " uid_source, first_seen_at) VALUES ('kuaishou','5362435333','搞AI的罗辑同学',"
        "'金融破壁人','expired','cookie','2026-09-22T00:00:00+08:00')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("SAU_DIR", str(sau_dir))
    with pytest.raises(ConfigError) as excinfo:
        _resolve_account_identity("kuaishou", "5362435333", Settings())
    assert "sau kuaishou login" in str(excinfo.value)


def test_drift_warning_is_logged_not_raised(ledger_settings, caplog):
    with caplog.at_level("WARNING"):
        identity = _resolve_account_identity("kuaishou", "5362435333", ledger_settings)
    assert identity == "搞AI的罗辑同学"
    assert "金融破壁人" in caplog.text
```

三处调用点改为先解析、再用解析结果拼命令。`upload_video`（`call_sau_target` 内）改为：

```python
    account_identity = _resolve_account_identity(target.platform, target.account, settings)
    if target.platform == "douyin":
        command = [
            str(settings.sau_exe), "douyin", "upload-video",
            "--account", account_identity,
            ...
```

（其余 `target.account` 出现在命令参数里的地方同样替换；小红书与 bilibili 调用点同理。）

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/test_sau_client.py -v`
Expected: PASS（新增用例 + 原有用例；原有用例若断言了 `_ensure_account_is_known` 的报错文案，按新文案更新）

- [ ] **Step 5: Commit**

```bash
git add src/content_pipeline/tools/sau_client.py tests/test_sau_client.py
git commit -m "feat(publish): resolve account identity from the ledger before upload

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: 清除 6 处账号名字面量

**Files:**
- Modify: `src/content_pipeline/models.py:57-61`、`:352-354`、`:386-388`、`:414-416`、`:155-163`（`PublishTarget.account`）
- Modify: `src/content_pipeline/profiles.py:36`（`UploadProfile.account` 放宽为允许空，默认空）——**2026-09-23 执行期扩展**：T6 让解析在发布链路生效后，`profiles/*.yaml` 里 `account: default` 这类**陈旧占位名**会被正确拒绝（对应的是 2026-07 那个 `bilibili_default.json`，现已不存在），`tests/test_orchestrator.py::test_dry_run_only_previews_upload_when_publish_is_explicit` 因此失败。
- Modify: `profiles/anime.yaml`、`profiles/finance.yaml`（`upload.account: default` → 留空 = 该平台唯一账号；两份都是 git 跟踪文件）
- Modify: `src/content_pipeline/api/ui_schema.py:116-118`、`:188-190`、`:260-261`
- Modify: `src/content_pipeline/deferred_publishing.py:405-407`
- Modify: `src/content_pipeline/ai_briefing_runner.py:46-51`
- Modify: `config/publish.defaults.yaml`、`src/content_pipeline/config/publish.defaults.yaml`
- Test: `tests/unit/test_account_literals.py`（新建；另加一条守卫：任何 profile YAML 的 `upload.account` 不得为非空陈旧名）
- Test（预期需要更新）：`tests/unit/test_publish_policy.py`、`tests/unit/test_deferred_publish.py`、`tests/unit/test_settings_center.py`、`tests/unit/test_web_console.py`、**`tests/test_orchestrator.py`**（最后一处是上面的 profile 陈旧引用修好后就该恢复通过的那个用例；它是 T6 行为变更的正确连带影响，不是回归）

**行为定义**：账号引用允许为空。空引用在发布时按 Task 5 的规则解析（该平台唯一账号则用它，多账号则报错）。

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\ai-popline\tests\unit\test_account_literals.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LITERALS = ("金融破壁人", "搞AI的罗辑同学", "每日金融摘要")
SOURCES = [
    "src/content_pipeline/models.py",
    "src/content_pipeline/api/ui_schema.py",
    "src/content_pipeline/deferred_publishing.py",
    "src/content_pipeline/ai_briefing_runner.py",
    "config/publish.defaults.yaml",
    "src/content_pipeline/config/publish.defaults.yaml",
]


def test_no_account_name_literals_in_production_sources():
    offenders = []
    for relative in SOURCES:
        text = (REPO / relative).read_text(encoding="utf-8")
        for literal in LITERALS:
            if literal in text:
                offenders.append(f"{relative}: {literal}")
    assert offenders == [], "账号名不该再出现在这些文件里：" + "; ".join(offenders)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_account_literals.py -v`
Expected: FAIL，列出全部 6 个文件

- [ ] **Step 3: 逐处改造**

1. `models.py:57-61` 之后新增可选规范化器：
```python
def _normalize_optional_reference(value: str | None) -> str:
    """账号引用可以为空：空 = 发布时按平台解析（该平台唯一账号）。"""
    return (value or "").strip()
```
2. `models.py` 的三个 `*Params` 类：`douyin_account: str = ""`、`kuaishou_account: str = ""`、`tencent_account: str = ""`，并把 `_normalize_required_text(self.douyin_account, ...)` 换成 `_normalize_optional_reference(self.douyin_account)`（三个类共 9 处）。
3. `models.py:158` 的 `PublishTarget.account` 校验改为 `_normalize_optional_reference`，docstring 注明"空 = 该平台唯一账号；多账号时会报错"。
4. `ui_schema.py`：三处 `_field(...)` 去掉 `default="..."`（保留字段名与标签）。
5. `deferred_publishing.py:405-407`：
```python
            "accounts": {
                "douyin": str(params.get("douyin_account") or ""),
                "kuaishou": str(params.get("kuaishou_account") or ""),
                "tencent": str(params.get("tencent_account") or ""),
            },
```
6. `ai_briefing_runner.py:46-51`：删掉硬编码 targets。**已确认机制**：`ai_briefing_pipeline.py:597` 本来就会调 `resolve_publish_plan("ai_briefing", snapshot.task, settings=settings)`，而该函数取 `task.publish_targets or entry["targets"]`——也就是说现在生效的正是 runner 硬编码的那份，策略文件里的 targets 被完全遮蔽。因此只要让 runner **不再传 targets** 即可自动改用策略：

```python
    publish = args.publish and not args.skip_publish
    task = TaskInput(
        description="生成每日 AI 资讯视频",
        content_type="ai_briefing",
        publish=publish,
        publish_targets=[],
        params={...},   # 其余参数保持不变
    )
```

不需要新函数，也不要在 runner 里再解析一次策略（避免两处解析）。
7. 两份 `publish.defaults.yaml`：`targets` 里的 `account:` 值清空（例：`- { platform: douyin }`），并在文件头注释写明"账号留空 = 按平台解析；也可填 UID 或昵称"。**两份文件的关系已确认**：`Settings.publish_defaults_file` 默认 `config/publish.defaults.yaml`；`publish_policy.py:102-106` 只在默认路径不可读时才回落到打包副本 `src/content_pipeline/config/publish.defaults.yaml`。因此定下规则：**打包副本不携带任何账号 targets**（各内容类型 `enabled: false, targets: []`），并在其文件头写明"这是打包兜底副本，正常运行读 `config/publish.defaults.yaml`；此处刻意留空，使两份不一致的最坏结果只是不发布，而不是发错账号"。`pyproject.toml:56` 的 `package-data` 保持不变。

- [ ] **Step 4: Run tests**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_account_literals.py tests/unit/test_publish_policy.py tests/unit/test_deferred_publish.py tests/unit/test_settings_center.py tests/unit/test_web_console.py -v`
Expected: 新测试 PASS；既有测试中凡是断言字面量默认值/报错文案的，按新语义更新（例如断言默认值为空、断言空引用报错时提示可用账号）

- [ ] **Step 5: 全量回归**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest -m "not publish and not external" --tb=short`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add src/content_pipeline/models.py src/content_pipeline/api/ui_schema.py \
  src/content_pipeline/deferred_publishing.py src/content_pipeline/ai_briefing_runner.py \
  config/publish.defaults.yaml src/content_pipeline/config/publish.defaults.yaml \
  tests/unit/test_account_literals.py tests/unit/test_publish_policy.py \
  tests/unit/test_deferred_publish.py tests/unit/test_settings_center.py \
  tests/unit/test_web_console.py
git commit -m "refactor: drop hardcoded account names; resolve them from the ledger

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: 运行态文件迁移到 UID

**Files:**
- Create: `G:\Job\ai-popline\scripts\migrate_accounts_to_uid.py`
- Modify（由脚本写入）: `output/publish_policy.json`、`output/schedules/*.json`、`examples/tasks/**/*.json`
- Test: `G:\Job\ai-popline\tests\unit\test_migrate_accounts_to_uid.py`

**Interfaces:**
- Produces: `rewrite_accounts(payload: dict, accounts: dict[str, list[LedgerAccount]]) -> tuple[dict, list[str]]` —— 返回（改写后的 payload，改写记录）；`migrate(paths: list[Path], backup_dir: Path, accounts) -> list[str]`

**规则**：把 `douyin_account`/`kuaishou_account`/`tencent_account` 与 `targets[].account` 的值，从"名字"换成账本里对应的 `platform_uid`；查不到或歧义 → 记录该条并**跳过**（不猜），迁移结束打印待人工处理清单。

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\ai-popline\tests\unit\test_migrate_accounts_to_uid.py
import json
from pathlib import Path

from content_pipeline.account_ledger import LedgerAccount
from scripts.migrate_accounts_to_uid import migrate, rewrite_accounts

ACCOUNTS = {
    "douyin": [LedgerAccount("douyin", "7640519636165559355", "金融破壁人", "金融破壁人",
                             "93006552820", "valid", "2026-09-22T20:30:46+08:00", "cookie")],
    "kuaishou": [LedgerAccount("kuaishou", "5362435333", "搞AI的罗辑同学", "金融破壁人",
                               None, "valid", "2026-09-22T22:03:07+08:00", "cookie")],
}


def test_rewrite_accounts_switches_params_and_targets():
    payload = {
        "params": {"douyin_account": "金融破壁人", "kuaishou_account": "搞AI的罗辑同学"},
        "publish_targets": [{"platform": "douyin", "account": "金融破壁人"}],
    }
    rewritten, changes = rewrite_accounts(payload, ACCOUNTS)
    assert rewritten["params"]["douyin_account"] == "7640519636165559355"
    assert rewritten["params"]["kuaishou_account"] == "5362435333"
    assert rewritten["publish_targets"][0]["account"] == "7640519636165559355"
    assert len(changes) == 3


def test_rewrite_accounts_reports_unknown_without_guessing():
    payload = {"params": {"douyin_account": "已经不存在的号"}}
    rewritten, changes = rewrite_accounts(payload, ACCOUNTS)
    assert rewritten["params"]["douyin_account"] == "已经不存在的号"
    assert changes == ["douyin_account=已经不存在的号: 账本里查不到，留待人工处理"]


def test_migrate_backs_up_before_writing(tmp_path):
    target = tmp_path / "publish_policy.json"
    target.write_text(json.dumps({"finance": {"targets": [
        {"platform": "kuaishou", "account": "搞AI的罗辑同学"}]}}, ensure_ascii=False),
        encoding="utf-8")
    backup = tmp_path / "backup"
    changes = migrate([target], backup, ACCOUNTS)
    assert (backup / "publish_policy.json").is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["finance"]["targets"][0]["account"] == "5362435333"
    assert changes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_migrate_accounts_to_uid.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.migrate_accounts_to_uid'`

- [ ] **Step 3: Write the implementation**

```python
# G:\Job\ai-popline\scripts\migrate_accounts_to_uid.py
"""把运行态文件里的账号名换成账本 UID（一次性迁移）。

先备份到 output/backups/<日期>/，查不到的引用原样保留并打印待人工处理清单。
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from content_pipeline.account_ledger import LedgerAccount, load_accounts
from content_pipeline.settings import Settings

PARAM_FIELDS = {"douyin_account": "douyin", "kuaishou_account": "kuaishou",
                "tencent_account": "tencent"}


def _uid_for(accounts: dict[str, list[LedgerAccount]], platform: str, value: str) -> str | None:
    rows = accounts.get(platform) or []
    for row in rows:
        if row.platform_uid == value:
            return value
    for row in rows:
        if row.identity == value or (row.nickname and row.nickname == value):
            return row.platform_uid
    return None


def rewrite_accounts(payload: dict, accounts) -> tuple[dict, list[str]]:
    changes: list[str] = []

    def _swap(container: dict, key: str, platform: str) -> None:
        value = str(container.get(key) or "").strip()
        if not value:
            return
        uid = _uid_for(accounts, platform, value)
        if uid is None:
            changes.append(f"{key}={value}: 账本里查不到，留待人工处理")
            return
        if uid != value:
            container[key] = uid
            changes.append(f"{key}: {value} -> {uid}")

    params = payload.get("params")
    if isinstance(params, dict):
        for key, platform in PARAM_FIELDS.items():
            if key in params:
                _swap(params, key, platform)
    for key in ("publish_targets", "targets"):
        for target in payload.get(key) or []:
            if isinstance(target, dict) and target.get("account"):
                _swap(target, "account", str(target.get("platform") or ""))
    return payload, changes


def migrate(paths: list[Path], backup_dir: Path, accounts) -> list[str]:
    changes: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rewritten, file_changes = rewrite_accounts(payload, accounts)
        if not file_changes:
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir / path.name)
        path.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        changes.extend(f"{path}: {change}" for change in file_changes)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="output")
    parser.add_argument("--backup-dir", default=None)
    args = parser.parse_args()
    settings = Settings()
    accounts = load_accounts(settings)
    if accounts is None:
        print("账本不可用：先运行 `sau accounts sync` 生成 SAU/db/accounts.db")
        return 1
    data_dir = Path(args.data_dir)
    targets = sorted((data_dir / "schedules").glob("*.json")) + [data_dir / "publish_policy.json"]
    targets += sorted(Path("examples/tasks").rglob("*.json"))
    backup_dir = Path(args.backup_dir) if args.backup_dir else data_dir / "backups" / "account-uid-migration"
    changes = migrate(targets, backup_dir, accounts)
    print("\n".join(changes) if changes else "没有需要迁移的引用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`scripts/` 需要能被测试导入：在 `scripts/__init__.py` 不存在时新建空文件。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_migrate_accounts_to_uid.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 对真实运行态文件执行迁移（迁移前 Task 3 必须已跑过，账本已存在）**

```bash
cd "G:\Job\ai-popline"
uv run python scripts/migrate_accounts_to_uid.py
git --no-pager diff --stat output/ examples/
```
Expected: 打印改写记录；`output/backups/account-uid-migration/` 里有备份；`git diff` 里 `douyin_account`/`account` 的值变成 UID

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_accounts_to_uid.py scripts/__init__.py \
  tests/unit/test_migrate_accounts_to_uid.py output/publish_policy.json \
  output/schedules examples/tasks
git commit -m "chore: migrate runtime account references to ledger UIDs

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: 页面文本解析（昵称 / 对外号）

**Files:**
- Create: `G:\Job\social-auto-upload\utils\account_page.py`
- Test: `G:\Job\social-auto-upload\tests\test_account_page.py`

**Interfaces:**
- Produces:
  - `parse_nickname(platform: str, page_text: str) -> str | None`
  - `parse_public_id(platform: str, page_text: str) -> str | None`
  - `async def read_identity_from_page(platform: str, page) -> tuple[str | None, str | None]`（`page` 鸭子类型，只需 `evaluate`）

**解析规则（2026-09-22 实测页面结构）**

- douyin：`抖音号：<id>` 行；该行**上一行**的非空文本即昵称。
- kuaishou：首个非空行里**不以数字开头**的一行即昵称（页头第一行是通知数，如 `49`）。

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\social-auto-upload\tests\test_account_page.py
from utils import account_page

DOUYIN_TEXT = "\n".join([
    "作品发布", "首页", "内容管理", "数据中心", "金融破壁人", "抖音号：93006552820",
])
KUAISHOU_TEXT = "\n".join([
    "49", "金融破壁人", "发布作品", "首页", "内容管理",
])


def test_parse_douyin_nickname_is_line_before_public_id():
    assert account_page.parse_nickname("douyin", DOUYIN_TEXT) == "金融破壁人"
    assert account_page.parse_public_id("douyin", DOUYIN_TEXT) == "93006552820"


def test_parse_kuaishou_nickname_skips_counter_line():
    assert account_page.parse_nickname("kuaishou", KUAISHOU_TEXT) == "金融破壁人"


def test_parse_returns_none_when_page_text_is_unhelpful():
    assert account_page.parse_nickname("douyin", "登录") is None
    assert account_page.parse_public_id("kuaishou", "登录") is None


def test_identity_from_text_bundles_both_fields():
    assert account_page.identity_from_text("douyin", DOUYIN_TEXT) == ("金融破壁人", "93006552820")
    assert account_page.identity_from_text("kuaishou", KUAISHOU_TEXT) == ("金融破壁人", None)


def test_read_identity_from_page_uses_injected_page():
    """异步包装用鸭子类型假 page 测（不依赖 patchright、不依赖 asyncio 插件）。"""

    class FakePage:
        async def evaluate(self, _script):
            return DOUYIN_TEXT

    result = asyncio.run(account_page.read_identity_from_page("douyin", FakePage()))
    assert result == ("金融破壁人", "93006552820")


def test_read_identity_from_page_returns_none_on_failure():
    class BrokenPage:
        async def evaluate(self, _script):
            raise RuntimeError("page closed")

    assert asyncio.run(account_page.read_identity_from_page("douyin", BrokenPage())) == (None, None)
```

（首行需要 `import asyncio`。**不要用 pytest-asyncio**：SAU 只有 pytest，没有 asyncio 插件。）

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_page.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.account_page'`

- [ ] **Step 3: Write the implementation**

```python
# G:\Job\social-auto-upload\utils\account_page.py
"""从创作页页面文本里读昵称与对外号。

纯解析与页面无关，便于单测；异步包装只依赖鸭子类型的 `page.evaluate`，
因此本模块不 import patchright。
"""
from __future__ import annotations

import logging
import re

__all__ = ["parse_nickname", "parse_public_id", "identity_from_text",
           "read_identity_from_page"]

_logger = logging.getLogger(__name__)

_PUBLIC_ID_PATTERNS = {
    "douyin": re.compile(r"抖音号[：:]\s*([0-9A-Za-z_.\-]{4,})"),
    "kuaishou": re.compile(r"快手号[：:]\s*([0-9A-Za-z_.\-]{4,})"),
}
_NICKNAME_LINE_RE = re.compile(r"^[^\s\d].{0,23}$")
_PAGE_TEXT_JS = "() => (document.body.innerText || '')"


def _lines(page_text: str) -> list[str]:
    return [line.strip() for line in str(page_text or "").splitlines() if line.strip()]


def parse_public_id(platform: str, page_text: str) -> str | None:
    pattern = _PUBLIC_ID_PATTERNS.get(platform)
    if pattern is None:
        return None
    match = pattern.search(str(page_text or ""))
    return match.group(1) if match else None


def parse_nickname(platform: str, page_text: str) -> str | None:
    lines = _lines(page_text)
    if platform == "douyin":
        pattern = _PUBLIC_ID_PATTERNS["douyin"]
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            for previous in reversed(lines[:index]):
                if _NICKNAME_LINE_RE.match(previous):
                    return previous
            return None
        return None
    if platform == "kuaishou":
        for line in lines:
            if _NICKNAME_LINE_RE.match(line):
                return line
        return None
    return None


def identity_from_text(platform: str, page_text: str) -> tuple[str | None, str | None]:
    return parse_nickname(platform, page_text), parse_public_id(platform, page_text)


async def read_identity_from_page(platform: str, page) -> tuple[str | None, str | None]:
    """读取当前页面文本并解析。任何异常都返回 (None, None)（旁路）。"""
    try:
        page_text = await page.evaluate(_PAGE_TEXT_JS)
    except Exception as exc:  # noqa: BLE001 - 旁路
        _logger.warning("读取页面文本失败，跳过昵称采集: %s", exc)
        return None, None
    return identity_from_text(platform, page_text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_page.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 用今天实测的真实页面文本核对解析（只读，不开浏览器）**

```bash
cd "G:\Job\social-auto-upload"
python -c "
from utils import account_page
ks = '49\n金融破壁人\n发布作品\n首页'
dx = '作品发布\n首页\nAI分身\nAI工坊\n山下富士\n抖音号：68344185416'
print(account_page.identity_from_text('kuaishou', ks))
print(account_page.identity_from_text('douyin', dx))
"
```
Expected: `('金融破壁人', None)` 与 `('山下富士', '68344185416')`

- [ ] **Step 6: Commit**

```bash
git add utils/account_page.py tests/test_account_page.py
git commit -m "feat(ledger): parse nickname and public id from creator page text

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: check 结果带出昵称 / 对外号 / UID

**Files:**
- Modify: `G:\Job\social-auto-upload\sau_cli.py:454-472`（`check_douyin_account`）、`:499-501`（`check_kuaishou_account`）
- Test: `G:\Job\social-auto-upload\tests\test_account_check_ledger.py`（追加）

**Interfaces:**
- Consumes: Task 9 的 `identity_from_text`；Task 2 的 `extract_platform_uid`
- Produces：两个 check 函数返回 dict 增加三个键：`nickname`、`public_id`、`platform_uid`（取不到为 `None`）。快手 check 由返回 `bool` **改为返回 dict**（与抖音同构），以便走同一个结构化输出。

**兼容性**：`classify_check_result` 优先解析 `SAU_CHECK_RESULT`，因此快手改成结构化输出是向后兼容的；但 `dispatch` 里快手 check 分支要同步改成打印结构化行、并且退出码按 `valid` 决定。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 G:\Job\social-auto-upload\tests\test_account_check_ledger.py
from utils import account_page


def test_identity_from_text_feeds_check_payload():
    """check 结果里的 nickname/public_id 由页面文本解析而来。"""
    text = "作品发布\n首页\n金融破壁人\n抖音号：93006552820"
    nickname, public_id = account_page.identity_from_text("douyin", text)
    assert (nickname, public_id) == ("金融破壁人", "93006552820")
    payload = {"valid": True, "status": "valid", "message": "登录状态有效",
               "nickname": nickname, "public_id": public_id, "platform_uid": None}
    assert payload["nickname"] == "金融破壁人"
```

（真正的集成由 Task 11 的落库测试覆盖；这里只锁定字段约定。）

- [ ] **Step 2: Run test to verify it fails → passes after edit**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_check_ledger.py -v`
Expected: 先确认现有用例仍 PASS，再改实现

- [ ] **Step 3: Write the implementation**

在 `sau_cli.py` 顶部加 `from utils import account_page` 与 `from utils.account_ledger import extract_platform_uid`。

`check_douyin_account` 改为（保留原有字段，追加三个）：

```python
async def check_douyin_account(account_name: str) -> dict:
    account_file = resolve_account_file("douyin", account_name)
    if not account_file.exists():
        return {
            "valid": False,
            "status": "missing",
            "message": f"抖音 cookie 文件不存在: {account_file}",
            "account_file": str(account_file),
            "nickname": None,
            "public_id": None,
            "platform_uid": None,
        }
    result = await douyin_cookie_auth(str(account_file), return_detail=True)
    cookie_uid, _ = extract_platform_uid("douyin", account_file)
    return {
        "valid": bool(result),
        "status": result.status,
        "message": result.message,
        "account_file": str(account_file),
        "final_url": result.final_url,
        "title": result.title,
        "diagnostic_path": result.diagnostic_path,
        "nickname": getattr(result, "nickname", None),
        "public_id": getattr(result, "public_id", None),
        "platform_uid": cookie_uid,
    }
```

`douyin_cookie_auth` 需在页面还开着时采集：在 `uploader/douyin_uploader/main.py` 里 `DouyinCookieAuthResult` 增加 `nickname: str | None = None`、`public_id: str | None = None` 两个字段，并在**已经加载完页面的分支**（校验成功、返回结果之前）调用：

```python
        nickname, public_id = await read_identity_from_page("douyin", page)
        result = DouyinCookieAuthResult(
            True, "cookie_valid", "登录状态有效",
            nickname=nickname, public_id=public_id,
            final_url=page.url, title=await page.title(),
        )
```

（使用 `from utils.account_page import read_identity_from_page`；具体插入点以该函数现有的 `return` 结构为准，**所有返回 `valid=True` 的路径都要带上这两个值**。）

**抖音兜底**：`creator-micro/content/upload` 页若读不到昵称（`parse_nickname` 返回 `None`），在返回结果前额外访问一次首页再读（spec 允许的 +2–3s 兜底）：

```python
        nickname, public_id = await read_identity_from_page("douyin", page)
        if nickname is None:
            await page.goto("https://creator.douyin.com/creator-micro/home",
                            wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(3000)
            nickname, public_id = await read_identity_from_page("douyin", page)
```

`check_kuaishou_account` 改为返回 dict：把 `kuaishou_cookie_auth` 的结果与 `extract_platform_uid("kuaishou", account_file)`、页面解析结果合并；若 `kuaishou_cookie_auth` 目前只返回 `bool`，则在 `uploader/ks_uploader/main.py: cookie_auth` 里按同样方式采集昵称（该函数已打开 `KUAISHOU_UPLOAD_URL` 页面，页头即昵称）并通过 `return_detail` 参数返回 `dict`。快手页面没有"快手号："时 `public_id` 为 `None`，属预期。

`dispatch` 的快手 check 分支改为与抖音同构：

```python
        if args.action == "check":
            result = await check_kuaishou_account(args.account)
            print("valid" if result["valid"] else "invalid")
            print("SAU_CHECK_RESULT:" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0 if result["valid"] else 1
```

- [ ] **Step 4: Run tests**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_check_ledger.py tests/test_account_page.py tests/test_account_dashboard.py -q`
Expected: 全 PASS

- [ ] **Step 5: 真实校验一次，确认字段带出（只读，会开浏览器）**

```bash
cd "G:\Job\social-auto-upload"
./.venv/Scripts/python.exe -m sau_cli kuaishou check --account "搞AI的罗辑同学"
./.venv/Scripts/python.exe -m sau_cli douyin check --account "金融破壁人"
```
Expected: 两次都打印 `valid` 与 `SAU_CHECK_RESULT:{...}`；快手那次的 `nickname` 为 `金融破壁人`，抖音那次的 `nickname` 为 `金融破壁人`、`public_id` 为 `93006552820`

- [ ] **Step 6: Commit**

```bash
git add sau_cli.py uploader/douyin_uploader/main.py uploader/ks_uploader/main.py tests/test_account_check_ledger.py
git commit -m "feat(ledger): emit nickname and public id from account checks

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: 校验结果落库（写入点 1）

**Files:**
- Modify: `G:\Job\social-auto-upload\server\account_dashboard.py:425-451`（`_worker_loop`）
- Test: `G:\Job\social-auto-upload\tests\test_account_check_ledger.py`（追加）

**Interfaces:**
- Consumes: Task 10 的结构化字段；Task 1 的 `ledger.record_check`
- Produces: `_structured_check_payload(stdout: str) -> dict | None`（模块内私有，与既有 `_structured_check_result` 并列，或直接复用它）＋ `_sync_ledger_check(platform, identity, status, message, checked_at, payload) -> None`（旁路）

- [ ] **Step 1: Write the failing test**

```python
# 追加到 G:\Job\social-auto-upload\tests\test_account_check_ledger.py
import json

from server.account_dashboard import AccountStatusManager, AccountRecord, build_check_args
from server.account_dashboard import classify_check_result


def _record(tmp_path, platform="kuaishou", account="搞AI的罗辑同学"):
    cookie = tmp_path / f"{platform}_{account}.json"
    cookie.write_text(json.dumps({"cookies": [{"name": "userId", "value": "5362435333"}],
                                  "origins": []}), encoding="utf-8")
    return AccountRecord(
        key=f"{platform}:{account}", platform=platform, platform_label="快手",
        account=account, cookie_path=cookie, cookie_file=cookie.name,
        modified="2026-09-22T22:03:07+08:00", modified_timestamp=0.0,
        persistence="浏览器档案 + Cookie", profile_exists=False,
    )


def test_worker_loop_writes_check_result_into_ledger(tmp_path, ledger_env):
    record = _record(tmp_path)
    payload = {"valid": True, "status": "valid", "message": "登录状态有效",
               "nickname": "金融破壁人", "public_id": None, "platform_uid": "5362435333"}
    stdout = "valid\nSAU_CHECK_RESULT:" + json.dumps(payload, ensure_ascii=False)

    def fake_runner(_args):
        return {"exit_code": 0, "stdout": stdout, "stderr": ""}

    manager = AccountStatusManager(fake_runner, start_worker=True)
    try:
        manager.enqueue([record])
        assert manager.wait_until_idle(10) is True
    finally:
        manager.stop()

    conn = ledger.connect()
    row, verdict = ledger.resolve(conn, "kuaishou", "5362435333")
    conn.close()
    assert verdict == "hit"
    assert row.status == "valid"
    assert row.nickname == "金融破壁人"
    assert row.checked_at is not None
    assert manager.get_status(record)["status"] == "valid"
```

（`AccountStatusManager` 的公开方法名已核对：`start` / `enqueue(accounts)` / `get_status(account)` / `merge_accounts` / `wait_until_idle(timeout)` / `stop(timeout)`，另有 `_worker_loop`。）

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_check_ledger.py -k worker_loop -v`
Expected: FAIL —— 账本里查不到该行（没落库）

- [ ] **Step 3: Write the implementation**

在 `_worker_loop` 的 `status, message = classify_check_result(result)` 之后插入（`with self._lock:` 之前）：

```python
            _sync_ledger_check(
                platform=account.platform,
                identity=account.account,
                status=status,
                message=message,
                checked_at=checked_at,
                payload=_structured_check_result(result.get("stdout", "")),
            )
```

并加助手：

```python
def _sync_ledger_check(platform: str, identity: str, status: str, message: str,
                       checked_at: str, payload: dict | None) -> None:
    """把校验结果写入账本。账本不可用只记日志，绝不影响校验本身。"""
    payload = payload or {}
    uid = payload.get("platform_uid")
    try:
        connection = _account_ledger.connect()
        try:
            _account_ledger.record_check(
                connection,
                platform=platform,
                identity=identity,
                status=status,
                status_message=message,
                checked_at=checked_at,
                nickname=payload.get("nickname"),
                public_id=payload.get("public_id"),
                platform_uid=str(uid) if uid else None,
                uid_source="cookie" if uid else None,
            )
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001 - 旁路
        _logger.warning("写入账号账本失败（校验结果不受影响）: %s", exc)
```

- [ ] **Step 4: Run tests**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_check_ledger.py tests/test_account_dashboard.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add server/account_dashboard.py tests/test_account_check_ledger.py
git commit -m "feat(ledger): persist account check results into the ledger

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: `accounts sync --probe` 补昵称

**Files:**
- Modify: `G:\Job\social-auto-upload\utils\account_sync.py`、`sau_cli.py`（`accounts sync` 加 `--probe` 参数并透传）
- Test: `G:\Job\social-auto-upload\tests\test_account_sync.py`（追加）

**Interfaces:**
- Produces: `sync_accounts(cookies_dir, conn=None, probes=None)`，`probes: dict[tuple[str, str], tuple[str | None, str | None]] | None`——键是 `(platform, identity)`，值是 `(nickname, public_id)`。
- **控制流必须是"先异步探测、再同步写库"**：`dispatch()` 是 async 函数，在同步函数里 `asyncio.run()` 会直接抛 `RuntimeError`（事件循环已在运行）。所以 CLI 先 `await` 探测、把结果收成字典，再调用同步的 `sync_accounts`。本模块因此保持**无 asyncio、无 patchright 依赖**，测试不必碰浏览器。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 G:\Job\social-auto-upload\tests\test_account_sync.py
def test_sync_with_probes_fills_nickname_and_public_id(cookies_dir, tmp_path):
    conn = ledger.connect(tmp_path / "accounts.db")
    account_sync.sync_accounts(
        cookies_dir, conn=conn,
        probes={("kuaishou", "搞AI的罗辑同学"): ("金融破壁人", None)},
    )
    row, _ = ledger.resolve(conn, "kuaishou", "5362435333")
    conn.close()
    assert row.nickname == "金融破壁人"


def test_sync_without_probes_leaves_nickname_unset(cookies_dir, tmp_path):
    conn = ledger.connect(tmp_path / "accounts.db")
    account_sync.sync_accounts(cookies_dir, conn=conn, probes={})
    row, _ = ledger.resolve(conn, "kuaishou", "5362435333")
    conn.close()
    assert row.nickname is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_sync.py -k probes -v`
Expected: FAIL with `TypeError: sync_accounts() got an unexpected keyword argument 'probes'`

- [ ] **Step 3: Write the implementation**

`sync_accounts` 增加 `probes` 参数，在 upsert 之后按需补写昵称/对外号：

```python
def sync_accounts(
    cookies_dir: Path,
    conn: sqlite3.Connection | None = None,
    probes: dict[tuple[str, str], tuple[str | None, str | None]] | None = None,
) -> dict[str, int]:
    """把 cookies 目录里的账号并进账本。已存在的行只补字段，不覆盖状态/昵称。

    ``probes`` 预先由调用方（异步 CLI）探测好，本函数不做任何 IO 等待。
    """
    own_conn = conn is None
    connection = conn or ledger.connect()
    stats = {"scanned": 0, "with_uid": 0, "synthetic": 0}
    try:
        for record in discover_accounts(Path(cookies_dir)):
            stats["scanned"] += 1
            uid, source = ledger.extract_platform_uid(record.platform, record.cookie_path)
            if uid:
                stats["with_uid"] += 1
                platform_uid = uid
            else:
                stats["synthetic"] += 1
                platform_uid = ledger.synthetic_uid(record.account)
                source = "synthetic"
            ledger.upsert_account(
                connection, platform=record.platform, platform_uid=platform_uid,
                identity=record.account, uid_source=source,
            )
            if probes:
                nickname, public_id = probes.get((record.platform, record.account), (None, None))
                if nickname or public_id:
                    ledger.record_check(
                        connection, platform=record.platform, identity=record.account,
                        status="unknown", nickname=nickname, public_id=public_id,
                        platform_uid=platform_uid,
                        uid_source="page" if not uid else None,
                    )
    finally:
        if own_conn:
            connection.close()
    return stats
```

CLI 侧（`dispatch` 的 `accounts sync` 分支）：先探测、再写库：

```python
        if args.action == "sync":
            cookies_dir = Path(args.cookies_dir) if args.cookies_dir else BASE_DIR / "cookies"
            probes = {}
            if getattr(args, "probe", False):
                for record in discover_accounts(cookies_dir):
                    checker = {"douyin": check_douyin_account,
                               "kuaishou": check_kuaishou_account}.get(record.platform)
                    if checker is None:
                        continue
                    result = await checker(record.account)
                    nickname = result.get("nickname") if isinstance(result, dict) else None
                    public_id = result.get("public_id") if isinstance(result, dict) else None
                    if nickname or public_id:
                        probes[(record.platform, record.account)] = (nickname, public_id)
            stats = _account_sync.sync_accounts(cookies_dir, probes=probes)
            print("ACCOUNTS_SYNC:" + json.dumps(stats, ensure_ascii=False))
            return 0
```

并给 `accounts sync` 加参数：`accounts_sync_parser.add_argument("--probe", action="store_true", help="Open each creator page once to fill nicknames")`。

- [ ] **Step 4: Run tests**

Run: `cd "G:\Job\social-auto-upload" && python -m pytest tests/test_account_sync.py -v`
Expected: 全 PASS

- [ ] **Step 5: 真机补齐昵称（会逐个开浏览器，约 1-2 分钟）**

```bash
cd "G:\Job\social-auto-upload"
./.venv/Scripts/python.exe -m sau_cli accounts sync --probe
./.venv/Scripts/python.exe -m sau_cli accounts show
```
Expected: 表格里 `kuaishou 搞AI的罗辑同学` 的昵称列显示 **金融破壁人**，`douyin 硅基思维TARS` 显示 **山下富士**、对外号 `68344185416`

- [ ] **Step 6: Commit**

```bash
git add utils/account_sync.py sau_cli.py tests/test_account_sync.py
git commit -m "feat(ledger): fill nicknames via accounts sync --probe

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 13: `ai-pipeline accounts list` 与文档

**Files:**
- Modify: `G:\Job\ai-popline\src\content_pipeline\cli\main.py`（注册 `accounts list`）
- Modify: `G:\Job\ai-popline\docs\configuration.md`（账号配置一节）
- Test: `G:\Job\ai-popline\tests\unit\test_accounts_cli.py`

**Interfaces:**
- Consumes: Task 5 的 `load_accounts`
- Produces: CLI `ai-pipeline accounts list [--platform P]`

- [ ] **Step 1: Write the failing test**

```python
# G:\Job\ai-popline\tests\unit\test_accounts_cli.py
from content_pipeline.cli.main import build_parser


def test_accounts_list_is_registered():
    parser = build_parser()
    args = parser.parse_args(["accounts", "list", "--platform", "kuaishou"])
    assert (args.command, args.accounts_command, args.platform) == ("accounts", "list", "kuaishou")
```

（若 `cli/main.py` 没有 `build_parser`，先把它从 `main()` 里抽出来——这属于本任务的重构范围。）

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_accounts_cli.py -v`
Expected: FAIL（`accounts` 未注册）

- [ ] **Step 3: Write the implementation**

在 `cli/main.py` 注册（与 `jobs` 同级）：

```python
    accounts_parser = subparsers.add_parser("accounts", help="Inspect the SAU account ledger")
    accounts_subparsers = accounts_parser.add_subparsers(dest="accounts_command")
    accounts_list = accounts_subparsers.add_parser("list", help="List ledger accounts")
    accounts_list.add_argument("--platform", help="Only show one platform")
```

处理函数（与 `jobs list` 同风格）：

```python
def _accounts_list(settings: Settings, platform: str | None) -> int:
    accounts = load_accounts(settings)
    if accounts is None:
        print("账本不可用：请先在 SAU 侧运行 `sau accounts sync`")
        return 1
    rows = accounts.get(platform, []) if platform else [a for group in accounts.values() for a in group]
    for row in sorted(rows, key=lambda item: (item.platform, item.identity)):
        print(f"{row.platform:<11} {row.identity:<20} 昵称={row.nickname or '-':<12} "
              f"uid={row.platform_uid:<24} 状态={row.status}")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "G:\Job\ai-popline" && uv run --extra test pytest tests/unit/test_accounts_cli.py -v`
Expected: PASS

- [ ] **Step 5: 更新文档**

在 `docs/configuration.md` 增加一节「账号引用怎么填」：

- 账号引用可以是 **UID**（推荐，账本主键）、**当前身份名**（cookie 文件名）、或**平台昵称**；留空表示"该平台唯一账号"。
- 名字会被解析成 SAU 的当前身份名；SAU 里改标识后无需改任何配置，但**已不存在的旧名字会当场报错**（不静默兜底），报错里会列出可用账号。
- 账本由 SAU 维护：`sau accounts sync`（首次/新增账号后）、`sau accounts sync --probe`（补昵称）、`sau accounts show`（查看）。ai-pipeline 侧只读：`ai-pipeline accounts list`。
- 若账本文件不存在或打不开，ai-pipeline 回退使用配置里的字面量（fail-open），此时改标识仍需人工同步。

- [ ] **Step 6: 全量回归并提交**

```bash
cd "G:\Job\ai-popline"
uv run --extra test pytest -m "not publish and not external" --tb=short
git add src/content_pipeline/cli/main.py tests/unit/test_accounts_cli.py docs/configuration.md
git commit -m "feat(cli): add accounts list and document account references

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 第一期验收（全部任务完成后）

- [ ] `sau accounts show` 打印 7 个账号，昵称列显示平台真实昵称（快手 `搞AI的罗辑同学` → 昵称 `金融破壁人`；抖音 `硅基思维TARS` → 昵称 `山下富士`）
- [ ] 在 SAU 账号页把 `kuaishou_搞AI的罗辑同学` 改标识为任意新名 → `sau accounts show` 里该行身份名跟着变、UID 不变
- [ ] 不修改 ai-pipeline 任何配置，跑一次 `uv run python -m content_pipeline.ai_briefing_runner --date auto --skip-publish`，再对同一任务跑 dry-run 发布，确认命令行里的 `--account` 是**新的身份名**
- [ ] 把该名字改回去（或改成 `搞AI的罗辑同学`），再验证一次
- [ ] `uv run --extra test pytest -m "not publish and not external"` 全绿；`python -m pytest tests/ -q`（SAU）全绿