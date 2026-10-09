"""管理员接口。

面向「系统管理员」角色：
    1. 审批系统接入配置查询与运行期切换；
    2. 风控规则维护（新增 / 编辑 / 启用禁用 / 删除）；
    3. 全量运行日志查询；
    4. 失败 / 阻塞任务手动重试。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..constants import LogLevel, LogType, MatchMode, RiskLevel, RuleStatus, TaskStatus, WriteStatus
from ..database import execute, json_loads, now_str, query_all, query_one
from ..exceptions import NotFoundError
from ..logger import log_info, query_logs
from ..modules import fetcher, pipeline, service
from ..modules.rules.engine import LOGIC_HANDLERS
from ..modules.writer import list_comment_logs

router = APIRouter(prefix="/api/admin", tags=["管理员接口"])


# ======================================================================
# 一、接入配置
# ======================================================================
@router.get("/config", summary="查询审批系统接入配置")
def admin_get_config() -> dict:
    """返回当前接入配置与阈值设置（不含密钥）。"""
    return {
        **settings.as_dict(),
        "approval_operator": settings.APPROVAL_OPERATOR,
        "api_timeout": settings.APPROVAL_API_TIMEOUT,
        "max_evidence_chars": settings.MAX_EVIDENCE_CHARS,
    }


class ConfigUpdateRequest(BaseModel):
    """运行期配置调整（仅影响当前进程）。"""
    approval_base_url: str | None = Field(default=None, description="审批系统网关地址")
    operator: str | None = Field(default=None, description="回写评论的操作人标识")
    prepay_ratio_threshold: float | None = Field(default=None, ge=0, le=1, description="预付款比例上限，如 0.3")
    payment_period_days_limit: int | None = Field(default=None, ge=1, le=365, description="付款周期上限（天）")
    ocr_engine: str | None = Field(default=None, description="OCR 引擎：auto/tesseract/paddle/sidecar")


@router.post("/config", summary="调整运行配置")
def admin_update_config(req: ConfigUpdateRequest) -> dict:
    """运行期调整接入地址与风控阈值（重启后以环境变量为准）。"""
    changed: list[str] = []
    if req.approval_base_url:
        settings.APPROVAL_BASE_URL = req.approval_base_url.rstrip("/")
        changed.append(f"审批系统地址 → {settings.APPROVAL_BASE_URL}")
    if req.operator:
        settings.APPROVAL_OPERATOR = req.operator
        changed.append(f"回写操作人 → {req.operator}")
    if req.prepay_ratio_threshold is not None:
        settings.PREPAY_RATIO_THRESHOLD = req.prepay_ratio_threshold
        changed.append(f"预付款比例上限 → {req.prepay_ratio_threshold}")
    if req.payment_period_days_limit is not None:
        settings.PAYMENT_PERIOD_DAYS_LIMIT = req.payment_period_days_limit
        changed.append(f"付款周期上限 → {req.payment_period_days_limit} 天")
    if req.ocr_engine:
        from ..modules.parser.ocr_engine import ocr_engine  # noqa: PLC0415
        settings.OCR_ENGINE = req.ocr_engine
        ocr_engine.engine = req.ocr_engine
        changed.append(f"OCR 引擎 → {req.ocr_engine}")

    log_info(0, LogType.TASK, "管理员调整运行配置：" + "；".join(changed or ["无变化"]))
    return {"updated": changed, "config": admin_get_config()}


# ======================================================================
# 二、风控规则管理
# ======================================================================
@router.get("/rules", summary="查询全部风控规则")
def admin_list_rules(rule_status: str | None = Query(None), keyword: str | None = Query(None)) -> dict:
    """查询规则列表，可按启用状态与关键字过滤。"""
    sql = "SELECT * FROM review_rules WHERE 1=1"
    params: list = []
    if rule_status:
        sql += " AND rule_status = ?"
        params.append(rule_status)
    if keyword:
        sql += " AND (rule_code LIKE ? OR rule_name LIKE ? OR match_text LIKE ?)"
        like = f"%{keyword}%"
        params.extend([like, like, like])
    sql += " ORDER BY sort_no, id"
    rules = query_all(sql, params)
    return {
        "total": len(rules),
        "list": rules,
        "match_mode_cn": MatchMode.CN,
        "rule_status_cn": RuleStatus.CN,
        "supported_logic": sorted(LOGIC_HANDLERS.keys()),
    }


class RuleRequest(BaseModel):
    """规则新增/编辑入参。"""
    rule_code: str = Field(..., description="规则编码（唯一）")
    rule_name: str = Field(..., description="规则名称")
    risk_level: str = Field(..., description="风险等级：低/中/高")
    rule_status: str = Field(default=RuleStatus.ENABLED, description="启用状态：enabled/disabled")
    match_mode: str = Field(..., description="匹配模式：keyword/regex/missing/logic")
    match_text: str = Field(..., description="匹配关键词或逻辑表达式")
    suggestion_text: str = Field(..., description="整改建议")
    remark: str = Field(default="", description="规则说明")
    sort_no: int = Field(default=999, description="排序号")


def _validate_rule(req: RuleRequest) -> None:
    if req.risk_level not in RiskLevel.ALL:
        raise ValueError(f"风险等级非法：{req.risk_level}，仅支持 {RiskLevel.ALL}")
    if req.match_mode not in MatchMode.ALL:
        raise ValueError(f"匹配模式非法：{req.match_mode}，仅支持 {MatchMode.ALL}")
    if req.match_mode == MatchMode.LOGIC:
        name = req.match_text.split(":")[0].strip()
        if name not in LOGIC_HANDLERS:
            raise ValueError(f"未注册的业务逻辑：{name}，可用逻辑：{sorted(LOGIC_HANDLERS.keys())}")


@router.post("/rules", summary="新增风控规则")
def admin_create_rule(req: RuleRequest) -> dict:
    """新增一条风控规则。"""
    _validate_rule(req)
    if query_one("SELECT id FROM review_rules WHERE rule_code = ?", (req.rule_code,)):
        raise ValueError(f"规则编码已存在：{req.rule_code}")
    ts = now_str()
    rule_id = int(execute(
        """INSERT INTO review_rules
             (rule_code, rule_name, risk_level, rule_status, match_mode, match_text,
              suggestion_text, remark, sort_no, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (req.rule_code, req.rule_name, req.risk_level, req.rule_status, req.match_mode,
         req.match_text, req.suggestion_text, req.remark, req.sort_no, ts, ts),
    ))
    log_info(0, LogType.RULE, f"管理员新增风控规则：{req.rule_code} {req.rule_name}")
    return {"rule_id": rule_id, "updated": True}


@router.put("/rules/{rule_id}", summary="编辑风控规则")
def admin_update_rule(rule_id: int, req: RuleRequest) -> dict:
    """编辑指定风控规则。"""
    _validate_rule(req)
    exists = query_one("SELECT id FROM review_rules WHERE id = ?", (int(rule_id),))
    if not exists:
        raise NotFoundError(f"规则不存在：rule_id={rule_id}")
    ts = now_str()
    execute(
        """UPDATE review_rules
              SET rule_code = ?, rule_name = ?, risk_level = ?, rule_status = ?, match_mode = ?,
                  match_text = ?, suggestion_text = ?, remark = ?, sort_no = ?, updated_at = ?
            WHERE id = ?""",
        (req.rule_code, req.rule_name, req.risk_level, req.rule_status, req.match_mode,
         req.match_text, req.suggestion_text, req.remark, req.sort_no, ts, int(rule_id)),
    )
    log_info(0, LogType.RULE, f"管理员编辑风控规则：{req.rule_code} {req.rule_name}")
    return {"rule_id": int(rule_id), "updated": True}


@router.post("/rules/{rule_id}/status", summary="启用/禁用风控规则")
def admin_toggle_rule(rule_id: int, rule_status: str = Query(..., description="enabled / disabled")) -> dict:
    """切换规则启用状态。"""
    if rule_status not in RuleStatus.ALL:
        raise ValueError(f"启用状态非法：{rule_status}")
    rule = query_one("SELECT * FROM review_rules WHERE id = ?", (int(rule_id),))
    if not rule:
        raise NotFoundError(f"规则不存在：rule_id={rule_id}")
    execute("UPDATE review_rules SET rule_status = ?, updated_at = ? WHERE id = ?",
            (rule_status, now_str(), int(rule_id)))
    log_info(0, LogType.RULE,
             f"管理员{RuleStatus.CN[rule_status]}规则：{rule['rule_code']} {rule['rule_name']}")
    return {"rule_id": int(rule_id), "rule_status": rule_status, "rule_status_cn": RuleStatus.CN[rule_status]}


@router.delete("/rules/{rule_id}", summary="删除风控规则")
def admin_delete_rule(rule_id: int) -> dict:
    """删除规则（已有命中记录引用时禁止删除，避免历史证据断链）。"""
    rule = query_one("SELECT * FROM review_rules WHERE id = ?", (int(rule_id),))
    if not rule:
        raise NotFoundError(f"规则不存在：rule_id={rule_id}")
    used = query_one("SELECT COUNT(*) AS c FROM rule_hits WHERE rule_id = ?", (int(rule_id),))
    if used and used["c"] > 0:
        raise ValueError(f"规则已被 {used['c']} 条历史命中记录引用，无法删除；如需停用请改为「禁用」。")
    execute("DELETE FROM review_rules WHERE id = ?", (int(rule_id),))
    log_info(0, LogType.RULE, f"管理员删除风控规则：{rule['rule_code']} {rule['rule_name']}")
    return {"rule_id": int(rule_id), "deleted": True}


# ======================================================================
# 三、日志查询
# ======================================================================
@router.get("/logs", summary="查询全量运行日志")
def admin_query_logs(task_id: int | None = Query(None, description="按任务ID过滤"),
                     log_level: str | None = Query(None, description="INFO/WARN/ERROR"),
                     log_type: str | None = Query(None, description="FETCH/ATTACHMENT/PARSE/RULE/WRITE/TASK/API/ERROR"),
                     limit: int = Query(200, ge=1, le=1000),
                     offset: int = Query(0, ge=0)) -> dict:
    """查询 task_logs 全链路日志。"""
    items = query_logs(task_id, log_level, log_type, limit, offset)
    total = query_one("SELECT COUNT(*) AS c FROM task_logs") or {"c": 0}
    return {
        "total": total["c"],
        "list": items,
        "log_level_cn": {k: k for k in LogLevel.ALL},
        "log_type_cn": LogType.CN,
    }


@router.get("/comment_logs", summary="查询评论回写日志")
def admin_comment_logs(task_id: int | None = Query(None), limit: int = Query(100, ge=1, le=500)) -> dict:
    """查询 comment_logs 回写日志。"""
    items = list_comment_logs(task_id, limit)
    return {"total": len(items), "list": items, "write_status_cn": WriteStatus.CN}


# ======================================================================
# 四、失败 / 阻塞任务处理
# ======================================================================
@router.get("/blocked_tasks", summary="查询阻塞任务")
def admin_blocked_tasks() -> dict:
    """列出所有处于 blocked 状态的任务，供管理员重试。"""
    tasks = fetcher.list_tasks(TaskStatus.BLOCKED, 200)
    return {
        "total": len(tasks),
        "list": [{
            "task_id": t["id"],
            "approval_code": t["approval_code"],
            "approval_title": t["approval_title"],
            "applicant_name": t["applicant_name"],
            "block_reason": t["block_reason"],
            "retry_count": t["retry_count"],
            "write_status": t["write_status"],
            "updated_at": t["updated_at"],
        } for t in tasks],
    }


@router.post("/retry/{task_id}", summary="手动重试失败/阻塞任务")
def admin_retry_task(task_id: int, operator: str = Query("系统管理员")) -> dict:
    """重试阻塞任务：状态回归 pending → parsing → reviewing → done，全程重新记录日志。"""
    return pipeline.retry_task(int(task_id), operator)


class BatchRetryRequest(BaseModel):
    """批量重试入参。"""
    task_ids: list[int] = Field(default_factory=list, description="待重试任务ID列表")
    operator: str = Field(default="系统管理员")


@router.post("/retry_batch", summary="批量重试阻塞任务")
def admin_retry_batch(req: BatchRetryRequest) -> dict:
    """批量重试阻塞任务。"""
    results = []
    for task_id in req.task_ids:
        try:
            detail = pipeline.retry_task(int(task_id), req.operator)
            results.append({
                "task_id": task_id,
                "task_status": detail["task"]["task_status"],
                "block_reason": detail["task"]["block_reason"],
                "success": detail["task"]["task_status"] == TaskStatus.DONE,
            })
        except Exception as exc:  # noqa: BLE001 - 单个失败不影响其他任务
            results.append({"task_id": task_id, "success": False, "error": str(exc)})
    return {"total": len(results), "results": results}


# ======================================================================
# 五、审查结果查询（法务审核人视角）
# ======================================================================
@router.get("/review_results/{task_id}", summary="查询任务审查结果")
def admin_review_result(task_id: int) -> dict:
    """查询指定任务的审查结论、命中规则与关注点。"""
    review = service.get_latest_review_result(int(task_id))
    if not review:
        raise NotFoundError(f"该任务尚无审查结果：task_id={task_id}")
    hits = query_all(
        "SELECT * FROM rule_hits WHERE task_id = ? ORDER BY "
        "CASE risk_level WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END, id",
        (int(task_id),),
    )
    return {
        "task_id": int(task_id),
        "review_id": review["id"],
        "overall_risk_level": review["overall_risk_level"],
        "summary_text": review["summary_text"],
        "focus_points": json_loads(review["focus_points_json"], []),
        "comment_text": review["comment_text"],
        "hit_count": review["hit_count"],
        "high_count": review["high_count"],
        "medium_count": review["medium_count"],
        "low_count": review["low_count"],
        "created_at": review["created_at"],
        "hit_rules": [{
            "rule_code": h["rule_code"],
            "rule_name": h["rule_name"],
            "risk_level": h["risk_level"],
            "evidence_text": h["evidence_text"],
            "evidence_position": h["evidence_position"],
            "suggestion_text": h["suggestion_text"],
            "hit_status": h["hit_status"],
        } for h in hits],
    }
