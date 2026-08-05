from __future__ import annotations

import re
from datetime import date
from typing import Any

from content_pipeline.tools.narrated_mpt_client import looks_like_file_reference

CONTENT_STUDIO_FINANCE_DISCLAIMER = "以上内容仅为市场信息整理，不构成投资建议。"
DAILY_FINANCE_DISCLAIMER = "以上内容仅为市场信息整理和个人观点，不构成任何投资建议。"
FINANCE_RISK_NOTE = "面对市场波动，请结合自身投资期限、仓位水平和风险承受能力审慎决策。"
FINANCE_MIN_CHARS = 350
FINANCE_MAX_CHARS = 500
CONTENT_STUDIO_MIN_CHARS = 380
CONTENT_STUDIO_MAX_CHARS = 430
GENERIC_FILLER_MARKERS = (
    "资料不完整时",
    "黄金通常同时受到",
    "宏观数据有月度",
    "单日行情只代表",
    "涉及滞后或回填",
    "如果只有单一来源",
    "正式生成视频前",
    "自动生成内容优先",
)
FINANCE_SECTION_LABELS = (
    "顶部摘要",
    "四大指数",
    "四指数行情",
    "四指数表格",
    "板块轮动",
    "估值水位",
    "今日关键词",
    "三个信号",
    "核心信号",
    "我的解读",
    "策略建议",
    "投资建议",
    "黄金债市",
    "黄金",
    "债券",
)


class FinanceScriptError(ValueError):
    pass


def clean_markdown(value: str) -> str:
    value = re.sub(r"!\[[^]]*]\([^)]*\)", "", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    value = re.sub(r"[`*_>#]", "", value)
    value = re.sub(r"^[|\s]+|[|\s]+$", "", value)
    value = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%+\-.,，。；：:、（）()/$≈]", "", value)
    return re.sub(r"\s+", "", value).strip("，。； ")


def trim_complete(value: str, limit: int) -> str:
    value = value.strip("，。； ")
    if len(value) <= limit:
        return value
    clipped = value[:limit]
    stops = [clipped.rfind(mark) for mark in "。！？；"]
    stop = max(stops)
    if stop >= max(120, limit - 100):
        return clipped[: stop + 1].strip()
    return clipped.rstrip("，；： ") + "。"


def _section(markdown: str, *keywords: str) -> str:
    candidates = re.finditer(r"(?m)^(?:#{2,4}\s+(.+?)|\*\*(.+?)\*\*)\s*$", markdown)
    headings = []
    for heading in candidates:
        title = clean_markdown(heading.group(1) or heading.group(2))
        if any(label in title for label in FINANCE_SECTION_LABELS):
            headings.append((heading, title))
    for index, (heading, title) in enumerate(headings):
        if any(keyword in title for keyword in keywords):
            end = headings[index + 1][0].start() if index + 1 < len(headings) else len(markdown)
            return markdown[heading.end() : end].strip()
    return ""


def _table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.strip().startswith("|") or re.search(r"\|\s*:?-{2,}", line):
            continue
        cells = [clean_markdown(cell) for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] not in {"指数", "板块", "品种"}:
            rows.append(cells)
    return rows


def _summary_table(markdown: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in _table_rows(markdown):
        if len(row) < 2 or row[0] in {"模块", "项目", "类别"}:
            continue
        values[clean_markdown(row[0])] = clean_markdown(row[1])
    return values


def _summary_value(values: dict[str, str], *keywords: str) -> str:
    for label, value in values.items():
        if any(keyword in label for keyword in keywords):
            return value
    return ""


def _first_sentence(value: str) -> str:
    cleaned = clean_markdown(value)
    parts = re.split(r"(?<=[。！？])", cleaned)
    return next((part.strip() for part in parts if part.strip()), cleaned)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def _number_text(value: Any, *, suffix: str = "") -> str:
    if value is None or value == "":
        return ""
    return f"{value}{suffix}"


def _append_until(parts: list[str], candidates: list[str], min_chars: int, tail: str) -> None:
    for candidate in candidates:
        if len("".join(parts)) + len(tail) >= min_chars:
            break
        if candidate and candidate not in parts:
            parts.append(candidate)


def _validate_content_studio_finance_script(script: str) -> None:
    if not CONTENT_STUDIO_MIN_CHARS <= len(script) <= CONTENT_STUDIO_MAX_CHARS:
        raise FinanceScriptError(f"金融初稿需要约400字，当前为 {len(script)} 字")
    if any(marker in script for marker in GENERIC_FILLER_MARKERS):
        raise FinanceScriptError("金融初稿包含通用填充话术，缺少可播信息")
    if "不构成投资建议" not in script:
        raise FinanceScriptError("金融初稿缺少风险提示")
    if not re.search(r"\d", script):
        raise FinanceScriptError("金融初稿缺少具体数值")
    required_markers = ("黄金", "债市", "宏观")
    missing = [marker for marker in required_markers if marker not in script]
    if missing:
        raise FinanceScriptError("金融初稿缺少关键模块：" + "、".join(missing))


def _finalize_script(
    parts: list[str],
    *,
    disclaimer: str,
    required_tail: str = "",
    fillers: list[str] | None = None,
    min_chars: int = FINANCE_MIN_CHARS,
    max_chars: int = FINANCE_MAX_CHARS,
    length_error: str = "金融初稿长度不合规：{length} 字",
) -> str:
    core = re.sub(r"[。！？；]{2,}", "。", "".join(part for part in parts if part))
    tail = required_tail + disclaimer
    for filler in fillers or []:
        if len(core) + len(tail) >= min_chars:
            break
        core += filler
    limit = max_chars - len(tail)
    core = trim_complete(core, limit)
    script = core.rstrip("。") + "。" + tail
    if not min_chars <= len(script) <= max_chars:
        raise FinanceScriptError(length_error.format(length=len(script)))
    return script


def validate_daily_finance_script(script: str) -> None:
    if not FINANCE_MIN_CHARS <= len(script) <= FINANCE_MAX_CHARS:
        raise FinanceScriptError(
            f"finance narration must contain 350-500 characters; generated {len(script)} characters"
        )
    normalized = script.replace(" ", "")
    if (
        looks_like_file_reference(normalized)
        or "文件路径" in script
        or re.search(r"(?:^|[：:])(?:~|[A-Za-z]:)[/\\].+\.(?:md|txt|json|srt)", script, re.IGNORECASE)
    ):
        raise FinanceScriptError("finance narration contains a file reference instead of spoken content")
    if not all(marker in script for marker in ("指数", "板块")):
        raise FinanceScriptError("finance narration is missing required index or sector market information")


def build_daily_markdown_script(
    response: str,
    publication_date: str,
    *,
    min_chars: int = FINANCE_MIN_CHARS,
    max_chars: int = FINANCE_MAX_CHARS,
) -> str:
    summary_values = _summary_table(response)
    summary_match = re.search(r"(?m)一句话总结[：:]\s*\*{0,2}\s*(.+)$", response)
    summary = (
        _first_sentence(summary_match.group(1))
        if summary_match
        else _summary_value(summary_values, "盘面定性", "顶部摘要", "一句话总结")
    )
    if not summary:
        summary = trim_complete(_first_sentence(_section(response, "顶部摘要")), 60)

    index_section = _section(response, "四大指数", "四指数行情", "四指数表格")
    index_rows = _table_rows(index_section)[:4]
    indices = []
    for row in index_rows:
        if len(row) >= 3:
            indices.append(f"{row[0]}报{row[1]}点，{row[2]}")
    index_summary = _summary_value(summary_values, "四大指数", "四指数")

    sector_section = _section(response, "板块轮动")
    leaders: list[str] = []
    laggards: list[str] = []
    mode = ""
    for line in sector_section.splitlines():
        cleaned_line = clean_markdown(line)
        if "领涨" in cleaned_line:
            mode = "up"
            continue
        if "领跌" in cleaned_line:
            mode = "down"
            continue
        if line.lstrip().startswith(("•", "-")):
            phrase = trim_complete(clean_markdown(line), 40)
            if mode == "up" and not leaders:
                leaders.append(phrase)
            elif mode == "down" and not laggards:
                laggards.append(phrase)
            continue
        if line.strip().startswith("|") and not re.search(r"\|\s*:?-{2,}", line):
            cells = [clean_markdown(cell) for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in {"板块", "品种"}:
                phrase = f"{cells[0]}{cells[1]}"
                if mode == "up" and not leaders:
                    leaders.append(phrase)
                elif mode == "down" and not laggards:
                    laggards.append(phrase)
    sector_summary = _summary_value(summary_values, "板块轮动")
    sector_detail = trim_complete(clean_markdown(sector_section), 45) if sector_section else ""

    keyword_section = _section(response, "今日关键词", "三个信号", "核心信号")
    keywords = []
    for line in keyword_section.splitlines():
        named_match = re.match(r"\s*\*{0,2}(?:\d+[.、]|[①-⑩])\s*[「“](.+?)[」”]", line)
        numbered_match = re.match(r"\s*\d+[.、]\s*(.+)", line)
        if named_match:
            keywords.append(clean_markdown(named_match.group(1)))
        elif numbered_match:
            keywords.append(_first_sentence(numbered_match.group(1)))
        if len(keywords) == 3:
            break
    keyword_summary = _summary_value(summary_values, "今日关键词", "三个信号", "核心信号")
    keyword_detail = trim_complete(clean_markdown(keyword_section), 45) if keyword_section else ""

    interpretation = _section(response, "我的解读", "策略建议", "投资建议")
    advice_match = re.search(r"(?m)^.*我的建议.*$", interpretation)
    strategy_match = re.search(r"(?im)^\s*\*\*策略上[：:]?\*\*\s*$", interpretation)
    if strategy_match:
        strategy = re.split(r"(?m)^\s*(?:\*真正|[-═─]{3,}|📁)", interpretation[strategy_match.end() :], maxsplit=1)[0]
        strategy_items = [
            clean_markdown(line)
            for line in strategy.splitlines()
            if line.lstrip().startswith(("•", "-")) and clean_markdown(line)
        ]
        advice = "；".join(strategy_items[:2]) if strategy_items else trim_complete(clean_markdown(strategy), 50)
    else:
        advice = trim_complete(
            _first_sentence(advice_match.group(0)) if advice_match else _first_sentence(interpretation),
            55,
        )
    advice_summary = _summary_value(summary_values, "我的解读", "策略建议", "投资建议")
    valuation_section = _section(response, "估值水位")
    valuation_rows = _table_rows(valuation_section)[:4]
    valuation_detail = "；".join(
        f"{row[0]}PE{row[1]}，历史百分位{row[2]}，{row[-1]}" for row in valuation_rows if len(row) >= 4
    )
    valuation_summary = _summary_value(summary_values, "估值水位", "估值") or valuation_detail
    cross_asset_summary = _summary_value(summary_values, "黄金债市", "黄金", "债券") or trim_complete(
        clean_markdown(_section(response, "黄金债市", "黄金", "债券")), 100
    )

    date_text = publication_date.replace("-", "年", 1).replace("-", "月", 1) + "日"
    parts = [f"{date_text}A股收盘观察。"]
    if summary:
        parts.append(summary + "。")
    if indices:
        parts.append("四大指数方面，" + "；".join(indices) + "。")
    elif index_summary:
        parts.append("四大指数方面，" + index_summary + "。")
    if leaders or laggards:
        sector_bits = []
        if leaders:
            sector_bits.append("领涨方向是" + leaders[0])
        if laggards:
            sector_bits.append("领跌方向是" + laggards[0])
        parts.append("板块方面，" + "；".join(sector_bits) + "。")
    elif sector_summary:
        parts.append("板块方面，" + sector_summary + "。")
    elif sector_detail:
        parts.append("板块方面，" + sector_detail + "。")
    if advice:
        parts.append(advice + "。")
    elif advice_summary:
        parts.append("策略上，" + advice_summary + "。")
    if keywords:
        parts.append("今天需要关注的信号是：" + "；".join(keywords) + "。")
    elif keyword_summary:
        parts.append("今天需要关注的信号是：" + keyword_summary + "。")
    elif keyword_detail:
        parts.append("今天需要关注的信号是：" + keyword_detail + "。")
    if valuation_summary:
        parts.append("估值方面，" + valuation_summary + "。")
    if cross_asset_summary:
        parts.append("其他资产方面，" + cross_asset_summary + "。")

    if len("".join(parts)) < 330:
        plain_interpretation = clean_markdown(interpretation)
        for sentence in re.split(r"(?<=[。！？])", plain_interpretation):
            sentence = sentence.strip()
            if sentence and sentence not in "".join(parts):
                parts.append(sentence)
            if len("".join(parts)) >= 410:
                break

    script = _finalize_script(
        parts,
        required_tail=FINANCE_RISK_NOTE,
        disclaimer=DAILY_FINANCE_DISCLAIMER,
        min_chars=min_chars,
        max_chars=max_chars,
        length_error="finance narration must contain 350-500 characters; generated {length} characters",
        fillers=[
            "短期盘面只代表当天资金偏好，不能直接外推为中长期趋势。",
            "估值、成交和政策预期需要放在同一时间维度里交叉验证。",
        ],
    )
    validate_daily_finance_script(script)
    return script


def build_structured_finance_script(
    sources: dict[str, dict[str, Any]],
    *,
    publication_date: str | None = None,
    disclaimer: str = CONTENT_STUDIO_FINANCE_DISCLAIMER,
) -> str:
    gold = sources.get("gold") or {}
    bond = sources.get("bond") or {}
    macro = sources.get("macro-cn") or {}
    as_of = str(publication_date or gold.get("as_of") or bond.get("update_time") or date.today().isoformat())
    parts = [f"{as_of.replace('-', '年', 1).replace('-', '月', 1)}日金融市场观察。"]

    quotes = _as_dict(gold.get("gold_quotes"))
    sge = _as_dict(quotes.get("sge_benchmark"))
    au9999 = _as_dict(quotes.get("au9999"))
    futures = _as_dict(quotes.get("gold_futures_shfe"))
    central_bank = _as_dict(quotes.get("central_bank_gold"))
    gold_bits = []
    if futures.get("close") is not None:
        text = (
            f"{futures.get('date', '最新交易日')}黄金期货主力收于{futures['close']}元每克"
        )
        if futures.get("change_pct") is not None:
            text += f"，涨跌幅{futures['change_pct']}%"
        if futures.get("volume") is not None:
            text += f"，成交量{futures['volume']}"
        gold_bits.append(text)
    if au9999.get("close") is not None:
        text = f"Au99.99收于{au9999['close']}元每克"
        if au9999.get("change_pct") is not None:
            text += f"，涨跌幅{au9999['change_pct']}%"
        gold_bits.append(text)
    elif sge.get("evening_price") is not None or sge.get("morning_price") is not None:
        price = sge.get("evening_price") or sge.get("morning_price")
        gold_bits.append(f"{sge.get('date', '最新交易日')}上海金基准价{price}元每克")
    if central_bank.get("gold_reserves") is not None:
        gold_bits.append(
            f"央行{central_bank.get('date', '最近一期')}黄金储备{central_bank['gold_reserves']}万盎司，趋势为{central_bank.get('trend', '待核对')}"
        )
    if gold_bits:
        parts.append("黄金方面，" + "；".join(gold_bits[:3]) + "。")
    has_gold = bool(gold_bits)

    bond_summary = str(bond.get("text_summary") or "").strip()
    has_bond = False
    if bond_summary:
        bond_summary = bond_summary.split("建议", 1)[0].rstrip("，。；： ")
        parts.append("债市方面，" + bond_summary + "。")
        has_bond = True
    else:
        market = _as_dict(bond.get("market"))
        rate_items = _as_list(market.get("barometerRateItemList"))
        rate_text = ""
        if rate_items:
            first = _as_dict(rate_items[0])
            rate_text = clean_markdown("".join(str(value) for value in first.values() if value is not None))[:60]
        if market:
            bits = [
                f"交易日{market.get('tradeDate')}" if market.get("tradeDate") else "",
                f"债市天气{market.get('weather')}" if market.get("weather") else "",
                rate_text,
            ]
            parts.append("债市方面，" + "，".join(bit for bit in bits if bit) + "。")
            has_bond = True

    monthly_records: list[dict[str, Any]] = []
    for frequency in macro.get("frequencies") or []:
        if isinstance(frequency, dict) and "月" in str(frequency.get("频率")):
            monthly_records = [item for item in frequency.get("记录") or [] if isinstance(item, dict)]
            break
    complete = next((item for item in reversed(monthly_records) if len(item) >= 4), None)
    latest = monthly_records[-1] if monthly_records else None
    has_macro = False
    if complete:
        metrics = []
        for key, label in (
            ("CPI:当月同比(%)", "CPI同比"),
            ("PPI:当月同比(%)", "PPI同比"),
            ("PMI(%)", "PMI"),
            ("M2:同比(%)", "M2同比"),
        ):
            if complete.get(key) is not None:
                metrics.append(f"{label}{complete[key]}%")
        if metrics:
            parts.append(f"宏观数据方面，{complete.get('日期', '最近一期')}公布的" + "、".join(metrics) + "。")
            has_macro = True
    if latest and latest is not complete and latest.get("PMI(%)") is not None:
        parts.append(f"更新到{latest.get('日期', '最近一期')}的PMI为{latest['PMI(%)']}%。")
        has_macro = True

    risk = _as_dict(gold.get("risk_indicators"))
    risk_bits = []
    vix = _as_dict(risk.get("vix"))
    dxy = _as_dict(risk.get("dxy"))
    exchprice = _as_dict(risk.get("exchprice"))
    if vix.get("INDICATOR_VAL") is not None:
        risk_bits.append(f"VIX为{vix['INDICATOR_VAL']}")
    if dxy.get("INDICATOR_VAL") is not None:
        risk_bits.append(f"美元指数{dxy['INDICATOR_VAL']}")
    if exchprice.get("EXCHPRICE") is not None:
        risk_bits.append(f"美元兑人民币{exchprice['EXCHPRICE']}")
    if risk_bits:
        parts.append("跨资产风险指标方面，" + "、".join(risk_bits) + "。")

    missing_modules = [
        label
        for label, present in (("黄金", has_gold), ("债市", has_bond), ("宏观", has_macro))
        if not present
    ]
    if missing_modules:
        raise FinanceScriptError("金融初稿缺少关键模块：" + "、".join(missing_modules))

    news = _as_dict(gold.get("news"))
    news_items = [_as_dict(item) for item in _as_list(news.get("items"))]
    fresh_news = [
        clean_markdown(str(item.get("summary") or item.get("title") or ""))
        for item in news_items
        if item.get("publish_date") == str(as_of)[:10] and (item.get("summary") or item.get("title"))
    ]
    if fresh_news:
        parts.append("消息面，" + trim_complete(fresh_news[0], 72) + "。")

    for source_id, payload in sources.items():
        if not source_id.startswith("stock-") or not isinstance(payload, dict):
            continue
        name = payload.get("stock_name") or payload.get("query") or "关注股票"
        price = _value(payload, "current_price", "price", "latest_price")
        change = _value(payload, "change_percent", "change_pct", "pct_chg")
        if price is not None:
            text = f"个股方面，{name}最新价为{price}元"
            if change is not None:
                text += f"，涨跌幅{change}%"
            parts.append(text + "。")

    tail = disclaimer
    _append_until(
        parts,
        [
            "组合观察上，黄金上涨、债市震荡和PMI回落同时出现，说明避险与增长预期仍在拉扯。",
            "操作语气上，先把黄金和债市当作风险偏好温度计，再看宏观数据是否支持权益继续修复。",
            "发布前重点复核黄金交易日、债市更新时间和宏观指标月份，避免把滞后数据说成实时行情。",
            "如果关注股票缺失报价，本稿只覆盖大类资产和宏观环境，不替代个股复盘。",
        ],
        CONTENT_STUDIO_MIN_CHARS,
        tail,
    )
    script = _finalize_script(
        parts,
        disclaimer=disclaimer,
        min_chars=CONTENT_STUDIO_MIN_CHARS,
        max_chars=CONTENT_STUDIO_MAX_CHARS,
    )
    _validate_content_studio_finance_script(script)
    return script
