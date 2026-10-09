"""结构化字段提取器。

从解析得到的「分段 + 全文」中抽取需求强制要求的两类字段：

    一、合同基本信息（8 项）
        合同标题、合同编号、签约主体、对方名称、合同金额、币种、生效时间、到期时间
    二、合同条款信息（8 项）
        付款条款、交付条款、验收条款、违约条款、保密条款、数据条款、
        知识产权条款、争议解决条款

每个字段统一返回：
    value           字段值（提取失败时返回占位文本「未识别」，规范要求禁止空值返回）
    evidence_text   对应的原文片段
    position        页码/段号/行号/字符偏移定位信息
    extract_status  success / missing / failed
    extract_method  提取方式（正则匹配 / 关键词匹配 / 表格提取 / OCR识别 / 推断补全）
    error_msg       提取失败的具体原因（含已检索的关键词，便于人工复核）
"""

from __future__ import annotations

import re

from ...constants import ExtractStatus
from .locator import join_text, position_of, snippet

# ----------------------------------------------------------------------
# 通用正则片段
# ----------------------------------------------------------------------
_DATE = r"\d{4}\s*[年\-/.]\s*\d{1,2}\s*[月\-/.]\s*\d{1,2}\s*日?"
_AMOUNT_NUM = r"([0-9][0-9,，]*(?:\.[0-9]{1,2})?)"
_AMOUNT_UNIT = r"(万元|万|亿元|亿|元|圆|USD|美元|人民币)"

#: 条款标题识别（用于切分条款正文边界）
_HEADING_RX = re.compile(r"^第[一二三四五六七八九十百零]+[条章节款项]")

#: 各条款的关键词表（同时用于正文边界判断）
CLAUSE_SPECS: list[tuple[str, list[str]]] = [
    ("付款条款", ["付款", "支付方式", "支付条款", "价款支付", "结算方式", "付款方式", "付款条件", "支付安排", "费用及支付", "价款及支付"]),
    ("交付条款", ["交付", "交货", "供货", "服务提供", "履行期限", "交付方式", "交付时间", "交付地点", "服务期限"]),
    ("验收条款", ["验收", "交付验收", "验收标准", "验收方式", "检验标准", "验收合格"]),
    ("违约条款", ["违约", "违约责任", "赔偿责任", "违约金", "责任承担"]),
    ("保密条款", ["保密", "保密义务", "机密信息", "保密信息", "商业秘密"]),
    ("数据条款", ["数据", "个人信息", "隐私", "用户信息", "数据处理"]),
    ("知识产权条款", ["知识产权", "著作权", "专利", "商标", "成果归属", "技术成果"]),
    ("争议解决条款", ["争议解决", "争议", "仲裁", "诉讼", "管辖", "法律适用"]),
]

#: 全部条款关键词（用于正文边界判断）
_ALL_CLAUSE_KEYWORDS: list[str] = [kw for _, kws in CLAUSE_SPECS for kw in kws]


# ======================================================================
# 工具函数
# ======================================================================
def _ok(value: str, seg: dict | None, method: str, evidence: str | None = None) -> dict:
    """构造提取成功的字段结果。"""
    return {
        "value": (value or "").strip() or ExtractStatus.PLACEHOLDER,
        "evidence_text": snippet(evidence if evidence is not None else (seg or {}).get("text", "")),
        "position": position_of(seg),
        "extract_status": ExtractStatus.SUCCESS,
        "extract_method": method,
        "error_msg": "",
    }


def _missing(reason: str, searched: str = "") -> dict:
    """构造提取失败的字段结果（含具体原因，禁止空值）。"""
    return {
        "value": ExtractStatus.PLACEHOLDER,
        "evidence_text": f"（全文未检索到相关内容，已检索关键词：{searched or reason}）",
        "position": "全文检索（未命中）",
        "extract_status": ExtractStatus.MISSING,
        "extract_method": "未命中",
        "error_msg": f"未在合同原文中匹配到该字段。{reason}",
    }


def _search(segments: list[dict], pattern: str):
    """逐分段正则匹配，返回 (match, segment) 或 (None, None)。"""
    rx = re.compile(pattern)
    for seg in segments:
        m = rx.search(seg.get("text") or "")
        if m:
            return m, seg
    return None, None


def _clean(value: str) -> str:
    return (value or "").strip().strip("。，；;、：: 　")


def _find_date_after_keyword(segments: list[dict], keywords: list[str],
                             gap: int = 8) -> tuple[str, dict] | tuple[None, None]:
    """「关键词 + 短间隔 + 日期」形式，如「有效期至2027年10月14日」「到期日：2027-10-14」。

    间隔中不允许跨越句号/分号，避免跨句误匹配。
    """
    rx = re.compile(r"(?:" + "|".join(keywords) + r")[^\n。；]{0," + str(gap) + r"}?(" + _DATE + r")")
    for seg in segments:
        m = rx.search(seg.get("text") or "")
        if m:
            return m.group(1).strip(), seg
    return None, None


def _find_date_before_keyword(segments: list[dict], keywords: list[str],
                              gap: int = 8) -> tuple[str, dict] | tuple[None, None]:
    """「日期 + 短间隔 + 关键词」形式，如「2026年10月15日起生效」「自2026-10-15起算」。"""
    rx = re.compile(r"(" + _DATE + r")[^\n。；]{0," + str(gap) + r"}?(?:" + "|".join(keywords) + r")")
    for seg in segments:
        m = rx.search(seg.get("text") or "")
        if m:
            return m.group(1).strip(), seg
    return None, None


def _normalize_date(raw: str) -> str:
    """日期标准化为 YYYY-MM-DD。"""
    nums = re.findall(r"\d+", raw or "")
    if len(nums) < 3:
        return (raw or "").strip()
    return f"{int(nums[0]):04d}-{int(nums[1]):02d}-{int(nums[2]):02d}"


# ======================================================================
# 一、合同基本信息提取
# ======================================================================
def _extract_title(segments: list[dict]) -> dict:
    for pat in (
        r"(?:合同|协议)(?:标题|名称)\s*[：:]\s*([^\n]{2,60})",
        r"项目名称\s*[：:]\s*([^\n]{2,60})",
    ):
        m, seg = _search(segments, pat)
        if m:
            return _ok(_clean(m.group(1)), seg, "正则匹配")

    m, seg = _search(segments, r"《([^》]{2,60}?(?:合同|协议))》")
    if m:
        return _ok(_clean(m.group(1)), seg, "正则匹配")

    for seg in segments[:5]:
        text = _clean(seg.get("text", ""))
        if 4 <= len(text) <= 50 and re.search(r"(合同|协议)$", text):
            return _ok(text, seg, "关键词匹配")

    return _missing("合同标题既无「合同名称」标注，也无《XXX合同》书名号形式，首部标题行未识别。")


def _extract_contract_no(segments: list[dict]) -> dict:
    pat = r"(?:合同编号|合同编码|合同号|协议编号|协议编码|编号)\s*[：:]\s*([A-Za-z0-9\-_/（）()一-龥]{3,40})"
    m, seg = _search(segments, pat)
    if m:
        return _ok(_clean(m.group(1)), seg, "正则匹配")
    return _missing("未找到「合同编号/合同号/编号」标注及编号值。", "合同编号、合同编码、合同号、协议编号、编号")


def _extract_party(segments: list[dict], role: str) -> dict:
    """提取签约主体（我方，甲方口径）或对方名称（乙方口径）。"""
    if role == "self":
        pats = [
            r"甲\s*方\s*(?:（[^）]{0,20}）|\([^)]{0,20}\))?\s*[：:]\s*([^\s，,。；;、\n]{2,50})",
            r"甲\s*方\s*(?:为|系)\s*([^\s，,。；;、\n]{2,50})",
            r"(?:采购方|委托方|发包方|我方)\s*[（(]?[^)）]{0,10}[)）]?\s*[：:]\s*([^\s，,。；;、\n]{2,50})",
        ]
        kws = "甲方、采购方、委托方、发包方"
        label = "签约主体"
    else:
        pats = [
            r"乙\s*方\s*(?:（[^）]{0,20}）|\([^)]{0,20}\))?\s*[：:]\s*([^\s，,。；;、\n]{2,50})",
            r"乙\s*方\s*(?:为|系)\s*([^\s，,。；;、\n]{2,50})",
            r"(?:供方|供应商|受托方|卖方|承包方|服务方|对方)\s*[（(]?[^)）]{0,10}[)）]?\s*[：:]\s*([^\s，,。；;、\n]{2,50})",
        ]
        kws = "乙方、供方、供应商、受托方、卖方、承包方、服务方"
        label = "对方名称"

    for pat in pats:
        m, seg = _search(segments, pat)
        if m:
            return _ok(_clean(m.group(1)), seg, "正则匹配")
    return _missing(f"未找到{label}（{kws}）的名称标注。", kws)


def _extract_amount(segments: list[dict]) -> tuple[dict, dict | None]:
    """提取合同金额，同时返回金额所在的原文分段（供币种推断定位使用）。"""
    pat = (
        r"(?:合同(?:总)?(?:金额|价款|总价|价税合计)|合同总金额|总金额|合同总价|项目总价|"
        r"采购金额|服务费(?:总额)?|价款(?:总额)?|合同价)\s*"
        r"(?:（[^）]{0,20}）|\([^)]{0,20}\))?\s*[：:为是]?\s*"
        r"(?:人民币|RMB|￥|¥)?\s*[（(]?\s*" + _AMOUNT_NUM + r"\s*[)）]?\s*" + _AMOUNT_UNIT + r"?"
    )
    m, seg = _search(segments, pat)
    if m:
        num = m.group(1).replace(",", "").replace("，", "")
        unit = (m.group(2) or "").strip()
        return _ok(f"{num}{unit}" if unit else f"{num}", seg, "正则匹配", evidence=seg.get("text")), seg

    # 兜底：金额/价款/总价所在段落中的「数字+元」
    for seg in segments:
        text = seg.get("text") or ""
        if re.search(r"(金额|价款|总价|报价|费用)", text):
            m2 = re.search(_AMOUNT_NUM + r"\s*" + _AMOUNT_UNIT, text)
            if m2:
                return _ok(f"{m2.group(1)}{m2.group(2)}", seg, "关键词匹配", evidence=text), seg

    return _missing("未找到「合同金额 / 合同总价 / 价款 / 采购金额」等金额标注及对应金额数值。"), None


def _extract_currency(segments: list[dict], amount_field: dict, amount_seg: dict | None = None) -> dict:
    pat = r"(?:币种|结算币种|货币|币别)\s*[：:]\s*(人民币|美元|欧元|港币|日元|CNY|USD|EUR|HKD|JPY)"
    m, seg = _search(segments, pat)
    if m:
        return _ok(_clean(m.group(1)), seg, "正则匹配")

    # 推断：从金额所在段落或金额值本身推断币种（定位沿用金额所在分段）
    text = (amount_field.get("evidence_text") or "") + " " + (amount_field.get("value") or "")
    if re.search(r"(美元|USD|\$|美金)", text):
        return _ok("美元(USD)", amount_seg, "推断补全", evidence=text)
    if re.search(r"(欧元|EUR)", text):
        return _ok("欧元(EUR)", amount_seg, "推断补全", evidence=text)
    if re.search(r"(港币|HKD)", text):
        return _ok("港币(HKD)", amount_seg, "推断补全", evidence=text)
    if re.search(r"(人民币|RMB|￥|¥|元)", text):
        return _ok("人民币(CNY)", amount_seg, "推断补全", evidence=text)

    return _missing("未找到「币种」标注，也无法从金额表述中推断币种。")


def _extract_effective_date(segments: list[dict]) -> dict:
    # 1) 优先解析「有效期 A 至 B」区间形式，取起始日期
    m, seg = _search(segments, r"(?:有效期|合同期限|服务期|合作期)[^\n]{0,15}?(" + _DATE + r")\s*(?:至|到|起至|—|-|~|～)\s*(" + _DATE + r")")
    if m:
        return _ok(_normalize_date(m.group(1)), seg, "正则匹配", evidence=seg.get("text"))

    # 2)「日期 + 起生效」形式
    value, seg = _find_date_before_keyword(segments, ["起生效", "生效", "之日起"])
    if value:
        return _ok(_normalize_date(value), seg, "关键词匹配", evidence=seg.get("text"))

    # 3)「生效日期/生效时间 + 日期」形式
    value, seg = _find_date_after_keyword(segments, ["生效日期", "生效时间", "生效日"])
    if value:
        return _ok(_normalize_date(value), seg, "关键词匹配", evidence=seg.get("text"))

    # 4) 兜底：签订日期/签署日期
    value, seg = _find_date_after_keyword(segments, ["签订日期", "签署日期", "签订时间"])
    if value:
        return _ok(_normalize_date(value), seg, "关键词匹配", evidence=seg.get("text"))

    return _missing("未找到合同生效时间/签订日期（检索关键词：起生效、生效日期、生效时间、签订日期、签署日期）。")


def _extract_expire_date(segments: list[dict]) -> dict:
    # 1) 优先解析「有效期 A 至 B」区间形式，取截止日期
    m, seg = _search(segments, r"(?:有效期|合同期限|服务期|合作期)[^\n]{0,15}?(" + _DATE + r")\s*(?:至|到|起至|—|-|~|～)\s*(" + _DATE + r")")
    if m:
        return _ok(_normalize_date(m.group(2)), seg, "正则匹配", evidence=seg.get("text"))

    # 2)「有效期至/到期/届满 + 日期」形式
    value, seg = _find_date_after_keyword(
        segments, ["有效期至", "有效期到", "到期日期", "到期日", "到期时间", "到期", "终止日期", "届满", "截止"])
    if value:
        return _ok(_normalize_date(value), seg, "关键词匹配", evidence=seg.get("text"))

    # 3)「日期 + 到期/届满」形式
    value, seg = _find_date_before_keyword(segments, ["到期", "届满", "终止"])
    if value:
        return _ok(_normalize_date(value), seg, "关键词匹配", evidence=seg.get("text"))

    return _missing("未找到合同到期时间/终止日期（检索关键词：有效期至、到期、终止、截止、届满）。")


# ======================================================================
# 二、合同条款信息提取
# ======================================================================
def _is_clause_boundary(text: str, current_kws: list[str]) -> bool:
    """判断某段是否为新的条款标题（作为条款正文的结束边界）。"""
    text = (text or "").strip()
    if not text:
        return True
    if _HEADING_RX.match(text):
        return True
    if len(text) <= 18:
        other_kws = [kw for kw in _ALL_CLAUSE_KEYWORDS if kw not in current_kws]
        if any(kw in text for kw in other_kws):
            return True
    return False


def _extract_clause(segments: list[dict], clause_name: str, keywords: list[str],
                    max_segments: int = 4, max_chars: int = 500) -> dict:
    """提取条款正文：定位首个关键词所在段落，并向后聚合至条款边界。"""
    start_idx = -1
    for idx, seg in enumerate(segments):
        text = seg.get("text") or ""
        if any(kw in text for kw in keywords):
            start_idx = idx
            break

    if start_idx < 0:
        return _missing(
            f"未在合同原文中检出差分相关条款（已检索关键词：{'、'.join(keywords)}）。",
            "、".join(keywords),
        )

    collected = [segments[start_idx]]
    for seg in segments[start_idx + 1: start_idx + max_segments]:
        if _is_clause_boundary(seg.get("text", ""), keywords):
            break
        collected.append(seg)

    evidence = join_text(collected, max_chars)
    return _ok(evidence, segments[start_idx], "关键词匹配", evidence=evidence)


# ======================================================================
# 对外入口
# ======================================================================
def extract_fields(segments: list[dict], full_text: str = "") -> dict:
    """执行全部字段提取。

    返回：
        {
          "basic_info": {字段名: 字段结果},
          "clause_info": {条款名: 条款结果},
          "fields": [全部字段结果（含 field_key / field_group）]
        }
    """
    basic_info: dict[str, dict] = {}
    clause_info: dict[str, dict] = {}
    fields: list[dict] = []

    def _push(group: str, key: str, result: dict) -> None:
        result = dict(result)
        result["field_key"] = key
        result["field_name"] = key
        result["field_group"] = group
        result["value_display"] = result["value"]
        if group == "basic":
            basic_info[key] = {k: v for k, v in result.items() if k not in ("field_key", "field_name", "field_group")}
        else:
            clause_info[key] = {k: v for k, v in result.items() if k not in ("field_key", "field_name", "field_group")}
        fields.append(result)

    # ---------------- 合同基本信息 ----------------
    title = _extract_title(segments)
    _push("basic", "合同标题", title)
    _push("basic", "合同编号", _extract_contract_no(segments))
    _push("basic", "签约主体", _extract_party(segments, "self"))
    _push("basic", "对方名称", _extract_party(segments, "counterparty"))

    amount, amount_seg = _extract_amount(segments)
    _push("basic", "合同金额", amount)
    _push("basic", "币种", _extract_currency(segments, amount, amount_seg))
    _push("basic", "生效时间", _extract_effective_date(segments))
    _push("basic", "到期时间", _extract_expire_date(segments))

    # ---------------- 合同条款信息 ----------------
    for clause_name, keywords in CLAUSE_SPECS:
        _push("clause", clause_name, _extract_clause(segments, clause_name, keywords))

    # ---------------- 汇总 ----------------
    success_count = sum(1 for f in fields if f["extract_status"] == ExtractStatus.SUCCESS)
    missing_fields = [f["field_key"] for f in fields if f["extract_status"] == ExtractStatus.MISSING]

    return {
        "basic_info": basic_info,
        "clause_info": clause_info,
        "fields": fields,
        "summary": {
            "total_fields": len(fields),
            "success_fields": success_count,
            "missing_fields": len(missing_fields),
            "missing_field_list": missing_fields,
        },
    }
