"""业务服务层：7 个核心工具接口的服务实现。

本层把「拉取 / 附件 / 解析 / 规则 / 回写」各模块与数据库持久化串联起来，
供 HTTP 接口（app/api/tools.py）与演示脚本共同调用，保证两条调用路径行为完全一致。

    list_pending_contract_approvals  工具 1：待办拉取
    get_contract_approval            工具 2：审批详情
    download_contract_attachment     工具 3：附件下载
    parse_contract_document          工具 4：文档解析
    run_contract_rules               工具 5：规则审查
    save_review_result               工具 6：结果保存
    write_approval_comment           工具 7：评论回写
"""

from __future__ import annotations

import time
from pathlib import Path

from ..config import settings
from ..constants import (
    DownloadStatus,
    ExtractStatus,
    HitStatus,
    LogType,
    ParseStatus,
    RiskLevel,
    RuleStatus,
)
from ..database import execute, json_dumps, json_loads, now_str, query_all, query_one
from ..exceptions import AttachmentMissingError, BlockedError, NotFoundError
from ..logger import gen_trace_id, log_error, log_info, log_task
from . import attachment as attachment_module
from . import fetcher
from .parser.document_parser import build_segments, parse_document, segments_to_text
from .parser.extractor import extract_fields
from .rules.engine import RuleEngine
from . import writer


# ======================================================================
# 通用解析辅助
# ======================================================================
def _reindex_segments(segments: list[dict]) -> list[dict]:
    """重排序号与字符偏移（多文档合并后使用）。"""
    result: list[dict] = []
    offset = 0
    for seg in segments:
        text = seg.get("text", "")
        new_seg = dict(seg)
        new_seg["char_start"] = offset
        new_seg["char_end"] = offset + len(text)
        result.append(new_seg)
        offset = new_seg["char_end"] + 1
    return result


def _code_list(task: dict) -> tuple:
    """返回 (task_id, approval_code)。"""
    return int(task["id"]), task["approval_code"]


def resolve_task(case_id) -> dict:
    """把 case_id 解析为任务记录。

    case_id 支持三种形式：
        1) 任务主键（数字或数字字符串），如 3
        2) 审批编号（approval_code），如 HTSP20261009002
        3) 审批实例号（instance_id），与审批编号一致
    """
    if case_id is None or str(case_id).strip() == "":
        raise NotFoundError("参数不能为空：case_id")

    raw = str(case_id).strip()
    if raw.isdigit():
        task = fetcher.get_task(int(raw))
        if task:
            return task
    task = fetcher.get_task_by_code(raw)
    if task:
        return task
    raise NotFoundError(
        f"未找到对应审批任务：case_id={case_id}",
        detail="请先调用「待办拉取工具」同步审批单，或传入正确的任务ID/审批编号。",
    )


def resolve_attachment(document_id) -> dict:
    """把 document_id 解析为附件记录。

    document_id 支持以下形式（推荐使用带前缀的显式形式或审批编号，避免自增ID歧义）：
        attach:10               显式指定附件ID（approval_attachments.id）
        task:9                  显式指定任务ID，取该任务下第一个附件
        code:HTSP20261009002    显式指定审批编号，取该审批单下第一个附件
        纯数字 10               先按附件ID解析，不存在时再按任务ID解析
        HTSP20261009002         审批编号（推荐，无歧义）
    """
    if document_id is None or str(document_id).strip() == "":
        raise NotFoundError("参数不能为空：document_id")

    raw = str(document_id).strip()
    prefix, _, rest = raw.partition(":")
    if prefix.lower() in ("attach", "attachment") and rest:
        # attach:<数字> 按附件表主键；attach:<外部附件编号> 按 attachment_id 列
        row = None
        if rest.isdigit():
            row = query_one("SELECT * FROM approval_attachments WHERE id = ?", (int(rest),))
        if row is None:
            row = query_one("SELECT * FROM approval_attachments WHERE attachment_id = ? ORDER BY id LIMIT 1", (rest,))
        if row:
            return row
        raise NotFoundError(f"附件不存在：attachment_id={rest}")
    if prefix.lower() == "task" and rest:
        rows = query_one(
            "SELECT * FROM approval_attachments WHERE task_id = ? ORDER BY id LIMIT 1",
            (int(rest),),
        )
        if rows:
            return rows
        raise NotFoundError(f"该任务下无附件记录：task_id={rest}")
    if prefix.lower() in ("code", "instance") and rest:
        raw = rest

    if raw.isdigit():
        row = query_one("SELECT * FROM approval_attachments WHERE id = ?", (int(raw),))
        if row:
            return row
        # 回退：当作任务主键处理
        rows = query_one(
            "SELECT * FROM approval_attachments WHERE task_id = ? ORDER BY id LIMIT 1",
            (int(raw),),
        )
        if rows:
            return rows

    # 当作审批编号处理
    task = fetcher.get_task_by_code(raw)
    if task:
        rows = attachment_module.list_task_attachments(int(task["id"]))
        if rows:
            return rows[0]

    raise NotFoundError(
        f"未找到对应文档/附件：document_id={document_id}",
        detail="请传入附件ID（可用 attach:12 显式指定）、任务ID（task:9）或审批编号（推荐）。",
    )


# ======================================================================
# 工具 1：待办拉取
# ======================================================================
def list_pending_contract_approvals(limit: int = 10) -> dict:
    """【工具 1】拉取待处理审批单列表。"""
    items = fetcher.list_pending_contract_approvals(limit)
    return {
        "total": len(items),
        "list": items,
        "limit": int(limit),
        "fetch_time": now_str(),
    }


# ======================================================================
# 工具 2：审批详情
# ======================================================================
def get_contract_approval(instance_id: str) -> dict:
    """【工具 2】查询单个审批单完整详情。"""
    return fetcher.get_contract_approval(instance_id)


# ======================================================================
# 工具 3：附件下载
# ======================================================================
def download_contract_attachment(instance_id: str, attachment_id: str, file_name: str) -> dict:
    """【工具 3】下载合同附件，返回本地存储路径与文件校验信息。"""
    task = fetcher.get_task_by_code(instance_id)
    task_id = int(task["id"]) if task else None
    if task_id:
        rows = attachment_module.list_task_attachments(task_id)
        if not rows:
            # 审批单尚未同步入库时，先同步一次元数据，保证附件记录存在
            detail = fetcher.get_contract_approval(instance_id)
            fetcher.create_or_update_task(detail)

    result = attachment_module.download_contract_attachment(
        instance_id, attachment_id, file_name, task_id=task_id
    )
    return result


# ======================================================================
# 工具 4：文档解析
# ======================================================================
def parse_task_documents(task_id: int, allow_download: bool = True) -> dict:
    """解析任务下的全部附件并做任务级合并，结果落库到 contract_parses。

    返回：
        {
          "task_id", "parse_status", "parse_error", "page_count", "char_count",
          "basic_info", "clause_info", "fields", "summary",
          "full_text", "segments", "document_detail": [各附件解析明细]
        }
    """
    task = fetcher.get_task(task_id)
    if not task:
        raise NotFoundError(f"未找到对应审批任务：task_id={task_id}")

    task_id, approval_code = _code_list(task)
    trace = gen_trace_id()
    start = time.time()
    log_task(task_id, f"开始解析合同文档（trace={trace}）", trace_id=trace)

    rows = attachment_module.list_task_attachments(task_id)
    if not rows:
        raise AttachmentMissingError(
            "附件缺失：该审批单未上传任何合同附件，无法执行解析",
            detail=f"审批编号：{approval_code}",
        )

    # 确保附件已下载到本地
    need_download = [
        r for r in rows
        if r["download_status"] != DownloadStatus.SUCCESS
        or not r["file_path"]
        or not Path(r["file_path"]).exists()
    ]
    if need_download and allow_download:
        attachment_module.download_task_attachments(task)

    rows = attachment_module.list_task_attachments(task_id)

    merged_segments: list[dict] = []
    document_detail: list[dict] = []
    page_offset = 0
    first_error: BlockedError | None = None

    for row in rows:
        file_path = row.get("file_path") or ""
        if not file_path:
            document_detail.append({
                "attachment_id": row["attachment_id"], "file_name": row["file_name"],
                "parse_status": ParseStatus.FAILED, "parse_error": "附件尚未下载到本地",
            })
            continue
        try:
            parsed = parse_document(file_path)
        except BlockedError as exc:
            log_error(task_id, LogType.PARSE,
                      f"附件 {row['file_name']} 解析失败：{exc.message}（{exc.detail}）", trace_id=trace)
            document_detail.append({
                "attachment_id": row["attachment_id"], "file_name": row["file_name"],
                "file_type": row["file_type"], "parse_status": ParseStatus.BLOCKED,
                "parse_error": exc.message, "block_reason": exc.block_reason, "detail": exc.detail,
            })
            first_error = first_error or exc
            continue

        extracted = extract_fields(parsed["segments"], parsed["full_text"])
        document_detail.append({
            "attachment_id": row["attachment_id"],
            "file_name": row["file_name"],
            "file_type": parsed["file_type"],
            "parse_status": ParseStatus.SUCCESS,
            "parse_error": "",
            "page_count": parsed["page_count"],
            "char_count": parsed["char_count"],
            "ocr_provider": parsed.get("ocr_provider", ""),
            "fields": extracted["fields"],
            "basic_info": extracted["basic_info"],
            "clause_info": extracted["clause_info"],
            "summary": extracted["summary"],
        })

        for seg in parsed["segments"]:
            new_seg = dict(seg)
            new_seg["page"] = int(seg.get("page", 1)) + page_offset
            merged_segments.append(new_seg)
        page_offset += max(1, int(parsed.get("page_count") or 1))

        log_info(task_id, LogType.PARSE,
                 f"附件 {row['file_name']} 解析成功：{parsed['page_count']} 页 / "
                 f"{parsed['char_count']} 字 / {len(parsed['segments'])} 个定位分段", trace_id=trace)

    if not merged_segments:
        reason = first_error.message if first_error else "全部附件解析失败"
        detail = first_error.detail if first_error else ""
        _persist_parse(task_id, {}, {}, ParseStatus.BLOCKED, reason, "", [], 0, 0, document_detail)
        exc = first_error or BlockedError(reason, detail=detail)
        log_error(task_id, LogType.PARSE, f"文档解析终止：{reason}", trace_id=trace)
        raise exc

    merged_segments = _reindex_segments(merged_segments)
    full_text = segments_to_text(merged_segments)
    extracted = extract_fields(merged_segments, full_text)

    parse_error = ""
    if document_detail and any(d["parse_status"] != ParseStatus.SUCCESS for d in document_detail):
        failed_names = "、".join(d["file_name"] for d in document_detail if d["parse_status"] != ParseStatus.SUCCESS)
        parse_error = f"部分附件解析失败（已跳过）：{failed_names}"

    primary = next((r for r in rows if r["file_path"]), None)
    _persist_parse(
        task_id, extracted["basic_info"], extracted["clause_info"], ParseStatus.SUCCESS,
        parse_error, full_text, merged_segments, page_offset, int(primary["id"]) if primary else 0,
        document_detail,
    )

    cost_ms = int((time.time() - start) * 1000)
    log_task(task_id, f"合同文档解析完成：{len(merged_segments)} 个定位分段，{len(full_text)} 字，耗时 {cost_ms}ms",
             trace_id=trace)

    return {
        "task_id": task_id,
        "approval_code": approval_code,
        "parse_status": ParseStatus.SUCCESS,
        "parse_error": parse_error,
        "page_count": page_offset,
        "char_count": len(full_text),
        "basic_info": extracted["basic_info"],
        "clause_info": extracted["clause_info"],
        "fields": extracted["fields"],
        "summary": extracted["summary"],
        "full_text": full_text,
        "segments": merged_segments,
        "document_detail": document_detail,
        "trace_id": trace,
        "cost_ms": cost_ms,
    }


def _persist_parse(task_id: int, basic_info: dict, clause_info: dict, parse_status: str,
                   parse_error: str, full_text: str, segments: list[dict], page_count: int,
                   attachment_id: int, document_detail: list[dict]) -> None:
    """把解析结果写入 contract_parses（按 task_id 唯一，重复解析覆盖更新）。"""
    ts = now_str()
    exists = query_one("SELECT id FROM contract_parses WHERE task_id = ?", (int(task_id),))
    params = (
        json_dumps(basic_info), json_dumps(clause_info), parse_status, parse_error[:1000],
        full_text, json_dumps(segments), int(page_count), int(attachment_id),
        json_dumps(_trim_detail(document_detail)), ts,
    )
    if exists:
        execute(
            """UPDATE contract_parses
                  SET basic_info_json = ?, clause_info_json = ?, parse_status = ?, parse_error = ?,
                      full_text = ?, segments_json = ?, page_count = ?, attachment_id = ?,
                      document_detail_json = ?, updated_at = ?
                WHERE task_id = ?""",
            params + (int(task_id),),
        )
    else:
        execute(
            """INSERT INTO contract_parses
                 (task_id, basic_info_json, clause_info_json, parse_status, parse_error, created_at,
                  full_text, segments_json, page_count, attachment_id, document_detail_json, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(task_id), params[0], params[1], params[2], params[3], ts,
             params[4], params[5], params[6], params[7], params[8], params[9]),
        )


def _trim_detail(document_detail: list[dict], max_chars: int = 60000) -> list[dict]:
    """裁剪多附件明细体积（避免明细中的字段证据过长导致存储膨胀）。"""
    text = json_dumps(document_detail)
    if len(text) <= max_chars:
        return document_detail
    trimmed = []
    for item in document_detail:
        item = dict(item)
        item.pop("fields", None)
        trimmed.append(item)
    return trimmed


def parse_contract_document(document_id) -> dict:
    """【工具 4】解析文档，返回结构化字段、对应原文片段与内容位置定位信息。"""
    row = resolve_attachment(document_id)
    task_id = int(row["task_id"])

    # 附件未下载时先下载
    if not row.get("file_path") or row["download_status"] != DownloadStatus.SUCCESS:
        task = fetcher.get_task(task_id)
        attachment_module.download_task_attachments(task)
        row = query_one("SELECT * FROM approval_attachments WHERE id = ?", (int(row["id"]),))

    merged = parse_task_documents(task_id)

    # 命中当前附件对应的解析明细
    detail = next(
        (d for d in merged["document_detail"] if d.get("attachment_id") == row["attachment_id"]),
        None,
    )
    if detail is None:
        detail = merged["document_detail"][0] if merged["document_detail"] else {}

    return {
        "document_id": document_id,
        "attachment_id": row["attachment_id"],
        "task_id": task_id,
        "approval_code": merged["approval_code"],
        "file_name": row["file_name"],
        "file_type": row["file_type"],
        "local_path": row.get("file_path", ""),
        "file_md5": row.get("file_md5", ""),
        "file_size": row.get("file_size", 0),
        "ocr_provider": detail.get("ocr_provider", ""),
        "parse_status": detail.get("parse_status", ParseStatus.PENDING),
        "parse_error": detail.get("parse_error", ""),
        "page_count": detail.get("page_count", 0),
        "char_count": detail.get("char_count", 0),
        "basic_info": detail.get("basic_info", {}),
        "clause_info": detail.get("clause_info", {}),
        "fields": detail.get("fields", []),
        "fields_summary": detail.get("summary", {}),
        # 任务级合并解析结果（多附件时使用；单附件时与本文档一致）
        "task_parse_status": merged["parse_status"],
        "task_parse_error": merged["parse_error"],
    }


# ======================================================================
# 工具 5：规则审查
# ======================================================================
def load_enabled_rules() -> list[dict]:
    """加载启用状态的风控规则。"""
    return query_all(
        "SELECT * FROM review_rules WHERE rule_status = ? ORDER BY sort_no, id",
        (RuleStatus.ENABLED,),
    )


def run_contract_rules(case_id) -> dict:
    """【工具 5】执行全量规则审查，返回风险结论与命中规则。"""
    task = resolve_task(case_id)
    task_id, approval_code = _code_list(task)
    trace = gen_trace_id()
    start = time.time()

    log_task(task_id, f"开始执行风控规则审查（trace={trace}）", trace_id=trace)

    parse_row = query_one("SELECT * FROM contract_parses WHERE task_id = ?", (task_id,))
    if not parse_row or parse_row["parse_status"] != ParseStatus.SUCCESS:
        # 尚未解析或解析未成功 → 先执行解析
        merged = parse_task_documents(task_id)
        parse_row = query_one("SELECT * FROM contract_parses WHERE task_id = ?", (task_id,))
    else:
        merged = None

    basic_info = json_loads(parse_row["basic_info_json"], {}) or {}
    clause_info = json_loads(parse_row["clause_info_json"], {}) or {}
    segments = json_loads(parse_row["segments_json"], []) or []
    full_text = parse_row["full_text"] or ""

    ctx = {
        "task_id": task_id,
        "full_text": full_text,
        "segments": segments,
        "basic_info": basic_info,
        "clause_info": clause_info,
        "char_count": len(full_text),
        "extract_summary": _fields_summary(basic_info, clause_info),
    }

    rules = load_enabled_rules()
    engine = RuleEngine(rules)
    result = engine.run(ctx)

    log_info(task_id, LogType.RULE,
             f"规则审查完成：启用规则 {len(rules)} 条，命中 {result['hit_count']} 条"
             f"（高 {result['high_count']} / 中 {result['medium_count']} / 低 {result['low_count']}），"
             f"总风险等级：{result['overall_risk_level']}", trace_id=trace)

    # 命中记录落库。
    # rule_hits 语义定位为「该任务当前有效的命中明细」——规则审查是对全部规则的幂等重算，
    # 若按 review_id 过滤只清理未绑定的旧记录，重复执行会在同一任务上累积出成倍命中。
    # 因此每轮审查先清空该任务的历史命中再整体写入；历史结论由 review_results 快照
    # （含 hit_count / high_count / summary_text / comment_text）与 comment_logs 完整保留。
    execute("DELETE FROM rule_hits WHERE task_id = ?", (task_id,))
    for hit in result["hits"]:
        execute(
            """INSERT INTO rule_hits
                 (task_id, rule_id, evidence_text, evidence_position, hit_status, created_at,
                  rule_code, rule_name, risk_level, suggestion_text, review_id, evidence_detail_json, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (task_id, int(hit.get("rule_id") or 0), hit["evidence_text"], hit["evidence_position"],
             HitStatus.HIT, now_str(), hit["rule_code"], hit["rule_name"], hit["risk_level"],
             hit["suggestion_text"], json_dumps(hit.get("evidence_detail", {})), now_str()),
        )

    cost_ms = int((time.time() - start) * 1000)
    log_task(task_id, f"规则审查结果已入库：命中记录 {len(result['hits'])} 条，耗时 {cost_ms}ms", trace_id=trace)

    return {
        "case_id": case_id,
        "task_id": task_id,
        "approval_code": approval_code,
        "overall_risk_level": result["overall_risk_level"],
        "hit_rules": result["hits"],
        "hit_count": result["hit_count"],
        "high_count": result["high_count"],
        "medium_count": result["medium_count"],
        "low_count": result["low_count"],
        "summary_text": result["summary_text"],
        "focus_points": result["focus_points"],
        "rule_total": len(rules),
        "trace_id": trace,
        "cost_ms": cost_ms,
    }


def _fields_summary(basic_info: dict, clause_info: dict) -> dict:
    """汇总字段提取情况（供摘要文案使用）。"""
    merged = dict(basic_info)
    merged.update(clause_info)
    total = len(merged)
    success = sum(1 for v in merged.values() if v.get("extract_status") == ExtractStatus.SUCCESS)
    missing = [k for k, v in merged.items() if v.get("extract_status") != ExtractStatus.SUCCESS]
    return {
        "total_fields": total,
        "success_fields": success,
        "missing_fields": len(missing),
        "missing_field_list": missing,
    }


# ======================================================================
# 工具 6：结果保存
# ======================================================================
def save_review_result(case_id, overall_risk_level: str, summary_text: str,
                       focus_points_json, comment_text: str = "") -> dict:
    """【工具 6】持久化审查结果（含命中规则、风险摘要、关注点）。"""
    task = resolve_task(case_id)
    task_id, approval_code = _code_list(task)

    if overall_risk_level not in RiskLevel.ALL:
        overall_risk_level = RiskLevel.max_of([overall_risk_level]) if overall_risk_level else RiskLevel.LOW

    if isinstance(focus_points_json, str):
        focus_points = json_loads(focus_points_json, []) or []
    else:
        focus_points = focus_points_json or []

    hits = query_all(
        "SELECT * FROM rule_hits WHERE task_id = ? ORDER BY "
        "CASE risk_level WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END, id",
        (task_id,),
    )
    counts = {
        "hit_count": len(hits),
        "high_count": sum(1 for h in hits if h["risk_level"] == RiskLevel.HIGH),
        "medium_count": sum(1 for h in hits if h["risk_level"] == RiskLevel.MEDIUM),
        "low_count": sum(1 for h in hits if h["risk_level"] == RiskLevel.LOW),
    }

    ts = now_str()
    review_id = int(execute(
        """
        INSERT INTO review_results
            (task_id, overall_risk_level, summary_text, focus_points_json, comment_text, created_at,
             hit_count, high_count, medium_count, low_count, save_status, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (task_id, overall_risk_level, summary_text, json_dumps(focus_points), comment_text, ts,
         counts["hit_count"], counts["high_count"], counts["medium_count"], counts["low_count"],
         "saved", ts),
    ))

    # 若评论正文为空，则用标准化模板自动拼接
    if not comment_text:
        review_row = query_one("SELECT * FROM review_results WHERE id = ?", (review_id,))
        comment_text = writer.build_comment_text(task, review_row, hits)
        execute("UPDATE review_results SET comment_text = ? WHERE id = ?", (comment_text, review_id))

    # 命中记录绑定本次审查结果
    execute("UPDATE rule_hits SET review_id = ?, updated_at = ? WHERE task_id = ? AND review_id = 0",
            (review_id, ts, task_id))

    log_task(task_id,
             f"审查结果已保存：review_id={review_id}，总风险等级={overall_risk_level}，"
             f"命中 {counts['hit_count']} 条（高 {counts['high_count']} / 中 {counts['medium_count']} / 低 {counts['low_count']}）")

    return {
        "review_id": review_id,
        "task_id": task_id,
        "approval_code": approval_code,
        "save_status": "success",
        "overall_risk_level": overall_risk_level,
        "summary_text": summary_text,
        "focus_points": focus_points,
        "comment_text": comment_text,
        "saved_at": ts,
        **counts,
    }


def get_review_result(review_id: int) -> dict | None:
    """查询审查结果。"""
    return query_one("SELECT * FROM review_results WHERE id = ?", (int(review_id),))


def get_latest_review_result(task_id: int) -> dict | None:
    """查询任务最新一条审查结果。"""
    return query_one(
        "SELECT * FROM review_results WHERE task_id = ? ORDER BY id DESC LIMIT 1",
        (int(task_id),),
    )


# ======================================================================
# 工具 7：评论回写
# ======================================================================
def write_approval_comment(instance_id: str, review_id: int) -> dict:
    """【工具 7】执行审批评论回写，返回回写状态与响应结果。"""
    return writer.write_approval_comment(instance_id, review_id)
