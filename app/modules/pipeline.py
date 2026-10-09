"""流程编排模块。

把「拉取 → 附件下载 → 文档解析 → 规则审查 → 结果入库 → 评论回写」串成一条闭环流水线，
并统一负责任务状态流转与异常阻塞处理：

    状态流转：pending → parsing → reviewing → done
               任意环节异常 → blocked（记录阻塞原因）→ 管理员重试 → 回归 parsing/reviewing

    评论回写状态流转：not_written → writing → success / failed
"""

from __future__ import annotations

import time

from ..constants import BlockReason, LogType, ParseStatus, TaskStatus, WriteStatus
from ..database import execute, json_dumps, json_loads, now_str, query_all, query_one
from ..exceptions import BlockedError, NotFoundError
from ..logger import gen_trace_id, log_error, log_info, log_task, log_warn
from . import attachment as attachment_module
from . import fetcher
from . import service


# ======================================================================
# 一、状态流转基础操作
# ======================================================================
def set_task_status(task_id: int, status: str, block_reason: str = "", trace_id: str = "") -> None:
    """更新任务状态（blocked 时写入阻塞原因）。"""
    execute(
        "UPDATE approval_tasks SET task_status = ?, block_reason = ?, updated_at = ? WHERE id = ?",
        (status, block_reason, now_str(), int(task_id)),
    )
    log_task(task_id, f"任务状态流转 → {TaskStatus.CN.get(status, status)}"
                      + (f"（阻塞原因：{block_reason}）" if block_reason else ""), trace_id=trace_id)


def block_task(task_id: int, reason: str, detail: str = "", trace_id: str = "") -> None:
    """把任务置为阻塞态并记录原因。"""
    set_task_status(task_id, TaskStatus.BLOCKED, reason, trace_id)
    log_error(task_id, LogType.TASK, f"任务阻塞：{reason}｜处置建议：{detail}", trace_id=trace_id)


# ======================================================================
# 二、单任务全流程
# ======================================================================
def process_task(task_id: int, force: bool = False) -> dict:
    """执行单个审批任务的全流程闭环。

    参数：
        task_id  审批任务主键
        force    True 时忽略「已完成」状态强制重跑（管理员重试场景）
    返回：
        标准化的全流程结果字典
    """
    task = fetcher.get_task(task_id)
    if not task:
        raise NotFoundError(f"未找到对应审批任务：task_id={task_id}")

    trace = gen_trace_id()
    start = time.time()
    approval_code = task["approval_code"]

    # ---------------- 幂等保护：已完成且回写成功则直接返回 ----------------
    if (task["task_status"] == TaskStatus.DONE
            and task["write_status"] == WriteStatus.SUCCESS
            and not force):
        log_task(task_id, "任务已完成且评论回写成功，跳过重复处理（幂等保护）", trace_id=trace)
        return build_task_detail(task_id, note="任务已完成，本次调用为重复触发，已跳过")

    log_task(task_id, f"===== 开始执行审查闭环：{approval_code}｜{task['approval_title']}（trace={trace}）=====",
             trace_id=trace)

    try:
        # ---------------- 步骤 1：附件下载（解析前确保本地文件就绪） ----------------
        log_task(task_id, "步骤 1/5：下载并校验合同附件", trace_id=trace)
        attachment_module.download_task_attachments(task)

        # ---------------- 步骤 2：文档解析 ----------------
        set_task_status(task_id, TaskStatus.PARSING, "", trace)
        log_task(task_id, "步骤 2/5：解析合同文档（电子文档解析 / 扫描件 OCR 识别）", trace_id=trace)
        parse_result = service.parse_task_documents(task_id)

        # ---------------- 步骤 3：规则审查 ----------------
        set_task_status(task_id, TaskStatus.REVIEWING, "", trace)
        log_task(task_id, "步骤 3/5：执行风控规则批量审查", trace_id=trace)
        review = service.run_contract_rules(task_id)

        # ---------------- 步骤 4：结果入库 ----------------
        log_task(task_id, "步骤 4/5：保存审查结果（结论 / 命中规则 / 关注点）", trace_id=trace)
        saved = service.save_review_result(
            case_id=task_id,
            overall_risk_level=review["overall_risk_level"],
            summary_text=review["summary_text"],
            focus_points_json=review["focus_points"],
            comment_text="",
        )

        # ---------------- 步骤 5：评论回写 ----------------
        if task["write_status"] != WriteStatus.SUCCESS or force:
            log_task(task_id, "步骤 5/5：回写审批评论", trace_id=trace)
            write_result = service.write_approval_comment(approval_code, saved["review_id"])
            if write_result["write_status"] != WriteStatus.SUCCESS:
                block_task(task_id, BlockReason.EXTERNAL_API_ERROR,
                           f"评论回写失败，请检查审批系统可用性后重试。响应：{write_result['write_response_text'][:200]}",
                           trace)
                return build_task_detail(task_id, note="评论回写失败，任务已阻塞，可由管理员重试")
        else:
            log_task(task_id, "步骤 5/5：评论此前已回写成功，跳过", trace_id=trace)

        # ---------------- 完成 ----------------
        set_task_status(task_id, TaskStatus.DONE, "", trace)
        cost_ms = int((time.time() - start) * 1000)
        log_task(task_id,
                 f"===== 审查闭环执行完成：总风险等级【{saved['overall_risk_level']}】，"
                 f"命中 {saved['hit_count']} 条规则，耗时 {cost_ms}ms =====",
                 trace_id=trace)
        return build_task_detail(task_id, note="审查闭环执行完成")

    except BlockedError as exc:
        block_task(task_id, exc.block_reason, exc.detail or exc.message, trace)
        return build_task_detail(task_id, note=f"任务阻塞：{exc.message}｜{exc.detail}")
    except Exception as exc:  # noqa: BLE001 - 兜底异常同样进入阻塞态，保证不崩溃
        block_task(task_id, BlockReason.FILE_PARSE_ERROR, f"未预期异常：{exc}", trace)
        log_error(task_id, LogType.ERROR, f"任务执行未预期异常：{exc}", trace_id=trace)
        return build_task_detail(task_id, note=f"任务阻塞：未预期异常 {exc}")


# ======================================================================
# 三、批量同步与处理
# ======================================================================
def sync_and_process(limit: int = 10) -> dict:
    """拉取待办 → 去重入库 → 逐个执行闭环。"""
    sync_result = fetcher.sync_pending_tasks(limit)
    processed: list[dict] = []
    for brief in sync_result["tasks"]:
        detail = process_task(brief["task_id"])
        processed.append({
            "task_id": detail["task"]["id"],
            "approval_code": detail["task"]["approval_code"],
            "task_status": detail["task"]["task_status"],
            "task_status_cn": TaskStatus.CN.get(detail["task"]["task_status"], ""),
            "write_status": detail["task"]["write_status"],
            "overall_risk_level": (detail.get("review") or {}).get("overall_risk_level", ""),
            "hit_count": (detail.get("review") or {}).get("hit_count", 0),
            "block_reason": detail["task"].get("block_reason", ""),
        })
    return {"sync": sync_result, "processed": processed}


def retry_task(task_id: int, operator: str = "系统管理员") -> dict:
    """管理员手动重试阻塞任务。

    重试后自动回归 parsing / reviewing 流程继续执行。
    """
    task = fetcher.get_task(task_id)
    if not task:
        raise NotFoundError(f"未找到对应审批任务：task_id={task_id}")

    execute(
        """UPDATE approval_tasks
              SET task_status = ?, block_reason = '', retry_count = retry_count + 1, updated_at = ?
            WHERE id = ?""",
        (TaskStatus.PENDING, now_str(), int(task_id)),
    )
    log_task(task_id,
             f"管理员【{operator}】手动重试任务（第 {int(task.get('retry_count') or 0) + 1} 次），"
             f"原阻塞原因：{task.get('block_reason') or '无'}，状态回归待处理")

    # ---------------- 重试前先刷新审批单最新数据 ----------------
    # 阻塞根因通常发生在审批系统一侧（申请人补传附件、重新上传清晰扫描件等），
    # 若不重新拉取详情，本地附件清单将停留在首次拉取时的状态，重试必然再次失败。
    try:
        refreshed = fetcher.refresh_task_from_approval(task_id)
        log_task(task_id,
                 f"已同步审批系统最新数据：附件数 {refreshed['attachment_count']}，转入流程重新执行")
    except Exception as exc:  # noqa: BLE001 - 刷新失败同样进入阻塞态，不中断服务
        detail = getattr(exc, "detail", "") or str(exc)
        block_task(task_id, BlockReason.EXTERNAL_API_ERROR,
                   f"重试前拉取审批单最新详情失败：{detail}", "")
        return build_task_detail(task_id, note=f"重试前数据同步失败，任务保持阻塞：{detail}")

    return process_task(task_id, force=True)


# ======================================================================
# 四、任务详情聚合（供前端/调用端展示）
# ======================================================================
def build_task_detail(task_id: int, note: str = "") -> dict:
    """聚合单个任务的完整信息：任务 / 附件 / 解析 / 命中 / 审查结果 / 回写日志。"""
    task = fetcher.get_task(task_id)
    if not task:
        raise NotFoundError(f"未找到对应审批任务：task_id={task_id}")

    attachments = attachment_module.list_task_attachments(task_id)

    parse_row = query_one("SELECT * FROM contract_parses WHERE task_id = ?", (task_id,))
    parse_view = None
    if parse_row:
        parse_view = {
            "parse_status": parse_row["parse_status"],
            "parse_error": parse_row["parse_error"],
            "page_count": parse_row["page_count"],
            "char_count": len(parse_row["full_text"] or ""),
            "basic_info": json_loads(parse_row["basic_info_json"], {}),
            "clause_info": json_loads(parse_row["clause_info_json"], {}),
            "segments": json_loads(parse_row["segments_json"], []),
            "document_detail": json_loads(parse_row["document_detail_json"], []),
            "updated_at": parse_row["updated_at"],
        }

    review_row = service.get_latest_review_result(task_id)
    review_view = None
    if review_row:
        review_view = {
            "review_id": review_row["id"],
            "overall_risk_level": review_row["overall_risk_level"],
            "summary_text": review_row["summary_text"],
            "focus_points": json_loads(review_row["focus_points_json"], []),
            "comment_text": review_row["comment_text"],
            "hit_count": review_row["hit_count"],
            "high_count": review_row["high_count"],
            "medium_count": review_row["medium_count"],
            "low_count": review_row["low_count"],
            "created_at": review_row["created_at"],
        }

    hits = query_all(
        "SELECT * FROM rule_hits WHERE task_id = ? ORDER BY "
        "CASE risk_level WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END, id",
        (task_id,),
    )
    hit_list = [{
        "rule_code": h["rule_code"],
        "rule_name": h["rule_name"],
        "risk_level": h["risk_level"],
        "evidence_text": h["evidence_text"],
        "evidence_position": h["evidence_position"],
        "suggestion_text": h["suggestion_text"],
        "hit_status": h["hit_status"],
        "evidence_detail": json_loads(h["evidence_detail_json"], {}),
    } for h in hits]

    comment_logs = query_all(
        "SELECT * FROM comment_logs WHERE task_id = ? ORDER BY id DESC LIMIT 20", (task_id,)
    )
    logs = query_all(
        "SELECT * FROM task_logs WHERE task_id = ? ORDER BY id DESC LIMIT 200", (task_id,)
    )

    return {
        "task": {
            "id": task["id"],
            "approval_code": task["approval_code"],
            "approval_title": task["approval_title"],
            "applicant_name": task["applicant_name"],
            "apply_time": task["apply_time"],
            "attachment_count": task["attachment_count"],
            "task_status": task["task_status"],
            "task_status_cn": TaskStatus.CN.get(task["task_status"], task["task_status"]),
            "write_status": task["write_status"],
            "write_status_cn": WriteStatus.CN.get(task["write_status"], task["write_status"]),
            "block_reason": task["block_reason"],
            "retry_count": task["retry_count"],
            "form_data": json_loads(task["form_data_json"], {}),
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        },
        "attachments": [{
            "attachment_id": a["attachment_id"],
            "file_name": a["file_name"],
            "file_type": a["file_type"],
            "file_path": a["file_path"],
            "file_size": a["file_size"],
            "file_md5": a["file_md5"],
            "download_status": a["download_status"],
            "download_error": a["download_error"],
        } for a in attachments],
        "parse": parse_view,
        "hits": hit_list,
        "review": review_view,
        "comment_logs": [{
            "write_status": c["write_status"],
            "write_response_text": c["write_response_text"],
            "created_at": c["created_at"],
            "http_status": c["http_status"],
        } for c in comment_logs],
        "logs": [{
            "log_level": row["log_level"],
            "log_type": row["log_type"],
            "log_content": row["log_content"],
            "created_at": row["created_at"],
            "trace_id": row["trace_id"],
        } for row in logs],
        "note": note,
    }


def list_task_summaries(task_status: str | None = None, limit: int = 100) -> list[dict]:
    """任务列表（含最新风险等级，供列表页展示）。"""
    tasks = fetcher.list_tasks(task_status, limit)
    result = []
    for task in tasks:
        review = service.get_latest_review_result(int(task["id"]))
        result.append({
            "task_id": task["id"],
            "approval_code": task["approval_code"],
            "approval_title": task["approval_title"],
            "applicant_name": task["applicant_name"],
            "apply_time": task["apply_time"],
            "attachment_count": task["attachment_count"],
            "task_status": task["task_status"],
            "task_status_cn": TaskStatus.CN.get(task["task_status"], task["task_status"]),
            "write_status": task["write_status"],
            "write_status_cn": WriteStatus.CN.get(task["write_status"], task["write_status"]),
            "block_reason": task["block_reason"],
            "retry_count": task["retry_count"],
            "overall_risk_level": review["overall_risk_level"] if review else "",
            "hit_count": review["hit_count"] if review else 0,
            "updated_at": task["updated_at"],
        })
    return result


def system_overview() -> dict:
    """系统总览统计（首页看板）。"""
    total = query_one("SELECT COUNT(*) AS c FROM approval_tasks") or {"c": 0}
    by_status = query_all("SELECT task_status, COUNT(*) AS c FROM approval_tasks GROUP BY task_status")
    # 风险分布只统计「每个任务的最新一次审查结论」，避免任务重跑后重复计数
    by_risk = query_all(
        """SELECT r.overall_risk_level AS overall_risk_level, COUNT(*) AS c
             FROM review_results r
            WHERE r.id = (SELECT MAX(id) FROM review_results WHERE task_id = r.task_id)
            GROUP BY r.overall_risk_level"""
    )
    rules = query_one("SELECT COUNT(*) AS c FROM review_rules WHERE rule_status = 'enabled'") or {"c": 0}
    hits = query_one("SELECT COUNT(*) AS c FROM rule_hits") or {"c": 0}
    return {
        "task_total": total["c"],
        "task_by_status": {row["task_status"]: row["c"] for row in by_status},
        "task_by_risk": {row["overall_risk_level"]: row["c"] for row in by_risk},
        "enabled_rule_count": rules["c"],
        "hit_total": hits["c"],
        "generated_at": now_str(),
    }


def reset_pipeline_data() -> dict:
    """清空任务相关数据（演示重置用，保留规则配置）。"""
    removed = 0
    for table in ("task_logs", "comment_logs", "review_results", "rule_hits",
                  "contract_parses", "approval_attachments", "approval_tasks"):
        rows = query_one(f"SELECT COUNT(*) AS c FROM {table}") or {"c": 0}
        execute(f"DELETE FROM {table}")
        removed += rows["c"]
    # 重置自增序列，保证演示可重复（任务ID / 附件ID 从 1 开始）
    try:
        execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('approval_tasks','approval_attachments','contract_parses','rule_hits',"
            " 'review_results','comment_logs','task_logs')"
        )
    except Exception:  # noqa: BLE001 - 非 SQLite 或无 sqlite_sequence 表时忽略
        pass

    # 清理本地已下载的附件
    from ..config import settings  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    if settings.STORAGE_DIR.exists():
        for child in settings.STORAGE_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
    log_info(0, LogType.TASK, f"演示数据已重置，共清理 {removed} 条记录及本地附件缓存")
    return {"deleted_records": removed}
