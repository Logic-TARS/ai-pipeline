"""只读 SAU 账号账本（SQLite），把配置里的账号引用解析成当前身份名。

SAU 是唯一写入方。账本不可用时返回 None，调用方按 fail-open 处理
（沿用配置里的字面量），因此账本本身出问题不会阻断发布。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from content_pipeline.core.errors import ConfigError
from content_pipeline.settings import Settings

__all__ = [
    "LEDGER_RELATIVE_PATH",
    "LedgerAccount",
    "ensure_account_publishable",
    "load_accounts",
    "resolve_publish_account",
    "describe_platform_accounts",
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
            "SELECT platform, platform_uid, identity, nickname, public_id, status, checked_at, uid_source FROM accounts"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    grouped: dict[str, list[LedgerAccount]] = {}
    for record in records:
        account = LedgerAccount(
            platform=record["platform"],
            platform_uid=record["platform_uid"],
            identity=record["identity"],
            nickname=record["nickname"],
            public_id=record["public_id"],
            status=record["status"],
            checked_at=record["checked_at"],
            uid_source=record["uid_source"],
        )
        grouped.setdefault(account.platform, []).append(account)
    return grouped


def describe_platform_accounts(accounts: dict[str, list[LedgerAccount]], platform: str) -> str:
    rows = accounts.get(platform) or []
    if not rows:
        return f"SAU 账号账本里没有 {platform} 平台的任何账号"
    parts = [
        f"{row.nickname or '（无昵称）'}(uid {row.platform_uid}, 身份名 {row.identity}, {row.status})" for row in rows
    ]
    return "、".join(parts)


def resolve_publish_account(settings: Settings, platform: str, ref: str) -> LedgerAccount | None:
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
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
            f'请先重新登录：sau {account.platform} login --account "{account.identity}"'
        )
    warnings: list[str] = []
    if account.nickname and account.nickname != account.identity:
        warnings.append(
            f"账号 {account.platform}:{account.identity} 的平台昵称是「{account.nickname}」，"
            "与身份名不一致（常见于改过标识）——请确认发布目标账号是否正确。"
        )
    checked = _parse_iso(account.checked_at)
    if checked is None:
        warnings.append(f"账号 {account.platform}:{account.identity} 没有校验记录，登录状态可能过期。")
    elif (now or datetime.now(UTC)) - checked > timedelta(days=max_age_days):
        warnings.append(
            f"账号 {account.platform}:{account.identity} 上次校验是 {account.checked_at}，登录状态可能过期。"
        )
    return warnings
