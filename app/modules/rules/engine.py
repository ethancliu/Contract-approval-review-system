"""规则引擎。

职责：规则加载 → 批量匹配 → 命中证据与位置输出 → 风险汇总与等级判定。

支持四种匹配模式（match_mode）：
    keyword  关键词匹配：match_text 用 | 分隔，命中任一关键词即命中
    regex    正则匹配  ：match_text 为正则表达式
    missing  缺失检测  ：match_text = "field:字段A,字段B" 或 "clause:条款A"，缺失即命中
    logic    业务逻辑  ：match_text = "内置逻辑名:参数"，交由本模块的 LOGIC_HANDLERS 判定

本模块为纯计算模块（不访问数据库），便于单元测试与复用；
规则数据的加载与命中记录的持久化由上层模块负责。
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from ...config import settings
from ...constants import ExtractStatus, MatchMode, RiskLevel
from ..parser.locator import position_of, snippet

# ======================================================================
# 一、业务逻辑处理器注册表
# ======================================================================
LogicHandler = Callable[[dict, str], Optional[dict]]
LOGIC_HANDLERS: dict[str, LogicHandler] = {}


def register_logic(name: str):
    """装饰器：注册一个业务逻辑处理器。"""

    def _wrap(fn: LogicHandler) -> LogicHandler:
        LOGIC_HANDLERS[name] = fn
        return fn

    return _wrap


def _hit(evidence_text: str, seg: dict | None = None, position: str = "", **detail) -> dict:
    """构造一条命中结果（handler 内部使用）。"""
    return {
        "evidence_text": snippet(evidence_text, settings.MAX_EVIDENCE_CHARS),
        "position": position or position_of(seg),
        "evidence_detail": detail or {},
        "segment": seg,
    }


def _sentence_around(text: str, keyword: str, max_len: int = 200) -> str:
    """截取包含关键词的完整句子作为证据原文。"""
    text = text or ""
    idx = text.find(keyword)
    if idx < 0:
        return snippet(text, max_len)
    # 向前找最近的句子边界
    start = max((text.rfind(ch, 0, idx) for ch in "。；;\n"), default=-1) + 1
    # 向后找最近的句子边界
    ends = [p for p in (text.find(ch, idx) for ch in "。；;\n") if p != -1]
    end = min(ends) + 1 if ends else len(text)
    return snippet(text[start:end].strip() or text, max_len)


def _window_segments(segments: list[dict], index: int, radius: int = 2) -> list[dict]:
    """取分段前后若干段构成上下文窗口。"""
    lo = max(0, index - radius)
    hi = min(len(segments), index + radius + 1)
    return segments[lo:hi]


def _index_of_segment(segments: list[dict], seg: dict) -> int:
    for i, s in enumerate(segments):
        if s is seg:
            return i
    for i, s in enumerate(segments):
        if s.get("text") == seg.get("text"):
            return i
    return -1


# ======================================================================
# 二、内置业务逻辑实现
# ======================================================================
@register_logic("prepay_ratio_over")
def _logic_prepay_ratio(ctx: dict, param: str) -> Optional[dict]:
    """预付款比例异常：预付款/首付款比例超过阈值（默认 30%）。"""
    try:
        threshold = float(param) if param else settings.PREPAY_RATIO_THRESHOLD
    except ValueError:
        threshold = settings.PREPAY_RATIO_THRESHOLD
    limit_pct = threshold * 100

    patterns = [
        r"预付(?:款|货款|费用|服务费)?\s*(?:比例|款项)?\s*(?:为|是|占|：|:)?\s*(\d{1,3}(?:\.\d+)?)\s*%",
        r"预付(?:款)?[^\n。；]{0,20}?(\d{1,3}(?:\.\d+)?)\s*%",
        r"首付(?:款)?[^\n。；]{0,20}?(\d{1,3}(?:\.\d+)?)\s*%",
        r"(\d{1,3}(?:\.\d+)?)\s*%[^\n。；]{0,15}?(?:作为)?预付(?:款)?",
        r"签订(?:合同)?(?:后)?[^\n。；]{0,20}?支付\s*(\d{1,3}(?:\.\d+)?)\s*%",
    ]

    best: Optional[tuple[float, dict, str]] = None
    for seg in ctx["segments"]:
        text = seg.get("text") or ""
        if "预付" not in text and "首付" not in text and "定金" not in text:
            continue
        for pat in patterns:
            for m in re.finditer(pat, text):
                try:
                    pct = float(m.group(1))
                except (ValueError, IndexError):
                    continue
                if pct <= limit_pct:
                    continue
                if best is None or pct > best[0]:
                    best = (pct, seg, _sentence_around(text, m.group(0)[:6] or "预付"))
    if best is None:
        return None
    pct, seg, evidence = best
    return _hit(
        evidence,
        seg,
        prepay_percent=pct,
        threshold_percent=limit_pct,
        message=f"预付款比例 {pct}% 超过内控上限 {limit_pct}%",
    )


@register_logic("payment_period_over")
def _logic_payment_period(ctx: dict, param: str) -> Optional[dict]:
    """付款周期不合理：约定「验收/交付/开票后 N 日内付款」且 N 超过阈值（默认 30 天）。"""
    try:
        limit_days = int(param) if param else settings.PAYMENT_PERIOD_DAYS_LIMIT
    except ValueError:
        limit_days = settings.PAYMENT_PERIOD_DAYS_LIMIT

    trigger_words = ("验收", "交付", "收货", "开票", "发票", "服务完成", "结算")
    pattern = re.compile(r"(\d{1,3})\s*(?:个)?(?:工作|自然)?\s*日内?\s*(?:支付|付款|付清|结清)")

    best: Optional[tuple[int, dict, str]] = None
    for seg in ctx["segments"]:
        text = seg.get("text") or ""
        for m in pattern.finditer(text):
            window = text[max(0, m.start() - 30): m.end() + 10]
            if not any(w in window for w in trigger_words):
                continue
            days = int(m.group(1))
            if days <= limit_days:
                continue
            if best is None or days > best[0]:
                best = (days, seg, _sentence_around(text, m.group(0)))
    if best is None:
        return None
    days, seg, evidence = best
    return _hit(
        evidence,
        seg,
        days=days,
        limit_days=limit_days,
        message=f"付款周期 {days} 日超过阈值 {limit_days} 日",
    )


@register_logic("breach_unbalanced")
def _logic_breach_unbalanced(ctx: dict, param: str) -> Optional[dict]:
    """违约责任缺失或不对等。

    判定方式：
        1) 违约条款整体缺失 → 命中；
        2) 逐句识别「违约责任主体」（取触发动词前首个出现的一方），
           若全部违约句子只指向同一方，则判定责任承担不对等；
        3) 违约金比例畸高（>30%）同样命中。
    """
    clause = ctx["clause_info"].get("违约条款", {})
    if clause.get("extract_status") != ExtractStatus.SUCCESS:
        return _hit(
            f"合同全文未检出差分违约责任条款。{clause.get('error_msg', '')}",
            None,
            "全文检索（未命中）",
            message="违约责任条款缺失",
        )

    text = clause.get("evidence_text") or ""
    sentences = [s.strip() for s in re.split(r"[。；;\n]", text) if s.strip()]
    penalty_sentences = [s for s in sentences if ("违约" in s or "赔偿" in s or "责任" in s)]

    # 逐句判定责任主体：取句子中「触发动词之前」最先出现的一方
    trigger_words = ("违约金", "赔偿", "承担违约", "支付", "承担责任", "负担")
    subjects: set[str] = set()
    for sentence in penalty_sentences:
        positions = [sentence.find(t) for t in trigger_words if sentence.find(t) >= 0]
        cut = min(positions) if positions else len(sentence)
        head = sentence[:cut]
        for party in ("甲方", "乙方"):
            if party in head:
                subjects.add(party)
                break

    if penalty_sentences and len(subjects) == 1:
        side = "甲方（我方）" if "甲方" in subjects else "乙方（对方）"
        return _hit(
            text, None, clause.get("position", ""),
            message=f"违约责任条款仅约定{side}一方的责任，双方责任承担不对等",
            unbalanced_side=side,
            penalty_sentence_count=len(penalty_sentences),
        )

    # 违约金比例畸高（>30%）同样视为风险
    m = re.search(r"违约金[^\n。；]{0,20}?(\d{1,3}(?:\.\d+)?)\s*%", text)
    if m and float(m.group(1)) > 30:
        return _hit(
            _sentence_around(text, m.group(0)),
            None, clause.get("position", ""),
            message=f"违约金比例 {m.group(1)}% 畸高",
            penalty_percent=float(m.group(1)),
        )
    return None


@register_logic("data_compliance_risk")
def _logic_data_compliance(ctx: dict, param: str) -> Optional[dict]:
    """数据处理合规风险：合同涉及个人信息/数据出境等，但缺少合规保障安排。"""
    risk_kws = ("个人信息", "用户数据", "数据出境", "敏感数据", "个人隐私",
                "用户信息", "客户数据", "生物识别", "人脸", "身份证号")
    guard_kws = ("加密", "脱敏", "匿名化", "同意", "授权", "合规", "安全评估",
                 "保护措施", "访问控制", "最小必要", "备案", "安全责任")

    hit_idx = -1
    hit_seg: dict | None = None
    for i, seg in enumerate(ctx["segments"]):
        text = seg.get("text") or ""
        if any(kw in text for kw in risk_kws):
            hit_idx, hit_seg = i, seg
            break
    if hit_seg is None:
        return None

    window = _window_segments(ctx["segments"], hit_idx, radius=2)
    window_text = "\n".join(s.get("text", "") for s in window)
    data_clause = ctx["clause_info"].get("数据条款", {})
    if data_clause.get("extract_status") == ExtractStatus.SUCCESS:
        window_text += "\n" + (data_clause.get("evidence_text") or "")

    if any(kw in window_text for kw in guard_kws):
        return None

    risk_word = next(kw for kw in risk_kws if kw in (hit_seg.get("text") or ""))
    return _hit(
        _sentence_around(hit_seg.get("text", ""), risk_word),
        hit_seg,
        message=f"合同涉及「{risk_word}」等数据处理，但未约定加密/授权/合规等保障措施",
        risk_keyword=risk_word,
    )


@register_logic("ip_ownership")
def _logic_ip_ownership(ctx: dict, param: str) -> Optional[dict]:
    """知识产权归属风险。"""
    clause = ctx["clause_info"].get("知识产权条款", {})
    if clause.get("extract_status") != ExtractStatus.SUCCESS:
        return _hit(
            f"合同全文未检出差分知识产权归属约定。{clause.get('error_msg', '')}",
            None,
            "全文检索（未命中）",
            message="未约定知识产权归属",
        )

    text = clause.get("evidence_text") or ""
    # 情形一：成果归属对方
    m = re.search(r"(?:知识产权|著作权|成果|专利|技术成果)[^\n。；]{0,30}?(?:归|属于|由)\s*(乙方|对方|供方|受托方|卖方|承包方|服务方)[^\n。；]{0,10}?(?:所有|享有|持有)?", text)
    if m:
        return _hit(_sentence_around(text, m.group(0)[:8]), None, clause.get("position", ""),
                    message=f"约定知识产权/成果归{m.group(1)}（对方）所有")
    # 情形二：有条款但未明确归属
    if not re.search(r"(?:归|属于|归属)\s*[^\n。；]{0,10}?(?:所有|享有|持有|双方共有|共有)", text):
        return _hit(text, None, clause.get("position", ""), message="知识产权条款未明确约定成果归属")
    return None


# ======================================================================
# 三、规则引擎
# ======================================================================
class RuleEngine:
    """规则匹配引擎。"""

    def __init__(self, rules: list[dict] | None = None) -> None:
        self.rules: list[dict] = rules or []

    # ------------------------------------------------------------------
    def load_rules(self, rules: list[dict]) -> "RuleEngine":
        """加载待执行的规则集合（通常由上层从 review_rules 表查询后传入）。"""
        self.rules = [
            r for r in rules
            if str(r.get("rule_status", MatchMode.KEYWORD)).lower() in ("enabled", "启用", "1", "true")
        ]
        return self

    # ------------------------------------------------------------------
    def run(self, ctx: dict) -> dict:
        """执行全量规则匹配。

        参数 ctx（由上层构造）：
            full_text / segments / basic_info / clause_info / char_count
        返回：
            {"hits": [...], "overall_risk_level": "低|中|高",
             "summary_text": "...", "focus_points": [...],
             "rule_total": n, "rule_enabled": n}
        """
        hits: list[dict] = []
        for rule in self.rules:
            try:
                hit = self._match_one(rule, ctx)
            except Exception as exc:  # noqa: BLE001 - 单条规则异常不影响其他规则
                hit = None
                ctx.setdefault("_rule_errors", []).append(f"{rule.get('rule_code')}: {exc}")
            if hit:
                hits.append(self._build_hit_record(rule, hit))

        hits.sort(key=lambda h: (-RiskLevel.ORDER.get(h["risk_level"], 1), h.get("rule_code", "")))
        summary = self.summarize(hits, ctx)
        return {
            "hits": hits,
            "rule_total": len(self.rules),
            "rule_errors": ctx.get("_rule_errors", []),
            **summary,
        }

    # ------------------------------------------------------------------
    def _match_one(self, rule: dict, ctx: dict) -> Optional[dict]:
        """按规则匹配模式执行单条规则。"""
        mode = (rule.get("match_mode") or "").strip().lower()
        match_text = (rule.get("match_text") or "").strip()

        if mode == MatchMode.KEYWORD:
            return self._match_keyword(match_text, ctx)
        if mode == MatchMode.REGEX:
            return self._match_regex(match_text, ctx)
        if mode == MatchMode.MISSING:
            return self._match_missing(match_text, ctx)
        if mode == MatchMode.LOGIC:
            name, _, param = match_text.partition(":")
            handler = LOGIC_HANDLERS.get(name.strip())
            if handler is None:
                raise ValueError(f"未注册的业务逻辑处理器：{name}")
            return handler(ctx, param.strip())
        raise ValueError(f"不支持的匹配模式：{mode}")

    # ------------------------------------------------------------------
    @staticmethod
    def _match_keyword(match_text: str, ctx: dict) -> Optional[dict]:
        keywords = [k.strip() for k in re.split(r"[|｜、,，]", match_text) if k.strip()]
        if not keywords:
            return None
        for seg in ctx["segments"]:
            text = seg.get("text") or ""
            for kw in keywords:
                if kw in text:
                    return _hit(_sentence_around(text, kw), seg,
                                message=f"命中关键词「{kw}」", keyword=kw)
        return None

    @staticmethod
    def _match_regex(match_text: str, ctx: dict) -> Optional[dict]:
        try:
            rx = re.compile(match_text)
        except re.error as exc:
            raise ValueError(f"正则表达式非法：{exc}") from exc
        for seg in ctx["segments"]:
            m = rx.search(seg.get("text") or "")
            if m:
                return _hit(_sentence_around(seg["text"], m.group(0)), seg,
                            message=f"命中正则「{m.group(0)}」", matched=m.group(0))
        return None

    @staticmethod
    def _match_missing(match_text: str, ctx: dict) -> Optional[dict]:
        scope, _, keys_raw = match_text.partition(":")
        keys = [k.strip() for k in re.split(r"[,，、]", keys_raw) if k.strip()]
        if not keys:
            return None

        scope = scope.strip().lower()
        if scope == "field":
            source, label = ctx["basic_info"], "字段"
        elif scope == "clause":
            source, label = ctx["clause_info"], "条款"
        else:
            raise ValueError(f"缺失检测的匹配范围非法（应为 field/clause）：{scope}")

        missing: list[dict] = []
        for key in keys:
            item = source.get(key)
            if not item or item.get("extract_status") != ExtractStatus.SUCCESS:
                missing.append({"key": key, "reason": (item or {}).get("error_msg", "原文中未检索到该项")})
        if not missing:
            return None

        names = "、".join(m["key"] for m in missing)
        detail = "；".join(f"{m['key']}：{m['reason']}" for m in missing)
        evidence = (
            f"全文共 {ctx.get('char_count', len(ctx.get('full_text', '')))} 字 / "
            f"{len(ctx['segments'])} 个定位分段，未检出差分{label}【{names}】。{detail}"
        )
        return _hit(evidence, None, "全文检索（未命中）",
                    message=f"{label}缺失：{names}", missing_keys=[m["key"] for m in missing])

    # ------------------------------------------------------------------
    @staticmethod
    def _build_hit_record(rule: dict, hit: dict) -> dict:
        """把引擎内部命中结构转换为标准命中记录。"""
        detail = dict(hit.get("evidence_detail") or {})
        return {
            "rule_id": rule.get("id", 0),
            "rule_code": rule.get("rule_code", ""),
            "rule_name": rule.get("rule_name", ""),
            "risk_level": rule.get("risk_level", RiskLevel.LOW),
            "match_mode": rule.get("match_mode", ""),
            "match_text": rule.get("match_text", ""),
            "evidence_text": hit.get("evidence_text", ""),
            "evidence_position": hit.get("position", ""),
            "evidence_detail": detail,
            "suggestion_text": rule.get("suggestion_text", ""),
            "hit_status": "hit",
        }

    # ------------------------------------------------------------------
    @staticmethod
    def summarize(hits: list[dict], ctx: dict) -> dict:
        """汇总风险等级、生成中文摘要与审批关注点。"""
        levels = [h["risk_level"] for h in hits]
        overall = RiskLevel.max_of(levels)

        high = [h for h in hits if h["risk_level"] == RiskLevel.HIGH]
        medium = [h for h in hits if h["risk_level"] == RiskLevel.MEDIUM]
        low = [h for h in hits if h["risk_level"] == RiskLevel.LOW]

        # ---------------- 中文摘要 ----------------
        basic_summary = (ctx.get("extract_summary") or {})
        total_fields = basic_summary.get("total_fields", 0)
        success_fields = basic_summary.get("success_fields", 0)
        missing_list = basic_summary.get("missing_field_list", [])

        if hits:
            names = "、".join(h["rule_name"] for h in hits[:5])
            more = f"等 {len(hits)} 项" if len(hits) > 5 else ""
            summary_text = (
                f"本次自动审查共命中 {len(hits)} 条风控规则，其中高风险 {len(high)} 条、"
                f"中风险 {len(medium)} 条、低风险 {len(low)} 条，综合判定合同总风险等级为【{overall}】。"
                f"主要风险集中在：{names}{more}。"
            )
        else:
            summary_text = (
                f"本次自动审查未命中任何风控规则，综合判定合同总风险等级为【{overall}】。"
                f"合同条款结构相对完整，未发现系统内置风险规则覆盖的异常项。"
            )

        summary_text += (
            f"合同结构化字段提取完整度：{success_fields}/{total_fields}。"
        )
        if missing_list:
            summary_text += f"未能从原文中识别的字段包括：{'、'.join(missing_list)}，建议人工确认原文是否确有约定。"
        summary_text += (
            "本结论由智能审查系统基于内置规则自动生成，仅用于辅助人工审批，"
            "不构成最终审批结论，最终审批权归人工法务。"
        )

        # ---------------- 审批关注点 ----------------
        focus_points: list[str] = []
        for h in hits:
            focus_points.append(
                f"【{h['risk_level']}风险】{h['rule_name']}：{h['suggestion_text']}"
                f"（证据位置：{h['evidence_position']}）"
            )
        if overall == RiskLevel.HIGH:
            focus_points.append("合同总风险等级为【高】，请法务人工重点复核全部高风险项，确认是否退回业务部门修改后再行审批。")
        if missing_list:
            focus_points.append(f"以下字段/条款未从原文中识别：{'、'.join(missing_list)}，请人工核对原文是否确有约定。")
        if not hits:
            focus_points.append("系统未命中内置风控规则，但仍建议人工确认合同商务条款与公司内控要求一致。")
        focus_points.append("系统证据定位在扫描件（OCR）场景下可能与原文存在少量偏差，请按位置标识核对原件。")
        focus_points.append("本意见由智能审查系统自动生成，仅辅助人工审批，不替代人工审核决策。")

        return {
            "overall_risk_level": overall,
            "summary_text": summary_text,
            "focus_points": focus_points[: settings.MAX_FOCUS_POINTS],
            "hit_count": len(hits),
            "high_count": len(high),
            "medium_count": len(medium),
            "low_count": len(low),
        }
